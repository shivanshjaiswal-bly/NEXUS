import unittest
from datetime import datetime, timezone, timedelta
import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app import (
    app,
    reports,
    compute_centroid,
    get_confidence,
    get_group_status,
    group_reports,
    calculate_distance,
    remove_expired_reports,
    REPORT_EXPIRY_MINUTES,
    road_matcher,
    OSM_DATA_PATH,
)
from road_segment import RoadSegment, RoadMatcher
from road_loader import load_road_network


class TestCentroidCalculation(unittest.TestCase):
    """Automated tests for geographic centroid calculations."""

    def test_one_report_centroid_equals_report(self):
        """One report -> centroid equals that report's latitude and longitude."""
        single_report = [
            {"latitude": 26.4499, "longitude": 80.3319, "condition": "Heavy", "incident": "Accident"}
        ]
        centroid_lat, centroid_lon = compute_centroid(single_report)
        self.assertAlmostEqual(centroid_lat, 26.4499, places=6)
        self.assertAlmostEqual(centroid_lon, 80.3319, places=6)

    def test_two_nearby_reports_centroid_is_average(self):
        """Two nearby reports -> centroid is their mathematical average."""
        report1 = {"latitude": 26.4490, "longitude": 80.3310, "condition": "Moderate", "incident": "None"}
        report2 = {"latitude": 26.4495, "longitude": 80.3315, "condition": "Heavy", "incident": "Accident"}
        
        # Distance between these two is ~74m (within 100m)
        dist_km = calculate_distance(report1["latitude"], report1["longitude"], report2["latitude"], report2["longitude"])
        self.assertLessEqual(dist_km, 0.1)

        centroid_lat, centroid_lon = compute_centroid([report1, report2])
        expected_lat = (26.4490 + 26.4495) / 2
        expected_lon = (80.3310 + 80.3315) / 2

        self.assertAlmostEqual(centroid_lat, expected_lat, places=6)
        self.assertAlmostEqual(centroid_lon, expected_lon, places=6)

    def test_three_nearby_reports_centroid_is_correct(self):
        """Three nearby reports -> centroid is their exact average."""
        report1 = {"latitude": 26.4491, "longitude": 80.3311, "condition": "Moderate", "incident": "None"}
        report2 = {"latitude": 26.4493, "longitude": 80.3314, "condition": "Heavy", "incident": "Road Work"}
        report3 = {"latitude": 26.4495, "longitude": 80.3317, "condition": "Heavy", "incident": "Road Work"}

        group = [report1, report2, report3]
        centroid_lat, centroid_lon = compute_centroid(group)

        expected_lat = (26.4491 + 26.4493 + 26.4495) / 3
        expected_lon = (80.3311 + 80.3314 + 80.3317) / 3

        self.assertAlmostEqual(centroid_lat, expected_lat, places=6)
        self.assertAlmostEqual(centroid_lon, expected_lon, places=6)

    def test_empty_group_centroid_returns_zero(self):
        """Empty group safely returns (0.0, 0.0) without division by zero."""
        centroid_lat, centroid_lon = compute_centroid([])
        self.assertEqual(centroid_lat, 0.0)
        self.assertEqual(centroid_lon, 0.0)


class TestConsensusAndConfidence(unittest.TestCase):
    """Tests ensuring existing community consensus and confidence logic remain intact."""

    def test_condition_consensus_majority(self):
        """Majority vote determines group condition."""
        group = [
            {"latitude": 26.4491, "longitude": 80.3311, "condition": "Heavy", "incident": "None"},
            {"latitude": 26.4492, "longitude": 80.3312, "condition": "Heavy", "incident": "None"},
            {"latitude": 26.4493, "longitude": 80.3313, "condition": "Normal", "incident": "None"},
        ]
        status = get_group_status(group)
        self.assertEqual(status["status"], "Heavy")

    def test_condition_consensus_severity_tiebreaker(self):
        """Tie in condition votes is broken by severity (Blocked > Heavy > Moderate > Normal)."""
        group = [
            {"latitude": 26.4491, "longitude": 80.3311, "condition": "Normal", "incident": "None"},
            {"latitude": 26.4492, "longitude": 80.3312, "condition": "Blocked", "incident": "None"},
        ]
        status = get_group_status(group)
        self.assertEqual(status["status"], "Blocked")

    def test_incident_consensus_majority(self):
        """Majority vote determines group incident."""
        group = [
            {"latitude": 26.4491, "longitude": 80.3311, "condition": "Heavy", "incident": "Road Work"},
            {"latitude": 26.4492, "longitude": 80.3312, "condition": "Heavy", "incident": "Road Work"},
            {"latitude": 26.4493, "longitude": 80.3313, "condition": "Heavy", "incident": "None"},
        ]
        status = get_group_status(group)
        self.assertEqual(status["incident"], "Road Work")

    def test_incident_consensus_severity_tiebreaker(self):
        """Tie in incident votes is broken by severity (Accident > Road Block > Road Work > Other > None)."""
        group = [
            {"latitude": 26.4491, "longitude": 80.3311, "condition": "Moderate", "incident": "Road Work"},
            {"latitude": 26.4492, "longitude": 80.3312, "condition": "Moderate", "incident": "Accident"},
        ]
        status = get_group_status(group)
        self.assertEqual(status["incident"], "Accident")

    def test_confidence_tiers(self):
        """Verify confidence levels: Low (1), Medium (2-3), High (4-5), Very High (6+)."""
        self.assertEqual(get_confidence(1), "Low")
        self.assertEqual(get_confidence(2), "Medium")
        self.assertEqual(get_confidence(3), "Medium")
        self.assertEqual(get_confidence(4), "High")
        self.assertEqual(get_confidence(5), "High")
        self.assertEqual(get_confidence(6), "Very High")
        self.assertEqual(get_confidence(10), "Very High")


