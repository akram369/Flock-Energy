# Urja Meter Ops Portal - Legacy Protocol Documentation

This document describes how the legacy "Urja Meter Ops" web portal (https://urja-ops.flockenergy.tech) operates under the hood, as discovered during reverse-engineering.

---

## 1. Authentication & Session Management

- **Login Page URL**: `https://urja-ops.flockenergy.tech/login`
- **Login Method**: `POST`
- **Content-Type**: `application/x-www-form-urlencoded` or multipart form data.
- **Payload**:
  - `email`: User's login email (e.g., `operator@urja.local`).
  - `password`: User's login password (e.g., `urja-ops-2026`).
- **Response**: SvelteKit-style JSON redirect descriptor.
  ```json
  {"type":"redirect","status":303,"location":"/meters"}
  ```
- **Session Cookie**: Successful login sets a secure session token cookie:
  - `__Secure-better-auth.session_token`
- **CSRF Requirements**:
  SvelteKit validates the origin of POST requests. Submitting requests requires providing:
  - `Origin: https://urja-ops.flockenergy.tech`
  - `Referer: https://urja-ops.flockenergy.tech/login`
  - A modern browser `User-Agent`.

---

## 2. API Endpoints

Once authenticated, the frontend client makes async fetch calls to several JSON endpoints.

### A. Meter Search & Listing
- **URL**: `GET /portal/meters/search?q={search_query}&page={page_num}`
- **Response Format**:
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "dtCode": "DT-001"
      }
    ],
    "total": 403
  }
  ```
- **Behavior**: Paginated by 20 items per page. The query parameter `q` searches across meter serial numbers or IDs.

### B. Meter Coordinates (Geo)
- **URL**: `GET /portal/meters/{meterId}/geo`
- **Response Format**:
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```

### C. Consumption History (Energy Readings)
- **URL**: `GET /portal/meters/{meterId}/energy`
- **Response Format**:
  ```json
  {
    "data": [
      {
        "timestamp": "23/06/2026 23:30",
        "kwh": "48438.74",
        "kvah": "52313.84",
        "voltR": "226"
      }
    ]
  }
  ```
- **Behavior**: Returns a historical list of 15-minute / 30-minute interval readings containing timestamps, active energy (kWh), apparent energy (kVAh), and voltage.

### D. Distribution Transformers
- **URL**: `GET /portal/dts?page={page_num}`
- **Response Format**:
  ```json
  {
    "data": [
      {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100
      }
    ],
    "total": 40
  }
  ```

### E. API Security Keys
- **URL**: `GET /portal/keys`
- **Response Format**:
  ```json
  {
    "data": {
      "signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"
    }
  }
  ```

---

## 3. The Bulk Export Endpoints & Signature Scheme

To support bulk data exports, the portal features a secure signed export endpoint.

- **URL**: `GET /portal/export?page=1`
- **Headers Required**:
  - `x-timestamp`: The current epoch timestamp in seconds (as string).
  - `x-signature`: The HMAC-SHA256 signature verifying the authenticity of the export request.
  
### HMAC Signature Generation
1. Fetch the `signingSecret` from `/portal/keys`.
2. Construct the message string by joining the HTTP method, request path, query string, and timestamp with a newline `\n`:
   ```
   METHOD + "\n" + PATH + "\n" + QUERY + "\n" + TIMESTAMP
   ```
   *Example*:
   ```
   GET
   /portal/export
   page=1
   1700000000
   ```
3. Hash this message with the `signingSecret` using HMAC-SHA256.
4. Output the signature as a lowercase hex string.

### Response Data Format
The `/portal/export?page=1` response contains the complete metadata list of all 403 meters in a single JSON payload. It is heavily structured and includes location and full network hierarchy:
```json
{
  "total": 403,
  "data": [
    {
      "meterId": "J100000",
      "serialNo": "SE33962",
      "make": "HPL",
      "phaseType": "single",
      "installStatus": "Decommissioned",
      "installType": "Whole Current",
      "build": "legacy",
      "dtCode": "DT-001",
      "hierarchy": {
        "zone": { "name": "Jaipur Zone 1", "code": "Z-01" },
        "circle": { "name": "Circle 1", "code": "C-01" },
        "division": { "name": "Division 1", "code": "D-01" },
        "subdivision": { "name": "Subdivision 1", "code": "SD-01" },
        "substation": { "name": "Substation 1", "code": "SS-01" },
        "feeder": { "name": "Feeder 1", "code": "F-001" },
        "dt": { "name": "Malviya Nagar DT 1", "code": "DT-001" }
      },
      "geo": {
        "lat": 26.938961002479868,
        "lng": 75.83095696146852
      }
    }
  ]
}
```

---

## 4. Observations & Quirks

- **No CSRF Tokens**: Unlike many SvelteKit apps, the login endpoint does not require a dynamic form token. SvelteKit's standard header checks (specifically the `Origin` header matching the Host) are the primary CSRF guard rails.
- **SvelteKit Router Redirects**: Accessing `/` returns the login page html, but POSTing to `/` returns a Method Not Allowed error. Login submissions must explicitly go to `/login`.
- **Stateless Sub-Endpoints**: The sub-endpoints (`/portal/meters/.../geo` and `/portal/meters/.../energy`) are fully structured JSON APIs, bypassing SvelteKit's standard client-side loader serialization format (`__data.json`), which simplifies client building.
- **Export Bulk Coverage**: Although `/portal/export?page=1` specifies `page=1`, it returns all 403 records at once, providing a clean bulk path.
