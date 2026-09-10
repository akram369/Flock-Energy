import os
import json
import httpx
import time
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.config import PORTAL_URL, DEFAULT_USERNAME, DEFAULT_PASSWORD

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SNAPSHOT_FILE = os.path.join(SNAPSHOT_DIR, "snapshot_cache.json")

class UrjaPortalClient:
    def __init__(self, base_url: str = PORTAL_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0, follow_redirects=False)
        self.username = DEFAULT_USERNAME
        self.password = DEFAULT_PASSWORD
        self.logged_in = False
        
        # Standard headers to satisfy SvelteKit CSRF
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/login"
        }
        self.client.headers.update(self.headers)

    def close(self):
        """Close the underlying HTTP client session."""
        try:
            self.client.close()
        except Exception:
            pass

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Authenticate with the legacy portal and store session cookies."""
        if username:
            self.username = username
        if password:
            self.password = password

        login_url = f"{self.base_url}/login"
        payload = {
            "email": self.username,
            "password": self.password
        }
        
        logger.info(f"Attempting login to Urja Portal for user {self.username}...")
        try:
            response = self.client.post(login_url, data=payload)
            if response.status_code == 200:
                # SvelteKit returns {"type":"redirect","status":303,"location":"/meters"}
                try:
                    res_json = response.json()
                    if res_json.get("type") == "redirect":
                        logger.info("Login successful (redirect returned)")
                        self.logged_in = True
                        return True
                except Exception:
                    pass
            
            # Fallback check
            if "__Secure-better-auth.session_token" in self.client.cookies:
                logger.info("Login successful (session token cookie found)")
                self.logged_in = True
                return True
                
            logger.error(f"Login failed: status {response.status_code}, body: {response.text[:200]}")
            self.logged_in = False
            return False
        except Exception as e:
            logger.error(f"Exception during login: {e}")
            self.logged_in = False
            return False

    def check_health(self) -> bool:
        """Quick health check to verify portal responsiveness."""
        try:
            res = self.client.get(f"{self.base_url}/login", timeout=5.0)
            return res.status_code in (200, 302, 303)
        except Exception:
            return False

    def _request_with_retry_and_reauth(self, method: str, path: str, max_retries: int = 2, **kwargs) -> httpx.Response:
        """Make an HTTP request with retry logic for transient errors and re-authentication on auth failure."""
        url = f"{self.base_url}{path}"
        
        if not self.logged_in:
            self.login()

        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                
                # Check for session expiration
                is_auth_error = (
                    response.status_code in (401, 403, 405) or
                    (response.status_code in (302, 303) and "login" in response.headers.get("Location", "").lower()) or
                    (response.status_code == 200 and "sign in" in response.text.lower() and "email" in response.text.lower())
                )

                if is_auth_error and attempt < max_retries:
                    logger.info("Session expired. Re-authenticating and retrying...")
                    if self.login():
                        continue
                    else:
                        raise httpx.HTTPStatusError("Re-authentication failed", request=response.request, response=response)

                response.raise_for_status()
                return response

            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                wait_time = 0.5 * (2 ** attempt)
                logger.warning(f"Transient HTTP error ({e}) on {method} {path}. Retrying in {wait_time}s...")
                time.sleep(wait_time)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"Request failed after {max_retries} retries.")

    def get_meters_search(self, q: str = "", page: int = 1) -> Dict[str, Any]:
        """Fetch page of meters from search API."""
        path = f"/portal/meters/search?q={httpx.URLEscape(q)}&page={page}"
        res = self._request_with_retry_and_reauth("GET", path)
        return res.json()

    def get_meter_geo(self, meter_id: str) -> Dict[str, Any]:
        """Fetch meter coordinates."""
        path = f"/portal/meters/{meter_id}/geo"
        try:
            res = self._request_with_retry_and_reauth("GET", path)
            return res.json()
        except Exception as e:
            logger.warning(f"Failed to fetch geo for meter {meter_id}: {e}")
            return {"data": {"latitude": None, "longitude": None}}

    def get_meter_energy(self, meter_id: str) -> Dict[str, Any]:
        """Fetch consumption readings."""
        path = f"/portal/meters/{meter_id}/energy"
        try:
            res = self._request_with_retry_and_reauth("GET", path)
            return res.json()
        except Exception as e:
            logger.error(f"Failed to fetch energy readings for meter {meter_id}: {e}")
            return {"data": []}

    def get_transformers(self, page: int = 1) -> Dict[str, Any]:
        """Fetch list of distribution transformers."""
        path = f"/portal/dts?page={page}"
        res = self._request_with_retry_and_reauth("GET", path)
        return res.json()

    def get_signing_secret(self) -> str:
        """Fetch signing secret from the keys endpoint."""
        res = self._request_with_retry_and_reauth("GET", "/portal/keys")
        return res.json()["data"]["signingSecret"]

    def export_meters(self) -> List[Dict[str, Any]]:
        """Fetch the full dataset using the HMAC signed export endpoint with local snapshot fallback."""
        try:
            # 1. Fetch secret
            secret = self.get_signing_secret()
            
            # 2. Prepare signing arguments
            method = "GET"
            path = "/portal/export"
            query = "page=1"
            timestamp = str(int(time.time()))
            
            # 3. Create signature: HMAC-SHA256(secret, "METHOD\nPATH\nQUERY\nTIMESTAMP")
            msg = f"{method}\n{path}\n{query}\n{timestamp}"
            signature = hmac.new(
                secret.encode("utf-8"),
                msg.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # 4. Request headers
            headers = {
                "x-timestamp": timestamp,
                "x-signature": signature
            }
            
            logger.info("Fetching full dataset from /portal/export...")
            res = self._request_with_retry_and_reauth("GET", f"{path}?{query}", headers=headers)
            data = res.json().get("data", [])
            
            # Persist snapshot locally for offline resiliency
            self._save_snapshot(data)
            return data

        except Exception as e:
            logger.error(f"Failed to export meters from portal: {e}. Attempting snapshot fallback...")
            snapshot = self._load_snapshot()
            if snapshot:
                logger.info(f"Successfully loaded {len(snapshot)} meters from local snapshot cache.")
                return snapshot
            raise

    def _save_snapshot(self, data: List[Dict[str, Any]]):
        """Save a local copy of the full dataset to ensure offline startup availability."""
        try:
            os.makedirs(SNAPSHOT_DIR, exist_ok=True)
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                json.dump({"saved_at": time.time(), "data": data}, f)
            logger.debug(f"Saved snapshot to {SNAPSHOT_FILE}")
        except Exception as e:
            logger.warning(f"Could not save snapshot file: {e}")

    def _load_snapshot(self) -> Optional[List[Dict[str, Any]]]:
        """Load the fallback snapshot if the legacy portal is offline."""
        try:
            if os.path.exists(SNAPSHOT_FILE):
                with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    return payload.get("data", [])
        except Exception as e:
            logger.warning(f"Could not load snapshot file: {e}")
        return None

    @staticmethod
    def clean_float(val: Any) -> Optional[float]:
        """Convert messy string numbers to float or None."""
        if val is None:
            return None
        s = str(val).strip()
        if not s or s == "—" or s.lower() == "n/a" or s.lower() == "null" or s.lower() == "none":
            return None
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def clean_timestamp(ts_str: str) -> str:
        """Convert legacy format (DD/MM/YYYY HH:MM) to ISO-8601 string."""
        if not ts_str:
            return ""
        s = ts_str.strip()
        try:
            dt = datetime.strptime(s, "%d/%m/%Y %H:%M")
            return dt.isoformat()
        except ValueError:
            return s
