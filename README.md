# Urja Meter Ops API Wrapper & Operations Dashboard (v2.0)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Welcome! This repository implements a production-grade **REST API Service** and **Operations Dashboard** built over the legacy "Urja Meter Ops" utility portal ([https://urja-ops.flockenergy.tech](https://urja-ops.flockenergy.tech)).

It automates authentication, executes HMAC-SHA256 request signing for bulk synchronization, normalizes dirty string telemetry into typed ISO-8601 models, provides a sub-millisecond in-memory query and geo-spatial search layer, and serves an interactive dark-mode operations dashboard featuring live consumption graphs, a Leaflet.js grid map, and a hierarchy explorer.

---

## 🏗️ Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │              Downstream Clients              │
                      │  (Data Teams, Microservices, Field Ops Apps) │
                      └──────────────────────┬───────────────────────┘
                                             │ REST / JSON (sub-ms)
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Urja Meter Ops API Wrapper (Port 8000)                          │
│                                                                                        │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  ┌────────────────────────┐  │
│  │    REST Router Layer    │  │    Geo & Query Engine   │  │  Interactive Dashboard │  │
│  │ • /api/v1/meters        │  │ • Haversine Radius Near │  │ • Leaflet.js Grid Map  │  │
│  │ • /api/v1/hierarchy     │  │ • Status/Make/DT Filter │  │ • Chart.js Energy Logs │  │
│  │ • /api/v1/analytics     │  │ • Subtree Node Search   │  │ • Hierarchy Explorer   │  │
│  └────────────┬────────────┘  └────────────┬────────────┘  └────────────────────────┘  │
│               │                            │                                           │
│               ▼                            ▼                                           │
│  ┌──────────────────────────────────────────────────────┐  ┌────────────────────────┐  │
│  │             Thread-Safe In-Memory Cache              │  │  Local Fallback Cache  │  │
│  │     (403 Meters, 40 Transformers, Full Hierarchy)    │◀─┤ (snapshot_cache.json)  │  │
│  └───────────────────────────▲──────────────────────────┘  └────────────────────────┘  │
│                              │                                                         │
│                              │ Background Sync Worker (5m TTL / Manual Flush)          │
│                              │                                                         │
│  ┌───────────────────────────┴──────────────────────────┐                              │
│  │                     Legacy Client Adapter                    │                      │
│  │  • Session Cookie Persistence & Re-Authentication    │                              │
│  │  • HMAC-SHA256 Bulk Request Signer (/portal/export)  │                              │
│  │  • Telemetry Cleanser (Floats, Timestamps, Nulls)    │                              │
│  └───────────────────────────┬──────────────────────────┘                              │
└──────────────────────────────┼─────────────────────────────────────────────────────────┘
                               │ HTTPS (Session Cookie + HMAC Signature)
                               ▼
            ┌──────────────────────────────────────┐
            │   Legacy Urja Meter Ops Web Portal   │
            │ (https://urja-ops.flockenergy.tech)  │
            └──────────────────────────────────────┘
```

---

## 🚀 Key Highlights & Built Extensions

1. **Cryptographic Request Signer**: Reverse-engineered the HMAC-SHA256 signature scheme required by the legacy `/portal/export` endpoint.
2. **Sub-Millisecond In-Memory Index**: Indexes the full 403-meter dataset and 40 distribution transformers in under 2 seconds. Subsequent reads, searches, and filters execute in **under 1 millisecond** without stressing the legacy portal.
3. **Geo-Spatial Query Layer**: Implements great-circle Haversine calculations (`/api/v1/meters/nearby`) to answer proximity questions (*"Which meters are within 5 km of these coordinates?"*).
4. **Network Topology Reconstructor**: Reconstructs the electrical grid tree (`Zone → Circle → Division → Subdivision → Substation → Feeder → DT → Meter`) accessible at `/api/v1/hierarchy` and `/api/v1/hierarchy/{code}`.
5. **Interactive Operations Dashboard**: Features an interactive **Leaflet.js map** plotting all 403 meters with status color-coding, a radius search tool, recursive hierarchy navigation, and **Chart.js graphs** for kWh/kVAh and phase voltage.
6. **Grid Health & Analytics**: Provides grid-wide operational metrics, manufacturer market share, phase configuration distribution, and anomaly detection at `/api/v1/analytics/summary`.
7. **Offline Startup Resilience**: Employs an automatic fallback snapshot cache (`data/snapshot_cache.json`) so the service starts cleanly even during legacy portal downtime.
8. **Automated Session Recovery**: Transparently detects session timeouts (302 redirects, 401s, 405s) and re-authenticates with exponential backoff.

---

## 📁 Repository Structure

```
flock-energy-api/
│
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI routes, cache manager, & background worker
│   ├── client.py            # Legacy HTTP adapter, HMAC request signing, & snapshot fallback
│   ├── models.py            # Typed Pydantic schemas (snake_case JSON output)
│   └── config.py            # Environment configurations & default credentials
│
├── static/                  # Modern Web Client SPA
│   ├── index.html           # Dashboard UI (Table, Leaflet Map, Analytics)
│   ├── style.css            # Dark/Light glassmorphic design system
│   └── app.js               # Frontend fetch logic, Leaflet map, & Chart.js integration
│
├── tests/
│   └── test_api.py          # 19 Unit & integration tests
│
├── data/
│   └── snapshot_cache.json  # Fallback snapshot for offline boot resilience
│
├── openapi.json             # Generated OpenAPI 3.1.0 specification
├── PROTOCOL.md              # In-depth legacy portal protocol documentation
├── REFLECTION.md            # Answers to reflection questions & Scale Analysis
├── README.md                # Master onboarding guide (this file)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Production container image definition
├── docker-compose.yml       # Single-command orchestration
└── generate_openapi.py      # Utility script to export openapi.json
```

---

## 🛠️ Quickstart: Setup & Running

### Option A: Local Python Setup

#### 1. Prerequisites
- Python 3.10 or higher (tested on Python 3.10 - 3.14).
- Dependencies: `fastapi`, `uvicorn`, `httpx`, `pydantic`.

#### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/flock-energy-api.git
cd flock-energy-api

# Install dependencies
pip install -r requirements.txt
```

#### 3. Configuration (Optional)
The service loads settings from environment variables with safe defaults:
| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORTAL_URL` | Base URL of legacy system | `https://urja-ops.flockenergy.tech` |
| `URJA_USERNAME` | Operator login email | `operator@urja.local` |
| `URJA_PASSWORD` | Operator login password | `urja-ops-2026` |
| `CACHE_REFRESH_INTERVAL` | Background cache sync interval (seconds) | `300` (5 minutes) |
| `API_HOST` | Host address to bind | `0.0.0.0` |
| `API_PORT` | Port to bind | `8000` |

#### 4. Run the Server
```bash
python -m uvicorn app.main:app --reload --port 8000
```

---

### Option B: Docker Setup
Run the entire service with zero local dependencies:
```bash
docker compose up -d --build
```

---

### 🌐 Accessing the Application
Once running:
- **Operations Dashboard**: Open [http://localhost:8000/](http://localhost:8000/) in your browser.
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Scalar Documentation**: [http://localhost:8000/scalar](http://localhost:8000/scalar)
- **Redoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw OpenAPI Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 🧪 Running Automated Tests

Run the complete 19-test suite covering authentication, pagination, geo-search, analytics, and error handling:
```bash
python -m unittest tests/test_api.py
```

---

## 📡 API Endpoints & Sample Requests

### 1. System Health Check
- **Endpoint**: `GET /api/v1/health`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/health"
  ```
- **Response**:
  ```json
  {
    "status": "healthy",
    "portal_connected": true,
    "cached_meters": 403,
    "cached_transformers": 40,
    "cache_age_seconds": 18.4,
    "uptime_seconds": 124.2,
    "timestamp": "2026-09-10T22:30:00.000000Z"
  }
  ```

### 2. List & Filter Smart Meters
- **Endpoint**: `GET /api/v1/meters`
- **Query Parameters**: `q`, `status`, `make`, `dt_code`, `page`, `limit`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/meters?status=Active&make=HPL&limit=2"
  ```
- **Response**:
  ```json
  {
    "data": [
      {
        "meter_id": "J100002",
        "serial_number": "SE53421",
        "make": "HPL",
        "phase_type": "single",
        "status": "Active",
        "installation_type": "Whole Current",
        "build_type": "legacy",
        "dt_code": "DT-001",
        "location": {
          "latitude": 26.9388,
          "longitude": 75.8309
        },
        "hierarchy": {
          "zone": { "name": "Jaipur Zone 1", "code": "Z-01" },
          "dt": { "name": "Malviya Nagar DT 1", "code": "DT-001" }
        }
      }
    ],
    "total": 182,
    "page": 1,
    "limit": 2,
    "cached_last_updated": 1721755400.0
  }
  ```

### 3. Geo-Spatial Nearby Radius Search
- **Endpoint**: `GET /api/v1/meters/nearby`
- **Query Parameters**: `lat`, `lng`, `radius_km` (default 5.0), `status`, `limit`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/meters/nearby?lat=26.9389&lng=75.8309&radius_km=3.0&limit=2"
  ```
- **Response**:
  ```json
  {
    "origin": { "latitude": 26.9389, "longitude": 75.8309 },
    "radius_km": 3.0,
    "total": 12,
    "data": [
      {
        "meter_id": "J100000",
        "serial_number": "SE33962",
        "make": "HPL",
        "status": "Active",
        "dt_code": "DT-001",
        "distance_km": 0.007
      }
    ]
  }
  ```

### 4. Meter Details
- **Endpoint**: `GET /api/v1/meters/{meter_id}`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/meters/J100000"
  ```

### 5. Consumption Readings (Energy & Voltage)
- **Endpoint**: `GET /api/v1/meters/{meter_id}/consumption`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/meters/J100000/consumption"
  ```
- **Response**:
  ```json
  {
    "meter_id": "J100000",
    "readings": [
      {
        "timestamp": "2026-06-23T23:30:00",
        "raw_timestamp": "23/06/2026 23:30",
        "kwh": 48438.74,
        "kvah": 52313.84,
        "voltage_r": 226.0
      }
    ]
  }
  ```

### 6. Grid Health & Analytics Summary
- **Endpoint**: `GET /api/v1/analytics/summary`
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/analytics/summary"
  ```

### 7. Electrical Network Hierarchy
- **Endpoint**: `GET /api/v1/hierarchy` (Entire tree) or `GET /api/v1/hierarchy/{code}` (Subtree)
- **Sample Request**:
  ```bash
  curl -s "http://localhost:8000/api/v1/hierarchy/DT-001"
  ```

### 8. Manual Cache Invalidation Trigger
- **Endpoint**: `POST /api/v1/cache/refresh`
- **Sample Request**:
  ```bash
  curl -s -X POST "http://localhost:8000/api/v1/cache/refresh"
  ```

---

## 🧠 Design Decisions & Trade-Offs

- **Aggressive Caching for High Performance**: The legacy portal takes ~500ms to return a single page of 20 meters. Querying it synchronously on every API call would result in a sluggish API and risk causing a denial-of-service on the legacy server. We bypass this by requesting the `/portal/export` bulk endpoint once at startup and caching all 403 meters in memory with a 5-minute background refresh. Reads, searches, and spatial queries resolve in **sub-millisecond times**.
- **Dynamic On-Demand Telemetry**: Meter profiles and locations are cached, but consumption telemetry histories are fetched **dynamically** from the legacy portal on-demand. This guarantees downstream users always receive the latest readings without consuming gigabytes of server RAM storing millions of timeseries points.
- **Data Cleansing & Type Normalization**: Legacy data formats presented numerous integration hurdles (active energy returned as `"—"`, voltage strings like `"226"`, legacy date format `DD/MM/YYYY HH:MM`). The wrapper normalizes all values into strict typed floats, `None`, and ISO-8601 timestamps.
- **FastAPI Framework Choice**: FastAPI provides native Pydantic schema validation, high async concurrency on ASGI (Uvicorn), and automatic OpenAPI 3.1 specification generation.

---

## 🧱 What Was Intentionally Skipped & Future Improvements

- **Persistent Relational Database**: Currently, cache lives in application memory with a local JSON snapshot fallback. In a large enterprise environment, this would be backed by PostgreSQL with PostGIS or SQLite with the R*Tree extension.
- **Multi-Tenant User Management**: The service uses a shared operator session against the legacy portal. Production deployments would issue tenant-scoped OAuth2 / JWT tokens with role-based access control.
- **Historical Telemetry Ingestion Pipeline**: Historical consumption could be streamed into a partitioned columnar store (ClickHouse or TimescaleDB) to enable long-term interval aggregation and transformer load forecasting.

---

## 📄 Key Document Links

- **Protocol Findings**: Full legacy reverse-engineering writeup in [PROTOCOL.md](file:///c:/Users/22000/Downloads/Flock-Energy-main/PROTOCOL.md).
- **OpenAPI 3.1 Specification**: Raw JSON contract in [openapi.json](file:///c:/Users/22000/Downloads/Flock-Energy-main/openapi.json).
- **Reflections & Scale Analysis**: Detailed evaluation questions and mathematical scale analysis in [REFLECTION.md](file:///c:/Users/22000/Downloads/Flock-Energy-main/REFLECTION.md).

---

## 📝 Reflection Summary

Detailed answers to all 5 evaluation questions plus the **Scale Analysis Note** are documented in [REFLECTION.md](file:///c:/Users/22000/Downloads/Flock-Energy-main/REFLECTION.md). In summary:
1. **Assumptions**: We assumed `/portal/export?page=1` provides full un-paginated coverage, that the network topology is strictly hierarchical, and that operator credentials represent a permanent gateway service account.
2. **Hardest Challenge**: Reverse-engineering SvelteKit's progressive form submission and deciphering the HMAC-SHA256 canonical string required for signed bulk exports.
3. **With Another Day**: We would implement SQLite R*Tree persistence and timeseries pre-aggregation.
4. **Mistakes Made**: Initially serial-scraping HTML pages before discovering the signed bulk export endpoint.
5. **Self-Criticism**: Global cache variables limit horizontal container scaling without a centralized Redis cache.
6. **Scale Analysis**: We analyzed performance across 1,000, 50,000, 500,000, and 10,000,000 smart meters, detailing the exact architecture transitions required (SQLite R*Tree → PostgreSQL PostGIS → Redis + ClickHouse + Kafka).
