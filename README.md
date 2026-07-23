# Urja Meter Ops API Wrapper & Dashboard (v2.0)

Welcome! This repository implements a clean, modern, and high-performance **REST API Wrapper** and an interactive **Operations Dashboard** built over the legacy, ageing SvelteKit portal "Urja Meter Ops" (https://urja-ops.flockenergy.tech).

It automates authentication, handles HMAC request signing for the legacy bulk export, normalizes dirty/string telemetry data into typed models, maintains a thread-safe in-memory index cache, and serves a premium dark-themed ops dashboard featuring real-time consumption graphs, active counters, and a grid hierarchy explorer.

---

## 🚀 Key Highlights & Extensions Built

1. **Cryptographic Request Signer**: Reverse-engineered the HMAC-SHA256 request signature mechanism required by the portal's `/portal/export` endpoint.
2. **In-Memory Cache & Search Index**: Implemented a thread-safe startup cache that fetches and indexes the entire 403-meter dataset and 40 transformers in under 2 seconds. Subsequent reads, searches, and filters run in **sub-millisecond times** without stressing the legacy portal.
3. **Network Hierarchy Tree builder**: Dynamically parses the nested zone-to-meter relational data to reconstruct a complete, traversable electrical grid topology (`Zone -> Circle -> Division -> Subdivision -> Sub Station -> Feeder -> DT -> Meter`).
4. **Data Normalization Engine**: Sanitizes legacy anomalies, parsing legacy date formats (`DD/MM/YYYY HH:MM`) into ISO-8601 timestamps and dirty voltage/energy strings (`"48438.74"`, `"—"`) into floating-point numbers or `None`.
5. **Modern Web Client**: Created a responsive dark dashboard using Glassmorphism, custom CSS variables, and Chart.js. Users can navigate nodes recursively or view line graphs detailing 15/30-minute active/apparent energy and line voltages.
6. **Robust Session Recovery**: Client adapter automatically detects session timeouts (302 redirects to login, 401s, 405s) and transparently handles re-login and request retries.

---

## 📁 Repository Structure

```
flock-energy-api/
│
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI Application routes & cache worker
│   ├── client.py            # Legacy portal HTTP adapter & request signing
│   ├── models.py            # Pydantic schema definitions (snake_case output)
│   └── config.py            # Config variables & environment loaders
│
├── static/                  # Web Client files
│   ├── index.html           # SPA Dashboard HTML structure
│   ├── style.css            # Custom vanilla CSS stylesheet
│   └── app.js               # Frontend fetch and Chart.js integration logic
│
├── tests/
│   └── test_api.py          # 12 Integration & Unit tests for all endpoints
│
├── openapi.json             # Generated OpenAPI 3.1.0 specification
├── PROTOCOL.md              # Documentation of the legacy portal's mechanics
├── requirements.txt         # Python package dependencies
└── generate_openapi.py      # Utility to dump OpenAPI spec from code routes
```

---

## 🛠️ Setup & Running

### 1. Prerequisites
- **Python**: v3.10+ (tested on Python 3.14)
- Dependencies: `fastapi`, `uvicorn`, `httpx`, `pydantic`.

### 2. Installation
Clone the repository and install the requirements:
```bash
pip install -r requirements.txt
```

### 3. Configuration (Optional)
The application loads settings from environment variables. If not provided, it falls back to the default credentials:
- `PORTAL_URL`: Base URL of legacy system (Default: `https://urja-ops.flockenergy.tech`)
- `URJA_USERNAME`: Login email (Default: `operator@urja.local`)
- `URJA_PASSWORD`: Login password (Default: `urja-ops-2026`)
- `CACHE_REFRESH_INTERVAL`: Seconds between background cache syncs (Default: `300` / 5 minutes)

### 4. Running the API & Dashboard
Start the Uvicorn ASGI server:
```bash
python -m uvicorn app.main:app --reload
```
Once started:
- **Web Dashboard**: Open `http://localhost:8000/` in your browser.
- **Interactive Documentation**: Access the Swagger UI at `http://localhost:8000/docs`.

### 5. Running Tests
Run the 12 unit/integration tests verifying endpoint routers, queries, and mocking:
```bash
python -m unittest tests/test_api.py
```

---

## 📡 API Endpoints & Sample Requests

### 1. List Meters
Retrieves a paginated list of smart meters. Filters by search query, operational status, manufacturer make, or DT code. Served instantly from cache.
- **Path**: `GET /api/v1/meters`
- **Query Params**: `q`, `status`, `make`, `dt_code`, `page`, `limit`
- **Sample Request**:
  ```bash
  curl "http://localhost:8000/api/v1/meters?q=J1&status=Active&limit=2"
  ```
- **Response**:
  ```json
  {
    "data": [
      {
        "meter_id": "J100021",
        "serial_number": "SE53421",
        "make": "HPL",
        "phase_type": "single",
        "status": "Active",
        "installation_type": "Whole Current",
        "build_type": "legacy",
        "dt_code": "DT-001",
        "location": { "latitude": 26.9388, "longitude": 75.8309 },
        "hierarchy": { ... }
      }
    ],
    "total": 1,
    "page": 1,
    "limit": 2,
    "cached_last_updated": 1721755400.0
  }
  ```

### 2. Get Meter Details
Retrieves details for a specific smart meter.
- **Path**: `GET /api/v1/meters/{meter_id}`
- **Sample Request**:
  ```bash
  curl "http://localhost:8000/api/v1/meters/J100000"
  ```

### 3. Get Meter Consumption Readings
Fetches real-time timeseries logs from the portal energy endpoint, parsing strings and handling missing data safely.
- **Path**: `GET /api/v1/meters/{meter_id}/consumption`
- **Sample Request**:
  ```bash
  curl "http://localhost:8000/api/v1/meters/J100000/consumption"
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

### 4. Get Grid Network Hierarchy
Exposes the fully reconstructed electrical grid hierarchy.
- **Path**: `GET /api/v1/hierarchy`
- **Sample Request**:
  ```bash
  curl "http://localhost:8000/api/v1/hierarchy"
  ```

---

## 🧠 Design Decisions & Trade-Offs

- **Aggressive Caching for High Performance**: The legacy portal is extremely slow, taking ~0.5 seconds to list a single page of meters. Querying this on every endpoint call would result in a laggy API and could cause denial of service on the legacy portal. We bypass this by requesting the `/portal/export` bulk endpoint once at startup and refreshing it every 5 minutes in a background thread. Reads, pagination, search, and network tree construction are served in **sub-milliseconds** entirely from memory.
- **Stateless Dynamic Telemetry**: While meter profiles and locations are cached, consumption telemetry histories are fetched **dynamically** from the legacy portal on-demand. This guarantees downstream users receive the most up-to-date readings without consuming server RAM storing millions of timeseries points.
- **Data Cleansing & Type Safety**: Legacy data formats represent a significant integrations challenge (e.g. returning active energy value `"—"` or strings like `"48.74"`). The wrapper parses these values into floats and sets invalid strings to `None` so downstream API clients don't encounter parsing issues.
- **FastAPI Framework choice**: Using FastAPI allows us to utilize Pydantic validation models, gain automatic serialization/deserialization, write clean code, and auto-export the `openapi.json` contract.

---

## 🧱 What We Skipped / What to Improve with More Time

- **Persistent Database Cache**: Currently, cache lives in application memory. If the wrapper restarts, it must pull data from the legacy portal during boot. Using Redis or SQLite as a persistent local cache would ensure instantaneous startup and robustness if the legacy portal is offline during restart.
- **Advanced Authentication**: The service-managed mode uses a single operator session. In a production multi-tenant wrapper, we should implement OAuth2 or API-Keys to secure endpoints and log user access.
- **Historical Consumption Cache**: Consumption readings could be cached locally with a shorter TTL (e.g. 15 minutes) to decrease load on the legacy portal for highly queried meters.

---

## 📝 Reflection

### 1. What assumptions did you make?
- We assumed that the `/portal/export?page=1` endpoint behaves as a bulk endpoint returning all 403 meters at once despite the `page=1` query parameter, which was confirmed during inspection.
- We assumed that the electrical network structure is linear (`Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meter`) and that meters are children of DTs.
- We assumed that the operations staff credentials provided represent a permanent read-only profile suitable for global gateway auth.

### 2. Which part was the most difficult, and how did you get unstuck?
The most difficult part was the initial authentication POST to `/`. The server returned a 405 Method Not Allowed SvelteKit routing error. We inspected SvelteKit's progressive form action patterns and the client router config (`app.[hash].js`), which revealed that the login endpoint is explicitly located at `/login` and expects standard browser headers (like `Origin` and `Referer`) to satisfy SvelteKit's CSRF checker. Once these headers were integrated, authentication was established successfully.

### 3. If you had another day, what would you improve?
- Implement **SQLite persistent indexing** using SQLAlchemy to allow SQL queries over the meter attributes.
- Build a map canvas inside the web dashboard to plot the smart meters' latitude/longitude coordinates dynamically on Leaflet.js.
- Configure alerting triggers in the dashboard to highlight meters experiencing voltage anomalies (e.g., voltage dropping below 210V or spiking above 250V).

### 4. What mistake did you make while solving this?
Initially, we attempted to scrape individual meter pages to load coordinates and DT associations. This required multiple serial requests and HTML parses using selectors, which was extremely slow and fragile. While searching SvelteKit page nodes, we discovered the `/portal/keys` and `/portal/export` signing endpoints. Using the HMAC signed endpoint allowed us to retrieve the complete network, profile, and location records in a single payload, completely eliminating the scraping code.

### 5. If you were reviewing your own submission, what would you criticise?
- **Global Variable Cache**: Storing the cached lists in global Python variables (`main.py`) rather than a scoped class instance or Dependency Injection container makes code testing tight and limits horizontal scaling.
- **Lack of Cache Hydration Status**: If the initial startup cache pull fails due to legacy network outage, the API starts with empty lists. We should fall back to a local JSON snapshot to guarantee high availability.
