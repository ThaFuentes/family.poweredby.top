import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from types import SimpleNamespace

from app.utils.household_mail import invite_email_body, random_login_password
from app.utils.household_vault import (
    FORMAT_HINT,
    parse_lock,
    normalize_lock,
    vault_blob,
    vault_enabled,
)


class LockFormatTests(unittest.TestCase):
    def test_famos_phrase(self):
        parsed = parse_lock("FAMOS-ourphrase")
        self.assertEqual(parsed, ("FAMOS", "ourphrase"))
        self.assertEqual(normalize_lock("FAMOS-ourphrase"), "FAMOS-ourphrase")

    def test_rejects_short_secret(self):
        self.assertIsNone(parse_lock("FAMOS-ab"))
        self.assertIsNone(parse_lock("FAM-ourphrase"))
        self.assertIsNone(parse_lock("FAMOSourphrase"))
        self.assertIsNone(parse_lock(""))

    def test_strips(self):
        self.assertEqual(parse_lock("  FAMOS-family1  "), ("FAMOS", "family1"))


class VaultBlobTests(unittest.TestCase):
    def test_missing_is_off(self):
        h = SimpleNamespace(settings_json=None)
        self.assertFalse(vault_enabled(h))
        self.assertEqual(vault_blob(h), {})

    def test_enabled_flag(self):
        h = SimpleNamespace(settings_json={"vault": {"enabled": True, "salt": "ab"}})
        self.assertTrue(vault_enabled(h))


class InviteCopyTests(unittest.TestCase):
    def test_body_has_key_and_optional_login(self):
        house = SimpleNamespace(name="Fuentes house", handle="fuentes")
        body = invite_email_body(
            household=house,
            code="FAM-ABC12",
            role="member",
            register_url="https://family.example/auth/register?family=FAM-ABC12",
            login_url="https://family.example/auth/login",
            username="maya",
            password="Fam-secret1",
            lock="FAMOS-ourphrase",
            person_name="Maya",
        )
        self.assertIn("FAM-ABC12", body)
        self.assertIn("maya", body)
        self.assertIn("Fam-secret1", body)
        self.assertIn("FAMOS-ourphrase", body)
        self.assertIn("fuentes", body)

    def test_password_shape(self):
        p = random_login_password()
        self.assertTrue(p.startswith("Fam-"))
        self.assertGreaterEqual(len(p), 8)


class DashboardPrefsTests(unittest.TestCase):
    def test_adult_defaults_home(self):
        from app.utils.dashboard import dashboard_prefs, default_start

        user = SimpleNamespace(role="admin", extra_data=None)
        self.assertEqual(default_start(user), "home")
        prefs = dashboard_prefs(user)
        self.assertEqual(prefs["start"], "home")
        self.assertIn("scan", prefs["tile_set"])
        self.assertIn("vault", prefs["tile_set"])
        self.assertTrue(prefs["show_needs"])

    def test_child_defaults_scan(self):
        from app.utils.dashboard import dashboard_prefs

        user = SimpleNamespace(role="child", extra_data=None)
        prefs = dashboard_prefs(user)
        self.assertEqual(prefs["start"], "scan")
        self.assertNotIn("legal", prefs["tile_set"])
        self.assertNotIn("vault", prefs["tile_set"])

    def test_saved_start(self):
        from app.utils.dashboard import dashboard_prefs

        user = SimpleNamespace(
            role="member",
            extra_data={"dashboard": {"start": "basket", "tiles": ["scan", "basket"], "show_needs": False}},
        )
        prefs = dashboard_prefs(user)
        self.assertEqual(prefs["start"], "basket")
        self.assertEqual(prefs["tiles"], ["scan", "basket"])
        self.assertFalse(prefs["show_needs"])


if __name__ == "__main__":
    unittest.main()
