

import os
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
try:
    from .places import get_engine as get_places_engine, migrate as migrate_places, search as search_places_records, places as places_table, PLACE_CATEGORIES, record_to_json
except ImportError:
    from places import get_engine as get_places_engine, migrate as migrate_places, search as search_places_records, places as places_table, PLACE_CATEGORIES, record_to_json
try:
    from .road_segment import RoadSegment, RoadMatcher
    from .road_loader import load_road_network
    from .router import Router
except ImportError:
    from road_segment import RoadSegment, RoadMatcher
    from road_loader import load_road_network
    from router import Router

try:
    from .routing_provider import (
        RoutingProviderChain,
        create_default_chain,
        ProviderRouteResult,
    )
except ImportError:
    from routing_provider import (
        RoutingProviderChain,
        create_default_chain,
        ProviderRouteResult,
    )

# Project directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
FRONTEND_BUILD_DIR = os.path.join(PROJECT_ROOT, "frontend-vite", "dist")

app = Flask(__name__)
CORS(app)

# Place persistence is separate from the existing in-memory traffic reports.
# SQLite is the safe local default; NEXUS_DATABASE_URL can select PostgreSQL.
places_engine = get_places_engine()
migrate_places(places_engine)

@app.get("/api/places/categories")
def get_place_categories():
    return jsonify({"categories": PLACE_CATEGORIES})

@app.get("/api/places")
def get_places():
    try:
        return jsonify(search_places_records(places_engine, request.args))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

@app.get("/api/places/<string:place_id>")
def get_place(place_id):
    from sqlalchemy import select
    with places_engine.connect() as connection:
        row = connection.execute(select(places_table).where(places_table.c.id == place_id, places_table.c.listing_status == "active")).mappings().first()
    if row is None:
        return jsonify({"error": "Place not found."}), 404
    return jsonify(record_to_json(row))

# Road network matcher instance
road_matcher = RoadMatcher()

# Local OpenStreetMap dataset path (configurable via environment variable)
DEFAULT_OSM_DATA_PATH = os.path.join(PROJECT_ROOT, "data", "osm_roads.geojson")
OSM_DATA_PATH = os.environ.get("NEXUS_OSM_DATA_PATH", DEFAULT_OSM_DATA_PATH)

# Load local OSM road network into matcher (fails safely if missing or invalid)
load_road_network(OSM_DATA_PATH, road_matcher)

# Standalone routing engine instance initialized with local OSM dataset
router = Router()
if os.path.exists(OSM_DATA_PATH):
    try:
        router.load_geojson(OSM_DATA_PATH)
        print(f"[NEXUS] Successfully loaded {router.feature_count} features into Router from '{OSM_DATA_PATH}'.")
    except Exception as e:
        print(f"[NEXUS] Warning: Failed to load road network into Router at '{OSM_DATA_PATH}': {e}. Running in unmapped mode.")
else:
    print(f"[NEXUS] Notice: Local OSM road dataset not found at '{OSM_DATA_PATH}'. Router running in unmapped mode.")

# Routing provider chain: local router preferred, OSRM fallback for out-of-coverage
OSRM_BASE_URL = os.environ.get("NEXUS_OSRM_BASE_URL", None)
OSRM_TIMEOUT_SECONDS = float(os.environ.get("NEXUS_OSRM_TIMEOUT_SECONDS", "10.0"))
routing_chain = create_default_chain(
    router,
    max_snap_distance_km=0.5,
    osrm_base_url=OSRM_BASE_URL,
    osrm_timeout_seconds=OSRM_TIMEOUT_SECONDS,
    enable_osrm_fallback=OSRM_BASE_URL is not None,
)

# ---------------------------------------------------------------------------
# Frontend: Serve NEXUS Web UI (avoids file:// browser restrictions)
# ---------------------------------------------------------------------------
@app.get("/")
def serve_root():
    frontend_dir = FRONTEND_BUILD_DIR if os.path.isfile(os.path.join(FRONTEND_BUILD_DIR, "index.html")) else FRONTEND_DIR
    return send_from_directory(frontend_dir, "index.html")


@app.get("/index.html")
def serve_index_html():
    return serve_root()


