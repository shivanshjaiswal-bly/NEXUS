# NEXUS v2: Development, System, and Demo Workflow

Community-Based Real-Time Traffic Intelligence & Emergency Routing (Kanpur)

Legend: **[NEW]** = added in v2, **[UP]** = upgraded from v1, unmarked = unchanged.
Code was not shared, so these changes are applied to the design and workflow. Each step lists the file to touch.

---

## 0. What changed and why

| # | Change | Why it matters | File | Effort |
|---|---|---|---|---|
| 1 | Persist reports in SQLite | In-memory reports vanish on every restart | `backend/storage.py` [NEW] | 3-4 h |
| 2 | Input guard: schema + rate limit | One person can spam reports and fake a "Blocked" road | `backend/trust.py` [NEW] | 3-4 h |
| 3 | Blocked-road warning | Blocked = x100 cost still returns a route silently | `backend/router.py` [UP] | 1-2 h |
| 4 | Production basics | Flask dev server, no health check, no CI | waitress, `/health`, logging, CI | 3 h |
| 5 | Live push via SSE | 10 s polling wastes requests and delays updates | `backend/events.py` [NEW] | 4-6 h |
| 6 | A* and realistic ETA | Dijkstra explores more nodes; distance-only cost ignores road class | `backend/router.py` [UP] | 4-6 h |
| 7 | Spatial index in matcher | Scanning every segment per report does not scale past 248 features | `backend/road_segment.py` [UP] | 2-3 h |
| 8 | Time-decay consensus | Hard 30-min cut-off treats a 29-min-old report like a fresh one | `backend/app.py` [UP] | 3-4 h |
| 9 | Alternates + vehicle profiles | Emergency users need options, and ambulances move differently from cars | `backend/router.py` [UP] | 1-2 days |
| 10 | Reroute prompt | Polling already keeps the route; now tell the user when it is affected | `frontend/index.html` [UP] | 3-4 h |
| 11 | Confirm / deny on reports | Cheapest way to raise or lower confidence from the community | app + frontend [NEW] | 1 day |
| 12 | Grow beyond Central Kanpur | 248 features is a demo-sized area | `data/osm_roads.geojson` [UP] | 1 day |

Effort figures are rough estimates for one student developer.

---

## 1. End-to-End Workflow (v2)

1. User opens NEXUS. Flask serves the frontend and the Leaflet map loads.
2. Map initializes with the Esri street basemap, the Kanpur boundary and local road context.
3. **[UP]** Live traffic loads once from `GET /api/traffic`, then updates arrive over **Server-Sent Events**. If SSE fails, the frontend falls back to the 10 s polling.
4. User opens Report Traffic, picks a condition/incident and submits.
5. **[NEW]** Backend validates the schema, then checks rate limit and reporter trust. Failed checks return `429` and the report is discarded.
6. **[NEW]** Valid reports are stored in SQLite.
7. **[UP]** RoadMatcher snaps each report to an OSM segment using a spatial index.
8. **[UP]** Reports are aggregated per segment with time-decay weights x reporter trust, giving a consensus condition and confidence.
9. **[NEW]** The updated traffic state is pushed to all connected clients.
10. User opens Emergency Route and picks Start and Destination by search or map click. Raw coordinates stay hidden.
11. **[UP]** Frontend sends `POST /api/route` with start, destination and an optional vehicle profile.
12. Router snaps both points to the nearest graph nodes.
13. **[UP]** Edge cost = `length / road-class speed x traffic multiplier` (Normal 1.0, Moderate 1.25, Heavy 1.75, Blocked 100.0).
14. **[UP]** A* search with a haversine heuristic finds the route.
15. **[NEW]** If the route crosses a Blocked segment, the response carries a warning plus an alternate route.
16. **[UP]** Backend returns geometry, distance, ETA, segments, alternates, warnings and status.
17. Frontend draws the emergency route separately from the traffic layer and fits the map.
18. **[NEW]** If a traffic update hits a segment on the active route, the UI asks "Reroute?". Accepting repeats step 11.

---

## 2. System Architecture (v2)

