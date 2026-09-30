"""End-to-end 2FA + BOT-account flows against the live schema."""
from __future__ import annotations

import os
import re
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from app import create_app
from app.builddb.builddb import db
from app.builddb.table_users import User
from app.utils import twofa


class TwofaFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.suffix = os.urandom(3).hex()
        cls.secret = twofa.new_totp_secret()
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=80, days=30, label="twofa-tests").code

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()

    # ------------------------------------------------------------- helpers

    def _csrf(self) -> str:
        # "/" works logged in (home) and out (302 -> login); both carry the injected meta.
        r = self.client.get("/", follow_redirects=True)
        text = r.data.decode("utf-8", "replace")
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _post(self, url, data=None, **kw):
        payload = dict(data or {})
        payload.setdefault("csrf_token", self._csrf())
        return self.client.post(url, data=payload, **kw)

    def _uid_opt(self, username: str):
        with self.app.app_context():
            row = User.query.filter_by(username=username).first()
            return None if row is None else int(row.id)

    def _uid(self, username: str) -> int:
        uid = self._uid_opt(username)
        self.assertIsNotNone(uid, f"user {username} missing")
        return uid

    def _logged_in(self) -> bool:
        return self.client.get("/").status_code == 200

    def _register_founder(self):
        """Idempotent: the household exists across the class run."""
        self.client.get("/auth/logout")
        u = f"founder_{self.suffix}"
        r = self.client.post(
            "/auth/login",
            data={"username": u, "password": "FamilyTest1!"},
        )
        if self._logged_in():
            return u
        r = self.client.post(
            "/auth/register",
            data={
                "name": "Founder",
                "username": u,
                "email": f"{u}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"Twofa House {self.suffix}",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )
        self.assertTrue(self._logged_in(), r.data[-300:])
        return u

    def _add_bot(self):
        """Idempotent: create once, just verify after that."""
        u = f"bot_{self.suffix}"
        self._register_founder()
        if self._uid_opt(u) is None:
            r = self._post(
                "/members/add",
                data={
                    "person_name": "Bot Botson",
                    "username": u,
                    "email": f"{u}@family.test",
                    "role": "member",
                    "password": "BotPass123!",
                    "is_bot": "1",
                    "security_email": f"{u}.codes@family.test",
                    "reset_email": f"{u}.resets@family.test",
                },
                follow_redirects=True,
            )
            self.assertEqual(r.status_code, 200, r.data[-300:])
        with self.app.app_context():
            row = User.query.filter_by(username=u).first()
            self.assertIsNotNone(row)
            self.assertTrue(row.is_bot)
            self.assertEqual(row.security_email, f"{u}.codes@family.test")
            self.assertEqual(row.reset_email, f"{u}.resets@family.test")
        return u

    def _set_app_2fa(self, username):
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            twofa.save_twofa(user, method="app", secret=self.secret)
            db.session.commit()

    def _allow_totp_reuse(self, username):
        """Tests sign in twice within one 30s window; production refuses that."""
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            twofa.save_twofa(user, last_totp_step=-999)
            db.session.commit()

    def _plain_login(self, username, password):
        return self.client.post(
            "/auth/login", data={"username": username, "password": password}
        )

    def _totp_login(self, username, password):
        """Full password + authenticator-code sign-in."""
        self._allow_totp_reuse(username)
        r = self._plain_login(username, password)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/2fa", r.headers.get("Location", ""))
        r2 = self._post("/auth/2fa", data={"code": twofa.totp_at(self.secret)})
        self.assertEqual(r2.status_code, 302, r2.data[-300:])

    # --------------------------------------------------------------- tests

    def test_01_founder_not_bot_normal_home(self):
        u = self._register_founder()
        r = self._plain_login(u, "FamilyTest1!")
        # No 2FA for the founder: password alone signs straight in.
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("/auth/2fa", r.headers.get("Location", ""))
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotIn(b"BOT account", home.data)
        self.client.get("/auth/logout")

    def test_02_add_bot_marks_columns(self):
        self._register_founder()
        bot = self._add_bot()
        self.assertEqual(bot, f"bot_{self.suffix}")
        self.client.get("/auth/logout")

    def test_02b_bot_without_2fa_is_walled_until_setup(self):
        bot = self._add_bot()
        self.client.get("/auth/logout")
        r = self._plain_login(bot, "BotPass123!")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/bot-setup", r.headers.get("Location", ""))
        page = self.client.get("/auth/bot-setup")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"This bot needs 2FA", page.data)
        self.assertIn(b"house stays closed", page.data)
        notes = self.client.get("/notes/")
        self.assertEqual(notes.status_code, 302)
        self.assertIn("/auth/bot-setup", notes.headers.get("Location", ""))
        started = self._post(
            "/appearance/2fa/start",
            data={"next": "setup"},
            follow_redirects=True,
        )
        self.assertEqual(started.status_code, 200)
        self.assertIn(b"Scan this", started.data)
        with self.app.app_context():
            user = User.query.filter_by(username=bot).first()
            secret = twofa.twofa_settings(user).get("secret")
        self.assertTrue(secret)
        done = self._post(
            "/appearance/2fa/confirm",
            data={"code": twofa.totp_at(secret), "next": "setup"},
            follow_redirects=True,
        )
        self.assertEqual(done.status_code, 200, done.data[-400:])
        self.assertIn(b"Reset password", done.data)
        self.assertNotIn(b"house stays closed", done.data)
        self.client.get("/auth/logout")

    def test_02c_separate_reset_email_keeps_the_wall_up(self):
        bot = f"bot_{self.suffix}"
        self._add_bot()
        self._set_app_2fa(bot)
        with self.app.app_context():
            user = User.query.filter_by(username=bot).first()
            user.reset_email = None
            db.session.commit()
        try:
            self.client.get("/auth/logout")
            self._totp_login(bot, "BotPass123!")
            home = self.client.get("/")
            self.assertEqual(home.status_code, 302)
            self.assertIn("/auth/bot-setup", home.headers.get("Location", ""))
            page = self.client.get("/auth/bot-setup")
            self.assertIn(b"Reset inbox", page.data)
            same = self._post(
                "/appearance/security-email",
                data={
                    "security_email": f"{bot}.codes@family.test",
                    "reset_email": f"{bot}@family.test",
                    "next": "setup",
                },
                follow_redirects=True,
            )
            self.assertIn(b"not the login email", same.data)
            self.assertIn(b"/auth/bot-setup", same.request.path.encode())
            saved = self._post(
                "/appearance/security-email",
                data={
                    "security_email": f"{bot}.codes@family.test",
                    "reset_email": f"{bot}.resets@family.test",
                    "next": "setup",
                },
                follow_redirects=True,
            )
            self.assertEqual(saved.status_code, 200, saved.data[-400:])
            self.assertIn(b"Reset password", saved.data)
            self.assertNotIn(b"house stays closed", saved.data)
        finally:
            with self.app.app_context():
                user = User.query.filter_by(username=bot).first()
                if user is not None:
                    user.reset_email = f"{bot}.resets@family.test"
                    db.session.commit()
            self.client.get("/auth/logout")

    def test_02d_one_inbox_save_leaves_the_other(self):
        """Each People button posts one field. The other inbox must stay."""
        bot = self._add_bot()
        target_id = self._uid(bot)
        codes = f"{bot}.codes@family.test"
        resets = f"{bot}.resets@family.test"
        other_reset = f"{bot}.other@family.test"
        other_codes = f"{bot}.codes2@family.test"
        try:
            saved_reset = self._post(
                f"/members/{target_id}/security-email",
                data={"reset_email": other_reset},
                follow_redirects=True,
            )
            self.assertEqual(saved_reset.status_code, 200)
            self.assertIn(b"Reset inbox saved", saved_reset.data)
            with self.app.app_context():
                user = User.query.filter_by(id=target_id).first()
                self.assertEqual(user.security_email, codes)
                self.assertEqual(user.reset_email, other_reset)
            saved_codes = self._post(
                f"/members/{target_id}/security-email",
                data={"security_email": other_codes},
                follow_redirects=True,
            )
            self.assertEqual(saved_codes.status_code, 200)
            self.assertIn(b"2FA inbox saved", saved_codes.data)
            with self.app.app_context():
                user = User.query.filter_by(id=target_id).first()
                self.assertEqual(user.security_email, other_codes)
                self.assertEqual(user.reset_email, other_reset)
        finally:
            with self.app.app_context():
                user = User.query.filter_by(id=target_id).first()
                if user is not None:
                    user.security_email = codes
                    user.reset_email = resets
                    db.session.commit()
            self.client.get("/auth/logout")

    def test_03_totp_login_challenge_and_bot_dashboard(self):
        bot = f"bot_{self.suffix}"
        self._set_app_2fa(bot)

        # Password alone must NOT sign in — it lands on /auth/2fa.
        r = self._plain_login(bot, "BotPass123!")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/2fa", r.headers.get("Location", ""))
        page = self.client.get("/auth/2fa")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"authenticator", page.data)

        # Wrong code -> still not signed in.
        wrong = self._post("/auth/2fa", data={"code": "000000"})
        self.assertEqual(wrong.status_code, 200)
        self.assertIn(b"not right", wrong.data)

        # Right code -> signed in, bot dashboard.
        self._allow_totp_reuse(bot)
        r = self._plain_login(bot, "BotPass123!")
        code = twofa.totp_at(self.secret)
        ok = self._post("/auth/2fa", data={"code": code})
        self.assertEqual(ok.status_code, 302, ok.data[-300:])
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"BOT account", home.data)
        self.assertIn(b"Reset password", home.data)
        self.assertIn(b"twofa_code", home.data)

        # Replay of the same code in the same window is refused.
        self.client.get("/auth/logout")
        r = self._plain_login(bot, "BotPass123!")
        self.assertEqual(r.status_code, 302)
        replay = self._post("/auth/2fa", data={"code": code})
        self.assertIn(b"already used", replay.data)
        self.client.get("/auth/logout")

    def test_04_quick_reset_with_current_password(self):
        bot = f"bot_{self.suffix}"
        self._totp_login(bot, "BotPass123!")
        r = self._post(
            "/auth/bot/reset-password",
            data={
                "current_password": "BotPass123!",
                "new_password": "BotPass456!",
                "confirm_password": "BotPass456!",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Password updated", r.data)
        self.client.get("/auth/logout")
        # Old password is rejected outright at sign-in.
        r = self._plain_login(bot, "BotPass123!")
        self.assertEqual(r.status_code, 200)
        # New password goes through the 2FA challenge again.
        self._allow_totp_reuse(bot)
        r = self._plain_login(bot, "BotPass456!")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/2fa", r.headers.get("Location", ""))
        self.client.get("/auth/logout")

    def test_05_quick_reset_with_totp_code_instead_of_password(self):
        bot = f"bot_{self.suffix}"
        self.client.get("/auth/logout")
        self._totp_login(bot, "BotPass456!")
        # Simulate the next 30s window: the operator reads a fresh code.
        self._allow_totp_reuse(bot)
        r = self._post(
            "/auth/bot/reset-password",
            data={
                "current_password": "",
                "twofa_code": twofa.totp_at(self.secret),
                "new_password": "BotPass789!",
                "confirm_password": "BotPass789!",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Password updated", r.data)
        self.client.get("/auth/logout")

    def test_06_non_bot_cannot_use_bot_reset(self):
        founder = f"founder_{self.suffix}"
        self.client.get("/auth/logout")
        r = self._plain_login(founder, "FamilyTest1!")
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("/auth/2fa", r.headers.get("Location", ""))
        r = self.client.post(
            "/auth/bot/reset-password",
            data={
                "csrf_token": self._csrf(),
                "current_password": "FamilyTest1!",
                "new_password": "NopeNope9!",
                "confirm_password": "NopeNope9!",
            },
        )
        self.assertEqual(r.status_code, 403)
        self.client.get("/auth/logout")

    def test_07_email_code_login_to_security_inbox(self):
        bot = f"bot_{self.suffix}"
        with self.app.app_context():
            user = User.query.filter_by(username=bot).first()
            twofa.save_twofa(user, method="email")
            db.session.commit()
            user_id = int(user.id)

        sent = {}

        def fake_send(to, subject, body, **kw):
            sent["to"], sent["subject"], sent["body"] = to, subject, body
            return True, "ok"

        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            r = self._plain_login(bot, "BotPass789!")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/auth/2fa", r.headers.get("Location", ""))
            self.assertIn(f"{bot}.codes@family.test", sent.get("to", ""))
            self.assertIn("sign-in code", sent.get("subject", ""))
            page = self.client.get("/auth/2fa")
            self.assertIn(b"emailed", page.data)

            # Cooldown blocks instant resend.
            resend = self._post("/auth/2fa", data={"do": "resend"})
            self.assertIn(b"seconds", resend.data)

            m = re.search(r"code is (\d{6})", sent.get("body", ""))
            self.assertIsNotNone(m, sent.get("body", ""))
            ok = self._post("/auth/2fa", data={"code": m.group(1)})
            self.assertEqual(ok.status_code, 302, ok.data[-300:])
        home = self.client.get("/")
        self.assertIn(b"BOT account", home.data)
        self.client.get("/auth/logout")

        with self.app.app_context():
            user = User.query.filter_by(id=user_id).first()
            twofa.save_twofa(user, method="app", secret=self.secret)
            db.session.commit()

    def test_08_reset_link_goes_to_reset_inbox(self):
        bot = f"bot_{self.suffix}"
        sent = {}

        def fake_send(to, subject, body, **kw):
            sent["to"], sent["subject"] = to, subject
            return True, "ok"

        self.client.get("/auth/logout")
        # Forgot-password path (passwords.py imports send_mail at module level).
        with patch("app.utils.passwords.send_mail", side_effect=fake_send):
            r = self.client.post(
                "/auth/forgot",
                data={"username": bot, "household": ""},
                follow_redirects=True,
            )
            self.assertEqual(r.status_code, 200)
            self.assertIn(f"{bot}.resets@family.test", sent.get("to", ""), sent)

        # Leader "Send password reset" path.
        # founder has no 2FA: plain login works
        r = self._plain_login(f"founder_{self.suffix}", "FamilyTest1!")
        self.assertEqual(r.status_code, 302)
        target_id = self._uid(bot)
        with patch("app.utils.passwords.send_mail", side_effect=fake_send):
            r = self._post(f"/members/{target_id}/reset", follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn(f"{bot}.resets@family.test", sent.get("to", ""), sent)
        self.client.get("/auth/logout")

    def test_99_unmark_bot_clears_twofa(self):
        bot = f"bot_{self.suffix}"
        founder = f"founder_{self.suffix}"
        self.client.get("/auth/logout")
        r = self._plain_login(founder, "FamilyTest1!")
        self.assertEqual(r.status_code, 302)
        target_id = self._uid(bot)
        r = self._post(f"/members/{target_id}/bot", data={"is_bot": "0"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            user = User.query.filter_by(id=target_id).first()
            self.assertFalse(user.is_bot)
            self.assertEqual(twofa.twofa_method(user), "")
            self.assertFalse(twofa.twofa_enabled(user))
        self.client.get("/auth/logout")

    def test_10_look_page_has_twofa_card_and_qr(self):
        bot = f"bot_{self.suffix}"
        founder = f"founder_{self.suffix}"
        self.client.get("/auth/logout")
        # founder (regular account) never sees the card
        self._plain_login(founder, "FamilyTest1!")
        look = self.client.get("/appearance/")
        self.assertEqual(look.status_code, 200)
        self.assertNotIn(b"Two-factor sign-in", look.data)
        self.client.get("/auth/logout")
        # bot does
        with self.app.app_context():
            user = User.query.filter_by(username=bot).first()
            twofa.save_twofa(user, method="app", secret=self.secret)
            db.session.commit()
        self._totp_login(bot, "BotPass789!")
        look = self.client.get("/appearance/")
        self.assertEqual(look.status_code, 200)
        self.assertIn(b"Two-factor sign-in", look.data)
        self.assertIn(b"Security inboxes", look.data)
        self.client.get("/auth/logout")


if __name__ == "__main__":
    unittest.main()