class TestReportsAPI(unittest.TestCase):
    """Tests for /api/reports endpoint."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        reports.clear()

    def tearDown(self):
        reports.clear()

    def test_get_reports_empty(self):
        """GET /api/reports returns empty list initially."""
        response = self.client.get("/api/reports")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_post_valid_report(self):
        """POST /api/reports creates report successfully."""
        payload = {
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
        }
        response = self.client.post("/api/reports", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["report"]["condition"], "Heavy")
        self.assertEqual(data["report"]["incident"], "Accident")
        self.assertEqual(data["report"]["latitude"], 26.4499)
        self.assertEqual(data["report"]["longitude"], 80.3319)
        self.assertIn("time", data["report"])

    def test_post_invalid_condition(self):
        """POST /api/reports rejects invalid condition."""
        payload = {
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Jam",
            "incident": "None",
        }
        response = self.client.post("/api/reports", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_post_invalid_incident(self):
        """POST /api/reports rejects invalid incident."""
        payload = {
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Normal",
            "incident": "UnknownIncident",
        }
        response = self.client.post("/api/reports", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_post_missing_coordinates(self):
        """POST /api/reports rejects missing coordinates."""
        payload = {
            "condition": "Normal",
            "incident": "None",
        }
        response = self.client.post("/api/reports", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_post_out_of_range_coordinates(self):
        """POST /api/reports rejects out-of-range coordinates."""
        payload = {
            "latitude": 95.0,
            "longitude": 80.3319,
            "condition": "Normal",
            "incident": "None",
        }
        response = self.client.post("/api/reports", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_report_expiry_purges_old_reports(self):
        """Reports older than 30 minutes are purged upon request."""
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=31)).isoformat()
        recent_time = (now - timedelta(minutes=10)).isoformat()

        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "None",
            "time": old_time,
        })
        reports.append({
            "latitude": 26.4500,
            "longitude": 80.3320,
            "condition": "Moderate",
            "incident": "Road Work",
            "time": recent_time,
        })

        response = self.client.get("/api/reports")
        self.assertEqual(response.status_code, 200)
        active_reports = response.get_json()
        self.assertEqual(len(active_reports), 1)
        self.assertEqual(active_reports[0]["condition"], "Moderate")


class TestTrafficAPI(unittest.TestCase):
    """Tests for /api/traffic endpoint, centroid calculation, and group fields."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        reports.clear()
        road_matcher.registered_segments.clear()

    def tearDown(self):
        reports.clear()
        road_matcher.registered_segments.clear()

    def test_get_traffic_empty(self):
        """GET /api/traffic returns empty list when no reports exist."""
        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_get_traffic_single_report_centroid_and_fields(self):
        """Single report -> /api/traffic returns centroid equal to report, and all required fields."""
        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        # Required fields in /api/traffic
        self.assertIn("latitude", group)
        self.assertIn("longitude", group)
        self.assertIn("status", group)
        self.assertIn("incident", group)
        self.assertIn("report_count", group)
        self.assertIn("confidence", group)
        self.assertIn("segment_id", group)

        # Centroid matches single report
        self.assertAlmostEqual(group["latitude"], 26.4499, places=6)
        self.assertAlmostEqual(group["longitude"], 80.3319, places=6)
        self.assertEqual(group["status"], "Heavy")
        self.assertEqual(group["incident"], "Accident")
        self.assertEqual(group["report_count"], 1)
        self.assertEqual(group["confidence"], "Low")

    def test_get_traffic_two_nearby_reports_centroid(self):
        """Two nearby reports (<100m) are clustered into 1 group with centroid as average."""
        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.4490,
            "longitude": 80.3310,
            "condition": "Moderate",
            "incident": "None",
            "time": now,
        })
        reports.append({
            "latitude": 26.4495,
            "longitude": 80.3315,
            "condition": "Heavy",
            "incident": "Accident",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        expected_lat = (26.4490 + 26.4495) / 2
        expected_lon = (80.3310 + 80.3315) / 2

        self.assertAlmostEqual(group["latitude"], expected_lat, places=6)
        self.assertAlmostEqual(group["longitude"], expected_lon, places=6)
        self.assertEqual(group["report_count"], 2)
        self.assertEqual(group["confidence"], "Medium")
        # Tie-breaker between Moderate and Heavy -> Heavy wins
        self.assertEqual(group["status"], "Heavy")
        # Tie-breaker between None and Accident -> Accident wins
        self.assertEqual(group["incident"], "Accident")

    def test_get_traffic_three_nearby_reports_centroid(self):
        """Three nearby reports are grouped with accurate average centroid."""
        now = datetime.now(timezone.utc).isoformat()
        r1 = {"latitude": 26.4491, "longitude": 80.3311, "condition": "Moderate", "incident": "None", "time": now}
        r2 = {"latitude": 26.4493, "longitude": 80.3314, "condition": "Moderate", "incident": "Road Work", "time": now}
        r3 = {"latitude": 26.4495, "longitude": 80.3317, "condition": "Heavy", "incident": "Road Work", "time": now}
        reports.extend([r1, r2, r3])

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        expected_lat = (26.4491 + 26.4493 + 26.4495) / 3
        expected_lon = (80.3311 + 80.3314 + 80.3317) / 3

        self.assertAlmostEqual(group["latitude"], expected_lat, places=6)
        self.assertAlmostEqual(group["longitude"], expected_lon, places=6)
        self.assertEqual(group["report_count"], 3)
        self.assertEqual(group["confidence"], "Medium")
        self.assertEqual(group["status"], "Moderate")  # 2 Moderate vs 1 Heavy
        self.assertEqual(group["incident"], "Road Work")  # 2 Road Work vs 1 None

    def test_get_traffic_distant_reports_separated(self):
        """Reports separated by more than 100m form distinct groups, each with its own centroid."""
        now = datetime.now(timezone.utc).isoformat()
        # Location A: Kanpur
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "None",
            "time": now,
        })
        # Location B: ~5 km away
        reports.append({
            "latitude": 26.4900,
            "longitude": 80.3319,
            "condition": "Normal",
            "incident": "None",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 2)

        # Each group has its own report as its centroid
        group_lats = {round(g["latitude"], 4) for g in traffic}
        self.assertIn(26.4499, group_lats)
        self.assertIn(26.4900, group_lats)

    def test_get_traffic_excludes_expired_reports(self):
        """Expired reports (>30 min) are not included in /api/traffic groups."""
        now = datetime.now(timezone.utc)
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
            "time": (now - timedelta(minutes=35)).isoformat(),
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_get_traffic_includes_segment_id_field_unmatched(self):
        """When no registered road network matches, segment_id is None without inventing road names."""
        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Moderate",
            "incident": "None",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)
        self.assertIn("segment_id", traffic[0])
        self.assertIsNone(traffic[0]["segment_id"])
        self.assertNotIn("road_name", traffic[0])

    def test_get_traffic_with_matched_road_segment(self):
        """When a road segment is registered and reports fall within tolerance, segment_id is attached."""
        road_matcher.register_segment(
            segment_id="osm:way:987654321",
            latitude=26.4499,
            longitude=80.3319,
            name="Mall Road",
            tolerance_km=0.08,
        )

        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:987654321")
        self.assertEqual(group["road_name"], "Mall Road")
        self.assertEqual(group["status"], "Heavy")
        self.assertEqual(group["incident"], "Accident")


