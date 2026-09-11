import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decimal import Decimal

from app.utils.vehicle_systems import (
    guess_slot,
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


if __name__ == "__main__":
    unittest.main()
