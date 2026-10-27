"""
NEXUS - Routing Provider Chain

Provides a modular routing provider architecture with:
- LocalRouterAdapter: wraps the existing local Router engine
- OSRMExternalProvider: external OSRM HTTP-based routing
- RoutingProviderChain: chains providers with fallback logic
- ProviderRouteResult: normalized provider result
- RoutingError: custom exception class

Key design decisions:
- Local router is the preferred provider (only source for NEXUS traffic intelligence)
- OSRM is only used as a fallback for out-of-coverage routes
- Configurable HTTPS endpoint and bounded timeout
- Fallback triggers only when local router reports outside regional coverage
- Clear handling of HTTP errors, rate limits, malformed JSON, and timeouts
"""

import json
import socket
import urllib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

try:
    from .router import Router, RouteResult as LocalRouteResult
except ImportError:
    from router import Router, RouteResult as LocalRouteResult


class RoutingError(Exception):
    """Base exception for routing provider errors."""
    pass


class RoutingTimeoutError(RoutingError):
    """Raised when a routing request times out."""
    pass


class RoutingRateLimitError(RoutingError):
    """Raised when the external provider rate-limits the request."""
    pass


@dataclass(frozen=True)
class ProviderRouteResult:
    """
    Normalized result from any routing provider.

    Attributes:
        found: Whether a route was found.
        status: Provider-specific status string.
        provider: Name of the provider that produced this result.
        traffic_aware: Whether NEXUS traffic intelligence was applied.
        coordinates: Ordered list of (lat, lon) tuples.
        segment_ids: Ordered list of segment IDs.
        road_names: Ordered list of road names.
        total_distance_km: Total route distance in kilometers.
        estimated_travel_time_s: Estimated travel time in seconds.
        error: Error message if the route was not found.
        raw: Raw provider-specific response data.
    """
    found: bool
    status: str
    provider: str
    traffic_aware: bool = False
    coordinates: List[Tuple[float, float]] = field(default_factory=list)
    segment_ids: List[str] = field(default_factory=list)
    road_names: List[str] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_travel_time_s: float = 0.0
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "status": self.status,
            "provider": self.provider,
            "traffic_aware": self.traffic_aware,
            "coordinates": [[lat, lon] for lat, lon in self.coordinates],
            "segment_ids": self.segment_ids,
            "road_names": self.road_names,
            "total_distance_km": round(self.total_distance_km, 4),
            "estimated_travel_time_s": round(self.estimated_travel_time_s, 2),
            "error": self.error,
            "raw": self.raw,
        }


class LocalRouterAdapter:
    """
    Adapter that wraps the existing local Router engine as a routing provider.

    This is the preferred provider. It uses NEXUS traffic intelligence
    (community traffic consensus multipliers and blocked segment handling)
    and respects the 0.5 km local snapping limit.
    """

    PROVIDER_NAME = "local"

    def __init__(self, router: Router, max_snap_distance_km: float = 0.5):
        self.router = router
        self.max_snap_distance_km = max_snap_distance_km

    def route(
        self,
        start: Tuple[float, float],
        destination: Tuple[float, float],
        traffic_multipliers: Optional[Dict[str, float]] = None,
        blocked_segment_ids: Optional[Set[str]] = None,
    ) -> ProviderRouteResult:
        try:
            result = self.router.find_route(
                start,
                destination,
                traffic_multipliers=traffic_multipliers,
                blocked_segment_ids=blocked_segment_ids,
                max_snap_distance_km=self.max_snap_distance_km,
            )

            return ProviderRouteResult(
                found=result.found,
                status=result.status,
                provider=self.PROVIDER_NAME,
                traffic_aware=traffic_multipliers is not None and len(traffic_multipliers) > 0,
                coordinates=[tuple(c) for c in result.coordinates],
                segment_ids=list(result.segment_ids),
                road_names=list(result.road_names),
                total_distance_km=result.total_distance_km,
                estimated_travel_time_s=result.estimated_travel_time_s,
                error=result.error,
                raw=None,
            )
        except Exception as exc:
            return ProviderRouteResult(
                found=False,
                status="LOCAL_ROUTING_ERROR",
                provider=self.PROVIDER_NAME,
                traffic_aware=False,
                error="Local routing error: " + str(exc),
            )


