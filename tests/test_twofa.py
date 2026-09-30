import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import time
from types import SimpleNamespace

from app.utils import twofa


def _with_session(app=None):
    """Push a minimal request context so session works without a DB."""
    from flask import Flask, session

    app = app or Flask(__name__)
    app.secret_key = "test"
    return app.test_request_context("/")


class TotpTests(unittest.TestCase):
    def test_known_rfc_vector(self):
        # RFC 6238 appendix: secret "12345678901234567890", 59s -> 287082
        import base64

        secret = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")
        self.assertEqual(twofa.totp_at(secret, 59), "287082")

    def test_code_matches_now(self):
        secret = twofa.new_totp_secret()
        code = twofa.totp_at(secret)
        self.assertTrue(twofa.totp_ok(secret, code))

    def test_wrong_and_garbage_codes_fail(self):
        secret = twofa.new_totp_secret()
        self.assertFalse(twofa.totp_ok(secret, "000000"))
        self.assertFalse(twofa.totp_ok(secret, ""))
        self.assertFalse(twofa.totp_ok(secret, "abcdef"))
        self.assertFalse(twofa.totp_ok(secret, "12345"))

    def test_spacing_tolerated(self):
        secret = twofa.new_totp_secret()
        code = twofa.totp_at(secret)
        spaced = code[:3] + " " + code[3:]
        self.assertTrue(twofa.totp_ok(secret, spaced))

    def test_otpauth_url_shape(self):
        url = twofa.otpauth_url("ABC234", "bot@fuentes")
        self.assertTrue(url.startswith("otpauth://totp/Family%20OS:"))
        self.assertIn("secret=ABC234", url)
        self.assertIn("digits=6", url)
        self.assertIn("period=30", url)


class EmailCodeTests(unittest.TestCase):
    def test_code_is_six_digits_and_hash_bound(self):
        code, code_hash = twofa.new_email_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertNotEqual(code, code_hash)
        pending = {"code_hash": code_hash, "code_sent_at": time.time()}
        self.assertTrue(twofa.email_code_ok(pending, code))
        self.assertFalse(twofa.email_code_ok(pending, "000000" if code != "000000" else "000001"))

    def test_expired_code_fails(self):
        code, code_hash = twofa.new_email_code()
        pending = {"code_hash": code_hash, "code_sent_at": time.time() - twofa.EMAIL_CODE_TTL_SECONDS - 5}
        self.assertFalse(twofa.email_code_ok(pending, code))

    def test_no_timestamp_fails(self):
        code, code_hash = twofa.new_email_code()
        self.assertFalse(twofa.email_code_ok({"code_hash": code_hash}, code))


class InboxTests(unittest.TestCase):
    def test_security_email_wins_for_2fa(self):
        user = SimpleNamespace(
            email="bot@x.test", security_email="codes@y.test", reset_email="resets@z.test"
        )
        self.assertEqual(twofa.twofa_inbox_for(user), "codes@y.test")
        self.assertEqual(twofa.reset_inbox_for(user), "resets@z.test")

    def test_fallback_to_login_email(self):
        user = SimpleNamespace(email="bot@x.test", security_email=None, reset_email=None)
        self.assertEqual(twofa.twofa_inbox_for(user), "bot@x.test")
        self.assertEqual(twofa.reset_inbox_for(user), "bot@x.test")

    def test_separate_inboxes_can_differ(self):
        user = SimpleNamespace(email="bot@x.test", security_email="a@b.test", reset_email=None)
        self.assertNotEqual(twofa.twofa_inbox_for(user), twofa.reset_inbox_for(user))


class MethodTests(unittest.TestCase):
    def _user(self, blob=None, is_bot=True):
        return SimpleNamespace(extra_data=blob, is_bot=is_bot)

    def test_off_by_default(self):
        user = self._user(None)
        self.assertEqual(twofa.twofa_method(user), "")
        self.assertFalse(twofa.twofa_enabled(user))

    def test_non_bot_never_counts_as_enabled(self):
        user = self._user({"twofa": {"method": "app", "secret": twofa.new_totp_secret()}}, is_bot=False)
        self.assertFalse(twofa.twofa_enabled(user))

    def test_app_needs_secret(self):
        user = self._user({"twofa": {"method": "app"}})
        self.assertEqual(twofa.twofa_method(user), "app")
        self.assertFalse(twofa.twofa_enabled(user))
        user = self._user({"twofa": {"method": "app", "secret": twofa.new_totp_secret()}})
        self.assertTrue(twofa.twofa_enabled(user))

    def test_email_needs_inbox(self):
        user = self._user({"twofa": {"method": "email"}})
        user.security_email = None
        user.email = None
        self.assertFalse(twofa.twofa_enabled(user))
        user.email = "bot@x.test"
        self.assertTrue(twofa.twofa_enabled(user))

    def test_bot_setup_wall(self):
        user = self._user(None)
        user.email = "bot@x.test"
        user.security_email = None
        user.reset_email = None
        self.assertEqual(twofa.bot_setup_remaining(user), ["twofa", "reset_email"])
        user.reset_email = "bot@x.test"
        self.assertEqual(twofa.bot_setup_remaining(user), ["twofa", "reset_email"])
        user.extra_data = {"twofa": {"method": "app", "secret": twofa.new_totp_secret()}}
        self.assertEqual(twofa.bot_setup_remaining(user), ["reset_email"])
        user.reset_email = "resets@x.test"
        self.assertEqual(twofa.bot_setup_remaining(user), [])
        user.extra_data = {"twofa": {"method": "email"}}
        self.assertEqual(twofa.bot_setup_remaining(user), [])
        user.is_bot = False
        user.reset_email = None
        user.extra_data = None
        self.assertEqual(twofa.bot_setup_remaining(user), [])
        self.assertTrue(twofa.bot_setup_path_ok("/auth/bot-setup"))
        self.assertTrue(twofa.bot_setup_path_ok("/appearance/2fa/qr.png"))
        self.assertFalse(twofa.bot_setup_path_ok("/"))
        self.assertFalse(twofa.bot_setup_path_ok("/notes/"))


class PendingTests(unittest.TestCase):
    def test_stash_and_pop(self):
        with _with_session():
            twofa.stash_pending_login(7, "app")
            pending = twofa.pending_login()
            self.assertEqual(pending["user_id"], 7)
            self.assertEqual(pending["method"], "app")
            self.assertEqual(twofa.pop_pending_login()["user_id"], 7)
            self.assertIsNone(twofa.pending_login())

    def test_fail_lockout(self):
        with _with_session():
            twofa.stash_pending_login(3, "email")
            pending = twofa.pending_login()
            fails = 0
            for _ in range(twofa.LOCK_AFTER_FAILS):
                fails = twofa.register_pending_fail(pending)
            self.assertEqual(fails, twofa.LOCK_AFTER_FAILS)
            self.assertIsNone(twofa.pending_login())


class ReplayTests(unittest.TestCase):
    def test_same_code_twice_is_replay_then_fresh(self):
        secret = twofa.new_totp_secret()
        code = twofa.totp_at(secret)

        class U(SimpleNamespace):
            pass

        user = U(extra_data={"twofa": {"method": "app", "secret": secret}}, is_bot=True)
        self.assertFalse(twofa.totp_replay_recent(user, code))
        twofa.mark_totp_used(user, code)
        self.assertTrue(twofa.totp_replay_recent(user, code))
        # a different code in the same window is not the replayed one
        other = "000000" if code != "000000" else "000001"
        self.assertFalse(twofa.totp_replay_recent(user, other))


if __name__ == "__main__":
    unittest.main()