@app.get("/assets/<path:filename>")
def serve_frontend_asset(filename):
    if not os.path.isdir(FRONTEND_BUILD_DIR):
        return jsonify({"error": "Built frontend assets are unavailable."}), 404
    return send_from_directory(os.path.join(FRONTEND_BUILD_DIR, "assets"), filename)

# ---------------------------------------------------------------------------
# In-memory store (lost on restart — intentional at this stage)
# ---------------------------------------------------------------------------
reports = []

REPORT_EXPIRY_MINUTES = 30
MAX_ROUTE_SNAP_DISTANCE_KM = 0.5
GEOCODER_URL = os.environ.get("NEXUS_GEOCODER_URL", "https://nominatim.openstreetmap.org/search")
GEOCODER_MIN_INTERVAL_SECONDS = 1.0
GEOCODER_CACHE_MAX_ENTRIES = 256
_geocoder_lock = threading.Lock()
_geocoder_last_request_at = 0.0
_geocoder_cache = {}

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------
VALID_CONDITIONS = {"Normal", "Moderate", "Heavy", "Blocked"}
VALID_INCIDENTS  = {"None", "Accident", "Road Work", "Road Block", "Other"}

# Severity rank used for dominant-condition / dominant-incident logic
CONDITION_SEVERITY = {
    "Normal":   0,
    "Moderate": 1,
    "Heavy":    2,
    "Blocked":  3,
}

INCIDENT_SEVERITY = {
    "None":       0,
    "Other":      1,
    "Road Work":  2,
    "Road Block": 3,
    "Accident":   4,
}

# ---------------------------------------------------------------------------
# Haversine distance (returns kilometres)
# ---------------------------------------------------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km

    lat1, lat2 = radians(lat1), radians(lat2)
    dlat = lat2 - lat1
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c

# ---------------------------------------------------------------------------
# Fallback Grouping: cluster unmatched reports within 100 m of group seed.
# ---------------------------------------------------------------------------
def group_reports_fallback(report_list):
    groups = []

    for report in report_list:
        placed = False

        for group in groups:
            # Use the first report (seed) as the fixed proximity anchor
            seed = group[0]
            dist = calculate_distance(
                report["latitude"],  report["longitude"],
                seed["latitude"],    seed["longitude"],
            )

            if dist <= 0.1:  # 100 metres
                group.append(report)
                placed = True
                break

        if not placed:
            groups.append([report])

    return groups


def group_reports():
    """Backward-compatible wrapper for geographic grouping."""
    return group_reports_fallback(reports)


# ---------------------------------------------------------------------------
# Centroid: geographic centre of all reports in a group
# ---------------------------------------------------------------------------
def compute_centroid(group):
    """Return the average latitude and longitude of the group."""
    if not group:
        return 0.0, 0.0
    avg_lat = sum(r["latitude"]  for r in group) / len(group)
    avg_lon = sum(r["longitude"] for r in group) / len(group)
    return avg_lat, avg_lon

# ---------------------------------------------------------------------------
# Confidence: how many reports back up the group
# ---------------------------------------------------------------------------
def get_confidence(report_count):
    if report_count == 1:
        return "Low"
    if report_count <= 3:
        return "Medium"
    if report_count <= 5:
        return "High"
    return "Very High"

# ---------------------------------------------------------------------------
# Community Consensus: condition and incident consensus with tie-breaking
# ---------------------------------------------------------------------------
def compute_consensus(group):
    """
    Consensus rules:
      - Pick the condition/incident with the highest vote count.
      - Ties are broken by severity (higher severity wins).
    """
    condition_votes = {}
    for r in group:
        c = r["condition"]
        condition_votes[c] = condition_votes.get(c, 0) + 1

    consensus_condition = max(
        condition_votes,
        key=lambda c: (condition_votes[c], CONDITION_SEVERITY[c])
    )

    incident_votes = {}
    for r in group:
        i = r["incident"]
        incident_votes[i] = incident_votes.get(i, 0) + 1

    consensus_incident = max(
        incident_votes,
        key=lambda i: (incident_votes[i], INCIDENT_SEVERITY.get(i, 0))
    )

    return consensus_condition, consensus_incident


