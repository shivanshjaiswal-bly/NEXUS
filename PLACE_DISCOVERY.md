# Local Discovery

## Data and coverage

The place directory starts empty. No business records, prices, hours, contact details, coordinates, ratings, or coverage claims are seeded. Add records only from a documented, permitted source and record `source_type`, `source_name`, `external_id`, and `source_url` as known. Demo records must use `source_type: demo` and remain visibly labeled.

## Database setup

The local default is SQLite at `backend/instance/places.sqlite`; it is separate from the in-memory traffic reports. SQLAlchemy is used for dialect-safe SQL and parameter binding. To use PostgreSQL, install `psycopg[binary]`, set `NEXUS_DATABASE_URL` (see `.env.example`), and start Flask. The place migration runs additively at app startup and records version `0001_places` in `nexus_schema_migrations`. It creates only `places` and its indexes. No existing tables are dropped or rewritten. To reverse that migration in a Python shell, call `backend.places.migrate(backend.places.get_engine(), "downgrade")`; this removes only the places table.

PostgreSQL was not available or configured during this implementation. Existing tests do not require a PostgreSQL service; the default SQLite database is local and ignored by git.

## API

- `GET /api/places/categories` returns `{ "categories": [{ "id": "hotels", "label": "Hotels" }, ...] }`.
- `GET /api/places?q=food&category=food&city=Kanpur&locality=...&page=1&per_page=20` returns `{ "items": [...], "page": 1, "per_page": 20, "total": 0 }`. Search covers name, description, address, subcategory, and locality. Active records only; names and stable IDs determine ordinary sort order. `per_page` is 1–100.
- `GET /api/places?lat=26.45&lon=80.33&radius_km=5` adds nearby filtering for records with coordinates (radius 0–100 km); all three parameters are required together.
- `GET /api/places/<id>` returns one active listing or HTTP 404 `{ "error": "Place not found." }`.
- Invalid filters and pagination return HTTP 400 with `{ "error": "..." }`.

Place source types are `sourced`, `user_reported`, and `demo`. Verification status is nullable and has no implied verified value. Database insertion/import can use `backend.places.validate_record`; this milestone intentionally exposes no unauthenticated public write endpoint.