class TestRoadSegmentAbstraction(unittest.TestCase):
    """Automated tests for the RoadSegment class abstraction."""

    def test_road_segment_instantiation_and_fields(self):
        """Test RoadSegment holds all expected attributes."""
        segment = RoadSegment(
            segment_id="osm:way:101",
            latitude=26.4499,
            longitude=80.3319,
            status="Heavy",
            incident="Accident",
            report_count=4,
            confidence="High",
            road_name="NH 27",
        )
        self.assertEqual(segment.segment_id, "osm:way:101")
        self.assertEqual(segment.latitude, 26.4499)
        self.assertEqual(segment.longitude, 80.3319)
        self.assertEqual(segment.status, "Heavy")
        self.assertEqual(segment.incident, "Accident")
        self.assertEqual(segment.report_count, 4)
        self.assertEqual(segment.confidence, "High")
        self.assertEqual(segment.road_name, "NH 27")

    def test_road_segment_to_dict_preserves_all_fields(self):
        """to_dict() provides backward-compatible dictionary for /api/traffic."""
        segment = RoadSegment(
            segment_id="osm:way:202",
            latitude=26.4500,
            longitude=80.3300,
            status="Moderate",
            incident="Road Work",
            report_count=2,
            confidence="Medium",
        )
        d = segment.to_dict()
        self.assertEqual(d["segment_id"], "osm:way:202")
        self.assertEqual(d["latitude"], 26.4500)
        self.assertEqual(d["longitude"], 80.3300)
        self.assertEqual(d["status"], "Moderate")
        self.assertEqual(d["incident"], "Road Work")
        self.assertEqual(d["report_count"], 2)
        self.assertEqual(d["confidence"], "Medium")

    def test_road_segment_no_invented_road_name(self):
        """road_name defaults to None and is not invented."""
        segment = RoadSegment(
            latitude=26.4499,
            longitude=80.3319,
            status="Normal",
            incident="None",
            report_count=1,
            confidence="Low",
        )
        self.assertIsNone(segment.road_name)
        d = segment.to_dict()
        self.assertNotIn("road_name", d)


