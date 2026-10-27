"""Validate and install a regional OSM road GeoJSON extract without relaxing routing."""
import argparse
import copy
import hashlib
import json
import lzma
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.router import Router

DATASET = ROOT / "data" / "osm_roads.geojson"
SNAP_LIMIT_KM = 0.50
ORIGINAL_PAIR = ((26.449, 80.331), (26.467, 80.354))
EXPANDED_PAIR = ((26.505250, 80.302119), (26.458249, 80.192471))


def _way_id(feature):
    props = feature.get("properties") or {}
    value = props.get("osm_id") or feature.get("id") or props.get("id")
    if value is None:
        return None
    match = re.search(r"(?:way/|way:)?(\d+)$", str(value))
    return match.group(1) if match else None


def _usable_road(feature):
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    return (geometry.get("type") == "LineString" and isinstance(coords, list)
            and len(coords) >= 2 and all(isinstance(p, list) and len(p) >= 2 for p in coords)
            and bool((feature.get("properties") or {}).get("highway")))


def validate_extract(collection):
    """Reject malformed road geometries, missing OSM way IDs, and duplicate IDs."""
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Input must be a GeoJSON FeatureCollection.")
    source_features = collection.get("features")
    if not isinstance(source_features, list) or not source_features:
        raise ValueError("Input FeatureCollection must contain features.")
    seen = set()
    valid_count = 0
    for feature in source_features:
        if not isinstance(feature, dict):
            raise ValueError("FeatureCollection contains a non-object feature.")
        props = feature.get("properties") or {}
        if "highway" not in props:
            continue
        way_id = _way_id(feature)
        if not way_id:
            raise ValueError("A highway feature is missing a stable numeric OSM way ID.")
        if way_id in seen:
            raise ValueError(f"Duplicate OSM way ID {way_id} in extract; refusing ambiguous geometry merge.")
        seen.add(way_id)
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") != "LineString" or not isinstance(coords, list) or len(coords) < 2:
            raise ValueError(f"OSM way {way_id} does not contain a routable LineString.")
        distinct = set()
        for point in coords:
            if not isinstance(point, list) or len(point) < 2:
                raise ValueError(f"OSM way {way_id} contains a malformed coordinate.")
            try:
                lon, lat = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                raise ValueError(f"OSM way {way_id} contains a non-numeric coordinate.")
            if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError(f"OSM way {way_id} contains an out-of-range coordinate.")
            distinct.add((lon, lat))
        if len(distinct) < 2:
            raise ValueError(f"OSM way {way_id} does not contain two distinct road nodes.")
        if not isinstance(props.get("highway"), str) or not props["highway"].strip():
            raise ValueError(f"OSM way {way_id} has an invalid highway classification.")
        valid_count += 1
    if not valid_count:
        raise ValueError("Input contains no valid OSM highway LineStrings.")
    return valid_count


def read_extract(path):
    """Read regular GeoJSON or BBBike's .geojson.xz download using stdlib xz support."""
    payload = Path(path).read_bytes()
    if payload.startswith(b"\xfd7zXZ\x00"):
        payload = lzma.decompress(payload)
    collection = json.loads(payload.decode("utf-8"))
    validate_extract(collection)
    return collection


def merge_road_extracts(existing, incoming, metadata):
    """Merge by OSM way ID. The newer regional extract takes precedence for matching ways."""
    validate_extract(incoming)
    if existing.get("type") != "FeatureCollection" or not isinstance(existing.get("features"), list):
        raise ValueError("Current dataset must be a GeoJSON FeatureCollection.")
    features = {}
    for feature in existing.get("features", []):
        way_id = _way_id(feature)
        if way_id and _usable_road(feature):
            features[way_id] = copy.deepcopy(feature)
    old_count = len(features)
    replaced = 0
    for feature in incoming.get("features", []):
        way_id = _way_id(feature)
        if not way_id or not _usable_road(feature):
            continue
        if way_id in features:
            replaced += 1
        normalized = copy.deepcopy(feature)
        normalized["id"] = f"way/{way_id}"
        normalized.setdefault("properties", {})["osm_id"] = int(way_id)
        # Retain OSM attributes as supplied, including name, highway, oneway,
        # junction, surface, lanes, maxspeed, access, and relation-independent tags.
        features[way_id] = normalized
    result = {"type": "FeatureCollection", "features": [features[k] for k in sorted(features, key=int)]}
    result["nexus_metadata"] = {
        "source": metadata["source"], "source_url": metadata["source_url"],
        "download_date": metadata["download_date"], "license": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors",
        "coverage_bbox_wgs84": metadata.get("coverage_bbox_wgs84"),
        "merged_by_osm_way_id": True, "previous_feature_count": old_count,
        "replacement_way_count": replaced,
    }
    return result


