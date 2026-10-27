# NEXUS

**A community-informed local discovery and traffic intelligence platform.**

## Overview

NEXUS helps people unfamiliar with a place make sense of it. It combines two local capabilities:

1. **Local Discovery** — a searchable directory of places (hotels, hostels, rental rooms, houses, food, shops, salons, healthcare, transport, and more) with filtering, pagination, and nearby-search by coordinates.
2. **Traffic Intelligence** — real-time, community-derived road conditions (Normal / Moderate / Heavy / Blocked) and traffic-adjusted routing with blocked-road handling.

The local place directory does **not** ship with business records. Place listings must be added from a documented, permitted source, and each record carries provenance (`source_type`, `source_name`, `source_url`, `last_updated_at`). Community-verified and price-transparency features are **planned**; the current implementation focuses on the discovery API and routing/traffic layers described below.

## Key Features

### Traffic Intelligence and road-network routing
- Local OpenStreetMap road network loaded from `data/osm_roads.geojson` (no external routing dependency at runtime).
- Dijkstra shortest/fastest path with typed road classification, one-way rules, and OSM `maxspeed` when present.
- Traffic-adjusted route estimates: `Normal` x 1.0, `Moderate` x 1.25, `Heavy` x 1.75; `Blocked` segments are excluded from routing.
- Geographic snapping of start/destination points to the nearest road node (default 0.50 km snap limit) with snapped-distance reporting.

### Traffic-adjusted route estimates and blocked-road handling
- `POST /api/route` returns a traffic-weighted route and, for blocked segments, an alternate path that avoids them.
- Overlay endpoints (`GET /api/traffic`, `GET /api/reports`) feed live condition and incident data consumed by the routing state.

### Local Discovery
- Category catalog: Hotels, Hostels & PGs, Rental rooms, Houses & apartments, Food, Shops & groceries, Salons & personal care, Healthcare, Transport, Other.
- `GET /api/places` supports query search (`q`), exact category, subcategory, city, locality, and pagination (`page`, `per_page` <= 100).
- `GET /api/places?lat=&lon=&radius_km=` returns nearby places by coordinates.
- `GET /api/places/<place_id>` returns one place's details.
- Records are vertically scoped: each carries name, category, subcategory, description, address, locality, city, state, country, contact, opening hours, attributes, and source provenance.

### Place listings, filters, details, and location-based discovery
- Implemented and available in the API above, with category, text, pagination, and geo-based filtering.
- Place records are **empty by default**: the directory starts empty and must be populated from a documented source before listings appear.

