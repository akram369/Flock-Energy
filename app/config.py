import os

# Legacy Urja Portal URL
PORTAL_URL = os.getenv("PORTAL_URL", "https://urja-ops.flockenergy.tech").rstrip("/")

# Default Credentials
DEFAULT_USERNAME = os.getenv("URJA_USERNAME", "operator@urja.local")
DEFAULT_PASSWORD = os.getenv("URJA_PASSWORD", "urja-ops-2026")

# API Service Port & Host
HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8000"))

# Cache settings
# How often to sync full datasets from legacy portal (in seconds)
CACHE_REFRESH_INTERVAL = int(os.getenv("CACHE_REFRESH_INTERVAL", "300"))
