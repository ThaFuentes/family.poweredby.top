import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils import hot_cache as hc
from app.builddb.builddb import schema_fingerprint


class HotCacheTests(unittest.TestCase):
    def setUp(self):
        hc.clear()

    def tearDown(self):
        hc.clear()

    def test_roundtrip_is_copied(self):
        hc.put("k", {"a": 1}, 30)
        hit = hc.get("k")
        self.assertEqual(hit, {"a": 1})
        hit["a"] = 9
        self.assertEqual(hc.get("k")["a"], 1)

    def test_expire(self):
        hc.put("k", 1, 0.02)
        self.assertEqual(hc.get("k"), 1)
        time.sleep(0.03)
        self.assertIsNone(hc.get("k"))

    def test_invalidate_household_drops_home_only(self):
        hc.put("home:3:a:1", {"x": 1}, 30)
        hc.put("home:4:a:1", {"x": 2}, 30)
        hc.put("upc:011111111111", {"ok": True}, 30)
        hc.invalidate_household(3)
        self.assertIsNone(hc.get("home:3:a:1"))
        self.assertEqual(hc.get("home:4:a:1")["x"], 2)
        self.assertTrue(hc.get("upc:011111111111")["ok"])

    def test_schema_fingerprint_stable(self):
        a = schema_fingerprint()
        b = schema_fingerprint()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 24)


class UpcCacheTests(unittest.TestCase):
    def setUp(self):
        hc.clear()

    def tearDown(self):
        hc.clear()

    def test_second_lookup_skips_catalogs(self):
        from app.utils.barcode_lookup import lookup_product

        hit = {
            "ok": True,
            "name": "Test Milk",
            "brand": "Horizon",
            "source": "openfoodfacts",
        }
        empty = {}
        with patch("app.utils.barcode_lookup._open_food_facts", return_value=hit) as food, patch(
            "app.utils.barcode_lookup._open_products_facts", return_value=empty
        ), patch(
            "app.utils.barcode_lookup._open_beauty_facts", return_value=empty
        ), patch(
            "app.utils.barcode_lookup._open_pet_facts", return_value=empty
        ), patch(
            "app.utils.barcode_lookup._upcitemdb", return_value=empty
        ):
            first = lookup_product("012345678901")
            second = lookup_product("012345678901")
        self.assertTrue(first.get("ok"))
        self.assertEqual(first.get("name"), "Test Milk")
        self.assertEqual(second.get("name"), "Test Milk")
        self.assertEqual(food.call_count, 1)


if __name__ == "__main__":
    unittest.main()
