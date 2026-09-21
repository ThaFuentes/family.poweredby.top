import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.classify import classify_product, classify_text


class ClassifyTests(unittest.TestCase):
    def test_car_battery(self):
        hit = classify_product(
            {"name": "DieHard Gold Automotive Battery Group 35", "brand": "DieHard", "category": "Batteries"}
        )
        self.assertEqual(hit["kind"], "car_battery")
        self.assertEqual(hit["item_type"], "grocery")
        self.assertEqual(hit["attach_to"], "vehicle")
        self.assertTrue(any("vehicle" in q.lower() for q in hit["questions"]))

    def test_bare_battery_is_car(self):
        self.assertEqual(classify_text("12V battery"), "car_battery")

    def test_aa_battery(self):
        hit = classify_product({"name": "Duracell AA Alkaline Battery 8-pack"})
        self.assertEqual(hit["kind"], "aa_battery")
        self.assertIsNone(hit["attach_to"])

    def test_motor_oil(self):
        hit = classify_product({"name": "Mobil 1 5W-30 Advanced Full Synthetic Motor Oil"})
        self.assertEqual(hit["kind"], "motor_oil")
        self.assertEqual(hit["attach_to"], "vehicle")

    def test_food(self):
        hit = classify_product(
            {"name": "Horizon Organic Whole Milk", "category": "Dairy", "source": "openfoodfacts"}
        )
        self.assertEqual(hit["kind"], "food")
        self.assertEqual(hit["item_type"], "grocery")

    def test_mower(self):
        hit = classify_product({"name": "Honda HRX217 lawn mower"})
        self.assertEqual(hit["kind"], "mower")
        self.assertEqual(hit["item_type"], "tool")

    def test_filter(self):
        hit = classify_product({"name": "FRAM Extra Guard Oil Filter PH3614"})
        self.assertEqual(hit["kind"], "filter")

    def test_knife_is_tool_not_grocery(self):
        self.assertEqual(classify_text("chef knife"), "tool")

    def test_bug_spray_is_household(self):
        self.assertEqual(classify_text("Raid ant and roach"), "household")
        hit = classify_product({"name": "Off Deep Woods bug spray"})
        self.assertEqual(hit["kind"], "household")
        self.assertEqual(hit["item_type"], "grocery")


class StoreRunTests(unittest.TestCase):
    def test_food_and_tp_and_aa(self):
        from types import SimpleNamespace
        from app.routes.groceries import is_store_run, is_auto_supply

        milk = SimpleNamespace(
            name="Milk",
            category="",
            grocery=SimpleNamespace(extra_data={"kind": "food"}),
        )
        tp = SimpleNamespace(
            name="Toilet paper",
            category="",
            grocery=SimpleNamespace(extra_data={"kind": "household"}),
        )
        aa = SimpleNamespace(
            name="Duracell AA",
            category="",
            grocery=SimpleNamespace(extra_data={"kind": "aa_battery"}),
        )
        car = SimpleNamespace(
            name="DieHard Gold",
            category="",
            grocery=SimpleNamespace(extra_data={"kind": "car_battery"}),
        )
        knife = SimpleNamespace(
            name="Chef knife",
            category="",
            grocery=SimpleNamespace(extra_data={"kind": "tool"}),
        )
        self.assertTrue(is_store_run(milk))
        self.assertTrue(is_store_run(tp))
        self.assertTrue(is_store_run(aa))
        self.assertFalse(is_store_run(car))
        self.assertFalse(is_store_run(knife))
        self.assertTrue(is_auto_supply(car))
        self.assertFalse(is_auto_supply(milk))


class RoomSplitTests(unittest.TestCase):
    def test_sync_sums_and_picks_primary(self):
        from decimal import Decimal
        from types import SimpleNamespace

        from app.utils.places import rooms_map, sync_rooms

        g = SimpleNamespace(extra_data={}, quantity=Decimal("0"), default_location=None, is_in_stock=False)
        sync_rooms(g, {"Alice's room": 2, "Master": 1, "Grandma's": 1})
        self.assertEqual(int(g.quantity), 4)
        self.assertEqual(g.default_location, "Alice's room")
        self.assertEqual(int(rooms_map(g)["Master"]), 1)


if __name__ == "__main__":
    unittest.main()

