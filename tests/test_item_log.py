import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from decimal import Decimal

from datetime import date

from app.utils.item_log import mpg_of, year_driven, _dec
from app.utils.dtc import parse_dtcs, normalize_dtc, lookup_dtc
from app.utils.stash_image import _MIME_EXT, _SKIP_SLOTS, commons_thumb_url


class MpgTests(unittest.TestCase):
    def test_fillup_mpg(self):
        self.assertEqual(mpg_of(240, 12), 20.0)
        self.assertEqual(mpg_of(Decimal("310"), Decimal("10.5")), 29.5)

    def test_ytd_miles_from_snapshots(self):
        snaps = [
            (date(2025, 12, 20), 80000),
            (date(2026, 3, 1), 82000),
            (date(2026, 9, 1), 86000),
        ]
        self.assertEqual(year_driven(snaps, 2026, 87432), 7432)

    def test_bad_gallons(self):
        self.assertIsNone(mpg_of(100, 0))
        self.assertIsNone(mpg_of(100, None))
        self.assertIsNone(mpg_of(None, 10))

    def test_money_parse(self):
        self.assertEqual(_dec("$42.50"), Decimal("42.50"))
        self.assertEqual(_dec("12.4"), Decimal("12.4"))
        self.assertIsNone(_dec(""))


class DtcTests(unittest.TestCase):
    def test_parse_several(self):
        self.assertEqual(parse_dtcs("p0420, P0171 and u0100"), ["P0420", "P0171", "U0100"])

    def test_normalize(self):
        self.assertEqual(normalize_dtc("p0420"), "P0420")
        self.assertIsNone(normalize_dtc("check engine"))

    def test_fallback_without_ai(self):
        hit = lookup_dtc("P0420", household=None)
        self.assertEqual(hit["code"], "P0420")
        self.assertIn("Catalyst", hit["meaning"])
        self.assertFalse(hit["used_ai"])


class PhotoBytesTests(unittest.TestCase):
    def test_roundtrip_and_empty_on_bad_key(self):
        from app.utils import crypto

        crypto._fernet = None
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        wrapped = crypto.encrypt_bytes(png)
        self.assertTrue(wrapped.startswith(crypto._FILE_MAGIC))
        self.assertEqual(crypto.decrypt_bytes(wrapped), png)


class StashImageTests(unittest.TestCase):
    def test_jpeg_mapped(self):
        self.assertEqual(_MIME_EXT["image/jpeg"], ".jpg")
        self.assertIn("image/png", _MIME_EXT)

    def test_skip_misc_slot(self):
        self.assertIn("misc", _SKIP_SLOTS)

    def test_commons_rejects_short_query(self):
        self.assertIsNone(commons_thumb_url("ab"))


if __name__ == "__main__":
    unittest.main()
