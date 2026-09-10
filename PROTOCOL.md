# Urja Meter Ops Portal - Legacy Protocol Documentation

This document describes how the legacy "Urja Meter Ops" web portal (`https://urja-ops.flockenergy.tech`) operates under the hood, as discovered through network inspection and bundle reverse-engineering.

---

## 1. Authentication & Session Architecture

The legacy portal is built on **SvelteKit** with server-side form actions and cookie-based session tracking.

- **Login Page**: `https://urja-ops.flockenergy.tech/login`
- **Method**: `POST`
- **Form URL**: `/login` (POSTing to `/` returns `HTTP 405 Method Not Allowed`)
- **Content-Type**: `application/x-www-form-urlencoded`
- **Payload**:
  ```
  email=operator@urja.local&password=urja-ops-2026
  ```
- **Response Format**:
  SvelteKit responds with an action redirect descriptor:
  ```json
  {"type":"redirect","status":303,"location":"/meters"}
  ```
- **Session Cookie**:
  A successful handshake issues a secure HTTP-only cookie:
  ```
  Set-Cookie: __Secure-better-auth.session_token=<token_hash>; Path=/; Secure; HttpOnly; SameSite=Lax
  ```
- **CSRF & Origin Protections**:
  SvelteKit validates inbound POST request origins. Direct HTTP client calls fail unless the following headers are supplied:
  - `Origin: https://urja-ops.flockenergy.tech`
  - `Referer: https://urja-ops.flockenergy.tech/login`
  - A browser `User-Agent` string.

### Sample Authentication via cURL
```bash
curl -i -X POST "https://urja-ops.flockenergy.tech/login" \
  -H "Origin: https://urja-ops.flockenergy.tech" \
  -H "Referer: https://urja-ops.flockenergy.tech/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=operator@urja.local&password=urja-ops-2026" \
  -c cookies.txt
```

---

## 2. Discovered Internal Endpoints

Once authenticated with the `__Secure-better-auth.session_token` cookie, the client communicates with internal REST-like endpoints.

### A. Meter Search & Listing
- **Endpoint**: `GET /portal/meters/search?q={query}&page={page}`
- **Purpose**: Paginated search across meter serial numbers or meter IDs (20 items/page).
- **Sample Response**:
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

### B. Meter Coordinates (Geo)
- **Endpoint**: `GET /portal/meters/{meterId}/geo`
- **Sample Response**:
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```
- **Quirk**: Coordinates are formatted as strings rather than numerical floats.

### C. Consumption Telemetry (Energy & Voltage)
- **Endpoint**: `GET /portal/meters/{meterId}/energy`
- **Purpose**: 15-minute / 30-minute interval timeseries log.
- **Sample Response**:
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
- **Anomalies**:
  - Timestamps use a legacy format (`DD/MM/YYYY HH:MM`).
  - Values are strings and occasionally contain invalid characters (`"—"`, `"null"`, `"N/A"`).

### D. Distribution Transformers
- **Endpoint**: `GET /portal/dts?page={page}`
- **Sample Response**:
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

### E. Cryptographic Key Endpoint
- **Endpoint**: `GET /portal/keys`
- **Sample Response**:
  ```json
  {
    "data": {
      "signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"
    }
  }
  ```

---

## 3. The Bulk Export Endpoints & HMAC-SHA256 Scheme

To prevent unauthorized mass data scraping, the legacy portal protects its bulk export route with an HMAC-SHA256 signature requirement.

- **URL**: `GET /portal/export?page=1`
- **Required Headers**:
  - `x-timestamp`: Unix epoch timestamp in seconds.
  - `x-signature`: Lowercase hexadecimal HMAC-SHA256 hash.

### Signature Algorithm
1. Retrieve the `signingSecret` from `GET /portal/keys`.
2. Construct the canonical message by joining:
   ```
   METHOD + "\n" + PATH + "\n" + QUERY_STRING + "\n" + TIMESTAMP
   ```
   *Example*:
   ```
   GET
   /portal/export
   page=1
   1719187200
   ```
3. Calculate the HMAC-SHA256 hash using `signingSecret` as key.
4. Set headers:
   - `x-timestamp: 1719187200`
   - `x-signature: <hex_digest>`

### Python Implementation Snippet
```python
import time
import hmac
import hashlib
import httpx

def get_bulk_meters(client: httpx.Client, base_url: str):
    # 1. Fetch secret
    key_res = client.get(f"{base_url}/portal/keys")
    secret = key_res.json()["data"]["signingSecret"]

    # 2. Build canonical string
    method = "GET"
    path = "/portal/export"
    query = "page=1"
    timestamp = str(int(time.time()))
    canonical_string = f"{method}\n{path}\n{query}\n{timestamp}"

    # 3. Hash
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    # 4. Request
    headers = {
        "x-timestamp": timestamp,
        "x-signature": signature
    }
    res = client.get(f"{base_url}{path}?{query}", headers=headers)
    return res.json().get("data", [])
```

### Full Dataset Payload
The export payload returns **all 403 meters** in a single call, completely nested with full network topology and GPS coordinates:
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

## 4. Key Observations, Quirks & Pitfalls

1. **Unpaginated Bulk Export**: Despite passing `page=1`, the export endpoint returns all 403 records at once.
2. **Missing Token Expiry Headers**: The legacy portal does not return `exp` claims in cookies. Session timeout must be detected reactively when requests return `HTTP 401`, `HTTP 405`, or redirect descriptors to `/login`.
3. **Data Dirtying**: String telemetry values (`"voltR": "226"`, `"kwh": "—"`) require strict defensive parsing before exposure to downstream REST consumers.
