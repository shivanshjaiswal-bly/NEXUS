"""
Tests for Standalone Router Engine (Step 25.1)
"""

import json
import os
import unittest

from backend.router import (
    Router,
    build_graph,
    haversine_distance,
    normalize_coord,
    Edge,
    SnappedNode,
    RouteResult,
)


class TestRouterEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.geojson_path = os.path.join(base_dir, "data", "osm_roads.geojson")
        cls.router = Router(cls.geojson_path)

    # 1. GeoJSON graph loading
    def test_01_geojson_graph_loading(self):
        self.assertEqual(self.router.feature_count, 248)
        self.assertEqual(len(self.router.nodes), 2179)
        self.assertEqual(self.router.count_connected_components(), 1)
        self.assertGreater(self.router.edge_count, 3000)

    # 2. Expected baseline segment IDs
    def test_02_baseline_segment_ids_exist(self):
        baselines = ["osm:way:115798991", "osm:way:23984102", "osm:way:9999901"]
        for seg_id in baselines:
            self.assertIn(
                seg_id,
                self.router.segment_ids,
                f"Required baseline segment {seg_id} missing from graph",
            )

    # 3. Node normalization
    def test_03_node_normalization(self):
        norm = normalize_coord(26.4490001234, 80.3310001234)
        self.assertEqual(norm, (26.449, 80.331))
        norm_str = normalize_coord("26.1234567", "80.7654321")
        self.assertEqual(norm_str, (26.123457, 80.765432))

    # 4. Haversine distance
    def test_04_haversine_distance(self):
        d = haversine_distance(26.449, 80.331, 26.467, 80.354)
        self.assertAlmostEqual(d, 3.02, delta=0.1)
        self.assertEqual(haversine_distance(26.449, 80.331, 26.449, 80.331), 0.0)

    # 5. One-way edge behavior
    def test_05_oneway_edge_behavior(self):
        synthetic = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "osm_id": 1001,
                        "oneway": "yes",
                        "highway": "primary",
                        "name": "OneWay St",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[80.33, 26.44], [80.34, 26.44]],
                    },
                }
            ],
        }
        r = build_graph(synthetic)
        node_a = normalize_coord(26.44, 80.33)
        node_b = normalize_coord(26.44, 80.34)

        fwd = r.find_route(node_a, node_b)
        self.assertTrue(fwd.found)
        self.assertEqual(fwd.status, "SUCCESS")

        rev = r.find_route(node_b, node_a)
        self.assertFalse(rev.found)
        self.assertEqual(rev.status, "NO_PATH_FOUND")

    # 6. Bidirectional edge behavior
    def test_06_bidirectional_edge_behavior(self):
        synthetic = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "osm_id": 1002,
                        "oneway": "no",
                        "highway": "secondary",
                        "name": "TwoWay Ave",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[80.33, 26.44], [80.34, 26.44]],
                    },
                }
            ],
        }
        r = build_graph(synthetic)
        node_a = normalize_coord(26.44, 80.33)
        node_b = normalize_coord(26.44, 80.34)

        fwd = r.find_route(node_a, node_b)
        self.assertTrue(fwd.found)
        self.assertEqual(fwd.status, "SUCCESS")

        rev = r.find_route(node_b, node_a)
        self.assertTrue(rev.found)
        self.assertEqual(rev.status, "SUCCESS")
        self.assertAlmostEqual(fwd.total_distance_km, rev.total_distance_km, places=4)

    # 7. Nearest-node snapping
    def test_07_nearest_node_snapping(self):
        # Point slightly offset from GT Road start node (26.449, 80.331)
        query_lat = 26.44905
        query_lon = 80.33105
        snapped = self.router.snap_to_nearest_node(query_lat, query_lon)

        self.assertIsNotNone(snapped)
        self.assertEqual(snapped.node, (26.449, 80.331))
        self.assertGreater(snapped.snap_distance_km, 0.0)
        self.assertLess(snapped.snap_distance_km, 0.05)  # Less than 50 meters

    # 8. Simple route between two connected nodes
    def test_08_simple_route_between_connected_nodes(self):
        node_a = (26.449, 80.331)
        node_b = (26.4499, 80.3319)
        res = self.router.find_route(node_a, node_b)

        self.assertTrue(res.found)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.node_count, 2)
        self.assertEqual(res.edge_count, 1)

    # 9. Route result contains ordered coordinates
    def test_09_route_result_ordered_coordinates(self):
        start = (26.449, 80.331)
        dest = (26.467, 80.354)
        res = self.router.find_route(start, dest)

        self.assertTrue(res.found)
        self.assertGreater(len(res.coordinates), 10)
        self.assertEqual(res.coordinates[0], start)
        self.assertEqual(res.coordinates[-1], dest)


    # 10. Route result contains segment IDs
    def test_10_route_result_contains_segment_ids(self):
        start = (26.449, 80.331)
        dest = (26.467, 80.354)
        res = self.router.find_route(start, dest)

        self.assertTrue(res.found)
        self.assertGreater(len(res.segment_ids), 0)
        for s_id in res.segment_ids:
            self.assertTrue(s_id.startswith("osm:way:"))

        self.assertEqual(res.segment_ids[0], "osm:way:115798991")

    # 11. Distance is positive
    def test_11_distance_is_positive(self):
        start = (26.449, 80.331)
        dest = (26.467, 80.354)
        res = self.router.find_route(start, dest)

        self.assertTrue(res.found)
        self.assertGreater(res.total_distance_km, 0.0)
        self.assertTrue(3.0 < res.total_distance_km < 10.0)

    # 12. Travel time is positive
    def test_12_travel_time_is_positive(self):
        start = (26.449, 80.331)
        dest = (26.467, 80.354)
        res = self.router.find_route(start, dest)

        self.assertTrue(res.found)
        self.assertGreater(res.estimated_travel_time_s, 0.0)

    # 13. No route returns a clear controlled result/error
    def test_13_no_route_controlled_result(self):
        dead_ends = [n for n in self.router.nodes if n not in self.router.adjacency or len(self.router.adjacency[n]) == 0]
        self.assertGreater(len(dead_ends), 0)
        dead_end = dead_ends[0]

        target = (26.449, 80.331)
        res = self.router.find_route(dead_end, target)

        self.assertFalse(res.found)
        self.assertEqual(res.status, "NO_PATH_FOUND")
        self.assertIsNotNone(res.error)
        self.assertIn("No traversable route found", res.error)

    # 14. Real Central Kanpur route query
    def test_14_real_central_kanpur_route(self):
        res = self.router.find_route((26.449, 80.331), (26.467, 80.354))
        self.assertTrue(res.found)
        self.assertEqual(res.status, "SUCCESS")
        self.assertIn("Grand Trunk Road", res.road_names)
        self.assertGreater(len(res.segment_ids), 5)

        d = res.to_dict()
        self.assertTrue(d["found"])
        self.assertIn("coordinates", d)
        self.assertIn("total_distance_km", d)
        self.assertIn("estimated_travel_time_s", d)

    # 15. Dynamic congestion rerouting via traffic multipliers
    def test_15_congestion_rerouting(self):
        u = (26.475488, 80.326401)
        v = (26.452836, 80.350253)

        r1 = self.router.find_route(u, v)
        self.assertTrue(r1.found)
        mid_seg = r1.segment_ids[1]

        r2 = self.router.find_route(u, v, traffic_multipliers={mid_seg: 100.0})
        self.assertTrue(r2.found)
        self.assertNotIn(mid_seg, r2.segment_ids)


if __name__ == "__main__":
    unittest.main()

