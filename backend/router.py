"""
NEXUS - Standalone Router Engine (Step 25.1)

Zero-external-API routing engine built on local OpenStreetMap GeoJSON road network data.
Provides graph construction, node snapping, and shortest/fastest path pathfinding
using Dijkstra's algorithm.

Key Features & Architectural Invariants:
1. Pure Python standard library (heapq, math, json, dataclasses, typing).
   Zero third-party graph or routing dependencies (no networkx, osrm, etc.).
2. Normalizes all coordinate nodes to 6 decimal places (approx. 0.11m precision).
3. Preserves exact segment identifiers: 'osm:way:<osm_id>'.
4. Calculates edge lengths using the Haversine formula (km) and base travel times (seconds).
5. Respects OSM 'oneway' properties:
   - 'yes'  -> forward traversal only (geometry order)
   - '-1'   -> reverse traversal only (geometry reverse order)
   - 'no'   -> bidirectional traversal
   - missing/other -> safe default bidirectional traversal (documented in code)
6. Supports dynamic traffic multipliers via edge_cost_func / traffic_multipliers mapping
   without coupling directly to Flask or global traffic state.
7. Origin/Destination nearest-node geographic snapping with distance reporting.
8. Controlled RouteResult dataclass output containing ordered coordinates, segment IDs,
   total distance (km), estimated travel time (s), and verified road names.
"""

import heapq
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# Earth radius in kilometers for Haversine distance calculations
EARTH_RADIUS_KM: float = 6371.0

# Deterministic fallback speeds (km/h) by OSM highway classification
# when explicit 'maxspeed' property is missing or invalid.
DEFAULT_FALLBACK_SPEEDS: Dict[str, float] = {
    "trunk": 60.0,
    "trunk_link": 50.0,
    "primary": 50.0,
    "primary_link": 40.0,
    "secondary": 40.0,
    "secondary_link": 30.0,
    "tertiary": 30.0,
    "tertiary_link": 25.0,
    "residential": 25.0,
    "service": 20.0,
    "unclassified": 25.0,
}

# Default speed when highway classification is completely unlisted
DEFAULT_ROAD_SPEED_KMH: float = 30.0



def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points in kilometers
    using the Haversine formula.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def normalize_coord(lat: float, lon: float) -> Tuple[float, float]:
    """
    Normalize coordinate tuple to 6 decimal places (approx. 0.11m precision),
    ensuring consistent node keys across segments and junctions.
    """
    return (round(float(lat), 6), round(float(lon), 6))


@dataclass(frozen=True)
class Edge:
    """
    Directed graph edge representing a segment section between two junction/waypoint nodes.
    """
    target: Tuple[float, float]
    distance_km: float
    base_travel_time_s: float
    speed_kmh: float
    segment_id: str
    name: Optional[str]
    highway: str
    geometry: Tuple[Tuple[float, float], Tuple[float, float]]


@dataclass
class SnappedNode:
    """
    Result of snapping a query coordinate to the nearest graph node.
    """
    node: Tuple[float, float]
    snap_distance_km: float
    original_coord: Tuple[float, float]


