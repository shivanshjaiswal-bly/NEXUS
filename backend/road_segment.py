"""
NEXUS - Road Segment Intelligence Foundation (Step 18 & 19)

Architectural Notes & Documented Limitations:
--------------------------------------------
1. Local Dataset Matching:
   RoadMatcher associates traffic clusters with verified local OpenStreetMap
   road segments loaded from a local dataset.
2. No External API Per-Report:
   Zero external network calls are made during report ingestion or traffic aggregation.
3. No Fake Road Matching:
   If a cluster does not fall within the tolerance distance of any known segment in the
   loaded local dataset, it safely defaults to `segment_id: None` and `road_name: None`.
4. No Invented Road Names:
   Road names originate strictly from the verified local OSM dataset. If an OSM feature
   lacks a name tag, `road_name` remains None.
"""

from typing import Optional, Dict, Any, List, Callable, Tuple


class RoadSegment:
    """
    Represents a road or network corridor segment with traffic intelligence.

    Attributes:
        segment_id (Optional[str]): Stable identifier for the road segment
            (e.g., OSM way ID like 'osm:way:115798991'), or None if unassigned/unmatched.
        latitude (float): Representative latitude (centroid of traffic reports or road center).
        longitude (float): Representative longitude (centroid of traffic reports or road center).
        status (str): Consensus traffic condition ('Normal', 'Moderate', 'Heavy', 'Blocked').
        incident (str): Consensus incident type ('None', 'Accident', 'Road Work', etc.).
        report_count (int): Number of community reports in this segment cluster.
        confidence (str): Confidence level ('Low', 'Medium', 'High', 'Very High').
        road_name (Optional[str]): Verified road name from OSM network data, or None.
            Never invented or hallucinated.
        geometry (Optional[List[Tuple[float, float]]]): List of (lat, lon) coordinates
            defining the road segment path.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        status: str,
        incident: str,
        report_count: int,
        confidence: str,
        segment_id: Optional[str] = None,
        road_name: Optional[str] = None,
        geometry: Optional[List[Tuple[float, float]]] = None,
    ):
        self.latitude = latitude
        self.longitude = longitude
        self.status = status
        self.incident = incident
        self.report_count = report_count
        self.confidence = confidence
        self.segment_id = segment_id
        self.road_name = road_name
        self.geometry = geometry or []

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the road segment to a backward-compatible dictionary for /api/traffic.
        
        Preserves all existing fields:
        - latitude
        - longitude
        - status
        - incident
        - report_count
        - confidence
        
        Adds:
        - segment_id (Optional[str])
        - road_name (Optional[str], only included when verified)
        - geometry (Optional[List[List[float]]], only included for matched segments with geometry)
          Format: [[lat, lon], ...] — ready for Leaflet polyline rendering.
        """
        data = {
            "segment_id": self.segment_id,
            "status": self.status,
            "incident": self.incident,
            "report_count": self.report_count,
            "confidence": self.confidence,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }
        if self.road_name is not None:
            data["road_name"] = self.road_name
        # Include geometry only when present (matched OSM segment with known shape).
        # Stored as (lat, lon) tuples internally; serialised as [[lat, lon], ...] for Leaflet.
        if self.geometry:
            data["geometry"] = [[pt[0], pt[1]] for pt in self.geometry]
        return data


