"""
Road Network Loader for NEXUS (Step 19)

Reads local OpenStreetMap road network data (GeoJSON / OSM JSON),
extracts usable road segments, normalizes coordinates and geometries,
and registers them into the RoadMatcher.

Safety and Robustness:
- Fails safely if the file is missing or invalid JSON.
- Never halts server startup if dataset is unavailable.
- Extracts genuine road names from properties/tags; never invents names.
"""

import json
import os
from typing import Optional, List, Dict, Any, Tuple
try:
    from .road_segment import RoadMatcher
except ImportError:
    from road_segment import RoadMatcher


def load_road_network(filepath: str, matcher: RoadMatcher, default_tolerance_km: float = 0.08) -> int:
    """
    Load local OSM road network data from filepath into matcher.

    Args:
        filepath: Path to the GeoJSON or OSM JSON file.
        matcher: RoadMatcher instance to register segments into.
        default_tolerance_km: Maximum distance in km to match reports to segment (default ~80m).

    Returns:
        int: Number of road segments successfully loaded and registered.
    """
    if not filepath or not os.path.exists(filepath):
        print(f"[NEXUS] Notice: Local OSM road dataset not found at '{filepath}'. Running in unmapped mode.")
        return 0

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[NEXUS] Warning: Failed to parse local OSM dataset at '{filepath}': {e}. Running in unmapped mode.")
        return 0

    if not isinstance(data, dict):
        print(f"[NEXUS] Warning: Local OSM dataset at '{filepath}' must be a JSON object.")
        return 0

    registered_count = 0

    # Format 1: GeoJSON FeatureCollection
    if data.get("type") == "FeatureCollection" and "features" in data:
        for feature in data.get("features", []):
            if not isinstance(feature, dict):
                continue

            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            geom_type = geometry.get("type")
            coords_raw = geometry.get("coordinates")

            # Extract stable segment_id
            osm_id = properties.get("osm_id") or feature.get("id") or properties.get("id")
            if not osm_id:
                continue

            segment_id = str(osm_id)
            if not segment_id.startswith("osm:"):
                segment_id = f"osm:way:{segment_id}" if "way" not in segment_id else f"osm:{segment_id}"

            # Extract verified road name (None if absent, never invented)
            road_name = properties.get("name")
            if road_name is not None:
                road_name = str(road_name).strip() or None

            # Tolerance from properties or default
            tolerance_km = float(properties.get("tolerance_km", default_tolerance_km))

            # Normalize coordinates to list of (lat, lon) tuples
            # Note: GeoJSON stores [longitude, latitude]
            norm_coords: List[Tuple[float, float]] = []
            if geom_type == "LineString" and isinstance(coords_raw, list):
                for pt in coords_raw:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        norm_coords.append((float(pt[1]), float(pt[0])))
            elif geom_type == "Point" and isinstance(coords_raw, (list, tuple)) and len(coords_raw) >= 2:
                norm_coords.append((float(coords_raw[1]), float(coords_raw[0])))

            if not norm_coords:
                continue

            rep_lat = sum(c[0] for c in norm_coords) / len(norm_coords)
            rep_lon = sum(c[1] for c in norm_coords) / len(norm_coords)

            matcher.register_segment(
                segment_id=segment_id,
                latitude=rep_lat,
                longitude=rep_lon,
                name=road_name,
                tolerance_km=tolerance_km,
                geometry=norm_coords,
            )
            registered_count += 1

    # Format 2: OpenStreetMap JSON elements export
    elif "elements" in data and isinstance(data["elements"], list):
        for element in data["elements"]:
            if not isinstance(element, dict) or element.get("type") != "way":
                continue

            osm_id = element.get("id")
            if not osm_id:
                continue

            segment_id = f"osm:way:{osm_id}"
            tags = element.get("tags") or {}
            road_name = tags.get("name")
            if road_name is not None:
                road_name = str(road_name).strip() or None

            geom = element.get("geometry") or []
            norm_coords = []
            for pt in geom:
                if isinstance(pt, dict) and "lat" in pt and "lon" in pt:
                    norm_coords.append((float(pt["lat"]), float(pt["lon"])))

            if not norm_coords:
                continue

            rep_lat = sum(c[0] for c in norm_coords) / len(norm_coords)
            rep_lon = sum(c[1] for c in norm_coords) / len(norm_coords)

            matcher.register_segment(
                segment_id=segment_id,
                latitude=rep_lat,
                longitude=rep_lon,
                name=road_name,
                tolerance_km=default_tolerance_km,
                geometry=norm_coords,
            )
            registered_count += 1

    print(f"[NEXUS] Successfully loaded {registered_count} road segments from '{filepath}'.")
    return registered_count
