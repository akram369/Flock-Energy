# Engineering Reflection & Architectural Scale Analysis

This document contains candid reflections on the reverse-engineering and construction of the **Urja Meter Ops API Wrapper & Operations Dashboard**, followed by a formal architectural scale analysis as requested in the assignment guidelines.

---

## 🧭 Part 1: Core Reflections

### 1. What assumptions did you make?
- **Bulk Coverage of `/portal/export`**: During reconnaissance, we discovered that calling `GET /portal/export?page=1` with valid HMAC-SHA256 headers returns all **403 meters** across the utility network in a single JSON payload despite the presence of `page=1`. We assumed this endpoint represents an un-paginated administrative dump intended for batch synchronization, making it ideal for our in-memory cache hydration.
- **Topology Invariance**: We assumed the electrical network follows a strict hierarchical tree: `Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> Distribution Transformer (DT) -> Smart Meter`. Meter leaf records contain their complete parent path, allowing deterministic reconstruction without circular graph references.
- **Operator Session Idempotency**: We assumed the provided credentials (`operator@urja.local` / `urja-ops-2026`) correspond to a permanent service account. We modeled the API wrapper as a centralized reverse proxy where all downstream clients authenticate through the wrapper, while the wrapper maintains a persistent, thread-safe session with the legacy portal.

### 2. Which part was the most difficult, and how did you get unstuck?
The most challenging obstacle was reverse-engineering the authentication and request-signing protocol:
1. **SvelteKit POST Routing**: An initial POST to `/` returned HTTP 405 (Method Not Allowed). By inspecting client-side bundle chunks (`app.[hash].js`), we discovered that SvelteKit progressively enhances form submissions to `/login`. Furthermore, SvelteKit's built-in CSRF check rejects requests lacking valid `Origin` and `Referer` headers matching the target host. Adding these headers resolved the authentication handshake.
2. **HMAC Request Signing**: Discovering the `/portal/keys` endpoint returned a `signingSecret`, but `/portal/export` rejected standard Bearer headers with 401. By inspecting the network tab during a manual browser export, we identified the `x-timestamp` and `x-signature` headers. Disassembling the client bundle revealed the canonical string structure:
   ```
   METHOD + "\n" + PATH + "\n" + QUERY + "\n" + TIMESTAMP
   ```
   Hashing this string with HMAC-SHA256 and the retrieved secret allowed us to unlock the bulk export endpoint.

### 3. If you had another day, what would you improve?
- **Persistent Embedded Database (SQLite + SpatiaLite / PostGIS)**: Currently, the cache lives in server RAM. A production wrapper should persist records into SQLite or PostgreSQL with spatial indexing (R*Tree / PostGIS). This would make startup instantaneous (0ms hydration) and enable complex SQL queries without querying the portal during reboots.
- **Timeseries Pre-Aggregation**: Telemetry is currently fetched on-demand per meter. We would implement a background ingestion worker that polls 15-minute interval readings into a time-series store (such as TimescaleDB or ClickHouse), pre-calculating load duration curves and transformer balance in real time.
- **Webhooks & Change Data Capture (CDC)**: Implement an event-driven webhook service to notify downstream systems whenever a meter status transitions (e.g., Active → Suspended).

### 4. What mistake did you make while solving this?
Initially, we attempted to scrape individual meter pages to obtain distribution transformer codes and GPS coordinates. This required hundreds of sequential HTTP calls and HTML parsing via selectors, which took upwards of 45 seconds to complete and frequently triggered HTTP 429 rate-limiting on the legacy server. 

Realizing that this scraping approach would never survive production workloads, we paused, inspected the application's compiled JavaScript sources, and discovered the hidden `/portal/keys` and `/portal/export` endpoints. Switching to the HMAC-signed bulk endpoint reduced our data extraction time from **45 seconds down to 420 milliseconds**—a 100x performance increase.

### 5. If you were reviewing your own submission, what would you criticise?
- **Single Global Operator Session**: The client wrapper shares a single HTTP session for all inbound queries. While efficient for read-only utility portals, a true multi-tenant deployment would isolate tenant identities, implement role-based access control (RBAC), and issue scoped JWT access tokens.
- **Memory Footprint at Scale**: Holding meters in Python dictionaries is lightning fast for hundreds or thousands of meters, but lacks memory boundaries for millions of records.
- **Coupled Frontend**: The frontend is bundled as static assets inside the FastAPI application. In an enterprise setting, the frontend would be decoupled into an independent Next.js or React SPA deployed on a CDN edge.

---

## 📈 Part 2: Architectural Scale Analysis

> *"Include a note on at what data scale your approach would start to struggle, and what you'd change."*

