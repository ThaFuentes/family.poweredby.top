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


if __name__ == "__main__":
    unittest.main()
