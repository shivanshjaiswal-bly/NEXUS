import copy
import json
import lzma
import unittest
import uuid
from pathlib import Path

from backend.router import Router, normalize_coord
from backend.app import app
from scripts.road_network import DATASET, inspect_network, install_extract, merge_road_extracts, read_extract, validate_extract


class RoadNetworkDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = json.loads(Path(DATASET).read_text(encoding="utf-8"))
        cls.report = inspect_network(DATASET)

    def test_original_route_coverage_remains_valid(self):
        original = self.report["original_pair"]
        self.assertTrue(all(p["within_snap_limit"] for p in original["endpoints"]))
        self.assertTrue(original["route_found"])
        self.assertGreater(original["route_distance_km"], 0)
        self.assertGreater(original["estimated_travel_time_s"], 0)

    def test_requested_points_are_covered_by_the_installed_dataset(self):
        requested = self.report["requested_pair"]
        self.assertTrue(all(p["within_snap_limit"] for p in requested["endpoints"]))
        self.assertTrue(requested["route_found"])
        self.assertGreater(requested["route_distance_km"], 0)
        self.assertGreater(requested["estimated_travel_time_s"], 0)

    def test_requested_route_api_succeeds_with_the_existing_snap_limit(self):
        client = app.test_client()
        response = client.post("/api/route", json={
            "start": {"lat": 26.505250, "lon": 80.302119},
            "destination": {"lat": 26.458249, "lon": 80.192471},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "SUCCESS")
        self.assertGreater(response.get_json()["total_distance_km"], 0)

    def test_report_includes_graph_size_bounds_and_components(self):
        self.assertEqual(self.report["feature_count"], 29466)
        self.assertEqual(self.report["connected_components"], 35)
        self.assertEqual(self.report["bounds_wgs84_lon_lat"], [80.0855366, 26.3123781, 80.4574299, 26.58751])

    def test_merge_deduplicates_by_osm_way_and_preserves_directional_tags(self):
        original = next(f for f in self.current["features"] if (f.get("properties") or {}).get("oneway") == "yes")
        incoming = copy.deepcopy(original)
        incoming["properties"]["maxspeed"] = "30"
        merged = merge_road_extracts(self.current, {"type": "FeatureCollection", "features": [incoming]}, {
            "source": "test source", "source_url": "https://example.invalid/data", "download_date": "2026-10-22",
        })
        way_id = str(original["properties"]["osm_id"])
        matches = [f for f in merged["features"] if str((f.get("properties") or {}).get("osm_id")) == way_id]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["properties"]["oneway"], "yes")
        self.assertEqual(matches[0]["properties"]["maxspeed"], "30")
        router = Router(); router.build_graph(merged)
        coords = original["geometry"]["coordinates"]
        start = normalize_coord(coords[0][1], coords[0][0]); next_node = normalize_coord(coords[1][1], coords[1][0])
        reverse_edges_for_way = [edge for edge in router.adjacency.get(next_node, [])
                                 if edge.target == start and edge.segment_id == f"osm:way:{way_id}"]
        self.assertEqual(reverse_edges_for_way, [])

    def test_rejects_duplicate_way_ids_and_invalid_road_geometry(self):
        feature = copy.deepcopy(self.current["features"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate OSM way ID"):
            validate_extract({"type": "FeatureCollection", "features": [feature, copy.deepcopy(feature)]})
        malformed = copy.deepcopy(feature)
        malformed["geometry"]["coordinates"][0] = [float("nan"), 26.4]
        with self.assertRaisesRegex(ValueError, "out-of-range coordinate"):
            validate_extract({"type": "FeatureCollection", "features": [malformed]})

    def test_reads_compressed_bbbike_geojson_without_external_converter(self):
        compressed = Path(__file__).resolve().parent / f".extract-{uuid.uuid4().hex}.geojson.xz"
        try:
            compressed.write_bytes(lzma.compress(json.dumps(self.current).encode("utf-8")))
            self.assertEqual(len(read_extract(compressed)["features"]), 29466)
        finally:
            compressed.unlink(missing_ok=True)

    def test_install_rejects_missing_route_before_backup_or_replacement(self):
        test_dir = Path(__file__).resolve().parent
        token = uuid.uuid4().hex
        dataset = test_dir / f".roads-{token}.geojson"
        extract = test_dir / f".extract-{token}.geojson"
        central_only = copy.deepcopy(self.current["features"][0])
        central_only["id"] = "way/999999991"
        central_only["properties"].update({"osm_id": 999999991, "highway": "primary", "oneway": "no"})
        central_only["geometry"]["coordinates"] = [[80.331, 26.449], [80.354, 26.467]]
        isolated_dataset = {"type": "FeatureCollection", "features": [central_only]}
        original_bytes = json.dumps(isolated_dataset).encode("utf-8")
        try:
            dataset.write_bytes(original_bytes)
            extract.write_text(json.dumps(isolated_dataset), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "requested_pair"):
                install_extract(extract, dataset, {
                    "source": "BBBike custom regional extract",
                    "source_url": "https://extract.bbbike.org/",
                    "download_date": "2026-10-22",
                })
            self.assertEqual(dataset.read_bytes(), original_bytes)
            self.assertEqual(list(test_dir.glob(f".roads-{token}.geojson.bak.*")), [])
        finally:
            dataset.unlink(missing_ok=True)
            extract.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
