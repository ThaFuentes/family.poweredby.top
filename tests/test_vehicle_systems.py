import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decimal import Decimal

from datetime import date
from types import SimpleNamespace

from app.utils.vehicle_systems import (
    fmt_day,
    guess_slot,
    group_parts,
    overview_on_it,
    parse_cost,
    systems_payload,
    valid_slot,
    valid_system,
)


class VehicleSystemTests(unittest.TestCase):
    def test_battery_slot(self):
        self.assertEqual(guess_slot("car_battery", "DieHard Gold"), ("electrical", "battery"))

    def test_oil_slot(self):
        self.assertEqual(guess_slot("motor_oil", "Mobil 1 5W-30"), ("engine", "oil"))

    def test_alternator_from_name(self):
        self.assertEqual(guess_slot("auto_part", "Motorcraft alternator 130A"), ("electrical", "alternator"))

    def test_cabin_filter(self):
        self.assertEqual(guess_slot("filter", "Cabin air filter"), ("hvac", "cabin_filter"))

    def test_valid_defaults(self):
        self.assertEqual(valid_system("nope"), "other")
        self.assertEqual(valid_slot("electrical", "battery"), "battery")
        self.assertEqual(valid_slot("electrical", "bogus"), "battery")
        self.assertEqual(valid_system("electronics"), "electronics")
        self.assertEqual(valid_slot("electronics", "radio"), "radio")
        self.assertEqual(valid_slot("body", "bumper"), "bumper")
        self.assertEqual(valid_slot("cooling", "radiator"), "radiator")

    def test_catalog_has_body_and_electronics(self):
        ids = [s["id"] for s in systems_payload()]
        self.assertIn("body", ids)
        self.assertIn("electronics", ids)
        self.assertIn("electrical", ids)
        self.assertIn("cooling", ids)
        elec = next(s for s in systems_payload() if s["id"] == "electronics")
        slot_ids = [x["id"] for x in elec["slots"]]
        self.assertIn("radio", slot_ids)
        self.assertIn("cameras", slot_ids)

    def test_cost_and_radio_guess(self):
        self.assertEqual(parse_cost("$89.50"), Decimal("89.50"))
        self.assertIsNone(parse_cost(""))
        self.assertEqual(guess_slot("auto_part", "Pioneer radio"), ("electronics", "radio"))

    def test_fmt_day(self):
        self.assertEqual(fmt_day(date(2026, 9, 12)), "Sep 12")
        self.assertEqual(fmt_day(None), "")

    def test_overview_keeps_three_newest(self):
        parts = [
            SimpleNamespace(
                system="electrical",
                slot="battery",
                name="Old battery",
                status="installed",
                is_current=True,
                installed_on=date(2024, 1, 1),
                created_at=None,
                replaced_id=None,
            ),
            SimpleNamespace(
                system="electrical",
                slot="alternator",
                name="Denso",
                status="installed",
                is_current=True,
                installed_on=date(2026, 9, 12),
                created_at=None,
                replaced_id=None,
            ),
            SimpleNamespace(
                system="cooling",
                slot="radiator",
                name="Spectra",
                status="installed",
                is_current=True,
                installed_on=date(2026, 8, 1),
                created_at=None,
                replaced_id=None,
            ),
            SimpleNamespace(
                system="engine",
                slot="oil",
                name="Oil",
                status="retired",
                is_current=False,
                installed_on=date(2020, 1, 1),
                created_at=None,
                replaced_id=None,
            ),
        ]
        grouped = group_parts(parts)
        elec = next(s for s in grouped if s["id"] == "electrical")
        self.assertEqual(elec["newest"].name, "Denso")
        self.assertEqual(elec["count"], 2)
        rows, total = overview_on_it(grouped, limit=3)
        names = [r["part"].name for r in rows]
        self.assertEqual(names[0], "Denso")
        self.assertIn("Spectra", names)
        self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
