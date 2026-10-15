"""
Tests for NEXUS Backend Route API (Step 25.2)

Verifies POST /api/route endpoint integration with backend/router.py.
"""

import os
import sys
import unittest

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app import app, router


class TestRouteAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    # 1. Valid route request -> HTTP 200
    def test_01_valid_route_request_returns_200(self):
        payload = {
            "start": {
                "lat": 26.4499,
                "lon": 80.3319,
            },
            "destination": {
                "lat": 26.4600,
                "lon": 80.3400,
            },
        }
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("found"))
        self.assertEqual(data.get("status"), "SUCCESS")

    # 2. Response contains route information from RouteResult
    def test_02_response_contains_route_result_fields(self):
        payload = {
            "start": {
                "lat": 26.4499,
                "lon": 80.3319,
            },
            "destination": {
                "lat": 26.4600,
                "lon": 80.3400,
            },
        }
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        expected_keys = {
            "found",
            "status",
            "coordinates",
            "segment_ids",
            "road_names",
            "total_distance_km",
            "estimated_travel_time_s",
            "snapped_start",
            "snapped_destination",
            "node_count",
            "edge_count",
            "error",
        }
        self.assertTrue(expected_keys.issubset(set(data.keys())))
        self.assertIsInstance(data["coordinates"], list)
        self.assertGreater(len(data["coordinates"]), 1)
        self.assertIsInstance(data["segment_ids"], list)
        self.assertGreater(len(data["segment_ids"]), 0)
        self.assertIsInstance(data["road_names"], list)
        self.assertGreater(data["total_distance_km"], 0.0)
        self.assertGreater(data["estimated_travel_time_s"], 0.0)
        self.assertIsNotNone(data["snapped_start"])
        self.assertIsNotNone(data["snapped_destination"])
        self.assertIn("node", data["snapped_start"])
        self.assertIn("distance_km", data["snapped_start"])

    # 3. Invalid JSON / body -> HTTP 400
    def test_03_invalid_json_or_body_returns_400(self):
        response = self.client.post("/api/route", data="not a json payload", content_type="text/plain")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

        response = self.client.post("/api/route", data="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

        response = self.client.post("/api/route", json=[1, 2, 3])
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())
    # 4. Missing start -> HTTP 400
    def test_04_missing_start_returns_400(self):
        payload = {"destination": {"lat": 26.4600, "lon": 80.3400}}
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    # 5. Missing destination -> HTTP 400
    def test_05_missing_destination_returns_400(self):
        payload = {"start": {"lat": 26.4499, "lon": 80.3319}}
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    # 6. Invalid latitude/longitude -> HTTP 400
    def test_06_invalid_latitude_longitude_returns_400(self):
        invalid_cases = [
            {"start": {"lat": "invalid", "lon": 80.3319}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499, "lon": "invalid"}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499, "lon": 80.3319}, "destination": {"lon": 80.34}},
            {"start": {"lat": True, "lon": 80.3319}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 95.0, "lon": 80.3319}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": -95.0, "lon": 80.3319}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499, "lon": 185.0}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499, "lon": -185.0}, "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": "not_an_object", "destination": {"lat": 26.46, "lon": 80.34}},
            {"start": {"lat": 26.4499, "lon": 80.3319}, "destination": 123},
        ]
        for payload in invalid_cases:
            with self.subTest(payload=payload):
                response = self.client.post("/api/route", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

    # 7. No-route behavior is handled without HTTP 500
    def test_07_no_route_handled_without_500(self):
        dead_ends = [
            n for n in router.nodes
            if n not in router.adjacency or len(router.adjacency[n]) == 0
        ]
        self.assertGreater(len(dead_ends), 0)
        dead_end_lat, dead_end_lon = dead_ends[0]
        payload = {
            "start": {"lat": dead_end_lat, "lon": dead_end_lon},
            "destination": {"lat": 26.449, "lon": 80.331},
        }
        response = self.client.post("/api/route", json=payload)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data.get("found"))
        self.assertEqual(data.get("status"), "NO_PATH_FOUND")
        self.assertIsNotNone(data.get("error"))

    # 8. Same start and destination node -> HTTP 200
    def test_08_identical_start_and_destination_returns_200(self):
        payload = {
            "start": {"lat": 26.449, "lon": 80.331},
            "destination": {"lat": 26.449, "lon": 80.331},
        }
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("found"))
        self.assertEqual(data.get("total_distance_km"), 0.0)
        self.assertEqual(len(data.get("coordinates")), 1)

    # 9. Regression: two DIFFERENT coordinates that collapse onto one snapped
    #    node must never be reported as a successful 0.00 km route.
    #    (Bug: "Distance: 0.00 km / Segments: 0 / Status: SUCCESS")
    def test_09_distinct_coords_snapped_to_same_node_do_not_fake_success(self):
        # Both points lie outside the mapped graph but nearest to the same
        # boundary node — the exact condition behind the reported bug.
        a = {"lat": 26.55, "lon": 80.25}
        b = {"lat": 26.60, "lon": 80.20}

        sa = router.snap_to_nearest_node(a["lat"], a["lon"])
        sb = router.snap_to_nearest_node(b["lat"], b["lon"])
        self.assertIsNotNone(sa)
        self.assertIsNotNone(sb)
        self.assertEqual(sa.node, sb.node)  # precondition of the bug

        response = self.client.post(
            "/api/route", json={"start": a, "destination": b}
        )
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data.get("found"))
        self.assertNotEqual(data.get("status"), "SUCCESS")
        self.assertIsNotNone(data.get("error"))

    # 10. Known coordinate-pair smoke test: a real route must be non-zero.
    def test_10_known_pair_returns_non_zero_route(self):
        response = self.client.post(
            "/api/route",
            json={
                "start": {"lat": 26.475488, "lon": 80.326401},
                "destination": {"lat": 26.452836, "lon": 80.350253},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("found"))
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertGreater(data.get("total_distance_km"), 0.0)
        self.assertGreater(data.get("estimated_travel_time_s"), 0.0)
        self.assertGreater(len(data.get("segment_ids")), 0)
        self.assertGreater(len(data.get("coordinates")), 1)


if __name__ == "__main__":
    unittest.main()

