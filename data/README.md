# NEXUS Road Network Datasets

This directory contains local OpenStreetMap road network data used by the NEXUS `road_loader` and `RoadMatcher` backend modules.

## Architecture

```
local OSM road data (GeoJSON / OSM JSON)
        ↓
road-network loader (backend/road_loader.py)
        ↓
normalized road segments (backend/road_segment.py)
        ↓
RoadMatcher (backend/road_segment.py)
        ↓
traffic groups (backend/app.py)
        ↓
/api/traffic
```

## Dataset Configuration

The backend defaults to loading:
```
data/osm_roads.geojson
```
You can point NEXUS to any custom local OSM extract by setting the environment variable:
```bash
export NEXUS_OSM_DATA_PATH="/path/to/custom_roads.geojson"
```

## Supported Formats

1. **GeoJSON `FeatureCollection`** (Recommended):
   - Features of geometry type `LineString` or `Point`.
   - Properties must include `osm_id` (or feature `id`).
   - Optional properties: `name` (road name), `tolerance_km` (match distance threshold).
2. **OpenStreetMap JSON export (`elements` array)**:
   - Elements of type `way` with `id`, `tags` (`name`), and `geometry` coordinate list.

## Guarantees & Non-Hallucination Policy

- **No external per-report queries**: Zero network calls during traffic reports or queries.
- **Fail-safe fallback**: If this file is missing or invalid, NEXUS launches normally in unmapped mode (`segment_id: null`).
- **No invented road names**: Road names are strictly read from the verified dataset. Unnamed segments report `road_name: null`.
