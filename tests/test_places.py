import unittest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from backend.places import (migrate, places, search, validate_record, record_to_json)
from backend.app import app


class PlaceDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", future=True, poolclass=StaticPool)
        migrate(self.engine)
        self.client = app.test_client()
        self.ids = ["test-place-a", "test-place-b"]
        now = "2026-10-22T00:00:00+00:00"
        self.records = [
            {"id": self.ids[0], "name": "Sample Cafe", "category": "food", "subcategory": "cafe", "description": "Coffee and food", "address": "Main Road", "locality": "Civil Lines", "city": "Kanpur", "state": "Uttar Pradesh", "country": "India", "latitude": 26.45, "longitude": 80.33, "attributes_json": "{}", "source_type": "demo", "source_name": "Automated test fixture", "external_id": None, "source_url": None, "last_updated_at": now, "listing_status": "active", "verification_status": None, "verified_at": None, "created_at": now, "updated_at": now},
            {"id": self.ids[1], "name": "Sample Pharmacy", "category": "healthcare", "subcategory": None, "description": None, "address": None, "locality": "Swaroop Nagar", "city": "Kanpur", "state": "Uttar Pradesh", "country": "India", "latitude": 26.47, "longitude": 80.35, "attributes_json": "{}", "source_type": "demo", "source_name": "Automated test fixture", "external_id": None, "source_url": None, "last_updated_at": now, "listing_status": "active", "verification_status": None, "verified_at": None, "created_at": now, "updated_at": now},
        ]
        with self.engine.begin() as conn: conn.execute(insert(places), self.records)

    def tearDown(self): self.engine.dispose()

    def test_record_validation_required_fields_and_coordinates(self):
        self.assertEqual(validate_record({"id":"x", "name":"X", "category":"food", "city":"Kanpur", "state":"UP", "source_type":"demo"})["id"], "x")
        for invalid in ({"id":"x"}, {"id":"x", "name":"X", "category":"made_up", "city":"X", "state":"X", "source_type":"demo"}, {"id":"x", "name":"X", "category":"food", "city":"X", "state":"X", "source_type":"demo", "latitude":100}):
            with self.assertRaises(ValueError): validate_record(invalid)

    def test_category_city_text_pagination_and_stable_sort(self):
        found = search(self.engine, {"category":"food", "city":"kan", "q":"Coffee", "page":"1", "per_page":"1"})
        self.assertEqual(found["total"], 1); self.assertEqual(found["items"][0]["id"], self.ids[0])
        page = search(self.engine, {"page":"1", "per_page":"1"})
        self.assertEqual(page["items"][0]["name"], "Sample Cafe")
        self.assertEqual(search(self.engine, {"city":"Delhi"})["total"], 0)

    def test_distance_and_invalid_geo_params(self):
        self.assertEqual(search(self.engine, {"lat":"26.45", "lon":"80.33", "radius_km":"1"})["total"], 1)
        for params in ({"lat":"91", "lon":"0", "radius_km":"1"}, {"lat":"0", "lon":"0"}, {"lat":"0", "lon":"0", "radius_km":"500"}):
            with self.assertRaises(ValueError): search(self.engine, params)

    def test_database_constraints_and_demo_provenance(self):
        self.assertEqual(record_to_json(self.records[0])["source_type"], "demo")
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(places).values(**{**self.records[0], "id":"invalid-category", "category":"not-a-category"}))

    def test_migration_downgrade_removes_only_places_table(self):
        migrate(self.engine, "downgrade")
        self.assertFalse(self.engine.dialect.has_table(self.engine.connect(), "places"))
        migrate(self.engine)
        self.assertTrue(self.engine.dialect.has_table(self.engine.connect(), "places"))

    def test_api_empty_categories_validation_and_not_found(self):
        response = self.client.get("/api/places?city=No-such-city")
        self.assertEqual(response.status_code, 200); self.assertEqual(response.get_json()["items"], [])
        self.assertEqual(self.client.get("/api/places?lat=91&lon=0&radius_km=2").status_code, 400)
        self.assertEqual(self.client.get("/api/places?page=0").status_code, 400)
        self.assertEqual(self.client.get("/api/places/unknown-test-id").status_code, 404)
        self.assertEqual(self.client.get("/api/places/categories").status_code, 200)


if __name__ == "__main__": unittest.main()