def get_group_status(group):
    """Backward-compatible aggregation of a single geographic group."""
    consensus_condition, consensus_incident = compute_consensus(group)
    count = len(group)
    centroid_lat, centroid_lon = compute_centroid(group)

    segment = road_matcher.match(
        group=group,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        status=consensus_condition,
        incident=consensus_incident,
        report_count=count,
        confidence=get_confidence(count),
        distance_func=calculate_distance,
    )

    return segment.to_dict()


# ---------------------------------------------------------------------------
# Road-Segment Traffic Aggregation (Step 21)
# ---------------------------------------------------------------------------
def aggregate_traffic():
    """
    Upgrade traffic aggregation:
    - Reports matched to an OSM road segment aggregate together by segment_id.
    - Unmatched reports fallback to 100-metre geographic proximity grouping.
    - Reports on different segment IDs are never merged.
    """
    matched_by_segment = {}
    segment_meta = {}
    unmatched_reports = []

    for r in reports:
        match = road_matcher.match_point(r["latitude"], r["longitude"], calculate_distance)
        if match:
            seg_id = match["segment_id"]
            if seg_id not in matched_by_segment:
                matched_by_segment[seg_id] = []
                segment_meta[seg_id] = match
            matched_by_segment[seg_id].append(r)
        else:
            unmatched_reports.append(r)

    traffic_results = []

    # 1. Aggregate matched reports sharing the same segment_id
    for seg_id, seg_reports in matched_by_segment.items():
        cond, inc = compute_consensus(seg_reports)
        count = len(seg_reports)
        conf = get_confidence(count)
        lat, lon = compute_centroid(seg_reports)
        meta = segment_meta[seg_id]

        segment = RoadSegment(
            segment_id=seg_id,
            road_name=meta.get("name"),
            latitude=lat,
            longitude=lon,
            status=cond,
            incident=inc,
            report_count=count,
            confidence=conf,
            geometry=meta.get("geometry"),
        )
        traffic_results.append(segment.to_dict())

    # 2. Aggregate unmatched reports using 100-metre fallback grouping
    fallback_groups = group_reports_fallback(unmatched_reports)
    for group in fallback_groups:
        cond, inc = compute_consensus(group)
        count = len(group)
        conf = get_confidence(count)
        lat, lon = compute_centroid(group)

        segment = RoadSegment(
            segment_id=None,
            road_name=None,
            latitude=lat,
            longitude=lon,
            status=cond,
            incident=inc,
            report_count=count,
            confidence=conf,
        )
        traffic_results.append(segment.to_dict())

    return traffic_results

# ---------------------------------------------------------------------------
# Expiry: purge reports older than REPORT_EXPIRY_MINUTES
# ---------------------------------------------------------------------------
def remove_expired_reports():
    current_time = datetime.now(timezone.utc)

    active = [
        r for r in reports
        if (current_time - datetime.fromisoformat(r["time"])).total_seconds() / 60
           < REPORT_EXPIRY_MINUTES
    ]

    reports.clear()
    reports.extend(active)

# ---------------------------------------------------------------------------
# API: individual community reports
# ---------------------------------------------------------------------------
@app.get("/api/reports")
def get_reports():
    remove_expired_reports()
    return jsonify(reports)


@app.post("/api/reports")
def add_report():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    condition = data.get("condition")
    incident  = data.get("incident", "None")
    latitude  = data.get("latitude")
    longitude = data.get("longitude")

    if condition not in VALID_CONDITIONS:
        return jsonify({
            "error": f"Invalid condition. Must be one of: {sorted(VALID_CONDITIONS)}"
        }), 400

    if incident not in VALID_INCIDENTS:
        return jsonify({
            "error": f"Invalid incident. Must be one of: {sorted(VALID_INCIDENTS)}"
        }), 400

    if latitude is None or longitude is None:
        return jsonify({"error": "latitude and longitude are required."}), 400

    try:
        latitude  = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return jsonify({"error": "latitude and longitude must be numbers."}), 400

    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return jsonify({"error": "Coordinates out of valid range."}), 400

    report = {
        "latitude":  latitude,
        "longitude": longitude,
        "condition": condition,
        "incident":  incident,
        "time":      datetime.now(timezone.utc).isoformat(),
    }

    reports.append(report)

    return jsonify({"success": True, "report": report}), 201

