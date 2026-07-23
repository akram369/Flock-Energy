import logging
import asyncio
import time
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any

from app.config import HOST, PORT, CACHE_REFRESH_INTERVAL
from app.client import UrjaPortalClient
from app.models import (
    MeterResponse, GeoLocation, MeterHierarchy, HierarchyItem,
    TransformerResponse, ConsumptionResponse, ConsumptionReading,
    HierarchyNode, AuthLoginRequest, AuthLoginResponse
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("urja_api_wrapper")

# Initialize FastAPI App
app = FastAPI(
    title="Flock Energy - Urja Meter Ops API",
    description="Clean, modern, documented REST API wrapping the legacy Urja Meter Ops portal. Serves a dashboard UI at /.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for easy cross-origin integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global clients & caches
portal_client = UrjaPortalClient()
cache_lock = asyncio.Lock()
meters_cache: List[MeterResponse] = []
meters_by_id: Dict[str, MeterResponse] = {}
transformers_cache: List[TransformerResponse] = []
hierarchy_tree: Dict[str, Any] = {}
cache_last_updated: float = 0.0

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
            
        # Traverse down hierarchy levels
        for attr, type_lbl in levels:
            item = getattr(meter.hierarchy, attr, None)
            if not item or not item.code or not item.name:
                continue
                
            # Look for existing child node
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
            
        # Add the meter itself as a leaf node
        meter_leaf = {
            "name": f"Meter {meter.meter_id}",
            "code": meter.meter_id,
            "type": "meter",
            "serial_number": meter.serial_number,
            "status": meter.status
        }
        
        # Verify not duplicate
        already_exists = False
        for child in curr_node["children"]:
            if child["code"] == meter.meter_id and child["type"] == "meter":
                already_exists = True
                break
        if not already_exists:
            curr_node["children"].append(meter_leaf)
            
    return root

async def refresh_all_caches():
    """Background or startup task to pull and format full dataset from legacy portal."""
    global meters_cache, meters_by_id, transformers_cache, hierarchy_tree, cache_last_updated
    async with cache_lock:
        logger.info("Starting background cache sync from legacy portal...")
        try:
            # 1. Ensure logged in
            if not portal_client.logged_in:
                portal_client.login()
                
            # 2. Fetch full meters dataset using signed export
            exported_raw = portal_client.export_meters()
            
            # Format and normalize meters
            new_meters: List[MeterResponse] = []
            new_meters_by_id: Dict[str, MeterResponse] = {}
            for m in exported_raw:
                meter_id = m.get("meterId")
                if not meter_id:
                    continue
                
                # Normalize hierarchy
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
                
                # Normalize geo
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
                
            # 3. Fetch all transformers (paginated loop)
            new_transformers: List[TransformerResponse] = []
            page = 1
            has_more = True
            while has_more:
                logger.info(f"Fetching transformers page {page}...")
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
            
            # 4. Build Hierarchy Tree
            new_tree = build_hierarchy_tree(new_meters)
            
            # Update cache states
            meters_cache = new_meters
            meters_by_id = new_meters_by_id
            transformers_cache = new_transformers
            hierarchy_tree = new_tree
            cache_last_updated = time.time()
            logger.info(f"Sync complete. Cached {len(meters_cache)} meters and {len(transformers_cache)} transformers.")
        except Exception as e:
            logger.error(f"Error during background cache refresh: {e}", exc_info=True)

async def cache_refresher_task():
    """Infinitely loop refreshing caches based on interval."""
    while True:
        await asyncio.sleep(CACHE_REFRESH_INTERVAL)
        await refresh_all_caches()

@app.on_event("startup")
async def startup_event():
    # Sync cache synchronously on startup so API is ready immediately
    await refresh_all_caches()
    # Start loop in background
    asyncio.create_task(cache_refresher_task())

# --- API ROUTES ---

@app.post("/api/v1/auth/login", response_model=AuthLoginResponse, tags=["Authentication"])
def login_endpoint(payload: AuthLoginRequest):
    """Authenticate specific credentials with the legacy portal."""
    temp_client = UrjaPortalClient()
    success = temp_client.login(payload.email, payload.password)
    if success:
        # Generate token (in a real app, JWT or session token; here, returning mock/success status)
        return AuthLoginResponse(
            success=True,
            session_token="mock-token-session-valid",
            message="Successfully logged into legacy portal and validated credentials."
        )
    raise HTTPException(status_code=401, detail="Invalid credentials for legacy portal.")

@app.get("/api/v1/meters", response_model=Dict[str, Any], tags=["Meters"])
def list_meters(
    q: Optional[str] = Query(None, description="Search search query for meter ID or serial number"),
    status: Optional[str] = Query(None, description="Filter by installation status (Active, Decommissioned, etc.)"),
    make: Optional[str] = Query(None, description="Filter by meter manufacturer"),
    dt_code: Optional[str] = Query(None, description="Filter by Distribution Transformer code"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Retrieve normalized meters from cache, supporting filtering, search, and pagination."""
    filtered = meters_cache
    
    # Apply search query
    if q:
        q_lower = q.lower()
        filtered = [
            m for m in filtered 
            if q_lower in m.meter_id.lower() or (m.serial_number and q_lower in m.serial_number.lower())
        ]
        
    # Apply status filter
    if status:
        status_lower = status.lower()
        filtered = [m for m in filtered if m.status and m.status.lower() == status_lower]
        
    # Apply make filter
    if make:
        make_lower = make.lower()
        filtered = [m for m in filtered if m.make and m.make.lower() == make_lower]
        
    # Apply DT filter
    if dt_code:
        dt_lower = dt_code.lower()
        filtered = [m for m in filtered if m.dt_code and m.dt_code.lower() == dt_lower]
        
    # Pagination
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
        
    # Retrieve dynamic readings from the legacy energy api
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
        
    # Sort readings by timestamp chronologically
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
    """Retrieve list of transformers in the system (served from cache)."""
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

# --- FRONTEND CLIENT SERVING ---

# Serve Dashboard UI at root /
@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

# Mount Static folder for style.css and app.js
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting API wrapper on {HOST}:{PORT}...")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
