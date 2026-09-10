import logging
import asyncio
import time
import math
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any

from app.config import HOST, PORT, CACHE_REFRESH_INTERVAL
from app.client import UrjaPortalClient
from app.models import (
    MeterResponse, GeoLocation, MeterHierarchy, HierarchyItem,
    NearbyMeterResponse, NearbyMetersListResponse,
    TransformerResponse, ConsumptionResponse, ConsumptionReading,
    HierarchyNode, AuthLoginRequest, AuthLoginResponse,
    AnalyticsSummaryResponse, StatusBreakdown, MakeBreakdown,
    PhaseBreakdown, DTLoadItem, AnomaliesSummary,
    HealthCheckResponse, CacheRefreshResponse
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("urja_api_wrapper")

start_time = time.time()

# Initialize FastAPI App
app = FastAPI(
    title="Flock Energy - Urja Meter Ops API",
    description="""
A clean, modern, and high-performance REST API wrapper over the legacy Urja Meter Ops portal.

### Features
- **In-Memory Cache & Query Engine**: Instant sub-millisecond filtering, search, and pagination over all 403 meters and 40 transformers.
- **Geo-Spatial Query Layer**: Locate meters near any geographic coordinates using the Haversine formula (`/api/v1/meters/nearby`).
- **Network Hierarchy Reconstructor**: Reconstructs the electrical grid topology from Zone down to Meter leaf nodes (`/api/v1/hierarchy`).
- **Telemetry Data Cleansing**: Normalizes dirty legacy strings, dates, and null markers into typed ISO-8601 timestamps and floats (`/api/v1/meters/{id}/consumption`).
- **Grid Analytics & Anomalies**: Grid-wide health metrics, manufacturer distribution, and anomaly counts (`/api/v1/analytics/summary`).
- **Cryptographic Bulk Signer**: Automates HMAC-SHA256 request signing for legacy `/portal/export`.
- **Interactive Operations Dashboard**: Serves a modern dark-mode web application with an interactive Leaflet map and Chart.js graphs at `/`.
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for cross-origin client applications
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global client, lock, and cache states
portal_client = UrjaPortalClient()
cache_lock = asyncio.Lock()
meters_cache: List[MeterResponse] = []
meters_by_id: Dict[str, MeterResponse] = {}
transformers_cache: List[TransformerResponse] = []
hierarchy_tree: Dict[str, Any] = {}
cache_last_updated: float = 0.0

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth in kilometers."""
    R = 6371.0  # Earth's mean radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 3)

def build_hierarchy_tree(meters: List[MeterResponse]) -> Dict[str, Any]:
    """Helper to reconstruct network tree: Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meter."""
    root = {"name": "Grid Root", "code": "root", "type": "root", "children": []}
    
    levels = [
        ("zone", "zone"),
        ("circle", "circle"),
        ("division", "division"),
        ("subdivision", "subdivision"),
        ("substation", "substation"),
        ("feeder", "feeder"),
        ("dt", "dt")
    ]
    
    for meter in meters:
        curr_node = root
        if not meter.hierarchy:
            continue
            
        for attr, type_lbl in levels:
            item = getattr(meter.hierarchy, attr, None)
            if not item or not item.code or not item.name:
                continue
                
            found = None
            for child in curr_node["children"]:
                if child["code"] == item.code and child["type"] == type_lbl:
                    found = child
                    break
            
            if not found:
                found = {
                    "name": item.name,
                    "code": item.code,
                    "type": type_lbl,
                    "children": []
                }
                curr_node["children"].append(found)
                
            curr_node = found
            
        meter_leaf = {
            "name": f"Meter {meter.meter_id}",
            "code": meter.meter_id,
            "type": "meter",
            "serial_number": meter.serial_number,
            "status": meter.status
        }
        
        already_exists = any(child["code"] == meter.meter_id and child["type"] == "meter" for child in curr_node["children"])
        if not already_exists:
            curr_node["children"].append(meter_leaf)
            
    return root

def find_subtree(node: Dict[str, Any], target_code: str) -> Optional[Dict[str, Any]]:
    """Recursively traverse hierarchy tree looking for a specific node code."""
    if node.get("code") == target_code:
        return node
    for child in node.get("children", []):
        res = find_subtree(child, target_code)
        if res is not None:
            return res
    return None

async def refresh_all_caches():
    """Background or startup task to pull and format full dataset from legacy portal."""
    global meters_cache, meters_by_id, transformers_cache, hierarchy_tree, cache_last_updated
    async with cache_lock:
        logger.info("Starting background cache sync from legacy portal...")
        try:
            if not portal_client.logged_in:
                portal_client.login()
                
            exported_raw = portal_client.export_meters()
            
            new_meters: List[MeterResponse] = []
            new_meters_by_id: Dict[str, MeterResponse] = {}
            for m in exported_raw:
                meter_id = m.get("meterId")
                if not meter_id:
                    continue
                
                raw_hierarchy = m.get("hierarchy") or {}
                hierarchy_model = MeterHierarchy(
                    zone=HierarchyItem(name=raw_hierarchy.get("zone", {}).get("name", ""), code=raw_hierarchy.get("zone", {}).get("code", "")) if raw_hierarchy.get("zone") else None,
                    circle=HierarchyItem(name=raw_hierarchy.get("circle", {}).get("name", ""), code=raw_hierarchy.get("circle", {}).get("code", "")) if raw_hierarchy.get("circle") else None,
                    division=HierarchyItem(name=raw_hierarchy.get("division", {}).get("name", ""), code=raw_hierarchy.get("division", {}).get("code", "")) if raw_hierarchy.get("division") else None,
                    subdivision=HierarchyItem(name=raw_hierarchy.get("subdivision", {}).get("name", ""), code=raw_hierarchy.get("subdivision", {}).get("code", "")) if raw_hierarchy.get("subdivision") else None,
                    substation=HierarchyItem(name=raw_hierarchy.get("substation", {}).get("name", ""), code=raw_hierarchy.get("substation", {}).get("code", "")) if raw_hierarchy.get("substation") else None,
                    feeder=HierarchyItem(name=raw_hierarchy.get("feeder", {}).get("name", ""), code=raw_hierarchy.get("feeder", {}).get("code", "")) if raw_hierarchy.get("feeder") else None,
                    dt=HierarchyItem(name=raw_hierarchy.get("dt", {}).get("name", ""), code=raw_hierarchy.get("dt", {}).get("code", "")) if raw_hierarchy.get("dt") else None
                )
                
                raw_geo = m.get("geo") or {}
                geo_model = GeoLocation(
                    latitude=portal_client.clean_float(raw_geo.get("lat")),
                    longitude=portal_client.clean_float(raw_geo.get("lng"))
                )
                
                meter_model = MeterResponse(
                    meter_id=meter_id,
                    serial_number=m.get("serialNo"),
                    make=m.get("make"),
                    phase_type=m.get("phaseType"),
                    status=m.get("installStatus"),
                    installation_type=m.get("installType"),
                    build_type=m.get("build"),
                    dt_code=m.get("dtCode"),
                    location=geo_model,
                    hierarchy=hierarchy_model
                )
                new_meters.append(meter_model)
                new_meters_by_id[meter_id] = meter_model
                
            new_transformers: List[TransformerResponse] = []
            page = 1
            has_more = True
            while has_more:
                try:
                    dt_res = portal_client.get_transformers(page)
                    dts = dt_res.get("data", [])
                    total = dt_res.get("total", 0)
                    
                    for dt in dts:
                        new_transformers.append(TransformerResponse(
                            code=dt.get("code", ""),
                            name=dt.get("name", ""),
                            feeder_code=dt.get("feederCode"),
                            capacity_kva=portal_client.clean_float(dt.get("capacityKva"))
                        ))
                    
                    if len(new_transformers) >= total or not dts:
                        has_more = False
                    else:
                        page += 1
                except Exception as e:
                    logger.warning(f"Could not load transformers page {page}: {e}")
                    has_more = False
            
            new_tree = build_hierarchy_tree(new_meters)
            
            meters_cache = new_meters
            meters_by_id = new_meters_by_id
            transformers_cache = new_transformers
            hierarchy_tree = new_tree
            cache_last_updated = time.time()
            logger.info(f"Sync complete. Cached {len(meters_cache)} meters and {len(transformers_cache)} transformers.")
        except Exception as e:
            logger.error(f"Error during cache refresh: {e}", exc_info=True)

async def cache_refresher_task():
    """Periodic loop refreshing cache based on configured TTL."""
    while True:
        await asyncio.sleep(CACHE_REFRESH_INTERVAL)
        await refresh_all_caches()

@app.on_event("startup")
async def startup_event():
    await refresh_all_caches()
    asyncio.create_task(cache_refresher_task())

@app.on_event("shutdown")
def shutdown_event():
    portal_client.close()

# --- API ROUTES ---

@app.get("/api/v1/health", response_model=HealthCheckResponse, tags=["System"])
def health_check():
    """Liveness & readiness health check endpoint for monitoring."""
    now = time.time()
    age = round(now - cache_last_updated, 1) if cache_last_updated > 0 else 0.0
    uptime = round(now - start_time, 1)
    status_str = "healthy" if len(meters_cache) > 0 else "degraded"
    
    return HealthCheckResponse(
        status=status_str,
        portal_connected=portal_client.logged_in,
        cached_meters=len(meters_cache),
        cached_transformers=len(transformers_cache),
        cache_age_seconds=age,
        uptime_seconds=uptime,
        timestamp=datetime.now(timezone.utc).isoformat()
    )

@app.post("/api/v1/cache/refresh", response_model=CacheRefreshResponse, tags=["System"])
async def trigger_cache_refresh():
    """Manually trigger an immediate cache invalidation and re-sync from the legacy portal."""
    await refresh_all_caches()
    return CacheRefreshResponse(
        success=True,
        message="Cache re-sync completed successfully.",
        meters_count=len(meters_cache),
        transformers_count=len(transformers_cache),
        refreshed_at=datetime.now(timezone.utc).isoformat()
    )

@app.post("/api/v1/auth/login", response_model=AuthLoginResponse, tags=["Authentication"])
def login_endpoint(payload: AuthLoginRequest):
    """Authenticate specific credentials with the legacy portal."""
    success = portal_client.login(payload.email, payload.password)
    if success:
        return AuthLoginResponse(
            success=True,
            session_token="mock-token-session-valid",
            message="Successfully logged into legacy portal and validated credentials."
        )
    raise HTTPException(status_code=401, detail="Invalid credentials for legacy portal.")

@app.get("/api/v1/meters", response_model=Dict[str, Any], tags=["Meters"])
def list_meters(
    q: Optional[str] = Query(None, description="Search query for meter ID or serial number"),
    status: Optional[str] = Query(None, description="Filter by operational status (Active, Decommissioned, Suspended)"),
    make: Optional[str] = Query(None, description="Filter by meter manufacturer (e.g. HPL, Genus, Secure)"),
    dt_code: Optional[str] = Query(None, description="Filter by Distribution Transformer code"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Retrieve normalized meters from cache with multi-attribute filtering, search, and pagination."""
    filtered = meters_cache
    
    if q:
        q_lower = q.lower()
        filtered = [
            m for m in filtered 
            if q_lower in m.meter_id.lower() or (m.serial_number and q_lower in m.serial_number.lower())
        ]
        
    if status:
        status_lower = status.lower()
        filtered = [m for m in filtered if m.status and m.status.lower() == status_lower]
        
    if make:
        make_lower = make.lower()
        filtered = [m for m in filtered if m.make and m.make.lower() == make_lower]
        
    if dt_code:
        dt_lower = dt_code.lower()
        filtered = [m for m in filtered if m.dt_code and m.dt_code.lower() == dt_lower]
        
    total = len(filtered)
    start = (page - 1) * limit
    end = start + limit
    paginated = filtered[start:end]
    
    return {
        "data": paginated,
        "total": total,
        "page": page,
        "limit": limit,
        "cached_last_updated": cache_last_updated
    }

@app.get("/api/v1/meters/nearby", response_model=NearbyMetersListResponse, tags=["Meters"])
def get_nearby_meters(
    lat: float = Query(..., description="Latitude of the search center coordinate", ge=-90.0, le=90.0),
    lng: float = Query(..., description="Longitude of the search center coordinate", ge=-180.0, le=180.0),
    radius_km: float = Query(5.0, description="Search radius in kilometers", gt=0.0, le=100.0),
    status: Optional[str] = Query(None, description="Optional filter by meter status (e.g. Active)"),
    limit: int = Query(50, description="Maximum number of nearby meters to return", ge=1, le=200)
):
    """
    Geo-spatial query layer: Locate meters within a specified radius from GPS coordinates.
    Uses the great-circle Haversine formula and returns meters sorted by proximity.
    """
    results: List[NearbyMeterResponse] = []
    status_lower = status.lower() if status else None
    
    for meter in meters_cache:
        if not meter.location or meter.location.latitude is None or meter.location.longitude is None:
            continue
            
        if status_lower and (not meter.status or meter.status.lower() != status_lower):
            continue
            
        dist = haversine_distance(lat, lng, meter.location.latitude, meter.location.longitude)
        if dist <= radius_km:
            results.append(NearbyMeterResponse(
                meter_id=meter.meter_id,
                serial_number=meter.serial_number,
                make=meter.make,
                phase_type=meter.phase_type,
                status=meter.status,
                dt_code=meter.dt_code,
                location=meter.location,
                distance_km=dist
            ))
            
    # Sort closest first
    results.sort(key=lambda x: x.distance_km)
    paginated = results[:limit]
    
    return NearbyMetersListResponse(
        origin={"latitude": lat, "longitude": lng},
        radius_km=radius_km,
        total=len(results),
        data=paginated
    )

@app.get("/api/v1/meters/{meter_id}", response_model=MeterResponse, tags=["Meters"])
def get_meter_details(meter_id: str):
    """Retrieve details for a specific smart meter."""
    if meter_id not in meters_by_id:
        raise HTTPException(status_code=404, detail=f"Meter with ID {meter_id} not found.")
    return meters_by_id[meter_id]

@app.get("/api/v1/meters/{meter_id}/consumption", response_model=ConsumptionResponse, tags=["Meters"])
def get_meter_consumption(meter_id: str):
    """Retrieve timeseries consumption history for a specific meter from the legacy portal."""
    if meter_id not in meters_by_id:
        raise HTTPException(status_code=404, detail=f"Meter with ID {meter_id} not found.")
        
    raw_readings = portal_client.get_meter_energy(meter_id)
    readings_list = raw_readings.get("data", [])
    
    cleaned_readings: List[ConsumptionReading] = []
    for r in readings_list:
        raw_ts = r.get("timestamp", "")
        cleaned_readings.append(ConsumptionReading(
            timestamp=portal_client.clean_timestamp(raw_ts),
            raw_timestamp=raw_ts,
            kwh=portal_client.clean_float(r.get("kwh")),
            kvah=portal_client.clean_float(r.get("kvah")),
            voltage_r=portal_client.clean_float(r.get("voltR"))
        ))
        
    try:
        cleaned_readings.sort(key=lambda x: x.timestamp)
    except Exception:
        pass
        
    return ConsumptionResponse(
        meter_id=meter_id,
        readings=cleaned_readings
    )

@app.get("/api/v1/transformers", response_model=Dict[str, Any], tags=["Transformers"])
def list_transformers(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Retrieve list of distribution transformers in the system."""
    total = len(transformers_cache)
    start = (page - 1) * limit
    end = start + limit
    paginated = transformers_cache[start:end]
    
    return {
        "data": paginated,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/v1/hierarchy", response_model=Dict[str, Any], tags=["Hierarchy"])
def get_network_hierarchy():
    """Retrieve the full reconstructed network hierarchy tree."""
    return hierarchy_tree

@app.get("/api/v1/hierarchy/{code}", response_model=Dict[str, Any], tags=["Hierarchy"])
def get_hierarchy_subtree(code: str):
    """Retrieve the network sub-tree starting from a specific node code (e.g. DT-001, F-001, Z-01)."""
    subtree = find_subtree(hierarchy_tree, code)
    if not subtree:
        raise HTTPException(status_code=404, detail=f"Hierarchy node with code '{code}' not found.")
    return subtree

@app.get("/api/v1/analytics/summary", response_model=AnalyticsSummaryResponse, tags=["Analytics"])
def get_analytics_summary():
    """
    Provides aggregated operational statistics, manufacturer market share,
    phase distribution, transformer load rankings, and health anomalies.
    """
    total_meters = len(meters_cache)
    total_transformers = len(transformers_cache)
    
    # Status counters
    active_cnt = sum(1 for m in meters_cache if m.status and m.status.lower() == "active")
    decom_cnt = sum(1 for m in meters_cache if m.status and m.status.lower() == "decommissioned")
    susp_cnt = sum(1 for m in meters_cache if m.status and m.status.lower() == "suspended")
    other_cnt = total_meters - (active_cnt + decom_cnt + susp_cnt)
    status_breakdown = StatusBreakdown(
        active=active_cnt,
        decommissioned=decom_cnt,
        suspended=susp_cnt,
        other=other_cnt
    )
    
    # Manufacturer make breakdown
    make_counts: Dict[str, int] = {}
    for m in meters_cache:
        make_name = m.make if m.make else "Unknown"
        make_counts[make_name] = make_counts.get(make_name, 0) + 1
        
    make_breakdown = [
        MakeBreakdown(
            make=k,
            count=v,
            percentage=round((v / total_meters * 100.0), 1) if total_meters > 0 else 0.0
        )
        for k, v in sorted(make_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # Phase distribution
    phase_counts: Dict[str, int] = {}
    for m in meters_cache:
        p_name = m.phase_type.capitalize() if m.phase_type else "Unknown"
        phase_counts[p_name] = phase_counts.get(p_name, 0) + 1
        
    phase_breakdown = [
        PhaseBreakdown(phase=k, count=v)
        for k, v in sorted(phase_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # Transformers load
    dt_meter_counts: Dict[str, int] = {}
    for m in meters_cache:
        if m.dt_code:
            dt_meter_counts[m.dt_code] = dt_meter_counts.get(m.dt_code, 0) + 1
            
    dt_lookup = {t.code: t for t in transformers_cache}
    top_transformers = []
    for dt_code, count in sorted(dt_meter_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        t_obj = dt_lookup.get(dt_code)
        name = t_obj.name if t_obj else f"Transformer {dt_code}"
        cap = t_obj.capacity_kva if t_obj else None
        top_transformers.append(DTLoadItem(
            dt_code=dt_code,
            dt_name=name,
            meter_count=count,
            capacity_kva=cap
        ))
        
    # Anomalies
    missing_geo = sum(1 for m in meters_cache if not m.location or m.location.latitude is None or m.location.longitude is None)
    unlinked_dt = sum(1 for m in meters_cache if not m.dt_code)
    inactive_cnt = decom_cnt + susp_cnt
    
    anomalies = AnomaliesSummary(
        missing_geo_count=missing_geo,
        unlinked_dt_count=unlinked_dt,
        inactive_meter_count=inactive_cnt
    )
    
    return AnalyticsSummaryResponse(
        total_meters=total_meters,
        total_transformers=total_transformers,
        status_breakdown=status_breakdown,
        make_breakdown=make_breakdown,
        phase_breakdown=phase_breakdown,
        top_transformers_by_meters=top_transformers,
        anomalies=anomalies,
        cache_last_updated=cache_last_updated
    )

# Rendered API Documentation with Scalar
@app.get("/scalar", response_class=HTMLResponse, tags=["System"], include_in_schema=False)
def get_scalar_docs():
    """Serves modern Scalar interactive API documentation."""
    return """
    <!doctype html>
    <html>
      <head>
        <title>Urja Meter Ops API - Scalar Reference</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" type="image/svg+xml" href="https://scalar.com/favicon.svg" />
      </head>
      <body>
        <script id="api-reference" data-url="/openapi.json"></script>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
      </body>
    </html>
    """

# Serve Dashboard UI at root /
@app.get("/", include_in_schema=False)
def serve_dashboard():
    return FileResponse("static/index.html")

# Mount Static assets (css, js, icons)
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting API wrapper on {HOST}:{PORT}...")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
