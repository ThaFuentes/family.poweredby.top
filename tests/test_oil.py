import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.oil import apply_tool_oil, apply_vehicle_oil, fields_from_text


class OilTests(unittest.TestCase):
    def test_vehicle_next_comes_from_the_interval(self):
        v = SimpleNamespace(
            oil_needs=None,
            oil_capacity=None,
            oil_type=None,
            filter_type=None,
            last_oil_change_date=None,
            last_oil_change_mileage=None,
            oil_interval_miles=None,
            oil_interval_months=None,
            next_oil_due_date=None,
            next_oil_due_mileage=None,
        )
        apply_vehicle_oil(
            v,
            {
                "needs": "5W-30 full synthetic, API SP",
                "capacity": "6 qt",
                "in_it": "Mobil 1 5W-30",
                "last_date": "2026-03-01",
                "last_miles": "80000",
                "interval_miles": "5000",
                "interval_months": "6",
            },
        )
        self.assertEqual(v.oil_needs, "5W-30 full synthetic, API SP")
        self.assertEqual(v.oil_type, "Mobil 1 5W-30")
        self.assertEqual(v.next_oil_due_date, date(2026, 9, 1))
        self.assertEqual(v.next_oil_due_mileage, 85000)

    def test_blank_does_not_wipe_when_ask_sends_one_field(self):
        v = SimpleNamespace(
            oil_needs="5W-30",
            oil_capacity="6 qt",
            oil_type="Mobil 1",
            filter_type=None,
            last_oil_change_date=date(2026, 1, 1),
            last_oil_change_mileage=1000,
            oil_interval_miles=5000,
            oil_interval_months=None,
            next_oil_due_date=None,
            next_oil_due_mileage=None,
        )
        apply_vehicle_oil(v, {"in_it": "Castrol 5W-30"}, clear=False)
        self.assertEqual(v.oil_needs, "5W-30")
        self.assertEqual(v.oil_type, "Castrol 5W-30")
        self.assertEqual(v.next_oil_due_mileage, 6000)

    def test_sentence_fills_the_form_fields(self):
        parsed = fields_from_text("Use 5W-30 full synthetic, about 6 quarts, every 5000 miles.")
        self.assertIn("5W-30", parsed["needs"])
        self.assertEqual(parsed["capacity"], "6 qt")
        self.assertEqual(parsed["interval_miles"], "5000")

    def test_tool_hours(self):
        t = SimpleNamespace(
            oil_needs=None,
            oil_capacity=None,
            oil_type=None,
            last_oil_date=None,
            last_oil_hours=None,
            oil_interval_hours=None,
            oil_interval_months=None,
            next_oil_due_date=None,
            next_oil_due_hours=None,
        )
        apply_tool_oil(t, {"needs": "SAE 30", "last_hours": "20", "interval_hours": "25"})
        self.assertEqual(t.oil_needs, "SAE 30")
        self.assertEqual(t.next_oil_due_hours, 45)


if __name__ == "__main__":
    unittest.main()