# ---------------------------------------------------------------------------
# API: aggregated road-level traffic groups
# ---------------------------------------------------------------------------
@app.get("/api/traffic")
def get_traffic():
    remove_expired_reports()
    traffic = aggregate_traffic()
    return jsonify(traffic)

# ---------------------------------------------------------------------------
# Helpers for Route API coordinate validation
# ---------------------------------------------------------------------------
def _validate_coordinate(coord_obj, field_name):
    """
    Validate that coord_obj is a dict with valid numeric 'lat' and 'lon'
    within geographic bounds: lat in [-90, 90], lon in [-180, 180].
    Returns ((lat, lon), None) on success, or (None, error_message) on failure.
    """
    if not isinstance(coord_obj, dict):
        return None, f"'{field_name}' must be an object with 'lat' and 'lon' fields."

    if "lat" not in coord_obj or "lon" not in coord_obj:
        return None, f"'{field_name}' must contain both 'lat' and 'lon'."

    lat_val = coord_obj.get("lat")
    lon_val = coord_obj.get("lon")

    # Reject booleans (isinstance(True, int) is True in Python) and None
    if isinstance(lat_val, bool) or isinstance(lon_val, bool) or lat_val is None or lon_val is None:
        return None, f"'{field_name}.lat' and '{field_name}.lon' must be valid numeric values."

    try:
        lat = float(lat_val)
        lon = float(lon_val)
    except (TypeError, ValueError):
        return None, f"'{field_name}.lat' and '{field_name}.lon' must be valid numeric values."

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None, f"'{field_name}' coordinates are out of valid geographic range (lat: [-90, 90], lon: [-180, 180])."

    return (lat, lon), None


@app.get("/api/geocode")
def search_places():
    """Search a place only after an explicit user request; cache and throttle provider calls."""
    global _geocoder_last_request_at
    query = (request.args.get("q") or "").strip()
    if len(query) < 2 or len(query) > 200:
        return jsonify({"error": "Enter a place name or address between 2 and 200 characters."}), 400

    cache_key = query.casefold()
    with _geocoder_lock:
        if cache_key in _geocoder_cache:
            return jsonify({"results": _geocoder_cache[cache_key], "cached": True})
        now = time.monotonic()
        if now - _geocoder_last_request_at < GEOCODER_MIN_INTERVAL_SECONDS:
            return jsonify({"error": "Place search is rate limited. Wait a moment and try again."}), 429
        _geocoder_last_request_at = now

    url = f"{GEOCODER_URL}?{urlencode({'q': query, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 5})}"
    provider_request = URLRequest(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NEXUS-Traffic-Intelligence/1.0",
        },
    )
    try:
        with urlopen(provider_request, timeout=6) as response:
            provider_data = json.loads(response.read().decode("utf-8"))
        if not isinstance(provider_data, list):
            raise ValueError("The geocoding provider returned an unexpected response.")
        results = []
        for item in provider_data:
            if not isinstance(item, dict) or not item.get("display_name"):
                continue
            try:
                latitude, longitude = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            results.append({
                "display_name": str(item["display_name"]),
                "lat": latitude,
                "lon": longitude,
            })
        with _geocoder_lock:
            if len(_geocoder_cache) >= GEOCODER_CACHE_MAX_ENTRIES:
                _geocoder_cache.pop(next(iter(_geocoder_cache)))
            _geocoder_cache[cache_key] = results
        return jsonify({"results": results, "cached": False})
    except Exception:
        app.logger.warning("Place search provider request failed", exc_info=app.debug)
        return jsonify({"error": "Place search is temporarily unavailable. Try again or choose the location on the map."}), 502

# ---------------------------------------------------------------------------
# Traffic-Aware Routing (Step 25.3): condition -> travel-time multiplier
# ---------------------------------------------------------------------------
# Deterministic multipliers for traversable traffic conditions. A Blocked
# segment is represented separately and excluded from each route request.
TRAFFIC_CONDITION_MULTIPLIERS = {
    "Normal":   1.0,
    "Moderate": 1.25,
    "Heavy":    1.75,
}


def traffic_condition_to_multiplier(condition):
    """
    Convert an existing aggregated traffic condition into a routing
    travel-time multiplier. Unknown/missing conditions default to 1.0.
    """
    return TRAFFIC_CONDITION_MULTIPLIERS.get(condition, 1.0)