class OSRMExternalProvider:
    """External OSRM HTTP-based routing provider.

    Uses the OSRM HTTP API as a fallback when the local router cannot route
    (e.g., coordinates outside regional coverage).

    Handles:
    - HTTP errors (4xx, 5xx)
    - Timeouts (socket.timeout)
    - Malformed JSON responses
    - Successful route responses
    """

    PROVIDER_NAME = "osrm"

    def __init__(self, base_url: str, timeout_seconds: float = 10.0):
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def route(self, start: Tuple[float, float], destination: Tuple[float, float]) -> ProviderRouteResult:
        lat, lon = start
        dest_lat, dest_lon = destination
        url = f"{self.base_url}/route/v1/driving/{lon},{lat};{dest_lon},{dest_lat}?overview=false"

        try:
            response = urllib.request.urlopen(url, timeout=self.timeout_seconds)
            raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)
        except socket.timeout:
            return ProviderRouteResult(
                found=False,
                status="OSRM_TIMEOUT",
                provider="osrm",
                traffic_aware=False,
                error="OSRM request timed out.",
                raw=None,
            )
        except json.JSONDecodeError:
            return ProviderRouteResult(
                found=False,
                status="OSRM_MALFORMED_JSON",
                provider="osrm",
                traffic_aware=False,
                error="OSRM returned malformed JSON response.",
                raw=None,
            )
        except urllib.error.URLError as e:
            return ProviderRouteResult(
                found=False,
                status="OSRM_ERROR",
                provider="osrm",
                traffic_aware=False,
                error=f"OSRM request failed: {e}",
                raw=None,
            )

        # Extract route from OSRM response
        if data.get("code") != "Ok" or not data.get("routes"):
            return ProviderRouteResult(
                found=False,
                status="OSRM_NO_ROUTE",
                provider="osrm",
                traffic_aware=False,
                error="OSRM could not find a route.",
                raw=data,
            )

        route = data["routes"][0]
        coordinates = [
            (lat, lon) for lat, lon in route["geometry"]["coordinates"]
        ]

        return ProviderRouteResult(
            found=True,
            status="SUCCESS",
            provider="osrm",
            traffic_aware=False,
            coordinates=coordinates,
            segment_ids=[],
            road_names=[],
            total_distance_km=route.get("distance", 0) / 1000.0,
            estimated_travel_time_s=route.get("duration", 0),
            error=None,
            raw=data,
        )
class RoutingProviderChain:
    """
    Chains multiple routing providers with fallback logic.

    The local router is always tried first. OSRM is only used as a fallback
    when the local router cannot route because coordinates are outside
    regional coverage (START_NOT_FOUND or DESTINATION_NOT_FOUND).

    Fallback does NOT trigger for:
    - Malformed requests
    - No path found within the local network (NO_PATH_FOUND)
    - Same snapped node (SAME_SNAPPED_NODE)
    - Internal errors
    """

    def __init__(
        self,
        providers: Optional[List[Any]] = None,
        fallback_statuses: Optional[Set[str]] = None,
    ):
        self.providers = providers or []
        self.fallback_statuses = fallback_statuses or {
            "START_NOT_FOUND",
            "DESTINATION_NOT_FOUND",
        }

    def add_provider(self, provider: Any) -> None:
        self.providers.append(provider)

    def route(
        self,
        start: Tuple[float, float],
        destination: Tuple[float, float],
        traffic_multipliers: Optional[Dict[str, float]] = None,
        blocked_segment_ids: Optional[Set[str]] = None,
    ) -> ProviderRouteResult:
        if not self.providers:
            return ProviderRouteResult(
                found=False,
                status="NO_PROVIDERS",
                provider="chain",
                traffic_aware=False,
                error="No routing providers configured.",
            )

        last_result = None

        for provider in self.providers:
            if isinstance(provider, LocalRouterAdapter):
                result = provider.route(
                    start,
                    destination,
                    traffic_multipliers=traffic_multipliers,
                    blocked_segment_ids=blocked_segment_ids,
                )
            else:
                result = provider.route(start, destination)

            last_result = result

            if result.found:
                return result

            if result.status not in self.fallback_statuses:
                return result

        return last_result or ProviderRouteResult(
            found=False,
            status="CHAIN_EXHAUSTED",
            provider="chain",
            traffic_aware=False,
            error="All routing providers exhausted without finding a route.",
        )


def create_default_chain(
    router: Router,
    max_snap_distance_km: float = 0.5,
    osrm_base_url: Optional[str] = None,
    osrm_timeout_seconds: float = 10.0,
    enable_osrm_fallback: bool = True,
) -> RoutingProviderChain:
    local_adapter = LocalRouterAdapter(
        router=router,
        max_snap_distance_km=max_snap_distance_km,
    )

    chain = RoutingProviderChain()
    chain.add_provider(local_adapter)

    if enable_osrm_fallback and osrm_base_url:
        osrm_provider = OSRMExternalProvider(
            base_url=osrm_base_url,
            timeout_seconds=osrm_timeout_seconds,
        )
        chain.add_provider(osrm_provider)

    return chain


