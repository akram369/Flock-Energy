import unittest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Import app modules
from app.main import app, refresh_all_caches
import app.main as main_module
from app.models import MeterResponse, GeoLocation, MeterHierarchy, HierarchyItem, TransformerResponse

class TestUrjaAPIWrapper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

        # Clear and mock global cache variables for deterministic unit tests
        main_module.meters_cache = [
            MeterResponse(
                meter_id="J100000",
                serial_number="SE33962",
                make="HPL",
                phase_type="single",
                status="Active",
                installation_type="Whole Current",
                build_type="legacy",
                dt_code="DT-001",
                location=GeoLocation(latitude=26.938961, longitude=75.830956),
                hierarchy=MeterHierarchy(
                    zone=HierarchyItem(name="Jaipur Zone 1", code="Z-01"),
                    circle=HierarchyItem(name="Circle 1", code="C-01"),
                    division=HierarchyItem(name="Division 1", code="D-01"),
                    subdivision=HierarchyItem(name="Subdivision 1", code="SD-01"),
                    substation=HierarchyItem(name="Substation 1", code="SS-01"),
                    feeder=HierarchyItem(name="Feeder 1", code="F-001"),
                    dt=HierarchyItem(name="Malviya Nagar DT 1", code="DT-001")
                )
            ),
            MeterResponse(
                meter_id="J200000",
                serial_number="SE99999",
                make="Genus",
                phase_type="three",
                status="Decommissioned",
                installation_type="CT Operated",
                build_type="modern",
                dt_code="DT-002",
                location=GeoLocation(latitude=27.123456, longitude=76.654321),
                hierarchy=MeterHierarchy(
                    zone=HierarchyItem(name="Jaipur Zone 1", code="Z-01"),
                    circle=HierarchyItem(name="Circle 1", code="C-01"),
                    division=HierarchyItem(name="Division 1", code="D-01"),
                    subdivision=HierarchyItem(name="Subdivision 1", code="SD-01"),
                    substation=HierarchyItem(name="Substation 1", code="SS-01"),
                    feeder=HierarchyItem(name="Feeder 1", code="F-001"),
                    dt=HierarchyItem(name="Malviya Nagar DT 2", code="DT-002")
                )
            )
        ]
        
        main_module.meters_by_id = {
            m.meter_id: m for m in main_module.meters_cache
        }
        
        main_module.transformers_cache = [
            TransformerResponse(code="DT-001", name="Malviya Nagar DT 1", feeder_code="F-001", capacity_kva=100.0),
            TransformerResponse(code="DT-002", name="Malviya Nagar DT 2", feeder_code="F-001", capacity_kva=250.0)
        ]
        
        main_module.hierarchy_tree = main_module.build_hierarchy_tree(main_module.meters_cache)

    def test_serve_dashboard(self):
        """Test that root route serves the index.html page."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_list_meters_all(self):
        """Test listing all cached meters."""
        response = self.client.get("/api/v1/meters")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(data["data"][0]["meter_id"], "J100000")

    def test_list_meters_filter_search(self):
        """Test search query query parameter."""
        response = self.client.get("/api/v1/meters?q=99999")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["meter_id"], "J200000")

    def test_list_meters_filter_status(self):
        """Test operational status filter."""
        response = self.client.get("/api/v1/meters?status=Decommissioned")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["meter_id"], "J200000")

    def test_list_meters_filter_make(self):
        """Test manufacturer make filter."""
        response = self.client.get("/api/v1/meters?make=HPL")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["meter_id"], "J100000")

    def test_get_meter_by_id_success(self):
        """Test retrieving specific meter details."""
        response = self.client.get("/api/v1/meters/J100000")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["serial_number"], "SE33962")
        self.assertEqual(data["location"]["latitude"], 26.938961)

    def test_get_meter_by_id_404(self):
        """Test retrieving non-existent meter ID returns 404."""
        response = self.client.get("/api/v1/meters/J999999")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_list_transformers(self):
        """Test retrieving transformers list."""
        response = self.client.get("/api/v1/transformers")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["data"][0]["code"], "DT-001")
        self.assertEqual(data["data"][1]["capacity_kva"], 250.0)

    def test_get_hierarchy(self):
        """Test network tree hierarchy endpoint."""
        response = self.client.get("/api/v1/hierarchy")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "root")
        self.assertTrue(len(data["children"]) > 0)
        self.assertEqual(data["children"][0]["type"], "zone")

    @patch("app.main.portal_client")
    def test_get_consumption(self, mock_portal_client):
        """Test retrieving dynamic energy and voltage readings."""
        # Setup mock readings from portal
        mock_portal_client.get_meter_energy.return_value = {
            "data": [
                {"timestamp": "23/06/2026 23:30", "kwh": "48438.74", "kvah": "52313.84", "voltR": "226"},
                {"timestamp": "23/06/2026 23:45", "kwh": "48439.12", "kvah": "52314.20", "voltR": "225"}
            ]
        }
        mock_portal_client.clean_timestamp.side_effect = lambda x: "2026-06-23T23:30:00" if "23:30" in x else "2026-06-23T23:45:00"
        mock_portal_client.clean_float.side_effect = lambda x: float(x) if x else None

        response = self.client.get("/api/v1/meters/J100000/consumption")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meter_id"], "J100000")
        self.assertEqual(len(data["readings"]), 2)
        self.assertEqual(data["readings"][0]["timestamp"], "2026-06-23T23:30:00")
        self.assertEqual(data["readings"][0]["kwh"], 48438.74)
        self.assertEqual(data["readings"][0]["voltage_r"], 226.0)

    @patch("app.main.portal_client")
    def test_auth_login_success(self, mock_portal_client):
        """Test mock portal login validation endpoint."""
        mock_portal_client.login.return_value = True
        
        payload = {"email": "operator@urja.local", "password": "urja-ops-2026"}
        response = self.client.post("/api/v1/auth/login", json=payload)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["session_token"], "mock-token-session-valid")

    @patch("app.main.portal_client")
    def test_auth_login_failure(self, mock_portal_client):
        """Test mock login with bad credentials."""
        mock_portal_client.login.return_value = False
        
        payload = {"email": "bad@urja.local", "password": "wrongpassword"}
        response = self.client.post("/api/v1/auth/login", json=payload)
        
        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid credentials", response.json()["detail"].lower())

if __name__ == "__main__":
    unittest.main()
