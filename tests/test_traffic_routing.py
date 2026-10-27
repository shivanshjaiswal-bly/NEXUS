"""
Tests for NEXUS Traffic-Aware Routing (Step 25.3)

Verifies that community-reported traffic consensus (via the existing
aggregate_traffic() pipeline) is converted into per-segment travel-time
multipliers and consumed by Router.find_route() through the existing
calculate_edge_cost(edge, traffic_multipliers, edge_cost_func) design.
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app import (
    app,
    reports,
    router,
    road_matcher,
    OSM_DATA_PATH,
    TRAFFIC_CONDITION_MULTIPLIERS,
    traffic_condition_to_multiplier,
    get_current_traffic_multipliers,
    get_current_traffic_routing_state,
    REPORT_EXPIRY_MINUTES,
)
from road_loader import load_road_network

# ---------------------------------------------------------------------------
# Deterministic Central Kanpur fixtures (verified against osm_roads.geojson):
#   - Baseline route between START and DEST traverses CONGESTED_SEGMENT
#     ("osm:way:44135116" / The Mall Road).
#   - A Heavy/Blocked consensus on that segment triggers a valid reroute.
#   - REPORT_COORD matches CONGESTED_SEGMENT via the existing RoadMatcher.
# ---------------------------------------------------------------------------
START = (26.475488, 80.326401)
DEST = (26.452836, 80.350253)
CONGESTED_SEGMENT = "osm:way:44135116"
REPORT_COORD = (26.476596, 80.3335725)
UNKNOWN_SEGMENT = "osm:way:999999999"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _expired_iso():
    expired = datetime.now(timezone.utc) - timedelta(minutes=REPORT_EXPIRY_MINUTES + 1)
    return expired.isoformat()


def _seed_report(condition, incident="None", time_iso=None):
    reports.append({
        "latitude": REPORT_COORD[0],
        "longitude": REPORT_COORD[1],
        "condition": condition,
        "incident": incident,
        "time": time_iso or _now_iso(),
    })


import json
import tempfile

TRAFFIC_FIXTURE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "way/44135116",
            "properties": {
                "osm_id": 44135116,
                "name": "The Mall Road",
                "highway": "primary",
                "maxspeed": 50,
                "oneway": "no",
                "tolerance_km": 0.08,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [80.326401, 26.475488],
                    [80.3335725, 26.476596],
                    [80.350253, 26.452836],
                ],
            },
        },
        {
            "type": "Feature",
            "id": "way/88888888",
            "properties": {
                "osm_id": 88888888,
                "name": "Alternate Road",
                "highway": "secondary",
                "maxspeed": 45,
                "oneway": "no",
                "tolerance_km": 0.08,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [80.326401, 26.475488],
                    [80.330000, 26.460000],
                    [80.350253, 26.452836],
                ],
            },
        },
    ],
}


class TrafficRoutingTestCase(unittest.TestCase):
    """Base class that isolates the shared in-memory report store and uses a deterministic fixture."""

    _fixture_file = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if TrafficRoutingTestCase._fixture_file is None:
            tf = tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False, encoding="utf-8")
            json.dump(TRAFFIC_FIXTURE, tf)
            tf.close()
            TrafficRoutingTestCase._fixture_file = tf.name

        router.build_graph(TRAFFIC_FIXTURE)
        road_matcher.registered_segments.clear()
        load_road_network(TrafficRoutingTestCase._fixture_file, road_matcher)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        router.load_geojson(OSM_DATA_PATH)
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)
        if TrafficRoutingTestCase._fixture_file and os.path.exists(TrafficRoutingTestCase._fixture_file):
            try:
                os.remove(TrafficRoutingTestCase._fixture_file)
            except OSError:
                pass
            TrafficRoutingTestCase._fixture_file = None

    def setUp(self):
        reports.clear()
        if CONGESTED_SEGMENT not in road_matcher.registered_segments:
            load_road_network(TrafficRoutingTestCase._fixture_file, road_matcher)
        self.addCleanup(reports.clear)


class TestTrafficConditionToMultiplier(TrafficRoutingTestCase):
    """1-5: Deterministic condition -> multiplier mapping."""

    # 1a. Mapping uses the exact existing NEXUS condition names.
    def test_01_multiplier_mapping_uses_existing_conditions(self):
        self.assertEqual(
            set(TRAFFIC_CONDITION_MULTIPLIERS.keys()),
            {"Normal", "Moderate", "Heavy"},
        )
        self.assertEqual(traffic_condition_to_multiplier("Normal"), 1.0)
        self.assertEqual(traffic_condition_to_multiplier("Moderate"), 1.25)
        self.assertEqual(traffic_condition_to_multiplier("Heavy"), 1.75)
        self.assertNotIn("Blocked", TRAFFIC_CONDITION_MULTIPLIERS)
        self.assertEqual(traffic_condition_to_multiplier("Blocked"), 1.0)

    # 1b. No traffic reports -> empty multiplier map, routing behaves as before.
    def test_02_no_reports_routing_unchanged(self):
        multipliers = get_current_traffic_multipliers()
        self.assertEqual(multipliers, {})

        baseline = router.find_route(START, DEST)
        weighted = router.find_route(START, DEST, traffic_multipliers=multipliers)
        self.assertTrue(baseline.found)
        self.assertTrue(weighted.found)
        self.assertEqual(baseline.segment_ids, weighted.segment_ids)
        self.assertEqual(baseline.total_distance_km, weighted.total_distance_km)

    # 2. Moderate traffic -> correct segment receives multiplier 1.25.
    def test_03_moderate_report_yields_125(self):
        _seed_report("Moderate")
        multipliers = get_current_traffic_multipliers()
        self.assertEqual(multipliers, {CONGESTED_SEGMENT: 1.25})

    # 3. Heavy traffic -> correct segment receives multiplier 1.75.
    def test_04_heavy_report_yields_175(self):
        _seed_report("Heavy", incident="Accident")
        multipliers = get_current_traffic_multipliers()
        self.assertEqual(multipliers, {CONGESTED_SEGMENT: 1.75})

    # Blocked traffic is represented as an exclusion, not a cost multiplier.
    def test_05_blocked_report_yields_exclusion(self):
        _seed_report("Blocked", incident="Road Block")
        multipliers, blocked_ids = get_current_traffic_routing_state()
        self.assertEqual(multipliers, {})
        self.assertEqual(blocked_ids, {CONGESTED_SEGMENT})

    # 4b. Consensus is reused: mixed reports resolve through existing logic.
    def test_06_consensus_condition_drives_multiplier(self):
        _seed_report("Normal")
        _seed_report("Heavy")
        # Existing consensus: Heavy majority/severity wins over Normal.
        multipliers = get_current_traffic_multipliers()
        self.assertEqual(multipliers, {CONGESTED_SEGMENT: 1.75})

    # 5. Unknown / unreported segment -> multiplier effectively remains 1.0.
    def test_07_unknown_segment_multiplier_is_1(self):
        _seed_report("Heavy")
        multipliers = get_current_traffic_multipliers()
        self.assertNotIn(UNKNOWN_SEGMENT, multipliers)
        self.assertEqual(multipliers.get(UNKNOWN_SEGMENT, 1.0), 1.0)

        edge = next(
            e for node_edges in router.adjacency.values() for e in node_edges
            if e.segment_id == CONGESTED_SEGMENT
        )
        base_cost = router.calculate_edge_cost(edge)
        unreported_cost = router.calculate_edge_cost(edge, {UNKNOWN_SEGMENT: 1.75})
        self.assertAlmostEqual(base_cost, unreported_cost)


class TestTrafficExpiry(TrafficRoutingTestCase):
    """6: Expired reports (> REPORT_EXPIRY_MINUTES) must not affect routing."""

    def test_08_expired_report_does_not_affect_multipliers(self):
        _seed_report("Blocked", incident="Road Block", time_iso=_expired_iso())
        multipliers = get_current_traffic_multipliers()
        self.assertEqual(multipliers, {})
        # Expired report is purged from the store as well.
        self.assertEqual(len(reports), 0)

    def test_09_expired_report_does_not_change_route(self):
        baseline = router.find_route(START, DEST)
        self.assertIn(CONGESTED_SEGMENT, baseline.segment_ids)

        _seed_report("Blocked", incident="Road Block", time_iso=_expired_iso())
        weighted = router.find_route(
            START, DEST, traffic_multipliers=get_current_traffic_multipliers()
        )
        self.assertTrue(weighted.found)
        self.assertEqual(baseline.segment_ids, weighted.segment_ids)
        self.assertIn(CONGESTED_SEGMENT, weighted.segment_ids)


class TestCongestionRerouting(TrafficRoutingTestCase):
    """7: Congestion on the baseline route must change route selection."""

    def test_10_heavy_traffic_changes_route_selection(self):
        baseline = router.find_route(
            START, DEST, traffic_multipliers=get_current_traffic_multipliers()
        )
        self.assertTrue(baseline.found)
        self.assertIn(CONGESTED_SEGMENT, baseline.segment_ids)

        _seed_report("Heavy", incident="Accident")
        congested = router.find_route(
            START, DEST, traffic_multipliers=get_current_traffic_multipliers()
        )
        self.assertTrue(congested.found)
        self.assertNotIn(CONGESTED_SEGMENT, congested.segment_ids)
        self.assertNotEqual(baseline.segment_ids, congested.segment_ids)

    def test_11_blocked_traffic_changes_route_selection(self):
        baseline = router.find_route(START, DEST)
        self.assertIn(CONGESTED_SEGMENT, baseline.segment_ids)

        _seed_report("Blocked", incident="Road Block")
        multipliers, blocked_ids = get_current_traffic_routing_state()
        blocked = router.find_route(
            START, DEST,
            traffic_multipliers=multipliers,
            blocked_segment_ids=blocked_ids,
        )
        self.assertTrue(blocked.found)
        self.assertNotIn(CONGESTED_SEGMENT, blocked.segment_ids)

    def test_12_edge_cost_weighting_uses_existing_calculate_edge_cost(self):
        edge = next(
            e for node_edges in router.adjacency.values() for e in node_edges
            if e.segment_id == CONGESTED_SEGMENT
        )
        base_cost = router.calculate_edge_cost(edge)

        _seed_report("Moderate")
        mod_cost = router.calculate_edge_cost(
            edge, get_current_traffic_multipliers()
        )
        self.assertAlmostEqual(mod_cost, base_cost * 1.25)

        reports.clear()
        _seed_report("Blocked", incident="Road Block")
        multipliers, blocked_ids = get_current_traffic_routing_state()
        self.assertEqual(multipliers, {})
        self.assertIn(CONGESTED_SEGMENT, blocked_ids)
        self.assertEqual(router.calculate_edge_cost(edge, multipliers), base_cost)


class TestRouteAPIWithTraffic(TrafficRoutingTestCase):
    """8: POST /api/route stays contract-stable and becomes traffic-aware."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        app.config["TESTING"] = True
        cls.client = app.test_client()

    ROUTE_PAYLOAD = {
        "start": {"lat": START[0], "lon": START[1]},
        "destination": {"lat": DEST[0], "lon": DEST[1]},
    }

    def test_13_api_valid_route_returns_200_with_stable_schema(self):
        response = self.client.post("/api/route", json=self.ROUTE_PAYLOAD)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        expected_keys = {
            "found", "status", "coordinates", "segment_ids", "road_names",
            "total_distance_km", "estimated_travel_time_s",
            "snapped_start", "snapped_destination",
            "node_count", "edge_count", "error",
        }
        self.assertEqual(set(data.keys()), expected_keys)
        self.assertTrue(data["found"])
        self.assertIn(CONGESTED_SEGMENT, data["segment_ids"])

    def test_14_api_route_avoids_blocked_segment(self):
        # Report a blockage through the existing community report API.
        report_resp = self.client.post("/api/reports", json={
            "latitude": REPORT_COORD[0],
            "longitude": REPORT_COORD[1],
            "condition": "Blocked",
            "incident": "Road Block",
        })
        self.assertEqual(report_resp.status_code, 201)

        response = self.client.post("/api/route", json=self.ROUTE_PAYLOAD)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["found"])
        self.assertNotIn(CONGESTED_SEGMENT, data["segment_ids"])


if __name__ == "__main__":
    unittest.main()
