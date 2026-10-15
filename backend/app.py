

import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
try:
    from .road_segment import RoadSegment, RoadMatcher
    from .road_loader import load_road_network
    from .router import Router
except ImportError:
    from road_segment import RoadSegment, RoadMatcher
    from road_loader import load_road_network
    from router import Router

# Project directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

app = Flask(__name__)
CORS(app)

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

# ---------------------------------------------------------------------------
# Frontend: Serve NEXUS Web UI (avoids file:// browser restrictions)
# ---------------------------------------------------------------------------
@app.get("/")
def serve_root():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/index.html")
def serve_index_html():
    return send_from_directory(FRONTEND_DIR, "index.html")

# ---------------------------------------------------------------------------
# In-memory store (lost on restart — intentional at this stage)
# ---------------------------------------------------------------------------
reports = []

REPORT_EXPIRY_MINUTES = 30

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

# ---------------------------------------------------------------------------
# Traffic-Aware Routing (Step 25.3): condition -> travel-time multiplier
# ---------------------------------------------------------------------------
# Deterministic mapping from NEXUS consensus conditions (VALID_CONDITIONS)
# to routing travel-time multipliers. "Blocked" uses a large finite penalty so
# Dijkstra avoids the segment without needing a special-cased removal step.
TRAFFIC_CONDITION_MULTIPLIERS = {
    "Normal":   1.0,
    "Moderate": 1.25,
    "Heavy":    1.75,
    "Blocked":  100.0,
}


def traffic_condition_to_multiplier(condition):
    """
    Convert an existing aggregated traffic condition into a routing
    travel-time multiplier. Unknown/missing conditions default to 1.0.
    """
    return TRAFFIC_CONDITION_MULTIPLIERS.get(condition, 1.0)


def get_current_traffic_multipliers():
    """
    Build a {segment_id: multiplier} mapping from the CURRENT community
    traffic consensus for consumption by Router.find_route().

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
    for segment in traffic_segments:
        seg_id = segment.get("segment_id")
        if seg_id:
            multipliers[seg_id] = traffic_condition_to_multiplier(segment.get("status"))

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

    try:
        # Step 25.3: automatically weight the route with current community
        # traffic consensus (expired reports purged inside the helper).
        traffic_multipliers = get_current_traffic_multipliers()
        route_result = router.find_route(
            start_coord,
            dest_coord,
            traffic_multipliers=traffic_multipliers,
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

if __name__ == "__main__":
    app.run(debug=True)
