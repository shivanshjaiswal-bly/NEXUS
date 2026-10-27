"""Versioned SQLAlchemy-backed place directory, independent of traffic data."""
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (CheckConstraint, Column, Float, Index, Integer, MetaData,
                        String, Table, Text, create_engine, select, text)
from sqlalchemy.engine import Engine

PLACE_CATEGORIES = [
    {"id": "hotels", "label": "Hotels"}, {"id": "hostels_pgs", "label": "Hostels and PGs"},
    {"id": "rental_rooms", "label": "Rental rooms"}, {"id": "houses_apartments", "label": "Houses and apartments"},
    {"id": "food", "label": "Restaurants and food"}, {"id": "shops_groceries", "label": "Shops and groceries"},
    {"id": "salons_personal_care", "label": "Salons and personal care"}, {"id": "healthcare", "label": "Pharmacies and healthcare"},
    {"id": "transport", "label": "Bus stands and transport"}, {"id": "other", "label": "Other local services"},
]
VALID_CATEGORIES = {item["id"] for item in PLACE_CATEGORIES}
metadata = MetaData()
places = Table("places", metadata,
    Column("id", String(80), primary_key=True), Column("name", String(200), nullable=False),
    Column("category", String(40), nullable=False), Column("subcategory", String(80)), Column("description", Text),
    Column("address", String(300)), Column("locality", String(160)), Column("city", String(120), nullable=False),
    Column("state", String(120), nullable=False), Column("country", String(80), nullable=False, server_default="India"),
    Column("latitude", Float), Column("longitude", Float), Column("contact", String(160)), Column("opening_hours", Text),
    Column("attributes_json", Text, nullable=False, server_default="{}"), Column("source_type", String(24), nullable=False),
    Column("source_name", String(160)), Column("external_id", String(200)), Column("source_url", Text),
    Column("last_updated_at", String(40)), Column("listing_status", String(24), nullable=False, server_default="active"),
    Column("verification_status", String(24)), Column("verified_at", String(40)),
    Column("created_at", String(40), nullable=False), Column("updated_at", String(40), nullable=False),
    CheckConstraint("category IN (" + ",".join(repr(x) for x in sorted(VALID_CATEGORIES)) + ")", name="ck_places_category"),
    CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="ck_places_latitude"),
    CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="ck_places_longitude"),
    CheckConstraint("source_type IN ('sourced','user_reported','demo')", name="ck_places_source_type"),
    CheckConstraint("listing_status IN ('active','inactive','pending')", name="ck_places_status"),
)
Index("ix_places_category_status", places.c.category, places.c.listing_status)
Index("ix_places_city_locality", places.c.city, places.c.locality)
Index("ix_places_external_source", places.c.source_name, places.c.external_id, unique=True)
Index("ix_places_name", places.c.name)

def get_engine() -> Engine:
    url = os.environ.get("NEXUS_DATABASE_URL")
    if not url:
        path = Path(os.environ.get("NEXUS_PLACES_SQLITE_PATH", Path(__file__).parent / "instance" / "places.sqlite"))
        path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + path.as_posix()
    return create_engine(url, future=True, pool_pre_ping=True)

def migrate(engine: Engine, direction="upgrade"):
    """Apply/undo the single additive migration; leaves all other tables intact."""
    if direction == "upgrade":
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS nexus_schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)"))
            if not conn.execute(text("SELECT version FROM nexus_schema_migrations WHERE version=:v"), {"v": "0001_places"}).first():
                metadata.create_all(conn, tables=[places], checkfirst=True)
                conn.execute(text("INSERT INTO nexus_schema_migrations(version, applied_at) VALUES (:v,:t)"), {"v": "0001_places", "t": datetime.now(timezone.utc).isoformat()})
    elif direction == "downgrade":
        with engine.begin() as conn:
            if conn.execute(text("SELECT version FROM nexus_schema_migrations WHERE version=:v"), {"v": "0001_places"}).first():
                places.drop(conn, checkfirst=True)
                conn.execute(text("DELETE FROM nexus_schema_migrations WHERE version=:v"), {"v": "0001_places"})
    else:
        raise ValueError("direction must be upgrade or downgrade")

def validate_record(record):
    if not isinstance(record, dict): raise ValueError("Place record must be an object.")
    for field in ("id", "name", "category", "city", "state", "source_type"):
        if not isinstance(record.get(field), str) or not record[field].strip(): raise ValueError(f"{field} is required.")
    if record["category"] not in VALID_CATEGORIES: raise ValueError("Unknown category.")
    if record["source_type"] not in {"sourced", "user_reported", "demo"}: raise ValueError("Invalid source_type.")
    for key, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = record.get(key)
        if value is not None:
            if isinstance(value, bool): raise ValueError(f"{key} must be numeric.")
            try: value = float(value)
            except (ValueError, TypeError): raise ValueError(f"{key} must be numeric.")
            if not low <= value <= high: raise ValueError(f"{key} is out of range.")
            record[key] = value
    if (record.get("latitude") is None) != (record.get("longitude") is None): raise ValueError("latitude and longitude must be supplied together.")
    return record

def record_to_json(row):
    result = dict(row)
    import json
    result["attributes"] = json.loads(result.pop("attributes_json", "{}"))
    return result

def search(engine, args):
    page = int(args.get("page", 1)); per_page = int(args.get("per_page", 20))
    if page < 1: raise ValueError("page must be at least 1.")
    if not 1 <= per_page <= 100: raise ValueError("per_page must be between 1 and 100.")
    stmt = select(places).where(places.c.listing_status == "active")
    for key in ("category", "subcategory", "city", "locality"):
        val = args.get(key, "").strip()
        if val:
            if key == "category" and val not in VALID_CATEGORIES: raise ValueError("Unknown category.")
            stmt = stmt.where(getattr(places.c, key).ilike(val) if key == "category" else getattr(places.c, key).ilike(f"%{val}%"))
    q = args.get("q", "").strip()
    if len(q) > 200: raise ValueError("q must be at most 200 characters.")
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(places.c.name.ilike(needle) | places.c.description.ilike(needle) | places.c.address.ilike(needle) | places.c.locality.ilike(needle) | places.c.subcategory.ilike(needle))
    coords = (args.get("lat"), args.get("lon"), args.get("radius_km"))
    if any(v is not None for v in coords):
        if any(v is None for v in coords): raise ValueError("lat, lon and radius_km are all required for nearby search.")
        try: lat, lon, radius = map(float, coords)
        except (ValueError, TypeError): raise ValueError("Geographic parameters must be numbers.")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 < radius <= 100: raise ValueError("Coordinates must be valid and radius_km must be in (0, 100].")
        from math import radians, sin, cos, asin, sqrt
        with engine.connect() as conn: rows = [record_to_json(r) for r in conn.execute(stmt.order_by(places.c.id)).mappings()]
        rows = [r for r in rows if r["latitude"] is not None and 6371 * 2 * asin(sqrt(sin(radians(r["latitude"]-lat)/2)**2 + cos(radians(lat))*cos(radians(r["latitude"]))*sin(radians(r["longitude"]-lon)/2)**2)) <= radius]
        total = len(rows); return {"items": rows[(page-1)*per_page:page*per_page], "page": page, "per_page": per_page, "total": total}
    with engine.connect() as conn:
        total = conn.execute(select(text("count(*)")).select_from(stmt.subquery())).scalar_one()
        rows = conn.execute(stmt.order_by(places.c.name.asc(), places.c.id.asc()).offset((page-1)*per_page).limit(per_page)).mappings()
        return {"items": [record_to_json(r) for r in rows], "page": page, "per_page": per_page, "total": total}