### Community verification and price transparency (project goals)
- Verification status, source attribution, and update timestamps are supported fields on place records.
- **Price transparency ("Fair Price") is not implemented yet** — see [Current limitations](#current-limitations) and [Roadmap](#roadmap).



## Screenshots

No screenshots are available for this repository yet. Add them under the repository root (for example `docs/screenshots/`) and reference them here once captured.

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite 8 |
| Mapping | Leaflet 1.9.4 (tiles from OpenStreetMap) |
| Backend | Python 3.10+, Flask, Flask-CORS, SQLAlchemy 2.x |
| Database (default) | SQLite at `backend/instance/places.sqlite` |
| Database (alternative) | PostgreSQL via `NEXUS_DATABASE_URL` |
| Routing engine | Local Dijkstra engine over OSM GeoJSON (stdlib only) |
| External routing (optional) | OSRM HTTP API *(only as fallback when configured)* |
| Data source | OpenStreetMap via BBBike Extract Service (ODbL 1.0) |

## Project Structure

```
NEXUS/
├── backend/
│   ├── app.py                  # Flask application & API routes
│   ├── places.py               # Place catalog: schema, migration, search
│   ├── router.py               # Local routing engine (Dijkstra)
│   ├── road_segment.py         # RoadSegment / RoadMatcher data model
│   ├── road_loader.py          # OSM GeoJSON loader
│   ├── routing_provider.py     # Provider chain & optional OSRM fallback
│   ├── migrations/             # Database migrations (0001_places.sql)
│   └── instance/               # SQLite database created at runtime
├── data/
│   ├── README.md               # Road dataset documentation
│   └── osm_roads.geojson       # Local routing graph (OSM/BBBike, ODbL)
├── frontend/                   # Legacy static frontend (superseded)
├── frontend-vite/              # React + Vite + TypeScript frontend
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── HomePage.tsx
│       └── Discovery.tsx
├── scripts/
│   └── road_network.py         # Road network install/verification tooling
├── tests/                      # pytest suite (backend)
├── .env.example                # Example environment variables
└── README.md                   # This file
```

## Prerequisites

- **Python** 3.10 or newer (with `venv` module and `pip`)
- **Node.js** 18 or newer and **npm**
- **Git** (to clone the repository)

No additional graph/routing packages are required for the local router.

## Local Installation and Setup

Open **PowerShell** in the repository root and run the following steps.

### 1. Create and activate the Python virtual environment (backend)

```powershell
python -m venv venv
venv\Scripts\activate
```

### 2. Install backend dependencies

```powershell
pip install -r requirements.txt
```

### 3. Install and run the frontend

```powershell
cd frontend-vite
npm install
```

**Development server** (serves on `http://localhost:5173`, proxies `/api` to Flask):

```powershell
npx vite
```

**Production build** (the backend serves `frontend-vite/dist` when it exists):

```powershell
npm run build
```

### 4. Start the backend

```powershell
cd ..
venv\Scripts\python.exe backend\app.py
```

The backend listens on `http://127.0.0.1:5000` by default. Open `http://localhost:5000` to view the app; the frontend is served from `frontend-vite/dist` when a production build is present, otherwise from `frontend/` as a fallback.

### Production-build workflow

```powershell
cd frontend-vite
npm run build
cd ..
# The Flask backend now serves the built frontend.
venv\Scripts\python.exe backend\app.py
```



## Environment Configuration

The backend reads the following variables. All values shown in `.env.example` are examples; **no real credentials are committed**.

| Variable | Purpose | Default |
|----------|---------|---------|
| `NEXUS_DATABASE_URL` | SQLAlchemy database URL (e.g. PostgreSQL) | SQLite at `backend/instance/places.sqlite` |
| `NEXUS_PLACES_SQLITE_PATH` | Path to the SQLite file | `backend/instance/places.sqlite` |
| `NEXUS_OSM_DATA_PATH` | Path to the local OSM road GeoJSON | `data/osm_roads.geojson` |
| `NEXUS_GEOCODER_URL` | Nominatim geocoder endpoint | `https://nominatim.openstreetmap.org/search` |

Copy `.env.example` to `.env` and edit only the values you need. Do not commit `.env` (it is gitignored).

## Database Setup

- **Default database:** SQLite at `backend/instance/places.sqlite` (local, gitignored).
- **PostgreSQL:** install `psycopg[binary]`, set `NEXUS_DATABASE_URL`, and start the backend.
- **Migration:** a single additive migration `0001_places` creates the `places` table and its indexes. It runs automatically at application startup (`backend.places.migrate`). It **never** drops or rewrites existing tables, and does not affect the in-memory traffic state.
- The migration file is located at `backend/migrations/0001_places.sql`; it is applied programmatically by SQLAlchemy.

## API Overview

All endpoints are served by the Flask application (`backend/app.py`). Simplified request/response shapes are shown below.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/places/categories` | Returns the full place category catalog. |
| `GET` | `/api/places` | List/search places (`q`, `category`, `subcategory`, `city`, `locality`, `page`, `per_page`). Nearby search additionally requires `lat`, `lon`, and `radius_km` together. |
| `GET` | `/api/places/<place_id>` | Return one active place (`404` if not found). |
| `GET` | `/api/traffic` | Aggregated road-level traffic groups (in-memory; expired reports removed). |
| `GET` | `/api/reports` | Individual community reports (in-memory; expired reports removed). |
| `POST` | `/api/route` | Local, traffic-adjusted route. Body: `{ "start": { "lat", "lon" }, "destination": { "lat", "lon" } }`. |
| `POST` | `/api/route-external` | Route with optional external provider (OSRM) fallback. Same body shape. |

### Example: local route request

```powershell
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:5000/api/route -ContentType "application/json" -Body '{"start":{"lat":26.4499,"lon":80.3319},"destination":{"lat":26.4600,"lon":80.3400}}' -UseDefaultCredentials
```

A successful route returns `found: true`, `status: "SUCCESS"`, plus `total_distance_km`, `estimated_travel_time_s`, `coordinates`, `segment_ids`, and `road_names`. The request applies the current traffic consensus and excludes blocked segments.

## Road Network Data

Routing is built from a local OpenStreetMap road network:

- **Source:** BBBike Extract Service (`https://extract.bbbike.org/`), a custom regional OpenStreetMap PBF extract for the Kanpur area.
- **License & attribution:** OpenStreetMap data is © OpenStreetMap contributors and available under the [Open Database License (ODbL) 1.0](https://www.openstreetmap.org/copyright).
- **Date:** extracted 2026-10-22.
- **Coverage:** Kanpur, Uttar Pradesh, India — approximately longitude `80.0855`–`80.4574`, latitude `26.3124`–`26.5875`.
- **Contents:** ~29,466 OSM way features, ~171,712 nodes, ~373,957 directed edges, 35 connected components (see `data/README.md` for exact statistics and the importer workflow).
- **Conversion:** PyOsmium 4.3.2; every retained feature is an original OSM `way` with its numeric `osm_id` preserved.

Full importer, backup, and validation instructions are in [`data/README.md`](data/README.md).

## Testing

### Backend tests

```powershell
venv\Scripts\python.exe -m pytest tests\
```

Expected result (all tests pass): `152 passed, 11 subtests passed`.

### Frontend checks

```powershell
cd frontend-vite
npx tsc --noEmit   # type-check (no output on success)
npm run build      # production build
```



## Current Limitations

- **Place listings are empty.** The directory starts empty and must be populated from a documented, permitted source before listings are visible.
- **Community profiles are not available yet** (sign-in / contributor accounts are planned).
- **Price transparency ("Fair Price") is not implemented.**
- **The place catalog is wiki-style and must be seeded** with only permitted, documented sources; no unauthenticated public write endpoint is exposed.
- **Route coverage is limited to the installed OSM extract** (Kanpur area). Coordinates farther than ~0.5 km from the road network return `START_NOT_FOUND`/`DESTINATION_NOT_FOUND` rather than a route.
- **OSRM fallback is not configured** by default; `POST /api/route-external` is the endpoint that would use it when an external routing service is configured.
- **In-memory traffic state resets on restart.** Reports expire after 30 minutes.
- The legacy `frontend/` directory is maintained only as a fallback; the active frontend is `frontend-vite`.

## Roadmap

The following are planned, separate from completed functionality:

- Full place-listing seeding workflow and contributor profile UI.
- **Fair Price / price transparency** for place records.
- Community verification workflows for place records.
- Persistent, production-ready traffic data store (the current implementation is in-memory).
- Configurable external routing (OSRM) fallback for out-of-coverage routes.

## Contributing

1. Fork the repository and create a feature branch from `main`.
2. Make focused changes; keep application code, tests, frontend source, configuration, documentation, and road data separate from temporary/debug artifacts.
3. Run the backend test suite and frontend checks before opening a pull request:

   ```powershell
   venv\Scripts\python.exe -m pytest tests\
   cd frontend-vite
   npx tsc --noEmit
   npm run build
   ```

4. Do not commit `.env`, virtual environments, caches, build output, or secrets.
5. Open a pull request against `main` with a clear description of the change and tests added.

## License and Attribution

- **Road data:** OpenStreetMap® data, © OpenStreetMap contributors, licensed under [ODbL 1.0](https://www.openstreetmap.org/copyright).
- **Project software:** no software license has been confirmed for this repository yet. If no license is later selected, the source code is offered under an **unlicensed** arrangement (all rights reserved) unless explicitly stated otherwise. Please confirm the project license before redistribution.

> NEXUS is **not deployed** and is **not production-ready**. Use it for local evaluation, development, and testing only.

