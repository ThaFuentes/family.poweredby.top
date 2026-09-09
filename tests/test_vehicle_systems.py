import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.vehicle_systems import guess_slot, valid_slot, valid_system


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


if __name__ == "__main__":
    unittest.main()
