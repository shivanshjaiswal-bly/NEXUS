"""
Tests for NEXUS Backend Route API (Step 25.2)

Verifies POST /api/route endpoint integration with backend/router.py.
"""

import os
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as app_module
from app import app, router
from backend.router import build_graph


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

    def test_flask_serves_built_frontend_and_real_traffic_apis(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        response.close()
        self.assertIn('id="root"', content)
        scripts = re.findall(r'<script type="module" crossorigin src="([^"]+)"', content)
        self.assertEqual(len(scripts), 1)
        asset_response = self.client.get(scripts[0])
        self.assertEqual(asset_response.status_code, 200)
        self.assertIn("/api/route", asset_response.get_data(as_text=True))
        asset_response.close()
        for endpoint in ("/api/traffic", "/api/reports"):
            api_response = self.client.get(endpoint)
            self.assertEqual(api_response.status_code, 200)
            self.assertIsInstance(api_response.get_json(), list)
            api_response.close()
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

    def test_blocked_only_route_returns_no_path_404(self):
        start = (26.0, 80.0)
        destination = (26.0, 80.01)
        fixture_router = build_graph({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"osm_id": 9901, "maxspeed": 30, "oneway": "yes"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[start[1], start[0]], [destination[1], destination[0]]],
                },
            }],
        })
        with patch.object(app_module, "router", fixture_router), patch.object(
            app_module,
            "get_current_traffic_routing_state",
            return_value=({}, {"osm:way:9901"}),
        ):
            response = self.client.post("/api/route", json={
                "start": {"lat": start[0], "lon": start[1]},
                "destination": {"lat": destination[0], "lon": destination[1]},
            })

        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data["found"])
        self.assertEqual(data["status"], "NO_PATH_FOUND")
        self.assertIn("No traversable route found", data["error"])

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
        a = {"lat": 27.50, "lon": 81.50}
        b = {"lat": 27.51, "lon": 81.50}

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
        self.assertEqual(data.get("status"), "START_NOT_FOUND")
        self.assertIn("outside the currently mapped road-network coverage", data["error"])
        self.assertIn("expand the road dataset", data["error"])

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
        self.assertNotEqual(
            data["snapped_start"]["node"], data["snapped_destination"]["node"]
        )

    def test_frontend_displays_route_api_error_payload(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        response.close()
        self.assertIn('id="root"', content)
        self.assertNotIn("dangerouslySetInnerHTML", content)
        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        self.assertIn('data.error || data.message || `Route calculation failed (HTTP ${response.status}).`', source)
        self.assertIn('className="inline-error" role="alert"', source)

    def test_route_button_requires_valid_selected_coordinates(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        response.close()

        self.assertIn('id="root"', content)
        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        self.assertIn("parseManualPoint(startCoordinates, \"start\")", source)
        self.assertIn("lat < -90 || lat > 90", source)
        self.assertIn("lon < -180 || lon > 180", source)
        self.assertIn('type="text" value={startCoordinates.lat}', source)
        self.assertIn('type="text" value={destinationCoordinates.lon}', source)
        self.assertIn("disabled={routeLoading}", source)

    def test_current_location_and_destination_use_independent_route_coordinates(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        response.close()

        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        location_handler = source.split("function useCurrentLocation()", 1)[1].split("function changeSearchQuery", 1)[0]
        route_handler = source.split("async function calculateRoute()", 1)[1].split("async function submitReport()", 1)[0]
        self.assertIn('setStart({ ...point, label: "Current location", source: "current" })', location_handler)
        self.assertNotIn("setDestination", location_handler)
        self.assertIn('body: JSON.stringify(requestCoordinates)', route_handler)
        self.assertIn('start: { lat: routeStart.lat, lon: routeStart.lon }', route_handler)
        self.assertIn('destination: { lat: routeDestination.lat, lon: routeDestination.lon }', route_handler)
        self.assertIn('const handleMapClick = (event: any) =>', source)
        self.assertIn('setStart({ ...point, label: "Map selection", source: "map" })', source)
        self.assertIn('setDestination({ ...point, label: "Map selection", source: "map" })', source)
        self.assertIn('map.off("click", handleMapClick)', source)

    def test_vite_forwards_route_api_calls_to_flask_during_development(self):
        config = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn('"/api":', config)
        self.assertIn('target: "http://127.0.0.1:5000"', config)

        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        route_handler = source.split("async function calculateRoute()", 1)[1].split("async function submitReport()", 1)[0]
        self.assertIn('fetch("/api/route"', route_handler)
        self.assertIn("routeRequestInFlight.current = true", route_handler)
        self.assertIn("routeRequestInFlight.current = false", route_handler)
        self.assertIn("const responseText = await response.text()", route_handler)
        self.assertIn('setRoute(data as Route); setPanel("route")', route_handler)
        self.assertIn('fetch(`/api/geocode?q=${encodeURIComponent(query)}`)', source)
        self.assertIn('onKeyDown={event => { if (event.key === "Enter")', source)
        self.assertIn('aria-label="Start latitude"', source)
        self.assertIn('aria-label="Destination longitude"', source)

    def test_location_and_panel_controls_have_map_selection_cleanup(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        response.close()

        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        self.assertIn("const closePanel = () => { setPanel(null); setSelectMode(null); }", source)
        self.assertIn("navigator.geolocation.getCurrentPosition", source)
        self.assertIn("error.PERMISSION_DENIED", source)
        self.assertIn("error.POSITION_UNAVAILABLE", source)
        self.assertIn("error.code === error.TIMEOUT", source)


class TestPlaceSearchAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def setUp(self):
        app_module._geocoder_cache.clear()
        app_module._geocoder_last_request_at = 0.0

    def test_explicit_place_search_returns_valid_choices_and_caches_results(self):
        provider_response = MagicMock()
        provider_response.__enter__.return_value = provider_response
        provider_response.read.return_value = json.dumps([
            {"display_name": "Kanpur, Uttar Pradesh, India", "lat": "26.449", "lon": "80.331"},
            {"display_name": "Invalid point", "lat": "999", "lon": "80"},
        ]).encode("utf-8")
        with patch.object(app_module, "urlopen", return_value=provider_response) as provider:
            response = self.client.get("/api/geocode?q=Kanpur")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["results"], [{"display_name": "Kanpur, Uttar Pradesh, India", "lat": 26.449, "lon": 80.331}])
            self.assertFalse(data["cached"])

            cached = self.client.get("/api/geocode?q=kanpur")
            self.assertEqual(cached.status_code, 200)
            self.assertTrue(cached.get_json()["cached"])
            self.assertEqual(provider.call_count, 1)
            outgoing = provider.call_args.args[0]
            self.assertIn("format=jsonv2", outgoing.full_url)
            self.assertIn("limit=5", outgoing.full_url)
            self.assertEqual(outgoing.get_header("User-agent"), "NEXUS-Traffic-Intelligence/1.0")

    def test_place_search_validates_query_and_throttles_uncached_requests(self):
        too_short = self.client.get("/api/geocode?q=x")
        self.assertEqual(too_short.status_code, 400)

        provider_response = MagicMock()
        provider_response.__enter__.return_value = provider_response
        provider_response.read.return_value = b"[]"
        with patch.object(app_module, "urlopen", return_value=provider_response) as provider:
            first = self.client.get("/api/geocode?q=Kanpur")
            self.assertEqual(first.status_code, 200)
            throttled = self.client.get("/api/geocode?q=Lucknow")
            self.assertEqual(throttled.status_code, 429)
            self.assertIn("rate limited", throttled.get_json()["error"])
            self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class TestFrontendMapSelectionRegression(unittest.TestCase):
    def test_report_location_selection_exposes_map_and_preserves_route_points(self):
        source = Path(__file__).resolve().parent.parent.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        self.assertIn('panel === "report" && selectMode !== "report"', source)
        self.assertIn('beginMapSelection("report")', source)
        self.assertIn('setReportCoord(point)', source)
        self.assertIn('if (reportCoord) L.circleMarker([reportCoord.lat, reportCoord.lon]', source)
        self.assertIn('setStart({ ...point, label: "Map selection", source: "map" })', source)
        self.assertIn('setDestination({ ...point, label: "Map selection", source: "map" })', source)
        self.assertIn('JSON.stringify(requestCoordinates)', source)
        self.assertIn('const point = { lat: event.latlng.lat, lon: event.latlng.lng }', source)

    def test_map_selection_disables_overlays_and_reports_failures(self):
        root = Path(__file__).resolve().parent.parent
        source = root.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        css = root.joinpath("frontend-vite", "src", "index.css").read_text(encoding="utf-8")
        self.assertIn('selectMode ? "is-selecting-map"', source)
        self.assertIn('.app.is-selecting-map > .sidebar', css)
        self.assertIn('data.error || data.message || `Route calculation failed', source)
        self.assertIn('data.success !== true', source)

class TestFrontendLeafletViewportRegression(unittest.TestCase):
    def test_map_enforces_minimum_zoom_and_uses_road_bounds(self):
        root = Path(__file__).resolve().parent.parent
        source = root.joinpath("frontend-vite", "src", "App.tsx").read_text(encoding="utf-8")
        css = root.joinpath("frontend-vite", "src", "index.css").read_text(encoding="utf-8")
        self.assertIn("const MIN_MAP_ZOOM = 11", source)
        self.assertIn("minZoom: MIN_MAP_ZOOM", source)
        self.assertIn("mapRef.current.getZoom() > MIN_MAP_ZOOM", source)
        self.assertIn("NEXUS_ROAD_BOUNDS", source)
        self.assertIn("map.fitBounds(NEXUS_ROAD_BOUNDS", source)
        self.assertIn("new ResizeObserver", source)
        self.assertIn("map.invalidateSize({ pan: false })", source)
        self.assertIn("html, body, #root { width: 100%; height: 100%; }", css)
        self.assertIn(".map-canvas, .map-canvas .leaflet-container { width: 100%; height: 100%; }", css)

class TestRouteCoverageRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_two_distinct_points_in_supported_coverage_route_successfully(self):
        start = {"lat": 26.475488, "lon": 80.326401}
        destination = {"lat": 26.452836, "lon": 80.350253}
        start_snap = router.snap_to_nearest_node(start["lat"], start["lon"])
        destination_snap = router.snap_to_nearest_node(destination["lat"], destination["lon"])
        self.assertIsNotNone(start_snap)
        self.assertIsNotNone(destination_snap)
        self.assertLess(start_snap.snap_distance_km, 0.5)
        self.assertLess(destination_snap.snap_distance_km, 0.5)
        self.assertNotEqual(start_snap.node, destination_snap.node)

        response = self.client.post("/api/route", json={"start": start, "destination": destination})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["found"])
        self.assertGreater(data["total_distance_km"], 0)
        self.assertGreater(data["estimated_travel_time_s"], 0)
        self.assertGreater(len(data["coordinates"]), 1)

    def test_user_provided_diagnostic_pair_returns_a_real_route(self):
        start = {"lat": 26.449, "lon": 80.331}
        destination = {"lat": 26.467, "lon": 80.354}
        for point in (start, destination):
            snapped = router.snap_to_nearest_node(point["lat"], point["lon"], 0.5)
            self.assertIsNotNone(snapped)
            self.assertEqual(snapped.snap_distance_km, 0.0)

        response = self.client.post("/api/route", json={"start": start, "destination": destination})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["found"])
        self.assertEqual(data["status"], "SUCCESS")
        self.assertGreater(data["total_distance_km"], 0)
        self.assertGreater(data["estimated_travel_time_s"], 0)
        self.assertGreater(len(data["coordinates"]), 1)
        self.assertGreater(len(data["segment_ids"]), 0)

    def test_flask_matches_the_exact_coordinates_from_each_current_request(self):
        points = [
            ((26.475488123, 80.326401456), (26.452836, 80.350253)),
            ((26.4499, 80.3319), (26.4600, 80.3400)),
        ]
        with patch.object(router, "find_route", wraps=router.find_route) as matcher:
            for start, destination in points:
                response = self.client.post("/api/route", json={
                    "start": {"lat": start[0], "lon": start[1]},
                    "destination": {"lat": destination[0], "lon": destination[1]},
                })
                self.assertEqual(response.status_code, 200)
        self.assertEqual(matcher.call_args_list[0].args[:2], points[0])
        self.assertEqual(matcher.call_args_list[1].args[:2], points[1])

    def test_reported_browser_points_are_outside_road_coverage(self):
        start = {"lat": 27.50, "lon": 81.50}
        destination = {"lat": 27.51, "lon": 81.50}
        start_snap = router.snap_to_nearest_node(start["lat"], start["lon"])
        destination_snap = router.snap_to_nearest_node(destination["lat"], destination["lon"])
        self.assertGreater(start_snap.snap_distance_km, 0.5)
        self.assertGreater(destination_snap.snap_distance_km, 0.5)
        self.assertEqual(start_snap.node, destination_snap.node)
        self.assertAlmostEqual(start_snap.snap_distance_km, 150.54, places=1)
        self.assertAlmostEqual(destination_snap.snap_distance_km, 151.31, places=1)

        response = self.client.post("/api/route", json={"start": start, "destination": destination})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["status"], "START_NOT_FOUND")
        self.assertIn("150.54 km away", data["error"])
        self.assertIn("expand the road dataset", data["error"])
        self.assertIsNone(data["snapped_start"])

    def test_outside_coverage_destination_is_rejected_explicitly(self):
        response = self.client.post("/api/route", json={
            "start": {"lat": 26.4499, "lon": 80.3319},
            "destination": {"lat": 27.50, "lon": 81.50},
        })
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["status"], "DESTINATION_NOT_FOUND")
        self.assertIn("150.54 km away", data["error"])

    def test_distinct_nearby_points_genuinely_snapping_to_same_supported_node_are_rejected(self):
        start = {"lat": 26.449001, "lon": 80.331001}
        destination = {"lat": 26.449002, "lon": 80.331002}
        start_snap = router.snap_to_nearest_node(start["lat"], start["lon"], 0.5)
        destination_snap = router.snap_to_nearest_node(destination["lat"], destination["lon"], 0.5)
        self.assertIsNotNone(start_snap)
        self.assertIsNotNone(destination_snap)
        self.assertLess(start_snap.snap_distance_km, 0.5)
        self.assertLess(destination_snap.snap_distance_km, 0.5)
        self.assertEqual(start_snap.node, destination_snap.node)

        response = self.client.post("/api/route", json={"start": start, "destination": destination})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["status"], "SAME_SNAPPED_NODE")

    def test_unmatched_report_coordinate_is_outside_segment_match_coverage(self):
        self.assertIsNone(app_module.road_matcher.match_point(
            27.50, 81.50, app_module.calculate_distance
        ))
