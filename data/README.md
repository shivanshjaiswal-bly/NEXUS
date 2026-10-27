# NEXUS road network data

`osm_roads.geojson` is the local routing graph source. It was installed on 2026-10-22 from the BBBike custom Kanpur OSM PBF extract requested for `west=80.10, south=26.35, east=80.45, north=26.60`.

The active graph contains 29,466 OSM way features, 171,712 normalized nodes, 373,957 directed edges, and 35 undirected connected components. Its observed WGS84 bounds are longitude 80.0855366–80.4574299 and latitude 26.3123781–26.5875100. The input PBF (`NEXUS-Kanpur-Roads-PBF.pbf`) had SHA-256 `291c10d27dae74baa86ff1a0a3ba3e8e9374d2472a2b7538bddb771ec3bb3c74`.

The extract was converted with PyOsmium 4.3.2. Every retained feature is an original OSM `way` with its numeric source ID preserved in `properties.osm_id` and its type in `properties.osm_type`; no feature-order, synthetic, or generated road IDs are used. The conversion retained 29,459 highway ways, including 77 closed highway ways, without missing node locations or degenerate geometries. It retains supplied `highway`, `oneway`, name, speed, access, and other OSM tags. The import merged 241 matching historical ways and retained seven older non-overlapping ways.

With the unchanged 0.50 km snap cap, the central-Kanpur regression route (26.449, 80.331 → 26.467, 80.354) succeeds at 4.853 km and 421.93 seconds. The expanded route (26.505250, 80.302119 → 26.458249, 80.192471) succeeds at 15.664 km and 1657.79 seconds. Its endpoint snaps are 0.012 km and 0.109 km, respectively.

## Source, attribution, and license

Source: [BBBike Extract Service](https://extract.bbbike.org/), custom regional OpenStreetMap PBF extract. © OpenStreetMap contributors. OpenStreetMap data is available under the [Open Database License (ODbL) 1.0](https://www.openstreetmap.org/copyright).

The pre-install dataset is preserved as the timestamped, byte-verified backup `osm_roads.geojson.bak.20261022T130852684810Z`; its SHA-256 is `ded9cfa4bc4262c512dfcd01edb9e86fa7a4679df95d434320e7bae7f19f6d2f`.

## Repeatable validation and installation

The importer accepts only WGS84 GeoJSON `FeatureCollection` road `LineString` features with a stable numeric original OSM way ID (`properties.osm_id`, a `way/<id>` feature ID, or the legacy equivalent). It rejects duplicate IDs, malformed coordinates, non-line highway features, missing IDs, and candidates for which either required route is outside the 0.50 km cap or disconnected. It preserves supplied one-way directionality and existing routing behavior.

For a PBF replacement, use Osmium (CLI or bindings) to read original OSM **ways**, preserve all tags, and emit `osm_type: "way"` plus the original numeric `osm_id` as properties. Do not export nodes or relations as road features and do not substitute generated IDs. Check the actual GeoJSON schema, missing/duplicate IDs, closed ways, bounds, graph connectivity, and both routes before installing.

Install only after those staging checks pass:

```powershell
.\venv\Scripts\python.exe scripts\road_network.py install C:\path\to\converted-roads.geojson --download-date YYYY-MM-DD --source-url https://extract.bbbike.org/
```

The command validates the merged candidate, creates and hash-verifies a timestamped backup, then atomically replaces the active file. Restart Flask after a successful install. Routing continues to use the existing one-way rules, traffic-adjusted costs, blocked-road exclusions, and 0.50 km maximum snap distance.