| Layer | File | Responsibility |
|---|---|---|
| Frontend | `frontend/index.html` | Leaflet map, traffic display, report UI, search, route UI, **[NEW]** EventSource client |
| API | `backend/app.py` | `GET /api/traffic`, report endpoint, `POST /api/route`, **[NEW]** `/health` |
| Input guard | `backend/trust.py` **[NEW]** | Schema validation, rate limit, reporter trust weight |
| Traffic layer | `backend/app.py` **[UP]** | Time-decay consensus, confidence, multipliers |
| Event stream | `backend/events.py` **[NEW]** | SSE push when traffic state changes |
| Storage | `backend/storage.py` **[NEW]** | SQLite reports (replaces in-memory list) |
| Road network | `data/osm_roads.geojson` | 248 road features, Central Kanpur |
| Loader | `backend/road_loader.py` | Loads local GeoJSON |
| Matcher | `backend/road_segment.py` **[UP]** | Report to segment, via spatial index |
| Router | `backend/router.py` **[UP]** | Graph, snapping, road-class edge cost, A*, alternates, warnings |

---

## 3. Traffic Intelligence Flow (v2)

1. User submits a report.
2. Backend validates condition, incident, latitude and longitude (inside Kanpur bounds).
3. **[NEW]** Rate limit and trust check. Fail returns 429.
4. **[NEW]** Report is stored in SQLite.
5. **[UP]** RoadMatcher associates it with an OSM segment (spatial index).
6. **[UP]** Per segment, each report gets `weight = 0.5 ^ (age / 10 min) x trust`. Reports are dropped when their weight falls below 0.1 (about 33 min), which matches today's 30-minute rule.
7. **[UP]** Consensus condition = highest total weight. Confidence = winner's share of total weight, scaled down when there are few reports.
8. **[NEW]** State is published and pushed to clients.
9. Frontend redraws `trafficLayer` only.

## 4. Emergency Routing Flow (v2)

1. User selects Start and Destination.
2. Frontend stores coordinates internally and sends `POST /api/route`.
3. Router snaps to the nearest graph nodes.
4. **[UP]** A* runs with `h = haversine distance / max road speed`. It stays admissible because every traffic multiplier is at least 1.
5. **[NEW]** The result is checked for Blocked segments, and warnings and alternates are attached.
6. Backend returns the route and statistics.
7. Frontend draws `emergencyRouteLayer` independently of the traffic layer.

---

## 5. Demo Workflow (v2)

1. Start the server: `.\venv\Scripts\python.exe -m backend.app` (production: waitress).
2. Open `http://127.0.0.1:5000/` and verify the map and traffic layer load.
3. Submit a sample report and verify the traffic layer updates **without a page refresh** (SSE).
4. **[NEW]** Restart the server and verify the report is still there (SQLite).
5. **[NEW]** Submit reports rapidly and verify the rate limit returns 429.
6. Open Emergency Route, set Start and Destination, click Find Emergency Route.
7. Verify the route line, distance, ETA and segment information.
8. Report Heavy or Blocked on a route segment. **[NEW]** The UI prompts "Reroute?". Accept and compare the new route.
9. **[NEW]** Block the only road to a destination and verify the warning appears.
10. Verify that traffic updates never remove the emergency route or the markers.

---

## 6. Verification Checkpoint

- Baseline: 95/95 automated tests passing.
- **[NEW]** Add tests for: storage survives restart; rate limit returns 429; decay weights and consensus; A* returns the same cost as Dijkstra on sample pairs; blocked-segment warning; SSE event emitted on state change.
- Gate: every phase ends with the full suite green before the next starts.

## 7. Design Rules

Kept from v1:
- Keep `trafficLayer`, `emergencyRouteLayer`, start marker and destination marker independent.
- Do not expose raw latitude/longitude to normal users.
- Keep routing local/offline at runtime.
- Traffic polling (or SSE) must not clear the emergency route.
- Make controlled changes and run the full test suite after each one.

Added in v2:
- **[NEW]** Never store reporter identity beyond a rate-limit key, and round stored coordinates.
- **[NEW]** SSE is an enhancement: the 10 s polling fallback must keep working.
- **[NEW]** Cost values for vehicle profiles are tunable config, not hard-coded.

## 8. Timed Plan

| Phase | When | Items |
|---|---|---|
| 1. Safe and durable | Day 1-2 | #1 SQLite, #2 input guard, #3 blocked warning, #4 production basics |
| 2. Fast and realistic | Day 3-7 | #5 SSE, #6 A* + road-class ETA, #7 spatial index, #8 time-decay |
| 3. Smarter | Week 2-3 | #9 alternates + profiles, #10 reroute prompt, #11 confirm/deny, #12 wider map |
