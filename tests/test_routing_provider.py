"""
Tests for NEXUS Routing Provider Chain (Step 25.4)

Verifies:
- LocalRouterAdapter wraps Router correctly
- OSRMExternalProvider handles HTTP/timeouts/malformed responses
- RoutingProviderChain falls back only for START_NOT_FOUND / DESTINATION_NOT_FOUND
- RoutingProviderChain does NOT fall back for NO_PATH_FOUND / SAME_SNAPPED_NODE / internal errors
- create_default_chain builds the expected provider chain
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from routing_provider import (
    LocalRouterAdapter,
    OSRMExternalProvider,
    RoutingProviderChain,
    ProviderRouteResult,
    RoutingError,
    create_default_chain,
)
from backend.router import Router, build_graph


class TestProviderRouteResult(unittest.TestCase):
    def test_01_to_dict_contains_expected_fields(self):
        result = ProviderRouteResult(
            found=True,
            status="SUCCESS",
            provider="local",
            traffic_aware=True,
            coordinates=[(26.45, 80.33), (26.46, 80.34)],
            segment_ids=["osm:way:1"],
            road_names=["Test Rd"],
            total_distance_km=1.5,
            estimated_travel_time_s=90.0,
            error=None,
            raw=None,
        )
        d = result.to_dict()
        self.assertTrue(d["found"])
        self.assertEqual(d["status"], "SUCCESS")
        self.assertEqual(d["provider"], "local")
        self.assertTrue(d["traffic_aware"])
        self.assertEqual(d["coordinates"], [[26.45, 80.33], [26.46, 80.34]])
        self.assertEqual(d["segment_ids"], ["osm:way:1"])
        self.assertEqual(d["road_names"], ["Test Rd"])
        self.assertEqual(d["total_distance_km"], 1.5)
        self.assertEqual(d["estimated_travel_time_s"], 90.0)
        self.assertIsNone(d["error"])
        self.assertIsNone(d["raw"])

    def test_02_defaults(self):
        result = ProviderRouteResult(
            found=False,
            status="NOT_FOUND",
            provider="chain",
        )
        self.assertFalse(result.traffic_aware)
        self.assertEqual(result.coordinates, [])
        self.assertEqual(result.segment_ids, [])
        self.assertEqual(result.road_names, [])
        self.assertEqual(result.total_distance_km, 0.0)
        self.assertEqual(result.estimated_travel_time_s, 0.0)
        self.assertIsNone(result.error)
        self.assertIsNone(result.raw)


class TestLocalRouterAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.geojson_path = os.path.join(base_dir, "data", "osm_roads.geojson")
        cls.router = Router(cls.geojson_path)

    def test_03_provider_name_is_local(self):
        adapter = LocalRouterAdapter(router=self.router)
        self.assertEqual(adapter.PROVIDER_NAME, "local")

    def test_04_successful_route_returns_found_true_traffic_aware(self):
        adapter = LocalRouterAdapter(router=self.router)
        result = adapter.route(
            (26.4499, 80.3319),
            (26.4600, 80.3400),
            traffic_multipliers={"osm:way:1": 1.25},
        )
        self.assertTrue(result.found)
        self.assertEqual(result.provider, "local")
        self.assertTrue(result.traffic_aware)
        self.assertGreater(len(result.coordinates), 1)
        self.assertGreater(result.total_distance_km, 0)

    def test_05_outside_coverage_returns_start_not_found(self):
        adapter = LocalRouterAdapter(router=self.router)
        result = adapter.route((27.50, 81.50), (27.51, 81.50))
        self.assertFalse(result.found)
        self.assertEqual(result.status, "START_NOT_FOUND")
        self.assertEqual(result.provider, "local")

    def test_06_destination_outside_coverage_returns_destination_not_found(self):
        adapter = LocalRouterAdapter(router=self.router)
        result = adapter.route((26.4499, 80.3319), (27.50, 81.50))
        self.assertFalse(result.found)
        self.assertEqual(result.status, "DESTINATION_NOT_FOUND")
        self.assertEqual(result.provider, "local")

    def test_07_no_path_found_no_fallback_signal(self):
        graph = build_graph({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"osm_id": 9001, "maxspeed": 50},
                    "geometry": {"type": "LineString", "coordinates": [[80.0, 26.0], [80.01, 26.0]]},
                }
            ],
        })
        result = graph.find_route((26.0, 80.0), (26.0, 80.01), blocked_segment_ids={"osm:way:9001"})
        self.assertFalse(result.found)
        self.assertEqual(result.status, "NO_PATH_FOUND")


class TestRoutingProviderChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.geojson_path = os.path.join(base_dir, "data", "osm_roads.geojson")
        cls.router = Router(cls.geojson_path)

    def test_12_local_provider_succeeds_no_fallback(self):
        adapter = LocalRouterAdapter(router=self.router)
        chain = RoutingProviderChain(providers=[adapter])
        result = chain.route((26.4499, 80.3319), (26.4600, 80.3400))
        self.assertTrue(result.found)
        self.assertEqual(result.provider, "local")

    def test_13_start_not_found_triggers_external_fallback(self):
        local = LocalRouterAdapter(router=self.router)
        external = MagicMock()
        external.route.return_value = ProviderRouteResult(
            found=True, status="SUCCESS", provider="osrm", traffic_aware=False,
            coordinates=[(27.50, 81.50), (27.51, 81.50)],
        )
        chain = RoutingProviderChain(providers=[local, external])
        result = chain.route((27.50, 81.50), (27.51, 81.50))
        self.assertTrue(result.found)
        self.assertEqual(result.provider, "osrm")
        external.route.assert_called_once()

    def test_14_destination_not_found_triggers_external_fallback(self):
        local = LocalRouterAdapter(router=self.router)
        external = MagicMock()
        external.route.return_value = ProviderRouteResult(
            found=True, status="SUCCESS", provider="osrm", traffic_aware=False,
            coordinates=[(26.45, 80.33), (27.50, 81.50)],
        )
        chain = RoutingProviderChain(providers=[local, external])
        result = chain.route((26.4499, 80.3319), (27.50, 81.50))
        self.assertTrue(result.found)
        self.assertEqual(result.provider, "osrm")
        external.route.assert_called_once()

    def test_15_no_path_found_does_not_trigger_fallback(self):
        local = LocalRouterAdapter(router=self.router)
        external = MagicMock()
        external.route.return_value = ProviderRouteResult(
            found=True, status="SUCCESS", provider="osrm", traffic_aware=False,
        )
        chain = RoutingProviderChain(providers=[local, external])
        # local returns NO_PATH_FOUND, external should NOT be called
        result = chain.route((26.4499, 80.3319), (26.4600, 80.3400), blocked_segment_ids={"osm:way:115798991"})
        self.assertFalse(result.found)
        self.assertEqual(result.status, "NO_PATH_FOUND")
        external.route.assert_not_called()

    def test_16_chain_exhausted_when_all_providers_fail(self):
        local = LocalRouterAdapter(router=self.router)
        external = MagicMock()
        external.route.return_value = ProviderRouteResult(
            found=False, status="OSRM_TIMEOUT", provider="osrm", traffic_aware=False,
        )
        chain = RoutingProviderChain(providers=[local, external])
        result = chain.route((27.50, 81.50), (27.51, 81.50))
        self.assertFalse(result.found)
        self.assertEqual(result.status, "OSRM_TIMEOUT")
        self.assertEqual(result.provider, "osrm")
        external.route.assert_called_once()

    def test_17_no_providers_returns_chain_exhausted(self):
        chain = RoutingProviderChain(providers=[])
        result = chain.route((26.45, 80.33), (26.46, 80.34))
        self.assertFalse(result.found)
        self.assertEqual(result.status, "NO_PROVIDERS")
        self.assertEqual(result.provider, "chain")


class TestCreateDefaultChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.geojson_path = os.path.join(base_dir, "data", "osm_roads.geojson")
        cls.router = Router(cls.geojson_path)

    def test_18_default_chain_has_local_provider(self):
        chain = create_default_chain(router=self.router)
        self.assertEqual(len(chain.providers), 1)
        self.assertIsInstance(chain.providers[0], LocalRouterAdapter)

    def test_19_default_chain_without_osrm_url_has_one_provider(self):
        chain = create_default_chain(router=self.router, osrm_base_url=None)
        self.assertEqual(len(chain.providers), 1)

    def test_20_default_chain_with_osrm_url_has_two_providers(self):
        chain = create_default_chain(
            router=self.router,
            osrm_base_url="https://router.project-osrm.org/route/v1/driving",
        )
        self.assertEqual(len(chain.providers), 2)
        self.assertIsInstance(chain.providers[0], LocalRouterAdapter)
        self.assertIsInstance(chain.providers[1], OSRMExternalProvider)


class TestOSRMExternalProvider(unittest.TestCase):
    def test_08_provider_name_is_osrm(self):
        provider = OSRMExternalProvider(base_url="https://example.com/osrm")
        self.assertEqual(provider.PROVIDER_NAME, "osrm")

    def test_09_traffic_aware_always_false(self):
        provider = OSRMExternalProvider(base_url="https://example.com/osrm")
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": "Ok", "routes": [{"geometry": {"coordinates": [[80.33, 26.45], [80.34, 26.46]]}, "distance": 1500, "duration": 90}]}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = provider.route((26.45, 80.33), (26.46, 80.34))
            self.assertFalse(result.traffic_aware)
            self.assertEqual(result.provider, "osrm")

    def test_10_timeout_returns_osrm_timeout(self):
        import socket
        provider = OSRMExternalProvider(base_url="https://example.com/osrm", timeout_seconds=1.0)
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            result = provider.route((26.45, 80.33), (26.46, 80.34))
            self.assertFalse(result.found)
            self.assertEqual(result.status, "OSRM_TIMEOUT")
            self.assertEqual(result.provider, "osrm")

    def test_11_malformed_json_returns_osrm_malformed_json(self):
        provider = OSRMExternalProvider(base_url="https://example.com/osrm")
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = provider.route((26.45, 80.33), (26.46, 80.34))
            self.assertFalse(result.found)
            self.assertEqual(result.status, "OSRM_MALFORMED_JSON")
            self.assertEqual(result.provider, "osrm")