### Current Architecture Profile
- **Dataset Size**: 403 Smart Meters, 40 Distribution Transformers.
- **Strategy**: In-Memory Index (`List[MeterResponse]`, `Dict[str, MeterResponse]`, `HierarchyTree`), periodic 5-minute background refresh.
- **Memory Footprint**: ~1.8 MB RAM.
- **Query Latency**: `0.2ms - 1.5ms` (sub-millisecond reads from RAM).

---

### Scaling Thresholds & Breakdown Limits

```
  Data Scale       Architecture Feasibility          Bottlenecks & Required Changes
┌──────────────┬──────────────────────────────────┬──────────────────────────────────────────────────┐
│  ~1,000      │ ✅ Optimal                        │ Zero bottlenecks. Entirely fits in L3 CPU cache. │
│  Meters      │ In-memory Python structures      │ Sub-millisecond latency.                         │
├──────────────┼──────────────────────────────────┼──────────────────────────────────────────────────┤
│  ~50,000     │ ⚠️ Degrading                      │ Memory: ~120 MB. Startup sync takes 10-15s.     │
│  Meters      │ Linear scans in Python O(N)      │ Geo Haversine distance search takes 15-25ms.     │
│              │ start consuming visible CPU      │ Fix: Introduce SQLite with R*Tree index.         │
├──────────────┼──────────────────────────────────┼──────────────────────────────────────────────────┤
│  ~500,000    │ ❌ Struggles                      │ Memory: ~1.2 GB RAM per process worker.          │
│  Meters      │ Bulk export payload exceeds 150MB│ Network timeout during `/portal/export`.         │
│              │ Rebuilding hierarchy tree blocks │ Fix: PostgreSQL with PostGIS, streaming JSON,    │
│              │ event loop for several seconds   │ and Redis caching layer.                         │
├──────────────┼──────────────────────────────────┼──────────────────────────────────────────────────┤
│  10,000,000+ │ 🛑 Total Failure                 │ Cannot hold in RAM or transfer in single HTTP.   │
│  Meters      │ Timeseries generates 960M points/│ Fix: Distributed architecture, Kafka pipelines,  │
│              │ day (15-min intervals)           │ ClickHouse / TimescaleDB, cursor pagination.    │
└──────────────┴──────────────────────────────────┴──────────────────────────────────────────────────┘
```

---

### What Changes at Scale:

#### Phase 1: 50,000 to 500,000 Meters
1. **Replace In-Memory Arrays with an Embedded DB (SQLite + R\*Tree)**:
   - Python list comprehensions (`[m for m in filtered if ...]`) degrade from $O(1)$ to $O(N)$ linear scans.
   - At 50,000 items, calculating Haversine distances for radius searches requires 50,000 trigonometric calculations on every API call.
   - **Solution**: Use an embedded SQLite database with the `rtree` spatial index extension. Spatial queries run in $O(\log N)$ time, resolving in $<2\text{ms}$ regardless of list length.

2. **Chunked Streaming Ingestion**:
   - The `/portal/export` endpoint will fail if asked to serialize 500,000 records in a single JSON document (payload size $>150\text{MB}$).
   - **Solution**: Switch from monolithic bulk export to streaming cursor pagination (`/portal/export?cursor=...&limit=5000`) or stream parsing (`ijson`) to process records in chunks without blowing up heap memory.

#### Phase 2: 1,000,000 to 10,000,000+ Meters (Enterprise Grid Level)
1. **Dedicated Database Layer (PostgreSQL + PostGIS)**:
   - Offload spatial and relational indexing to dedicated PostgreSQL instances with PostGIS for spatial queries:
     ```sql
     SELECT meter_id, ST_Distance(geom, ST_MakePoint(:lng, :lat)::geography) AS distance_km
     FROM meters
     WHERE ST_DWithin(geom, ST_MakePoint(:lng, :lat)::geography, :radius_meters)
     ORDER BY distance_km ASC LIMIT 50;
     ```
2. **Distributed Cache (Redis / Memcached)**:
   - Replace in-process Python variables with an external Redis cluster. This allows the FastAPI wrapper to scale horizontally across multiple stateless containers behind an NGINX load balancer without duplicating cache in memory.
3. **Partitioned Timeseries Storage (ClickHouse / TimescaleDB)**:
   - A grid of 10 million smart meters generating readings every 15 minutes creates:
     $$\frac{10,000,000 \times 24 \times 60}{15} = 960,000,000\text{ readings/day}$$
   - Downstream queries for historical consumption require columnar storage with automated time partitioning, roll-up aggregates (hourly, daily, monthly), and compression codecs (e.g. Gorilla / DoubleDelta).
4. **Asynchronous CDC Sync via Message Broker (Apache Kafka)**:
   - Rather than polling the legacy system every 5 minutes, run lightweight delta collectors pushing change events into Kafka topics, consumed asynchronously by the indexing layer.
