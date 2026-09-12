import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from types import SimpleNamespace

from app.utils.access import (
    family_code_variants,
    family_invite_ok,
    normalize_code,
    revoke_key_by_code,
    service_code_variants,
)


class AccessCodeTests(unittest.TestCase):
    def test_family_prefix(self):
        self.assertIn("FAM-ABC12", family_code_variants("fam-abc12"))
        self.assertIn("ABC12", family_code_variants("FAM-ABC12"))
        self.assertIn("FAM-OLDCODE", family_code_variants("OLDCODE"))

    def test_service_prefix(self):
        self.assertEqual(service_code_variants("SRV-HELLO1")[0], "SRV-HELLO1")
        self.assertIn("SRV-HELLO1", service_code_variants("hello1"))
        self.assertNotIn("SRV-FAM-X", service_code_variants("FAM-X"))

    def test_normalize_strips(self):
        self.assertEqual(normalize_code("  srv-ab  "), "SRV-AB")

    def test_revoked_family_key_rejected(self):
        from datetime import datetime

        inv = SimpleNamespace(revoked_at=datetime.utcnow(), used_at=None)
        ok, msg = family_invite_ok(inv)
        self.assertFalse(ok)
        self.assertIn("revoked", msg.lower())

    def test_revoke_blank_code(self):
        ok, msg, kind = revoke_key_by_code("   ")
        self.assertFalse(ok)
        self.assertEqual(kind, "")
        self.assertIn("Paste", msg)


if __name__ == "__main__":
    unittest.main()