def get_current_traffic_routing_state():
    """
    Build the current {segment_id: multiplier} and blocked segment IDs for
    Router.find_route(). Blocked segments are infeasible; other multipliers
    scale the base travel time in seconds.

    - Purges expired reports first (> REPORT_EXPIRY_MINUTES old) so stale
      reports never influence routing.
    - Reuses the existing aggregate_traffic() consensus pipeline; unmatched
      groups (segment_id None) carry no router key and are skipped.
    - Segments without current reports are absent from the mapping;
      Router.calculate_edge_cost() treats them as multiplier = 1.0.
    """
    remove_expired_reports()
    traffic_segments = aggregate_traffic()

    multipliers = {}
    blocked_segment_ids = set()
    for segment in traffic_segments:
        seg_id = segment.get("segment_id")
        if seg_id:
            condition = segment.get("status")
            if condition == "Blocked":
                blocked_segment_ids.add(seg_id)
            else:
                multipliers[seg_id] = traffic_condition_to_multiplier(condition)

    return multipliers, blocked_segment_ids


def get_current_traffic_multipliers():
    """Compatibility helper returning only traversable segment multipliers."""
    multipliers, _ = get_current_traffic_routing_state()
    return multipliers

# ---------------------------------------------------------------------------
# API: offline graph routing between start and destination
# ---------------------------------------------------------------------------
@app.post("/api/route")
def get_route():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    if "start" not in data:
        return jsonify({"error": "Missing required field: 'start'."}), 400

    if "destination" not in data:
        return jsonify({"error": "Missing required field: 'destination'."}), 400

    start_coord, err = _validate_coordinate(data.get("start"), "start")
    if err:
        return jsonify({"error": err}), 400

    dest_coord, err = _validate_coordinate(data.get("destination"), "destination")
    if err:
        return jsonify({"error": err}), 400

    # Development-only trace to correlate browser-selected points with the
    # coordinates validated and passed to this request's route matcher.
    if app.debug:
        app.logger.debug("POST /api/route received start=%s destination=%s", start_coord, dest_coord)

    try:
        # Step 25.3: automatically weight the route with current community
        # traffic consensus (expired reports purged inside the helper).
        traffic_multipliers, blocked_segment_ids = get_current_traffic_routing_state()
        route_result = router.find_route(
            start_coord,
            dest_coord,
            traffic_multipliers=traffic_multipliers,
            blocked_segment_ids=blocked_segment_ids,
            max_snap_distance_km=MAX_ROUTE_SNAP_DISTANCE_KM,
        )
    except Exception:
        return jsonify({
            "found": False,
            "status": "INTERNAL_ROUTING_ERROR",
            "error": "An unexpected error occurred during route calculation.",
        }), 400

    result_dict = route_result.to_dict()
    if route_result.found:
        return jsonify(result_dict), 200
    else:
        return jsonify(result_dict), 404


# ---------------------------------------------------------------------------
# API: routing with fallback to external provider (OSRM)
# ---------------------------------------------------------------------------
@app.post("/api/route-external")
def get_route_external():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    if "start" not in data:
        return jsonify({"error": "Missing required field: 'start'."}), 400

    if "destination" not in data:
        return jsonify({"error": "Missing required field: 'destination'."}), 400

    start_coord, err = _validate_coordinate(data.get("start"), "start")
    if err:
        return jsonify({"error": err}), 400

    dest_coord, err = _validate_coordinate(data.get("destination"), "destination")
    if err:
        return jsonify({"error": err}), 400

    # Development-only trace to correlate browser-selected points with the
    # coordinates validated and passed to this request's route matcher.
    if app.debug:
        app.logger.debug(
            "POST /api/route-external received start=%s destination=%s", start_coord, dest_coord
        )

    try:
        route_result = routing_chain.route(
            start_coord,
            dest_coord,
            traffic_multipliers=get_current_traffic_multipliers(),
            blocked_segment_ids=None,
        )
    except Exception:
        return jsonify(
            {
                "found": False,
                "status": "INTERNAL_ROUTING_ERROR",
                "error": "An unexpected error occurred during external route calculation.",
            }
        ), 400

    result_dict = route_result.to_dict()
    if route_result.found:
        return jsonify(result_dict), 200
    else:
        return jsonify(result_dict), 404


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
