from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class GeoLocation(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class HierarchyItem(BaseModel):
    name: str
    code: str

class MeterHierarchy(BaseModel):
    zone: Optional[HierarchyItem] = None
    circle: Optional[HierarchyItem] = None
    division: Optional[HierarchyItem] = None
    subdivision: Optional[HierarchyItem] = None
    substation: Optional[HierarchyItem] = None
    feeder: Optional[HierarchyItem] = None
    dt: Optional[HierarchyItem] = None

class MeterResponse(BaseModel):
    meter_id: str = Field(..., description="Unique identifier of the smart meter")
    serial_number: Optional[str] = Field(None, description="Serial number of the meter")
    make: Optional[str] = Field(None, description="Manufacturer of the meter")
    phase_type: Optional[str] = Field(None, description="Phase type (e.g., single, three)")
    status: Optional[str] = Field(None, description="Current operational status")
    installation_type: Optional[str] = Field(None, description="Installation configuration")
    build_type: Optional[str] = Field(None, description="Build or version generation")
    dt_code: Optional[str] = Field(None, description="Associated Distribution Transformer code")
    location: Optional[GeoLocation] = Field(None, description="Geo coordinates of the meter")
    hierarchy: Optional[MeterHierarchy] = Field(None, description="Full electrical network parent structure")

class NearbyMeterResponse(BaseModel):
    meter_id: str
    serial_number: Optional[str] = None
    make: Optional[str] = None
    phase_type: Optional[str] = None
    status: Optional[str] = None
    dt_code: Optional[str] = None
    location: Optional[GeoLocation] = None
    distance_km: float = Field(..., description="Distance in kilometers from search coordinates")

class NearbyMetersListResponse(BaseModel):
    origin: Dict[str, float] = Field(..., description="Latitude and longitude coordinates searched")
    radius_km: float = Field(..., description="Search radius in kilometers")
    total: int = Field(..., description="Number of meters found within radius")
    data: List[NearbyMeterResponse]

class TransformerResponse(BaseModel):
    code: str = Field(..., description="Unique identifier of the distribution transformer")
    name: str = Field(..., description="Human-readable name of the DT")
    feeder_code: Optional[str] = Field(None, description="Associated Feeder code")
    capacity_kva: Optional[float] = Field(None, description="Capacity in kVA")

class ConsumptionReading(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 formatted timestamp")
    raw_timestamp: str = Field(..., description="Original raw timestamp from the portal")
    kwh: Optional[float] = Field(None, description="Active energy reading in kWh")
    kvah: Optional[float] = Field(None, description="Apparent energy reading in kVAh")
    voltage_r: Optional[float] = Field(None, description="Voltage on phase R (V)")

class ConsumptionResponse(BaseModel):
    meter_id: str
    readings: List[ConsumptionReading]

class HierarchyNode(BaseModel):
    name: str
    code: str
    type: str  # zone, circle, division, subdivision, substation, feeder, dt, meter
    children: List[Any] = []

# Resolve self-referencing forward reference for recursive Pydantic model
HierarchyNode.model_rebuild()

class AuthLoginRequest(BaseModel):
    email: str
    password: str

class AuthLoginResponse(BaseModel):
    success: bool
    session_token: str
    message: str

# Analytics Models
class MakeBreakdown(BaseModel):
    make: str
    count: int
    percentage: float

class PhaseBreakdown(BaseModel):
    phase: str
    count: int

class StatusBreakdown(BaseModel):
    active: int
    decommissioned: int
    suspended: int
    other: int

class DTLoadItem(BaseModel):
    dt_code: str
    dt_name: str
    meter_count: int
    capacity_kva: Optional[float] = None

class AnomaliesSummary(BaseModel):
    missing_geo_count: int
    unlinked_dt_count: int
    inactive_meter_count: int

class AnalyticsSummaryResponse(BaseModel):
    total_meters: int
    total_transformers: int
    status_breakdown: StatusBreakdown
    make_breakdown: List[MakeBreakdown]
    phase_breakdown: List[PhaseBreakdown]
    top_transformers_by_meters: List[DTLoadItem]
    anomalies: AnomaliesSummary
    cache_last_updated: float

class HealthCheckResponse(BaseModel):
    status: str
    portal_connected: bool
    cached_meters: int
    cached_transformers: int
    cache_age_seconds: float
    uptime_seconds: float
    timestamp: str

class CacheRefreshResponse(BaseModel):
    success: bool
    message: str
    meters_count: int
    transformers_count: int
    refreshed_at: str