class RoadMatcher:
    """
    Matches clusters of community GPS reports to known local OSM road segments.
    
    A local road segment registry is populated from a local dataset.
    When a cluster falls within tolerance of a known segment, it is associated
    with that segment. Otherwise, it safely defaults to segment_id=None without
    inventing road data.
    """

    def __init__(self, registered_segments: Optional[Dict[str, Dict[str, Any]]] = None):
        self.registered_segments: Dict[str, Dict[str, Any]] = registered_segments or {}

    @property
    def segments(self) -> List[Dict[str, Any]]:
        """Return all registered segments as a list of dictionaries for testing and inspection."""
        result = []
        for seg_id, seg_data in self.registered_segments.items():
            result.append({
                "segment_id": seg_id,
                "road_name": seg_data.get("name"),
                "latitude": seg_data["latitude"],
                "longitude": seg_data["longitude"],
                "geometry": seg_data.get("geometry", []),
            })
        return result

    def register_segment(
        self,
        segment_id: str,
        latitude_or_name: Any = None,
        longitude_or_center: Any = None,
        name_or_geometry: Optional[Any] = None,
        tolerance_km: float = 0.05,
        geometry: Optional[List[Tuple[float, float]]] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        name: Optional[str] = None,
    ) -> None:
        """
        Register a known road segment from OSM or local network data.
        
        Supports both signatures:
        - Keyword: register_segment(segment_id, latitude=lat, longitude=lon, name=name, geometry=geom)
        - Positional (test): register_segment(segment_id, name, [lat, lon], [[lat, lon], ...])
        """
        # If keyword arguments are used (road_loader)
        if latitude is not None or longitude is not None:
            final_lat = latitude if latitude is not None else float(latitude_or_name)
            final_lon = longitude if longitude is not None else float(longitude_or_center)
            final_name = name if name is not None else name_or_geometry
            final_geom = geometry if geometry else [(final_lat, final_lon)]
        # If positional arguments are used (tests)
        elif isinstance(latitude_or_name, str) and isinstance(longitude_or_center, (list, tuple)):
            # Old test signature: (segment_id, name, [lat, lon], [[lat, lon], ...])
            final_name = latitude_or_name
            center_coords = longitude_or_center
            geom_list = name_or_geometry if name_or_geometry else []
            
            final_lat = float(center_coords[0])
            final_lon = float(center_coords[1])
            final_geom = [(float(pt[0]), float(pt[1])) for pt in geom_list] if geom_list else [(final_lat, final_lon)]
        else:
            # Standard new signature: (segment_id, latitude, longitude, name, tolerance_km, geometry)
            final_lat = float(latitude_or_name) if latitude_or_name is not None else 0.0
            final_lon = float(longitude_or_center) if longitude_or_center is not None else 0.0
            final_name = name_or_geometry
            final_geom = geometry if geometry else [(final_lat, final_lon)]
        
        self.registered_segments[segment_id] = {
            "name": final_name,
            "latitude": final_lat,
            "longitude": final_lon,
            "tolerance_km": tolerance_km,
            "geometry": final_geom,
        }

    def match(
        self,
        group: List[Dict[str, Any]],
        centroid_lat: float,
        centroid_lon: float,
        status: str,
        incident: str,
        report_count: int,
        confidence: str,
        distance_func: Optional[Callable[[float, float, float, float], float]] = None,
    ) -> RoadSegment:
        """
        Attempt to match a traffic group's centroid to a known road segment.
        Calculates distance to representative point and line geometry nodes.
        If no known segment matches within tolerance, returns a RoadSegment with
        segment_id=None and road_name=None, properly documenting the unmatched state.
        """
        matched_id = None
        matched_name = None
        matched_geom = None

        if distance_func and self.registered_segments:
            best_dist = float("inf")
            for seg_id, seg_data in self.registered_segments.items():
                tolerance = seg_data.get("tolerance_km", 0.05)
                nodes = seg_data.get("geometry") or [(seg_data["latitude"], seg_data["longitude"])]

                # Minimum distance to any node of the road segment
                seg_min_dist = min(
                    distance_func(centroid_lat, centroid_lon, pt_lat, pt_lon)
                    for pt_lat, pt_lon in nodes
                )

                if seg_min_dist <= tolerance and seg_min_dist < best_dist:
                    best_dist = seg_min_dist
                    matched_id = seg_id
                    matched_name = seg_data.get("name")
                    matched_geom = seg_data.get("geometry")

        return RoadSegment(
            segment_id=matched_id,
            road_name=matched_name,
            latitude=centroid_lat,
            longitude=centroid_lon,
            status=status,
            incident=incident,
            report_count=report_count,
            confidence=confidence,
            geometry=matched_geom,
        )

    def match_point(
        self,
        lat: float,
        lon: float,
        distance_func: Optional[Callable[[float, float, float, float], float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Match a single (lat, lon) coordinate to the closest registered road segment within tolerance.
        Returns a dictionary with segment information, or None if unmatched.
        """
        if not distance_func or not self.registered_segments:
            return None

        best_dist = float("inf")
        matched = None

        for seg_id, seg_data in self.registered_segments.items():
            tolerance = seg_data.get("tolerance_km", 0.05)
            nodes = seg_data.get("geometry") or [(seg_data["latitude"], seg_data["longitude"])]

            min_dist = min(
                distance_func(lat, lon, pt_lat, pt_lon)
                for pt_lat, pt_lon in nodes
            )

            if min_dist <= tolerance and min_dist < best_dist:
                best_dist = min_dist
                matched = {
                    "segment_id": seg_id,
                    "name": seg_data.get("name"),
                    "latitude": seg_data["latitude"],
                    "longitude": seg_data["longitude"],
                    "geometry": seg_data.get("geometry"),
                }

        return matched
