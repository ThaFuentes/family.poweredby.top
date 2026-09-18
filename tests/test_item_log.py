import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decimal import Decimal

from app.utils.item_log import mpg_of, _dec


class MpgTests(unittest.TestCase):
    def test_fillup_mpg(self):
        self.assertEqual(mpg_of(240, 12), 20.0)
        self.assertEqual(mpg_of(Decimal("310"), Decimal("10.5")), 29.5)

    def test_bad_gallons(self):
        self.assertIsNone(mpg_of(100, 0))
        self.assertIsNone(mpg_of(100, None))
        self.assertIsNone(mpg_of(None, 10))

    def test_money_parse(self):
        self.assertEqual(_dec("$42.50"), Decimal("42.50"))
        self.assertEqual(_dec("12.4"), Decimal("12.4"))
        self.assertIsNone(_dec(""))


if __name__ == "__main__":
    unittest.main()
