import httpx
import time
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.config import PORTAL_URL, DEFAULT_USERNAME, DEFAULT_PASSWORD

logger = logging.getLogger(__name__)

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
            # We don't follow redirects on POST to handle SvelteKit JSON redirect payload
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

    def _request_with_reauth(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request. If it fails due to auth expiration, re-authenticate and retry once."""
        url = f"{self.base_url}{path}"
        
        # If not logged in, login first
        if not self.logged_in:
            self.login()

        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.RequestError as e:
            logger.error(f"HTTP request error: {e}")
            raise

        # Detect session expiration
        # The legacy portal might redirect to login page (302/303), or return 401/405/403
        is_auth_error = (
            response.status_code in (401, 403, 405) or
            (response.status_code in (302, 303) and "login" in response.headers.get("Location", "").lower()) or
            (response.status_code == 200 and "sign in" in response.text.lower() and "email" in response.text.lower())
        )

        if is_auth_error:
            logger.info("Session expired or unauthorized. Re-authenticating...")
            if self.login():
                # Retry request
                logger.info(f"Retrying {method} request to {path}...")
                response = self.client.request(method, url, **kwargs)
            else:
                raise httpx.HTTPStatusError("Re-authentication failed", request=response.request, response=response)

        response.raise_for_status()
        return response

    def get_meters_search(self, q: str = "", page: int = 1) -> Dict[str, Any]:
        """Fetch page of meters from search API."""
        path = f"/portal/meters/search?q={httpx.URLEscape(q)}&page={page}"
        res = self._request_with_reauth("GET", path)
        return res.json()

    def get_meter_geo(self, meter_id: str) -> Dict[str, Any]:
        """Fetch meter coordinates."""
        path = f"/portal/meters/{meter_id}/geo"
        try:
            res = self._request_with_reauth("GET", path)
            return res.json()
        except Exception as e:
            logger.warning(f"Failed to fetch geo for meter {meter_id}: {e}")
            return {"data": {"latitude": None, "longitude": None}}

    def get_meter_energy(self, meter_id: str) -> Dict[str, Any]:
        """Fetch consumption readings."""
        path = f"/portal/meters/{meter_id}/energy"
        try:
            res = self._request_with_reauth("GET", path)
            return res.json()
        except Exception as e:
            logger.error(f"Failed to fetch energy readings for meter {meter_id}: {e}")
            return {"data": []}

    def get_transformers(self, page: int = 1) -> Dict[str, Any]:
        """Fetch list of distribution transformers."""
        path = f"/portal/dts?page={page}"
        res = self._request_with_reauth("GET", path)
        return res.json()

    def get_signing_secret(self) -> str:
        """Fetch signing secret from the keys endpoint."""
        res = self._request_with_reauth("GET", "/portal/keys")
        return res.json()["data"]["signingSecret"]

    def export_meters(self) -> List[Dict[str, Any]]:
        """Fetch the full dataset using the HMAC signed export endpoint."""
        # 1. Fetch key
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
        res = self._request_with_reauth("GET", f"{path}?{query}", headers=headers)
        return res.json().get("data", [])

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
            # Fallback to current datetime or raw string if parsing fails
            return s