class TestRoadMatcher(unittest.TestCase):
    """Automated tests for RoadMatcher matching logic and documentation."""

    def setUp(self):
        self.matcher = RoadMatcher()

    def test_matcher_unmatched_defaults_to_none(self):
        """When no registered segments exist, match returns segment_id=None without hallucinating."""
        group = [{"latitude": 26.4499, "longitude": 80.3319, "condition": "Normal", "incident": "None"}]
        segment = self.matcher.match(
            group=group,
            centroid_lat=26.4499,
            centroid_lon=80.3319,
            status="Normal",
            incident="None",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertIsNone(segment.segment_id)
        self.assertIsNone(segment.road_name)

    def test_matcher_registered_segment_match(self):
        """Matcher associates cluster to a registered road segment within tolerance."""
        self.matcher.register_segment(
            segment_id="osm:way:456",
            latitude=26.4499,
            longitude=80.3319,
            name="Civil Lines Road",
            tolerance_km=0.05,
        )

        group = [{"latitude": 26.4500, "longitude": 80.3320, "condition": "Heavy", "incident": "None"}]
        segment = self.matcher.match(
            group=group,
            centroid_lat=26.4500,
            centroid_lon=80.3320,
            status="Heavy",
            incident="None",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertEqual(segment.segment_id, "osm:way:456")
        self.assertEqual(segment.road_name, "Civil Lines Road")

    def test_matcher_out_of_tolerance_remains_unmatched(self):
        """Reports farther than tolerance distance remain unmatched."""
        self.matcher.register_segment(
            segment_id="osm:way:456",
            latitude=26.4499,
            longitude=80.3319,
            name="Civil Lines Road",
            tolerance_km=0.02,
        )

        # ~5 km away
        group = [{"latitude": 26.4900, "longitude": 80.3319, "condition": "Heavy", "incident": "None"}]
        segment = self.matcher.match(
            group=group,
            centroid_lat=26.4900,
            centroid_lon=80.3319,
            status="Heavy",
            incident="None",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertIsNone(segment.segment_id)
        self.assertIsNone(segment.road_name)


class TestRoadNetworkLoader(unittest.TestCase):
    """Automated tests for local OpenStreetMap road-network loading (Step 19)."""

    def setUp(self):
        self.matcher = RoadMatcher()

    def test_load_valid_geojson_dataset(self):
        """Loads valid local OSM GeoJSON dataset, registering segments with valid IDs."""
        count = load_road_network(OSM_DATA_PATH, self.matcher)
        self.assertGreaterEqual(count, 3)
        self.assertIn("osm:way:115798991", self.matcher.registered_segments)
        self.assertIn("osm:way:23984102", self.matcher.registered_segments)
        self.assertIn("osm:way:9999901", self.matcher.registered_segments)

    def test_missing_dataset_fails_safely(self):
        """Missing dataset path returns 0 without raising an exception."""
        non_existent_path = os.path.join(os.path.dirname(__file__), "missing_dataset.geojson")
        count = load_road_network(non_existent_path, self.matcher)
        self.assertEqual(count, 0)
        self.assertEqual(len(self.matcher.registered_segments), 0)

    def test_invalid_dataset_fails_safely(self):
        """Corrupted/invalid JSON dataset fails safely and returns 0."""
        invalid_path = os.path.join(os.path.dirname(__file__), "temp_invalid.json")
        try:
            with open(invalid_path, "w", encoding="utf-8") as f:
                f.write("{invalid_json: true, unterminated string...")
            count = load_road_network(invalid_path, self.matcher)
            self.assertEqual(count, 0)
        finally:
            if os.path.exists(invalid_path):
                os.remove(invalid_path)

    def test_registering_road_segments_with_geometry(self):
        """Extracted segments retain normalized coordinates and geometry."""
        load_road_network(OSM_DATA_PATH, self.matcher)
        seg = self.matcher.registered_segments["osm:way:115798991"]
        self.assertEqual(seg["name"], "Grand Trunk Road")
        self.assertIsInstance(seg["geometry"], list)
        self.assertGreater(len(seg["geometry"]), 1)
        # Verify coordinates are (lat, lon)
        lat, lon = seg["geometry"][0]
        self.assertAlmostEqual(lat, 26.4490, places=3)
        self.assertAlmostEqual(lon, 80.3310, places=3)

    def test_match_gps_point_to_known_local_road_segment(self):
        """A GPS point near a known road segment matches that segment and receives its verified name."""
        load_road_network(OSM_DATA_PATH, self.matcher)
        group = [{"latitude": 26.4499, "longitude": 80.3319, "condition": "Heavy", "incident": "Accident"}]
        matched = self.matcher.match(
            group=group,
            centroid_lat=26.4499,
            centroid_lon=80.3319,
            status="Heavy",
            incident="Accident",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertEqual(matched.segment_id, "osm:way:115798991")
        self.assertEqual(matched.road_name, "Grand Trunk Road")

    def test_preserving_unmatched_behavior(self):
        """A GPS point far from any known road segment remains unmatched (segment_id=None, road_name=None)."""
        load_road_network(OSM_DATA_PATH, self.matcher)
        group = [{"latitude": 26.5500, "longitude": 80.4500, "condition": "Normal", "incident": "None"}]
        matched = self.matcher.match(
            group=group,
            centroid_lat=26.5500,
            centroid_lon=80.4500,
            status="Normal",
            incident="None",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertIsNone(matched.segment_id)
        self.assertIsNone(matched.road_name)

    def test_ensuring_road_names_come_only_from_supplied_data(self):
        """A matched segment with no 'name' property in the OSM data does not invent a road name."""
        load_road_network(OSM_DATA_PATH, self.matcher)
        # Coordinate near osm:way:9999901 (26.4550, 80.3350)
        group = [{"latitude": 26.4550, "longitude": 80.3350, "condition": "Moderate", "incident": "None"}]
        matched = self.matcher.match(
            group=group,
            centroid_lat=26.4550,
            centroid_lon=80.3350,
            status="Moderate",
            incident="None",
            report_count=1,
            confidence="Low",
            distance_func=calculate_distance,
        )
        self.assertEqual(matched.segment_id, "osm:way:9999901")
        self.assertIsNone(matched.road_name)
        d = matched.to_dict()
        self.assertNotIn("road_name", d)

    def test_existing_api_behavior_with_loaded_osm_dataset(self):
        """End-to-end /api/traffic with loaded dataset returns verified OSM segment and road name."""
        app.config["TESTING"] = True
        client = app.test_client()
        reports.clear()
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)

        now = datetime.now(timezone.utc).isoformat()
        # Report near Mall Road
        reports.append({
            "latitude": 26.4650,
            "longitude": 80.3500,
            "condition": "Moderate",
            "incident": "Road Work",
            "time": now,
        })

        response = client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:23984102")
        self.assertEqual(group["road_name"], "Mall Road")
        self.assertEqual(group["status"], "Moderate")
        self.assertEqual(group["incident"], "Road Work")
        self.assertEqual(group["report_count"], 1)
        self.assertEqual(group["confidence"], "Low")
        self.assertIn("latitude", group)
        self.assertIn("longitude", group)


class TestFrontendServing(unittest.TestCase):
    """Automated tests confirming Flask serves the NEXUS frontend Web UI."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_get_root_serves_frontend(self):
        """GET / returns HTTP 200 and loads the NEXUS frontend HTML."""
        with self.client.get("/") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.content_type)
            content = response.get_data(as_text=True)
            self.assertIn("NEXUS — Real-Time Traffic Intelligence", content)
            self.assertIn('id="map"', content)
            self.assertIn("loadTraffic()", content)
            self.assertIn("tile.openstreetmap.org", content)

    def test_get_index_html_serves_frontend(self):
        """GET /index.html returns HTTP 200 and loads the NEXUS frontend HTML."""
        with self.client.get("/index.html") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.content_type)
            content = response.get_data(as_text=True)
            self.assertIn("NEXUS — Real-Time Traffic Intelligence", content)


class TestEndToEndRoadMatchingPipeline(unittest.TestCase):
    """End-to-end integration tests verifying the full flow:
    POST /api/reports -> grouping -> centroid -> RoadMatcher -> GET /api/traffic
    with real local OSM GeoJSON data.
    """

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        reports.clear()
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)

    def tearDown(self):
        reports.clear()
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)

    def test_startup_loads_dataset_into_road_matcher(self):
        """Verify startup successfully loaded data/osm_roads.geojson into road_matcher."""
        self.assertGreaterEqual(len(road_matcher.registered_segments), 3)
        self.assertIn("osm:way:115798991", road_matcher.registered_segments)
        self.assertIn("osm:way:23984102", road_matcher.registered_segments)
        self.assertIn("osm:way:9999901", road_matcher.registered_segments)

    def test_case_a_single_gps_report_near_known_osm_road(self):
        """Test Case A: Single GPS report close to known OSM road receives correct segment_id and road_name."""
        post_resp = self.client.post("/api/reports", json={
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
        })
        self.assertEqual(post_resp.status_code, 201)

        get_resp = self.client.get("/api/traffic")
        self.assertEqual(get_resp.status_code, 200)
        traffic = get_resp.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:115798991")
        self.assertEqual(group["road_name"], "Grand Trunk Road")
        self.assertEqual(group["status"], "Heavy")
        self.assertEqual(group["incident"], "Accident")
        self.assertEqual(group["report_count"], 1)
        self.assertEqual(group["confidence"], "Low")
        self.assertAlmostEqual(group["latitude"], 26.4499, places=6)
        self.assertAlmostEqual(group["longitude"], 80.3319, places=6)

    def test_case_b_multiple_nearby_reports_on_same_road(self):
        """Test Case B: Multiple nearby reports on same road form one group, preserve consensus, confidence, count, and match segment."""
        # 3 reports within ~50m along Grand Trunk Road
        r1 = {"latitude": 26.4498, "longitude": 80.3318, "condition": "Heavy", "incident": "Accident"}
        r2 = {"latitude": 26.4500, "longitude": 80.3320, "condition": "Heavy", "incident": "Accident"}
        r3 = {"latitude": 26.4502, "longitude": 80.3322, "condition": "Moderate", "incident": "None"}

        for r in (r1, r2, r3):
            resp = self.client.post("/api/reports", json=r)
            self.assertEqual(resp.status_code, 201)

        get_resp = self.client.get("/api/traffic")
        self.assertEqual(get_resp.status_code, 200)
        traffic = get_resp.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:115798991")
        self.assertEqual(group["road_name"], "Grand Trunk Road")
        self.assertEqual(group["report_count"], 3)
        self.assertEqual(group["confidence"], "Medium")
        # Consensus: 2 Heavy vs 1 Moderate -> Heavy
        self.assertEqual(group["status"], "Heavy")
        # Consensus: 2 Accident vs 1 None -> Accident
        self.assertEqual(group["incident"], "Accident")
        # Centroid: exact average
        expected_lat = (26.4498 + 26.4500 + 26.4502) / 3
        expected_lon = (80.3318 + 80.3320 + 80.3322) / 3
        self.assertAlmostEqual(group["latitude"], expected_lat, places=6)
        self.assertAlmostEqual(group["longitude"], expected_lon, places=6)

    def test_case_c_gps_point_far_from_local_road_dataset(self):
        """Test Case C: GPS point far from local dataset remains unmatched (segment_id=None, road_name=None)."""
        post_resp = self.client.post("/api/reports", json={
            "latitude": 26.5500,
            "longitude": 80.4500,
            "condition": "Blocked",
            "incident": "Road Block",
        })
        self.assertEqual(post_resp.status_code, 201)

        get_resp = self.client.get("/api/traffic")
        self.assertEqual(get_resp.status_code, 200)
        traffic = get_resp.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertIsNone(group["segment_id"])
        self.assertNotIn("road_name", group)
        self.assertEqual(group["status"], "Blocked")
        self.assertEqual(group["incident"], "Road Block")
        self.assertEqual(group["report_count"], 1)
        self.assertEqual(group["confidence"], "Low")

    def test_case_d_unnamed_osm_road_segment_never_receives_fabricated_name(self):
        """Test Case D: Unnamed OSM road segment matches segment_id but never invents a road name."""
        # Near unnamed service road osm:way:9999901 (26.4550, 80.3350)
        post_resp = self.client.post("/api/reports", json={
            "latitude": 26.4550,
            "longitude": 80.3350,
            "condition": "Moderate",
            "incident": "Road Work",
        })
        self.assertEqual(post_resp.status_code, 201)

        get_resp = self.client.get("/api/traffic")
        self.assertEqual(get_resp.status_code, 200)
        traffic = get_resp.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:9999901")
        # Must never receive a fabricated road name
        self.assertNotIn("road_name", group)
        self.assertEqual(group["status"], "Moderate")
        self.assertEqual(group["incident"], "Road Work")

    def test_multiple_distinct_roads_mapped_correctly(self):
        """Reports on two distinct roads correctly form two groups with respective OSM data."""
        # Report 1 on Grand Trunk Road
        self.client.post("/api/reports", json={
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
        })
        # Report 2 on Mall Road (~2.5 km away)
        self.client.post("/api/reports", json={
            "latitude": 26.4660,
            "longitude": 80.3520,
            "condition": "Normal",
            "incident": "None",
        })

        get_resp = self.client.get("/api/traffic")
        self.assertEqual(get_resp.status_code, 200)
        traffic = get_resp.get_json()
        self.assertEqual(len(traffic), 2)

        matched_names = {g.get("road_name") for g in traffic}
        matched_ids = {g.get("segment_id") for g in traffic}
        self.assertIn("Grand Trunk Road", matched_names)
        self.assertIn("Mall Road", matched_names)
        self.assertIn("osm:way:115798991", matched_ids)
        self.assertIn("osm:way:23984102", matched_ids)


class TestStep22RoadVisualization(unittest.TestCase):
    """
    Step 22: Road-Segment Traffic Visualization.

    Backend tests verify that:
    A. Matched OSM segments expose 'geometry' in /api/traffic.
    B. Geometry format is [[lat, lon], ...] (Leaflet-ready).
    C. Unmatched (segment_id=null) groups do NOT include geometry.
    D. 'road_name' is absent for unnamed segments.
    E. RoadSegment.to_dict() serialises geometry correctly.
    F. Frontend HTML contains polyline rendering logic.
    """

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        reports.clear()
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)

    def tearDown(self):
        reports.clear()
        road_matcher.registered_segments.clear()
        load_road_network(OSM_DATA_PATH, road_matcher)

    # A + B — matched segment exposes geometry in correct [[lat, lon]] format
    def test_matched_segment_includes_geometry(self):
        """Matched OSM segment in /api/traffic includes 'geometry' as [[lat, lon], ...]."""
        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.4499,
            "longitude": 80.3319,
            "condition": "Heavy",
            "incident": "Accident",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:115798991")
        self.assertIn("geometry", group)

        geom = group["geometry"]
        self.assertIsInstance(geom, list)
        self.assertGreaterEqual(len(geom), 2)

        # Each point must be [lat, lon] — lat in range ~26, lon in range ~80
        for point in geom:
            self.assertIsInstance(point, list)
            self.assertEqual(len(point), 2)
            lat, lon = point
            self.assertAlmostEqual(lat, 26.449, delta=0.1)
            self.assertAlmostEqual(lon, 80.331, delta=0.1)

    # C — unmatched group omits geometry
    def test_unmatched_group_has_no_geometry(self):
        """Unmatched (segment_id=null) group must not include 'geometry'."""
        now = datetime.now(timezone.utc).isoformat()
        reports.append({
            "latitude": 26.5500,
            "longitude": 80.4500,
            "condition": "Moderate",
            "incident": "None",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertIsNone(group["segment_id"])
        self.assertNotIn("geometry", group)

    # D — unnamed segment omits road_name, still includes geometry
    def test_unnamed_segment_has_geometry_but_no_road_name(self):
        """Unnamed OSM segment includes geometry but no road_name key."""
        now = datetime.now(timezone.utc).isoformat()
        # Near osm:way:9999901 (unnamed service road at ~26.4550, 80.3350)
        reports.append({
            "latitude": 26.4550,
            "longitude": 80.3350,
            "condition": "Normal",
            "incident": "None",
            "time": now,
        })

        response = self.client.get("/api/traffic")
        self.assertEqual(response.status_code, 200)
        traffic = response.get_json()
        self.assertEqual(len(traffic), 1)

        group = traffic[0]
        self.assertEqual(group["segment_id"], "osm:way:9999901")
        self.assertNotIn("road_name", group)
        self.assertIn("geometry", group)
        self.assertGreaterEqual(len(group["geometry"]), 2)

    # E — RoadSegment.to_dict() serialises geometry as [[lat, lon]]
    def test_road_segment_to_dict_serialises_geometry(self):
        """RoadSegment.to_dict() converts internal (lat, lon) tuples to [[lat, lon]] lists."""
        segment = RoadSegment(
            segment_id="osm:way:test001",
            latitude=26.4499,
            longitude=80.3319,
            status="Heavy",
            incident="Accident",
            report_count=2,
            confidence="Medium",
            road_name="Test Road",
            geometry=[(26.4490, 80.3310), (26.4499, 80.3319), (26.4510, 80.3330)],
        )
        d = segment.to_dict()
        self.assertIn("geometry", d)
        self.assertEqual(d["geometry"], [[26.4490, 80.3310], [26.4499, 80.3319], [26.4510, 80.3330]])

    # RoadSegment with empty geometry omits the field
    def test_road_segment_empty_geometry_omitted(self):
        """RoadSegment with no geometry does not include 'geometry' in to_dict()."""
        segment = RoadSegment(
            latitude=26.4499,
            longitude=80.3319,
            status="Normal",
            incident="None",
            report_count=1,
            confidence="Low",
        )
        d = segment.to_dict()
        self.assertNotIn("geometry", d)

    # F — frontend HTML contains polyline rendering logic
    def test_frontend_html_contains_polyline_rendering(self):
        """GET / serves frontend HTML that includes Leaflet polyline rendering for OSM segments."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        # Polyline rendering keyword
        self.assertIn("L.polyline", content)
        # Geometry field access
        self.assertIn("group.geometry", content)
        # Unmatched fallback circle marker is still present
        self.assertIn("L.circleMarker", content)
        # Legend distinguishes OSM-matched vs unmatched
        self.assertIn("legend-line", content)
        self.assertIn("legend-dot", content)


class TestStep23RealtimePolling(unittest.TestCase):
    """
    Step 23: Near-real-time traffic updates (frontend polling).

    Verifies that the served frontend:
    A. Polls GET /api/traffic about every 10 seconds.
    B. Starts exactly one automatic setInterval timer.
    C. Handles visibilitychange (pause when hidden, refresh when visible).
    D. Still calls loadTraffic() on load and after a successful report POST.
    E. Shows a live update status, including a non-destructive failure message.
    F. Preserves Step 22 polyline / circle-marker visualization and clearLayers on success.
    """

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_frontend_uses_approximately_10_second_polling(self):
        """Automatic traffic refresh interval is ~10 seconds, not 60."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertIn("TRAFFIC_POLL_MS = 10000", content)
        self.assertIn("setInterval(loadTraffic, TRAFFIC_POLL_MS)", content)
        self.assertNotIn("60000", content)

    def test_frontend_has_exactly_one_automatic_polling_timer(self):
        """There is exactly one setInterval call for traffic polling."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertEqual(content.count("setInterval("), 1)
        self.assertIn("if (trafficPollTimer !== null)", content)
        self.assertIn("startTrafficPolling()", content)
        self.assertIn("stopTrafficPolling()", content)

    def test_frontend_handles_visibilitychange(self):
        """Hidden tabs stop polling; becoming visible calls loadTraffic() and resumes polling."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertIn('document.addEventListener("visibilitychange"', content)
        self.assertIn("document.hidden", content)
        self.assertIn("stopTrafficPolling()", content)
        # Immediate refresh when the tab is shown again
        self.assertRegex(
            content,
            r'visibilitychange[\s\S]*document\.hidden[\s\S]*loadTraffic\(\)[\s\S]*startTrafficPolling\(\)',
        )

    def test_frontend_calls_load_traffic_and_refreshes_after_submit(self):
        """loadTraffic() exists and is still invoked after a successful report submission."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertIn("loadTraffic()", content)
        self.assertIn('fetch("/api/traffic")', content)
        # Immediate refresh after this user's successful POST (must appear once in submitTrafficReport)
        submit_idx = content.find("async function submitTrafficReport()")
        self.assertGreater(submit_idx, -1)
        next_fn = content.find("\n        function ", submit_idx + 1)
        submit_block = content[submit_idx: next_fn if next_fn != -1 else None]
        self.assertIn("loadTraffic()", submit_block)
        self.assertEqual(submit_block.count("loadTraffic()"), 1)

    def test_frontend_live_status_and_non_destructive_failure(self):
        """Live status text updates on success; failures retry without clearing existing layers."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertIn("Live traffic • Updated just now", content)
        self.assertIn("Live traffic • Update failed — retrying", content)
        self.assertIn('id="liveTrafficStatus"', content)
        self.assertIn("trafficLayer.clearLayers()", content)
        # Failure paths set the retry status and return before redrawing
        self.assertIn("Update failed — retrying", content)
        fail_ok_idx = content.find("if (!response.ok)")
        self.assertGreater(fail_ok_idx, -1)
        clear_idx = content.find("trafficLayer.clearLayers()")
        self.assertGreater(clear_idx, fail_ok_idx)
        fail_block = content[fail_ok_idx:clear_idx]
        self.assertIn("Update failed — retrying", fail_block)
        self.assertIn("return;", fail_block)
        self.assertNotIn("trafficLayer.clearLayers()", fail_block)

    def test_frontend_preserves_step22_visualization(self):
        """Step 22 polyline vs circle-marker rendering remains intact."""
        content = self.client.get("/").get_data(as_text=True)
        self.assertIn("L.polyline", content)
        self.assertIn("group.geometry", content)
        self.assertIn("L.circleMarker", content)
        self.assertIn("legend-line", content)
        self.assertIn("legend-dot", content)
        self.assertIn("segmentWeight", content)


if __name__ == "__main__":
    unittest.main()

