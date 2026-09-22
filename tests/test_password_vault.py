import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.password_vault import (
    REAUTH_SECONDS,
    can_manage_entry,
    can_view_entry,
    confirm_app_login,
    decrypt_vault_text,
    encrypt_vault_text,
    grant_is_live,
    grant_status,
    href_for,
    open_fields,
    parse_duration,
    remaining_text,
    seal_fields,
    share_label,
    site_label,
)


def _user(**kwargs):
    defaults = dict(
        id=1,
        household_id=9,
        role="member",
        is_admin=False,
        is_leader=False,
        is_authenticated=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _entry(**kwargs):
    defaults = dict(
        id=1,
        household_id=9,
        created_by=1,
        share_mode="personal",
        grants=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class EncryptTests(unittest.TestCase):
    def test_roundtrip_all_fields(self):
        hid = 77
        fields = {
            "title": "Aminos AI Bots",
            "login": "dad@house.test",
            "secret": "S3cret-Netflix!",
            "url": "https://aminos.example",
            "purpose": "Work bots",
            "details": "Recovery is the house Gmail",
            "phone": "555-0100",
            "account_no": "A-441",
            "two_factor": "app",
            "two_factor_detail": "Pat's phone",
            "call_info": "PIN 9921, account under dad",
        }
        sealed = seal_fields(fields, hid)
        for key, plain in fields.items():
            self.assertNotEqual(sealed[key], plain)
            self.assertFalse(plain in sealed[key])
            self.assertTrue(sealed[key].startswith("gAAAAA"))
            self.assertEqual(decrypt_vault_text(sealed[key], hid), plain)

    def test_empty_still_ciphertext(self):
        blob = encrypt_vault_text("", 3)
        self.assertTrue(blob.startswith("gAAAAA"))
        self.assertEqual(decrypt_vault_text(blob, 3), "")

    def test_households_do_not_share_keys(self):
        token = encrypt_vault_text("Netflix-Pass", 11)
        self.assertNotEqual(decrypt_vault_text(token, 12), "Netflix-Pass")
        self.assertEqual(decrypt_vault_text(token, 11), "Netflix-Pass")

    def test_open_fields_reads_row(self):
        hid = 4
        row = SimpleNamespace(
            household_id=hid,
            title=encrypt_vault_text("Water bill", hid),
            login=encrypt_vault_text("city@water", hid),
            secret=encrypt_vault_text("pipe-99", hid),
            url=encrypt_vault_text("water.city.gov", hid),
            purpose=encrypt_vault_text("Utilities", hid),
            details=encrypt_vault_text("Account 441", hid),
        )
        opened = open_fields(row)
        self.assertEqual(opened["title"], "Water bill")
        self.assertEqual(opened["secret"], "pipe-99")
        self.assertEqual(opened["url"], "water.city.gov")


class AccessTests(unittest.TestCase):
    def test_creator_sees_personal(self):
        owner = _user(id=1, role="admin", is_admin=True, is_leader=True)
        row = _entry(created_by=1, share_mode="personal")
        self.assertTrue(can_view_entry(row, owner))
        self.assertTrue(can_manage_entry(row, owner))

    def test_other_member_misses_personal(self):
        owner_row = _entry(created_by=1, share_mode="personal")
        other = _user(id=2, role="member")
        self.assertFalse(can_view_entry(owner_row, other))
        self.assertFalse(can_manage_entry(owner_row, other))

    def test_household_share_is_visible(self):
        row = _entry(created_by=1, share_mode="household")
        member = _user(id=2, role="member")
        self.assertTrue(can_view_entry(row, member))
        self.assertFalse(can_manage_entry(row, member))

    def test_selected_until_expiry(self):
        live = SimpleNamespace(user_id=2, expires_at=datetime.utcnow() + timedelta(hours=2), revoked_at=None)
        dead = SimpleNamespace(user_id=2, expires_at=datetime.utcnow() - timedelta(minutes=1), revoked_at=None)
        row = _entry(created_by=1, share_mode="selected", grants=[live])
        member = _user(id=2)
        self.assertTrue(can_view_entry(row, member))
        row.grants = [dead]
        self.assertFalse(can_view_entry(row, member))
        self.assertTrue(grant_is_live(live))
        self.assertFalse(grant_is_live(dead))
        self.assertEqual(grant_status(dead), "ended")
        self.assertIn("ended", remaining_text(dead))

    def test_revoked_is_dead_even_with_time_left(self):
        g = SimpleNamespace(
            user_id=2,
            expires_at=datetime.utcnow() + timedelta(hours=4),
            revoked_at=datetime.utcnow(),
        )
        row = _entry(created_by=1, share_mode="selected", grants=[g])
        member = _user(id=2)
        self.assertFalse(grant_is_live(g))
        self.assertFalse(can_view_entry(row, member))
        self.assertEqual(grant_status(g), "revoked")
        self.assertIn("taken back", remaining_text(g))

    def test_remaining_text_hours(self):
        g = SimpleNamespace(
            user_id=2,
            expires_at=datetime.utcnow() + timedelta(hours=1, minutes=5),
            revoked_at=None,
        )
        text = remaining_text(g)
        self.assertIn("left", text)
        self.assertNotEqual(text, "1 hour")
        forever = SimpleNamespace(user_id=2, expires_at=None, revoked_at=None)
        self.assertIn("no end", remaining_text(forever))

    def test_child_never(self):
        row = _entry(share_mode="household")
        kid = _user(id=8, role="child")
        self.assertFalse(can_view_entry(row, kid))
        self.assertFalse(can_manage_entry(row, kid))

    def test_other_household_blocked(self):
        row = _entry(household_id=9, share_mode="household")
        stranger = _user(id=9, household_id=99, role="admin", is_admin=True)
        self.assertFalse(can_view_entry(row, stranger))

    def test_leader_can_manage_not_auto_see_personal(self):
        row = _entry(created_by=2, share_mode="personal")
        leader = _user(id=1, role="admin", is_admin=True, is_leader=True)
        self.assertFalse(can_view_entry(row, leader))
        self.assertTrue(can_manage_entry(row, leader))


class FullLoginTests(unittest.TestCase):
    def _pat(self):
        return _user(
            username="pat",
            email="pat@house.test",
            check_password=lambda p: p == "FamilyTest1!",
        )

    def test_username_and_password_open(self):
        self.assertTrue(
            confirm_app_login(
                self._pat(),
                username="pat",
                password="FamilyTest1!",
            )
        )

    def test_password_alone_fails(self):
        self.assertFalse(
            confirm_app_login(
                self._pat(),
                username="",
                password="FamilyTest1!",
            )
        )

    def test_wrong_user_fails(self):
        self.assertFalse(
            confirm_app_login(
                self._pat(),
                username="maya",
                password="FamilyTest1!",
            )
        )

    def test_wrong_password_fails(self):
        self.assertFalse(
            confirm_app_login(
                self._pat(),
                username="pat",
                password="nope",
            )
        )


class HelperTests(unittest.TestCase):
    def test_idle_window_lets_them_write(self):
        self.assertGreaterEqual(REAUTH_SECONDS, 45 * 60)

    def test_href(self):
        self.assertEqual(href_for("https://netflix.com"), "https://netflix.com")
        self.assertEqual(href_for("netflix.com"), "https://netflix.com")
        self.assertEqual(href_for(""), "")

    def test_site_label(self):
        self.assertEqual(site_label("https://www.netflix.com/browse"), "netflix.com")
        self.assertEqual(site_label("netflix.com"), "netflix.com")
        self.assertEqual(site_label(""), "")

    def test_share_label(self):
        self.assertEqual(share_label("household"), "Whole household")
        self.assertEqual(share_label("selected"), "These people")

    def test_parse_duration_forever(self):
        self.assertIsNone(parse_duration("forever"))
        when = parse_duration("1h")
        self.assertIsNotNone(when)
        delta = when - datetime.utcnow()
        self.assertGreater(delta.total_seconds(), 50 * 60)
        self.assertLess(delta.total_seconds(), 70 * 60)


class VaultHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(ROOT)
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.suffix = os.urandom(3).hex()
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=20, days=30, label="vault-tests").code

    def _csrf(self, html):
        import re

        text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _logout(self):
        self.client.get("/auth/logout", follow_redirects=True)

    def _register(self, username, household=None, invite="", name=None):
        self._logout()
        r = self.client.get("/auth/register")
        if r.status_code == 302:
            self._logout()
            r = self.client.get("/auth/register")
        data = {
            "name": name or username,
            "username": username,
            "email": f"{username}@family.test",
            "password": "FamilyTest1!",
            "household_name": household or "",
            "family_key": invite,
            "invite_code": invite,
            "service_key": "" if invite else self.service_key,
        }
        return self.client.post("/auth/register", data=data, follow_redirects=True)

    def _unlock(self, username):
        page = self.client.get("/vault/")
        token = self._csrf(page.data)
        return self.client.post(
            "/vault/unlock",
            data={
                "username": username,
                "password": "FamilyTest1!",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )

    def test_reauth_and_encryption_and_share(self):
        import re

        admin = f"vault_a_{self.suffix}"
        member = f"vault_m_{self.suffix}"
        kid = f"vault_k_{self.suffix}"
        self._register(admin, household=f"Vault {self.suffix}", name="Pat")
        locked = self.client.get("/vault/")
        self.assertEqual(locked.status_code, 200)
        self.assertIn(b"Open vault", locked.data)
        self.assertNotIn(b"Household handle", locked.data)
        self.assertNotIn(b"Netflix house", locked.data)

        token = self._csrf(locked.data)
        pw_only = self.client.post(
            "/vault/unlock",
            data={"password": "FamilyTest1!", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertIn(b"not this login", pw_only.data)
        self.assertNotIn(b"New login", pw_only.data)
        token = self._csrf(pw_only.data)
        opened = self._unlock(admin)
        self.assertEqual(opened.status_code, 200)
        self.assertIn(b"Add a login", opened.data)
        self.assertIn(b"Stays open while you use it", opened.data)
        self.assertNotIn(b'name="secret"', opened.data)
        token = self._csrf(opened.data)
        stay = self.client.post(
            "/vault/stay",
            data={"csrf_token": token},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(stay.status_code, 200)
        self.assertTrue(stay.get_json().get("ok"))
        token = self._csrf(opened.data)
        added = self.client.post(
            "/vault/add",
            data={
                "title": "Netflix house",
                "login": "family@house.test",
                "secret": "WatchIt-99",
                "url": "https://netflix.com",
                "purpose": "Streaming",
                "details": "Kids profile is the fourth one",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(added.status_code, 200, added.data[-400:])
        self.assertIn(b"Netflix house", added.data)
        self.assertIn(b"Add a login", added.data)
        self.assertNotIn(b"WatchIt-99", added.data)

        with self.app.app_context():
            from app.builddb.table_vault_entries import VaultEntry

            row = VaultEntry.query.order_by(VaultEntry.id.desc()).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.share_mode, "personal")
            self.assertNotEqual(row.title, "Netflix house")
            self.assertNotIn("WatchIt-99", row.secret or "")
            self.assertNotIn("family@house.test", row.login or "")
            self.assertNotIn("netflix.com", (row.url or "").lower())
            self.assertTrue((row.title or "").startswith("gAAAAA"))
            netflix_id = row.id
        sheet = self.client.get(f"/vault/{netflix_id}")
        self.assertEqual(sheet.status_code, 200)
        self.assertIn(b"family@house.test", sheet.data)
        self.assertIn(b"WatchIt-99", sheet.data)
        self.assertIn(b"Kids profile is the fourth one", sheet.data)
        self.assertIn(b"Open site", sheet.data)
        self.assertIn(b"Who can see it", sheet.data)
        self.assertIn(b"Edit this", sheet.data)
        self.assertIn(b"Two-factor", sheet.data)
        self.assertIn(b"Password / login", sheet.data)
        self.assertIn(b"Passwords", opened.data)
        self.assertIn(b"Billing", opened.data)
        self.assertIn(b"Shareable", opened.data)
        self.assertIn("no-store", sheet.headers.get("Cache-Control", ""))
        token = self._csrf(sheet.data)
        shared = self.client.post(
            f"/vault/{netflix_id}/share",
            data={"share_mode": "household", "next": "sheet", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(shared.status_code, 200)
        self.assertIn(b"Whole household", shared.data)
        self.assertIn(b"family@house.test", shared.data)

        page = self.client.get("/members/")
        token = self._csrf(page.data)
        inv = self.client.post(
            "/members/invite",
            data={
                "role": "member",
                "label": "Spouse",
                "csrf_token": token,
                "next": "sheet",
                "panel": "keys",
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        m = re.search(r"Family key ([A-Z0-9-]+)", inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(m, inv.data[-800:])
        self._register(member, invite=m.group(1), name="Spouse")
        member_locked = self.client.get("/vault/")
        self.assertEqual(member_locked.status_code, 200)
        self.assertNotIn(b"WatchIt-99", member_locked.data)
        member_open = self._unlock(member)
        self.assertIn(b"Netflix house", member_open.data)

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": admin, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        self._unlock(admin)
        token = self._csrf(self.client.get("/vault/").data)
        with self.app.app_context():
            from app.builddb.table_users import User

            spouse = User.query.filter_by(username=member).first()
            self.assertIsNotNone(spouse)
            spouse_id = spouse.id
        water = self.client.post(
            "/vault/add",
            data={
                "title": "Water bill",
                "login": "water-user",
                "secret": "Pipe-Secret",
                "purpose": "City utilities",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(water.status_code, 200)
        self.assertIn(b"Water bill", water.data)
        with self.app.app_context():
            from app.builddb.table_vault_entries import VaultEntry

            water_row = VaultEntry.query.order_by(VaultEntry.id.desc()).first()
            self.assertEqual(water_row.share_mode, "personal")
            water_id = water_row.id
        token = self._csrf(water.data)
        water_share = self.client.post(
            f"/vault/{water_id}/grant",
            data={
                "person": str(spouse_id),
                "for": "1h",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(water_share.status_code, 200)
        self.assertIn(b"These people", water_share.data)
        self.assertIn(b"Spouse", water_share.data)
        self.assertIn(b"left", water_share.data)

        token = self._csrf(self.client.get("/vault/").data)
        private = self.client.post(
            "/vault/add",
            data={
                "title": "Only Pat bank",
                "login": "pat-bank",
                "secret": "Bank-Only",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertIn(b"Only Pat bank", private.data)

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": member, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        spouse_open = self._unlock(member)
        body = spouse_open.data
        self.assertIn(b"Water bill", body)
        self.assertIn(b"Netflix house", body)
        self.assertNotIn(b"Only Pat bank", body)
        self.assertNotIn(b"Bank-Only", body)

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": admin, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        token = self._csrf(self.client.get("/members/").data)
        kid_inv = self.client.post(
            "/members/invite",
            data={
                "role": "child",
                "csrf_token": token,
                "next": "sheet",
                "panel": "keys",
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        km = re.search(r"Family key ([A-Z0-9-]+)", kid_inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(km)
        self._register(kid, invite=km.group(1), name="Kid")
        blocked = self.client.get("/vault/")
        self.assertEqual(blocked.status_code, 403)
        sneak = self.client.get(f"/vault/{netflix_id}")
        self.assertEqual(sneak.status_code, 403)

    def test_kinds_and_access_clock(self):
        admin = f"vault_b_{self.suffix}"
        member = f"vault_s_{self.suffix}"
        self._register(admin, household=f"VaultB {self.suffix}", name="Pat")
        self._unlock(admin)
        token = self._csrf(self.client.get("/vault/").data)
        added = self.client.post(
            "/vault/add",
            data={
                "kind": "billing",
                "title": "City water",
                "phone": "555-0199",
                "account_no": "W-441",
                "login": "water-user",
                "secret": "Pipe-Secret",
                "url": "https://water.city.test",
                "two_factor": "sms",
                "call_info": "PIN 4410, last 4 1234",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(added.status_code, 200)
        billing = self.client.get("/vault/?kind=billing")
        self.assertIn(b"City water", billing.data)
        self.assertNotIn(b"Pipe-Secret", billing.data)
        passwords = self.client.get("/vault/?kind=password")
        self.assertNotIn(b"City water", passwords.data)
        with self.app.app_context():
            from app.builddb.table_vault_entries import VaultEntry

            row = VaultEntry.query.order_by(VaultEntry.id.desc()).first()
            self.assertEqual(row.kind, "billing")
            bill_id = row.id
        sheet = self.client.get(f"/vault/{bill_id}")
        self.assertIn(b"555-0199", sheet.data)
        self.assertIn(b"W-441", sheet.data)
        self.assertIn(b"PIN 4410", sheet.data)
        self.assertIn(b"Text / SMS", sheet.data)
        self.assertIn(b"Has it now", sheet.data)
        self.assertIn(b"Nobody else can see this right now", sheet.data)

        page = self.client.get("/members/")
        token = self._csrf(page.data)
        inv = self.client.post(
            "/members/invite",
            data={
                "role": "member",
                "label": "Spouse",
                "csrf_token": token,
                "next": "sheet",
                "panel": "keys",
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        import re

        m = re.search(r"Family key ([A-Z0-9-]+)", inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(m, inv.data[-800:])
        self._register(member, invite=m.group(1), name="Spouse")
        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": admin, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        self._unlock(admin)
        with self.app.app_context():
            from app.builddb.table_users import User

            spouse = User.query.filter_by(username=member).first()
            spouse_id = spouse.id
        token = self._csrf(self.client.get(f"/vault/{bill_id}").data)
        given = self.client.post(
            f"/vault/{bill_id}/grant",
            data={
                "person": str(spouse_id),
                "for": "1h",
                "next": "sheet",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(given.status_code, 200)
        body = given.data.decode("utf-8", "replace")
        self.assertIn("Spouse", body)
        self.assertRegex(body, r"(min left|hr left)")
        self.assertIn("Never opened", body)
        self.assertIn("Given for 1 hour", body)
        self.assertNotIn('name="person" type="checkbox"', body)
        self.assertNotIn('type="checkbox" name="person"', body)

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": member, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        self._unlock(member)
        opened = self.client.get(f"/vault/{bill_id}")
        self.assertEqual(opened.status_code, 200)
        self.assertIn(b"Pipe-Secret", opened.data)
        self.client.post(
            f"/vault/{bill_id}/seen",
            data={"action": "copy_secret"},
            headers={"X-CSRF-Token": self._csrf(opened.data)},
        )

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": admin, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        self._unlock(admin)
        after = self.client.get(f"/vault/{bill_id}")
        after_body = after.data.decode("utf-8", "replace")
        self.assertIn("Opened", after_body)
        self.assertIn("copied the password", after_body)

        with self.app.app_context():
            from app.builddb.table_vault_grants import VaultGrant

            g = VaultGrant.query.filter_by(entry_id=bill_id, user_id=spouse_id).first()
            self.assertIsNotNone(g)
            g.expires_at = datetime.utcnow() - timedelta(minutes=2)
            from app.builddb.builddb import db

            db.session.commit()
        expired = self.client.get(f"/vault/{bill_id}")
        exp_body = expired.data.decode("utf-8", "replace")
        self.assertIn("Ended", exp_body)
        self.assertIn("time ran out", exp_body)
        self.assertIn("Nobody else can see this right now", exp_body)
        self.assertNotRegex(exp_body, r"Has it now[\s\S]*?(min left|hr left)")

        self._logout()
        self.client.post(
            "/auth/login",
            data={"username": member, "password": "FamilyTest1!"},
            follow_redirects=True,
        )
        self._unlock(member)
        gone = self.client.get("/vault/")
        self.assertNotIn(b"City water", gone.data)


if __name__ == "__main__":
    unittest.main()