@dataclass
class RouteResult:
    """
    Structured outcome of a pathfinding query.
    """
    found: bool
    status: str
    coordinates: List[Tuple[float, float]] = field(default_factory=list)
    segment_ids: List[str] = field(default_factory=list)
    road_names: List[str] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_travel_time_s: float = 0.0
    snapped_start: Optional[SnappedNode] = None
    snapped_destination: Optional[SnappedNode] = None
    node_count: int = 0
    edge_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert route result into a JSON-serializable dictionary."""
        return {
            "found": self.found,
            "status": self.status,
            "coordinates": [[lat, lon] for lat, lon in self.coordinates],
            "segment_ids": self.segment_ids,
            "road_names": self.road_names,
            "total_distance_km": round(self.total_distance_km, 4),
            "estimated_travel_time_s": round(self.estimated_travel_time_s, 2),
            "snapped_start": {
                "node": list(self.snapped_start.node),
                "distance_km": round(self.snapped_start.snap_distance_km, 4),
            } if self.snapped_start else None,
            "snapped_destination": {
                "node": list(self.snapped_destination.node),
                "distance_km": round(self.snapped_destination.snap_distance_km, 4),
            } if self.snapped_destination else None,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "error": self.error,
        }



class Router:
    """
    Standalone graph-based routing engine for local road networks.
    """

    def __init__(
        self,
        geojson_path: Optional[str] = None,
        fallback_speeds: Optional[Dict[str, float]] = None,
        default_speed_kmh: float = DEFAULT_ROAD_SPEED_KMH,
    ):
        self.geojson_path = geojson_path
        self.fallback_speeds = fallback_speeds or DEFAULT_FALLBACK_SPEEDS
        self.default_speed_kmh = default_speed_kmh

        # Adjacency list: node -> List[Edge]
        self.adjacency: Dict[Tuple[float, float], List[Edge]] = {}
        # Undirected adjacency for connectivity inspection: node -> Set[node]
        self._undirected_adj: Dict[Tuple[float, float], Set[Tuple[float, float]]] = {}
        # All unique normalized nodes
        self.nodes: Set[Tuple[float, float]] = set()
        # All segment IDs registered in the graph
        self.segment_ids: Set[str] = set()
        # Total directed edge count
        self.edge_count: int = 0
        # Feature count loaded
        self.feature_count: int = 0

        if geojson_path:
            self.load_geojson(geojson_path)

    def load_geojson(self, filepath: str) -> None:
        """
        Load GeoJSON file and construct the routing graph.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Road network GeoJSON file not found at: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.build_graph(data)
    def build_graph(self, geojson_data: Dict[str, Any]) -> None:
        """
        Parse GeoJSON FeatureCollection and populate the adjacency graph.
        """
        if not isinstance(geojson_data, dict) or geojson_data.get("type") != "FeatureCollection":
            raise ValueError("Invalid GeoJSON data: expected a FeatureCollection root object.")

        features = geojson_data.get("features", [])
        if not isinstance(features, list):
            raise ValueError("Invalid GeoJSON: 'features' must be a list.")

        self.adjacency.clear()
        self._undirected_adj.clear()
        self.nodes.clear()
        self.segment_ids.clear()
        self.edge_count = 0
        self.feature_count = 0

        for feature in features:
            if not isinstance(feature, dict):
                continue

            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            geom_type = geometry.get("type")
            coords_raw = geometry.get("coordinates")

            if geom_type != "LineString" or not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue

            osm_id = properties.get("osm_id") or feature.get("id") or properties.get("id")
            if not osm_id:
                continue
            segment_id = str(osm_id)
            if not segment_id.startswith("osm:"):
                segment_id = f"osm:way:{segment_id}" if "way" not in segment_id else f"osm:{segment_id}"

            self.segment_ids.add(segment_id)

            road_name = properties.get("name")
            if road_name is not None:
                road_name = str(road_name).strip() or None

            highway = str(properties.get("highway", "residential")).lower()

            maxspeed_prop = properties.get("maxspeed")
            speed_kmh = None
            if maxspeed_prop is not None:
                try:
                    speed_kmh = float(maxspeed_prop)
                except (ValueError, TypeError):
                    speed_kmh = None

            if speed_kmh is None or speed_kmh <= 0.0:
                speed_kmh = self.fallback_speeds.get(highway, self.default_speed_kmh)

            oneway_raw = str(properties.get("oneway", "no")).strip().lower()
            if oneway_raw in ("yes", "1", "true"):
                allow_forward = True
                allow_backward = False
            elif oneway_raw in ("-1", "reverse"):
                allow_forward = False
                allow_backward = True
            else:
                allow_forward = True
                allow_backward = True

            normalized_points: List[Tuple[float, float]] = []
            for pt in coords_raw:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    normalized_points.append(normalize_coord(pt[1], pt[0]))

            if len(normalized_points) < 2:
                continue

            self.feature_count += 1

            for i in range(len(normalized_points) - 1):
                u = normalized_points[i]
                v = normalized_points[i + 1]

                if u == v:
                    continue

                self.nodes.add(u)
                self.nodes.add(v)

                self._undirected_adj.setdefault(u, set()).add(v)
                self._undirected_adj.setdefault(v, set()).add(u)

                dist_km = haversine_distance(u[0], u[1], v[0], v[1])
                base_time_s = (dist_km / speed_kmh) * 3600.0 if speed_kmh > 0 else 0.0

                if allow_forward:
                    edge_fwd = Edge(
                        target=v,
                        distance_km=dist_km,
                        base_travel_time_s=base_time_s,
                        speed_kmh=speed_kmh,
                        segment_id=segment_id,
                        name=road_name,
                        highway=highway,
                        geometry=(u, v),
                    )
                    self.adjacency.setdefault(u, []).append(edge_fwd)
                    self.edge_count += 1

                if allow_backward:
                    edge_rev = Edge(
                        target=u,
                        distance_km=dist_km,
                        base_travel_time_s=base_time_s,
                        speed_kmh=speed_kmh,
                        segment_id=segment_id,
                        name=road_name,
                        highway=highway,
                        geometry=(v, u),
                    )
                    self.adjacency.setdefault(v, []).append(edge_rev)
                    self.edge_count += 1


    def count_connected_components(self) -> int:
        """
        Count the number of connected components in the undirected representation
        of the road network.
        """
        if not self.nodes:
            return 0

        visited: Set[Tuple[float, float]] = set()
        components = 0

        for node in self.nodes:
            if node not in visited:
                components += 1
                queue = [node]
                visited.add(node)
                while queue:
                    current = queue.pop()
                    for neighbor in self._undirected_adj.get(current, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

        return components

    def snap_to_nearest_node(
        self,
        latitude: float,
        longitude: float,
        max_snap_distance_km: Optional[float] = None,
    ) -> Optional[SnappedNode]:
        """
        Snap any arbitrary GPS coordinate to the nearest normalized graph node
        using geographic Haversine distance.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            max_snap_distance_km: Optional maximum allowable distance threshold in km.

        Returns:
            SnappedNode with nearest node coordinate and snapping distance in km,
            or None if graph is empty or exceeds max threshold.
        """
        if not self.nodes:
            return None

        target = normalize_coord(latitude, longitude)
        if target in self.nodes:
            return SnappedNode(node=target, snap_distance_km=0.0, original_coord=target)

        best_node: Optional[Tuple[float, float]] = None
        min_dist = float("inf")

        for node in self.nodes:
            dist = haversine_distance(latitude, longitude, node[0], node[1])
            if dist < min_dist:
                min_dist = dist
                best_node = node

        if best_node is None:
            return None

        if max_snap_distance_km is not None and min_dist > max_snap_distance_km:
            return None

        return SnappedNode(
            node=best_node,
            snap_distance_km=min_dist,
            original_coord=target,
        )

    def calculate_edge_cost(
        self,
        edge: Edge,
        traffic_multipliers: Optional[Dict[str, float]] = None,
        edge_cost_func: Optional[Callable[[Edge, float], float]] = None,
    ) -> float:
        """
        Isolated traversal cost calculation for a graph edge.

        Allows dynamic traffic multipliers or custom weighting functions without
        tight coupling to external or global traffic state.

        By default this is effective travel time in seconds:
        ``base_travel_time_s * traffic_multiplier``. A supplied callback may
        instead return a generalized routing cost; that cost is used only for
        path selection and is not assumed to be seconds for the reported ETA.
        """
        mult = 1.0
        if traffic_multipliers and edge.segment_id in traffic_multipliers:
            mult = max(1.0, float(traffic_multipliers[edge.segment_id]))

        if edge_cost_func is not None:
            return edge_cost_func(edge, mult)

        return edge.base_travel_time_s * mult

    @staticmethod
    def calculate_edge_travel_time(
        edge: Edge,
        traffic_multipliers: Optional[Dict[str, float]] = None,
    ) -> float:
        """Return the modelled edge travel time in seconds, independent of
        any optional generalized path-selection cost.
        """
        mult = 1.0
        if traffic_multipliers and edge.segment_id in traffic_multipliers:
            mult = max(1.0, float(traffic_multipliers[edge.segment_id]))
        return edge.base_travel_time_s * mult

    def find_route(
        self,
        start: Tuple[float, float],
        destination: Tuple[float, float],
        traffic_multipliers: Optional[Dict[str, float]] = None,
        edge_cost_func: Optional[Callable[[Edge, float], float]] = None,
        max_snap_distance_km: Optional[float] = None,
        blocked_segment_ids: Optional[Set[str]] = None,
    ) -> RouteResult:
        """
        Calculate the optimal route between start and destination using Dijkstra's algorithm.

        Args:
            start: (latitude, longitude)
            destination: (latitude, longitude)
            traffic_multipliers: Optional dict mapping segment_id to dynamic congestion multiplier.
            edge_cost_func: Optional custom cost calculation callable.
            max_snap_distance_km: Optional maximum snapping distance threshold.
            blocked_segment_ids: Segment IDs unavailable for this request. The
                shared graph remains unchanged; directed adjacency still
                enforces the source road's one-way rules.

        Returns:
            RouteResult with ordered coordinates, segment IDs, distance, and time.
        """
        if not self.nodes:
            return RouteResult(
                found=False,
                status="NO_GRAPH",
                error="Router graph is empty. Load network data before routing.",
            )

        snapped_start = self.snap_to_nearest_node(start[0], start[1], max_snap_distance_km)
        if not snapped_start:
            nearest_start = self.snap_to_nearest_node(start[0], start[1]) if max_snap_distance_km is not None else None
            error = (
                f"Start is outside the currently mapped road-network coverage. Nearest network node is "
                f"{nearest_start.snap_distance_km:.2f} km away; the route snapping limit is "
                f"{max_snap_distance_km:.2f} km. Select a point near mapped roads or expand the road dataset to cover this area."
                if nearest_start else f"Start coordinate ({start[0]}, {start[1]}) could not be snapped to the road network."
            )
            return RouteResult(found=False, status="START_NOT_FOUND", error=error)

        snapped_dest = self.snap_to_nearest_node(destination[0], destination[1], max_snap_distance_km)
        if not snapped_dest:
            nearest_dest = self.snap_to_nearest_node(destination[0], destination[1]) if max_snap_distance_km is not None else None
            error = (
                f"Destination is outside the currently mapped road-network coverage. Nearest network node is "
                f"{nearest_dest.snap_distance_km:.2f} km away; the route snapping limit is "
                f"{max_snap_distance_km:.2f} km. Select a point near mapped roads or expand the road dataset to cover this area."
                if nearest_dest else f"Destination coordinate ({destination[0]}, {destination[1]}) could not be snapped to the road network."
            )
            return RouteResult(found=False, status="DESTINATION_NOT_FOUND", error=error)
        start_node = snapped_start.node
        dest_node = snapped_dest.node

        # Degenerate case: start and destination snap to the identical graph node
        if start_node == dest_node:
            # A zero-length SUCCESS is only truthful when the caller asked for
            # the same place twice. Two DIFFERENT requested coordinates that
            # collapse onto one node (common for points outside the mapped
            # graph, which has no snapping distance cap) must never be
            # reported as a successful 0.00 km route — that is the
            # "Distance: 0.00 km / Segments: 0 / SUCCESS" bug.
            if normalize_coord(start[0], start[1]) == normalize_coord(destination[0], destination[1]):
                return RouteResult(
                    found=True,
                    status="SUCCESS",
                    coordinates=[start_node],
                    segment_ids=[],
                    road_names=[],
                    total_distance_km=0.0,
                    estimated_travel_time_s=0.0,
                    snapped_start=snapped_start,
                    snapped_destination=snapped_dest,
                    node_count=1,
                    edge_count=0,
                )

            return RouteResult(
                found=False,
                status="SAME_SNAPPED_NODE",
                snapped_start=snapped_start,
                snapped_destination=snapped_dest,
                error=(
                    "Start and destination both resolve to the same road-network "
                    "location. Please select points farther apart and closer to "
                    "mapped roads."
                ),
            )

        # Dijkstra priority queue: (cumulative_cost, insertion_counter, current_node)
        distances: Dict[Tuple[float, float], float] = {start_node: 0.0}
        parent: Dict[Tuple[float, float], Tuple[Tuple[float, float], Edge]] = {}
        pq: List[Tuple[float, int, Tuple[float, float]]] = [(0.0, 0, start_node)]
        entry_counter = 0

        while pq:
            current_cost, _, current_node = heapq.heappop(pq)

            if current_cost > distances[current_node]:
                continue

            if current_node == dest_node:
                break

            for edge in self.adjacency.get(current_node, []):
                if blocked_segment_ids and edge.segment_id in blocked_segment_ids:
                    continue
                next_node = edge.target
                edge_cost = self.calculate_edge_cost(edge, traffic_multipliers, edge_cost_func)
                new_cost = current_cost + edge_cost

                if next_node not in distances or new_cost < distances[next_node]:
                    distances[next_node] = new_cost
                    parent[next_node] = (current_node, edge)
                    entry_counter += 1
                    heapq.heappush(pq, (new_cost, entry_counter, next_node))

        if dest_node not in distances:
            return RouteResult(
                found=False,
                status="NO_PATH_FOUND",
                snapped_start=snapped_start,
                snapped_destination=snapped_dest,
                error="No traversable route found between the specified locations under current direction constraints.",
            )

        # Reconstruct path backwards from destination to start
        path_nodes: List[Tuple[float, float]] = [dest_node]
        path_edges: List[Edge] = []
        curr = dest_node

        while curr != start_node:
            prev_node, edge = parent[curr]
            path_edges.append(edge)
            curr = prev_node
            path_nodes.append(curr)

        path_nodes.reverse()
        path_edges.reverse()

        total_distance = sum(e.distance_km for e in path_edges)
        # ETA always uses the traffic-adjusted travel-time model, even when a
        # custom generalized cost function was used to select the path.
        total_time = sum(
            self.calculate_edge_travel_time(edge, traffic_multipliers)
            for edge in path_edges
        )

        # Ordered segment IDs traversed (preserving chronological order of distinct segments)
        ordered_segment_ids: List[str] = []
        for e in path_edges:
            if not ordered_segment_ids or ordered_segment_ids[-1] != e.segment_id:
                ordered_segment_ids.append(e.segment_id)

        # Ordered verified road names (excluding None/empty and consecutive duplicates)
        ordered_road_names: List[str] = []
        for e in path_edges:
            if e.name and (not ordered_road_names or ordered_road_names[-1] != e.name):
                ordered_road_names.append(e.name)

        return RouteResult(
            found=True,
            status="SUCCESS",
            coordinates=path_nodes,
            segment_ids=ordered_segment_ids,
            road_names=ordered_road_names,
            total_distance_km=total_distance,
            estimated_travel_time_s=total_time,
            snapped_start=snapped_start,
            snapped_destination=snapped_dest,
            node_count=len(path_nodes),
            edge_count=len(path_edges),
        )


def build_graph(geojson_data: Dict[str, Any]) -> Router:
    """
    Convenience factory to build a Router instance directly from a GeoJSON dictionary.
    """
    router = Router()
    router.build_graph(geojson_data)
    return router

