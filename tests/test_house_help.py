"""Help page, Ask answers about it, soft put-back, and threat-map clamps."""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class HelpSayTests(unittest.TestCase):
    def test_app_questions_answer_and_oil_does_not(self):
        from app.utils.house_help import local_help_say

        key = local_help_say("how do I add an api key")
        self.assertIn("Household", key)
        self.assertIn("Replace blank", key)
        self.assertIsNone(local_help_say("what oil does the tundra take"))
        self.assertIsNone(local_help_say("help me add milk to the basket"))
        self.assertIn("Happened", local_help_say("how do I put back what the bot did"))
        self.assertIn("site owner", local_help_say("where is the security map"))
        self.assertEqual(local_help_say("help"), local_help_say("Help"))


class UndoAndHelpTests(unittest.TestCase):
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

            cls.service_key = mint_service_pass(max_uses=20, days=30, label="help-tests").code

    def _csrf(self, html):
        import re

        text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _register(self, username):
        self.client.get("/auth/logout", follow_redirects=True)
        r = self.client.get("/auth/register")
        if r.status_code == 302:
            self.client.get("/auth/logout", follow_redirects=True)
            r = self.client.get("/auth/register")
        return self.client.post(
            "/auth/register",
            data={
                "name": username,
                "username": username,
                "email": f"{username}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"Help {self.suffix}",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )

    def test_help_page_is_readable_and_a_child_cannot_open_happened(self):
        user = f"help_{self.suffix}"
        self._register(user)
        page = self.client.get("/help")
        self.assertEqual(page.status_code, 200)
        body = page.data.decode("utf-8", "replace")
        self.assertIn("AI keys", body)
        self.assertIn("Put back", body)
        self.assertIn("Security map", body)
        self.assertIn("Help", self.client.get("/").data.decode("utf-8", "replace"))

        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_users import User

            parent = User.query.filter_by(username=user).first()
            kid = User(
                household_id=parent.household_id,
                username=f"help_kid_{self.suffix}",
                name="Kid",
                role="child",
                email=f"help_kid_{self.suffix}@family.test",
            )
            kid.set_password("FamilyTest1!")
            db.session.add(kid)
            db.session.commit()
            kid_name = kid.username

        self.client.get("/auth/logout", follow_redirects=True)
        self.client.post("/auth/login", data={"username": kid_name, "password": "FamilyTest1!"})
        kid_help = self.client.get("/help")
        self.assertEqual(kid_help.status_code, 200)
        self.assertIn(b"AI keys", kid_help.data)
        happened = self.client.get("/members/happened")
        self.assertEqual(happened.status_code, 403)

    def test_put_back_hides_a_new_item_once_and_restores_an_edit(self):
        user = f"undo_{self.suffix}"
        self._register(user)
        from app.utils.activity import reverse_row

        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_household_activity import HouseholdActivity
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            parent = User.query.filter_by(username=user).one()
            item = Item(
                household_id=parent.household_id,
                item_type="vehicle",
                name="Undo Truck",
                created_by=parent.id,
            )
            db.session.add(item)
            db.session.flush()
            added = HouseholdActivity(
                household_id=parent.household_id,
                user_id=parent.id,
                action="bot.vehicle.add",
                summary="A bot added the vehicle Undo Truck",
                target_table="items",
                target_id=item.id,
                item_id=item.id,
                old_json={"undo": "hide_item"},
                reversible=True,
            )
            db.session.add(added)
            db.session.commit()
            ok, msg = reverse_row(added, by_id=parent.id)
            self.assertTrue(ok, msg)
            db.session.refresh(item)
            self.assertIsNotNone(item.removed_at)
            again, again_msg = reverse_row(added, by_id=parent.id)
            self.assertFalse(again)
            self.assertIn("Already", again_msg)
            db.session.refresh(item)
            self.assertIsNotNone(item.removed_at)

            edited = Item(
                household_id=parent.household_id,
                item_type="house",
                name="Old porch",
                created_by=parent.id,
            )
            db.session.add(edited)
            db.session.flush()
            change = HouseholdActivity(
                household_id=parent.household_id,
                user_id=parent.id,
                action="bot.house.update",
                summary="A bot updated Old porch",
                target_table="items",
                target_id=edited.id,
                item_id=edited.id,
                old_json={"undo": "fields", "item": {"name": "Old porch", "category": None, "notes": None}},
                reversible=True,
            )
            edited.name = "New porch"
            db.session.add(change)
            db.session.commit()
            ok, msg = reverse_row(change, by_id=parent.id)
            self.assertTrue(ok, msg)
            db.session.refresh(edited)
            self.assertEqual(edited.name, "Old porch")

    def test_put_back_moves_a_bot_note_to_the_recycle_bin(self):
        user = f"note_{self.suffix}"
        self._register(user)
        from app.utils.activity import reverse_row

        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_household_activity import HouseholdActivity
            from app.builddb.table_maya_bot import HouseholdTrash
            from app.builddb.table_notes import Note
            from app.builddb.table_users import User

            parent = User.query.filter_by(username=user).one()
            note = Note(
                household_id=parent.household_id,
                user_id=parent.id,
                visibility="household",
                title="Bot note",
                body="hello",
            )
            db.session.add(note)
            db.session.flush()
            row = HouseholdActivity(
                household_id=parent.household_id,
                user_id=parent.id,
                action="bot.note.add",
                summary="A bot added the note Bot note",
                target_table="notes",
                target_id=note.id,
                old_json={"undo": "trash", "ids": [note.id]},
                reversible=True,
            )
            db.session.add(row)
            db.session.commit()
            note_id = note.id
            ok, msg = reverse_row(row, by_id=parent.id)
            self.assertTrue(ok, msg)
            self.assertIsNone(Note.query.filter_by(id=note_id).first())
            bin_row = HouseholdTrash.query.filter_by(
                household_id=parent.household_id, target_table="notes", target_id=note_id
            ).first()
            self.assertIsNotNone(bin_row)

    def test_sign_in_drops_the_pre_login_session_and_files_are_not_cached(self):
        user = f"fresh_{self.suffix}"
        self.client.get("/auth/logout", follow_redirects=True)
        self.client.get("/auth/register")
        with self.client.session_transaction() as sess:
            sess["planted"] = "before"
            old_csrf = sess.get("csrf_token")
        signed = self.client.post(
            "/auth/register",
            data={
                "name": user,
                "username": user,
                "email": f"{user}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"Fresh {self.suffix}",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )
        self.assertEqual(signed.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn("planted", sess)
            self.assertTrue(sess.get("csrf_token"))
            self.assertNotEqual(sess.get("csrf_token"), old_csrf)
            self.assertIn("_user_id", sess)

        from app.utils.crypto import send_bytes

        with self.app.app_context():
            resp = send_bytes(b"hello", "image/jpeg", "a\r\nLocation: evil.jpg")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))
        disp = resp.headers.get("Content-Disposition", "")
        self.assertNotIn("\r", disp)
        self.assertNotIn("\n", disp)
        other = send_bytes(b"hello", "text/html", "note.html")
        self.assertTrue(other.headers.get("Content-Disposition", "").startswith("attachment"))

    def test_a_missing_file_version_is_not_put_back(self):
        from types import SimpleNamespace

        from app.utils.activity_undo import undo_recorded

        row = SimpleNamespace(
            action="maya.file.replace",
            old_json={"undo": "file_version", "version_id": 0},
            household_id=1,
            target_id=1,
            item_id=None,
            target_table="photo_notes",
        )
        with self.app.app_context():
            ok, msg = undo_recorded(row)
        self.assertFalse(ok)
        self.assertIn("not available", msg.lower())

    def test_a_vault_look_up_cannot_be_undone(self):
        from types import SimpleNamespace

        from app.utils.activity_undo import undo_recorded

        row = SimpleNamespace(
            action="bot.vault.read",
            old_json={"undo": "hide_item"},
            household_id=1,
            target_id=1,
            item_id=None,
            target_table="vault_entries",
        )
        ok, msg = undo_recorded(row)
        self.assertFalse(ok)
        self.assertIn("can't", msg.lower())

    def test_threat_map_rejects_a_bad_country_and_clamps_replay(self):
        from app.routes.security.threat_map import clamp_replay_limit
        from app.routes.security.threat_queries import clean_iso2, country_detail

        self.assertEqual(clean_iso2("us"), "US")
        self.assertEqual(clean_iso2("XX"), "XX")
        self.assertIsNone(clean_iso2("U"))
        self.assertIsNone(clean_iso2("US'; DROP"))
        self.assertEqual(clamp_replay_limit("99999"), 1500)
        self.assertEqual(clamp_replay_limit("-4"), 1)
        self.assertEqual(clamp_replay_limit("nope"), 1500)
        detail = country_detail("nope")
        self.assertEqual(detail.get("error"), "bad_iso")

        self.client.get("/auth/logout", follow_redirects=True)
        summary = self.client.get("/security/threat-map/summary")
        self.assertEqual(summary.status_code, 401)
        self.assertIn("no-store", summary.headers.get("Cache-Control", ""))
        country = self.client.get("/security/threat-map/country/US%27")
        self.assertEqual(country.status_code, 401)