def _bounds(collection):
    xs, ys = [], []
    for feature in collection.get("features", []):
        for lon, lat, *_ in (feature.get("geometry") or {}).get("coordinates", []):
            xs.append(float(lon)); ys.append(float(lat))
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def inspect_network(path):
    router = Router(str(path))
    bounds = _bounds(json.loads(Path(path).read_text(encoding="utf-8")))
    report = {
        "file": str(path), "feature_count": router.feature_count, "node_count": len(router.nodes),
        "directed_edge_count": router.edge_count, "connected_components": router.count_connected_components(),
        "bounds_wgs84_lon_lat": bounds, "snap_limit_km": SNAP_LIMIT_KM,
    }
    for label, pair in (("original_pair", ORIGINAL_PAIR), ("requested_pair", EXPANDED_PAIR)):
        endpoints = []
        for point in pair:
            snapped = router.snap_to_nearest_node(*point)
            endpoints.append({"coordinate": list(point), "nearest_node": list(snapped.node) if snapped else None,
                              "distance_km": snapped.snap_distance_km if snapped else None,
                              "within_snap_limit": bool(snapped and snapped.snap_distance_km <= SNAP_LIMIT_KM)})
        route = router.find_route(pair[0], pair[1], max_snap_distance_km=SNAP_LIMIT_KM)
        report[label] = {"endpoints": endpoints, "route_found": route.found, "route_status": route.status,
                         "route_distance_km": route.total_distance_km if route.found else None,
                         "estimated_travel_time_s": route.estimated_travel_time_s if route.found else None,
                         "segment_count": len(route.segment_ids) if route.found else 0,
                         "error": route.error}
    return report


def install_extract(extract_path, dataset_path, metadata):
    """Validate merged candidate, back up current bytes, then atomically install."""
    extract = read_extract(extract_path)
    existing = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    metadata = dict(metadata)
    parsed_url = urlparse(metadata.get("source_url", ""))
    if parsed_url.scheme != "https" or parsed_url.hostname not in {"extract.bbbike.org", "download.bbbike.org"}:
        raise ValueError("Source URL must identify the HTTPS BBBike extract or download service.")
    try:
        datetime.strptime(metadata["download_date"], "%Y-%m-%d")
    except (KeyError, ValueError):
        raise ValueError("download_date must be the actual retrieval date in YYYY-MM-DD format.")
    metadata.setdefault("coverage_bbox_wgs84", _bounds(extract))
    candidate = merge_road_extracts(existing, extract, metadata)
    dataset_path = Path(dataset_path)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dataset_path.parent, suffix=".geojson.tmp", delete=False) as temp:
            json.dump(candidate, temp, ensure_ascii=False, separators=(",", ":")); temp.write("\n")
            temp_path = Path(temp.name)
        report = inspect_network(temp_path)
        for key in ("original_pair", "requested_pair"):
            item = report[key]
            if not all(endpoint["within_snap_limit"] for endpoint in item["endpoints"]):
                raise RuntimeError(f"Refusing installation: {key} has an endpoint outside the {SNAP_LIMIT_KM:.2f} km snap limit.")
            if not item["route_found"]:
                raise RuntimeError(f"Refusing installation: {key} has no valid connected route: {item['error']}")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = dataset_path.with_name(f"{dataset_path.name}.bak.{timestamp}")
        shutil.copy2(dataset_path, backup_path)
        original_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        backup_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        if backup_hash != original_hash:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("Backup verification failed; refusing dataset installation.")
        os.replace(temp_path, dataset_path)
        temp_path = None
        report["backup"] = str(backup_path)
        report["backup_sha256_verified"] = backup_hash
        report["installed"] = str(dataset_path)
        return report
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Report graph coverage and route checks for the current dataset")
    validate.add_argument("--dataset", type=Path, default=DATASET)
    install = sub.add_parser("install", help="Merge and safely install a downloaded regional OSM GeoJSON extract")
    install.add_argument("extract", type=Path)
    install.add_argument("--dataset", type=Path, default=DATASET)
    install.add_argument("--source", default="BBBike custom regional extract")
    install.add_argument("--source-url", default="https://extract.bbbike.org/")
    install.add_argument("--download-date", required=True, help="Extract's actual retrieval date (YYYY-MM-DD)")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            report = inspect_network(args.dataset)
        else:
            datetime.strptime(args.download_date, "%Y-%m-%d")
            report = install_extract(args.extract, args.dataset, vars(args))
        print(json.dumps(report, indent=2))
        if args.command == "validate" and not all(report[k]["route_found"] for k in ("original_pair", "requested_pair")):
            return 2
        return 0
    except Exception as error:
        print(f"road network operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
