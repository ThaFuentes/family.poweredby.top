"""Maya bot API (/api/v1/maya) and the owner's Maya permissions checklist.

Safe by construction: classes that build the app point MySQL at 127.0.0.1:9
(nothing listens there) and the test asserts it cannot connect, so these
tests can never touch the real household database. The process settings are
put back afterwards, so this file can run in the same process as the
household suites. DB-backed checks run on an in-memory SQLite engine swapped
into the app.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

DEAD = {"MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "9", "MYSQL_USER": "maya_test_nobody",
        "MYSQL_PASSWORD": "not-a-real-password", "MYSQL_DATABASE": "maya_test_nodb"}
# Captured before this file changes anything. Importing the suite must not
# leave the household database pointed at a closed port.
_PRIOR_MYSQL = {key: os.environ.get(key) for key in DEAD}


def _apply_mysql(values: dict) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _publish(connector) -> None:
    """create_app and the security connector read these names at call time."""
    import sys

    connect = sys.modules.get("poweredbytop.models.connect_db")
    if connect is None:
        return
    connect.DATABASE_URI = connector.DATABASE_URI
    connect.MYSQL_HOST = connector.MYSQL_HOST
    connect.MYSQL_PORT = connector.MYSQL_PORT
    connect.MYSQL_DATABASE = connector.MYSQL_DATABASE


def use_dead_database():
    import dbconnector

    _apply_mysql(DEAD)
    dbconnector.MYSQL_HOST = DEAD["MYSQL_HOST"]
    dbconnector.MYSQL_PORT = DEAD["MYSQL_PORT"]
    dbconnector.MYSQL_USER = DEAD["MYSQL_USER"]
    dbconnector.MYSQL_PASSWORD = DEAD["MYSQL_PASSWORD"]
    dbconnector.MYSQL_DATABASE = DEAD["MYSQL_DATABASE"]
    dbconnector.DATABASE_URI = (
        f"mysql+pymysql://{DEAD['MYSQL_USER']}:{DEAD['MYSQL_PASSWORD']}@"
        f"{DEAD['MYSQL_HOST']}:{DEAD['MYSQL_PORT']}/{DEAD['MYSQL_DATABASE']}"
    )
    _publish(dbconnector)
    return dbconnector


def restore_household_database():
    from dotenv import load_dotenv

    import dbconnector

    _apply_mysql(_PRIOR_MYSQL)
    load_dotenv(os.path.join(ROOT, ".env"))
    dbconnector.MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
    dbconnector.MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
    dbconnector.MYSQL_USER = os.environ.get("MYSQL_USER")
    dbconnector.MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
    dbconnector.MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE")
    dbconnector.DATABASE_URI = (
        f"mysql+pymysql://{dbconnector.MYSQL_USER}:{dbconnector.MYSQL_PASSWORD}@"
        f"{dbconnector.MYSQL_HOST}:{dbconnector.MYSQL_PORT}/{dbconnector.MYSQL_DATABASE}"
    )
    _publish(dbconnector)
    return dbconnector


import dbconnector  # noqa: E402

from app import create_app  # noqa: E402
from app.builddb.builddb import db  # noqa: E402
from app.utils import maya_perms, maya_store  # noqa: E402


def _png_with_exif() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (8, 8), (200, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x010E] = "GPS 29.7604 -95.3698"  # ImageDescription
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


class DeadDatabase(unittest.TestCase):
    def test_points_at_dead_address(self):
        connector = use_dead_database()
        try:
            self.assertIn("127.0.0.1:9", connector.DATABASE_URI)
            import pymysql

            with self.assertRaises(Exception):
                pymysql.connect(host="127.0.0.1", port=9, user="x", password="y", connect_timeout=2)
        finally:
            restore_household_database()


class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_dead_database()
        try:
            cls.app = create_app()
            cls.app.config["TESTING"] = True
        except Exception:
            restore_household_database()
            raise

    @classmethod
    def tearDownClass(cls):
        restore_household_database()

    def test_routes_registered(self):
        rules = {r.rule for r in self.app.url_map.iter_rules()}
        for path in ("/api/v1/maya/capabilities", "/api/v1/maya/items", "/api/v1/maya/items/<int:item_id>",
                     "/api/v1/maya/basket", "/api/v1/maya/reminders", "/api/v1/maya/notes",
                     "/api/v1/maya/files/<kind>/<int:row_id>", "/api/v1/maya/records", "/api/v1/maya/cases",
                     "/api/v1/maya/trash", "/api/v1/maya/trash/<int:trash_id>/restore",
                     "/api/v1/maya/activity", "/api/v1/maya/people", "/api/v1/maya/vault",
                     "/maya-permissions/", "/api/v1/auth/reset"):
            self.assertIn(path, rules, path)

    def test_every_route_perm_is_in_catalog(self):
        from app.routes.maya_api import MAYA_ROUTES

        for r in MAYA_ROUTES:
            if r["perm"] is not None:
                self.assertIn(r["perm"], maya_perms.CATALOG_BY_ID, r)

    def test_no_route_touches_the_checklist_or_secrets(self):
        from app.routes.maya_api import MAYA_ROUTES

        for r in MAYA_ROUTES:
            low = r["path"].lower()
            for bad in ("permission", "checklist", "secret", "password_hash", "api_key", "/keys"):
                self.assertNotIn(bad, low, r)

    def test_maya_api_needs_a_session(self):
        c = self.app.test_client()
        res = c.get("/api/v1/maya/capabilities", base_url="https://localhost")
        self.assertIn(res.status_code, (401, 403))

    def test_owner_page_needs_login(self):
        c = self.app.test_client()
        res = c.get("/maya-permissions/", base_url="https://localhost")
        self.assertIn(res.status_code, (302, 401, 403))

    # ---- gate (no DB: identity and switches are patched)

    def _call(self, endpoint, method="GET", perm_on=True, maya=True, **kw):
        view = self.app.view_functions["bot_api." + endpoint].__wrapped__

        class U:
            id = 7
            household_id = 1
            is_bot = True
            username = "grokbots"
            name = "Maya Bot"

        with self.app.test_request_context(method=method, base_url="https://localhost"), \
                patch("app.routes.maya_api.api_user", return_value=U()), \
                patch("app.routes.maya_api.audit"), \
                patch.object(maya_perms, "is_maya", return_value=maya), \
                patch.object(maya_perms, "allowed", return_value=perm_on):
            return view(**kw)

    def test_gate_refuses_non_maya_bot(self):
        res = self._call("maya_trash_restore", "POST", maya=False, trash_id=1)
        res = res[0] if isinstance(res, tuple) else res
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "not_maya")

    def test_gate_refuses_switch_off(self):
        res = self._call("maya_trash_restore", "POST", perm_on=False, trash_id=1)
        res = res[0] if isinstance(res, tuple) else res
        self.assertEqual(res.status_code, 403)
        self.assertIn("permission_off", res.get_data(as_text=True))

    def test_forbidden_ids_never_pass_need(self):
        from app.routes import maya_api

        with self.app.test_request_context(base_url="https://localhost"), \
                patch("app.routes.maya_api.api_user"), patch("app.routes.maya_api.audit"), \
                patch.object(maya_perms, "allowed", return_value=True):
            for pid in maya_perms.FORBIDDEN_IDS:
                res = maya_api.need(pid)
                res = res[0] if isinstance(res, tuple) else res
                self.assertEqual(res.status_code, 403)
                self.assertIn("hard_limit", res.get_data(as_text=True))


class Catalog(unittest.TestCase):
    def test_granular_and_defaults(self):
        ids = set(maya_perms.CATALOG_BY_ID)
        for area in ("inventory", "vehicles", "tools", "house", "notes", "records", "reminders", "basket"):
            for act in ("read", "create", "edit", "delete", "restore"):
                self.assertIn(f"{area}.{act}", ids)
        for p in maya_perms.CATALOG:
            self.assertEqual(p["default"], not p["high_risk"], p["id"])
        high = {p["id"] for p in maya_perms.CATALOG if p["high_risk"]}
        for pid in ("people.role", "people.remove", "settings.security", "trash.purge", "records.amounts"):
            self.assertIn(pid, high)

    def test_unimplemented_never_on(self):
        off = [p["id"] for p in maya_perms.CATALOG if not p["implemented"]]
        self.assertIn("settings.security", off)

    def test_hard_limits_listed(self):
        text = " ".join(maya_perms.HARD_LIMITS).lower()
        self.assertIn("checklist", text)
        self.assertIn("password hashes", text)
        self.assertIn("audit", text)


class Uploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_dead_database()
        try:
            cls.app = create_app()
        except Exception:
            restore_household_database()
            raise

    @classmethod
    def tearDownClass(cls):
        restore_household_database()

    def test_sniff_trusts_bytes(self):
        self.assertEqual(maya_store.sniff(b"%PDF-1.7 ...")[0], ".pdf")
        self.assertIsNone(maya_store.sniff(b"<?php echo 1; ?>"))

    def test_exif_stripped(self):
        from PIL import Image
        from werkzeug.datastructures import FileStorage

        raw = _png_with_exif()
        self.assertIn(b"SecretCam", raw)
        with self.app.app_context():
            clean, err = maya_store.clean_upload(FileStorage(io.BytesIO(raw), filename="../../evil name.php"),
                                                 allowed=maya_store.DOC_EXTS)
        self.assertIsNone(err)
        self.assertEqual(clean.filename, "evil_name.jpg")
        data = clean.read()
        self.assertNotIn(b"SecretCam", data)
        with Image.open(io.BytesIO(data)) as im:
            self.assertFalse(dict(im.getexif()))

    def test_rejects_wrong_type_and_size(self):
        from werkzeug.datastructures import FileStorage

        with self.app.app_context():
            _c, err = maya_store.clean_upload(FileStorage(io.BytesIO(b"MZ\x90\x00"), filename="a.jpg"),
                                              allowed=maya_store.DOC_EXTS)
            self.assertTrue(err)
            _c, err = maya_store.clean_upload(FileStorage(io.BytesIO(b"%PDF-" + b"0" * 2000), filename="a.pdf"),
                                              allowed=maya_store.DOC_EXTS, max_bytes=1000)
            self.assertIn("over", err)

    def test_archive_outside_app(self):
        with self.app.app_context():
            root = maya_store.archive_root()
            app_dir = os.path.dirname(self.app.root_path)
            self.assertFalse(str(root).startswith(os.path.realpath(app_dir) + os.sep))
            self.assertIsNone(maya_store._safe_upload_path(1, "../etc/passwd"))
            self.assertIsNone(maya_store._safe_upload_path(1, "2/x.enc"))


class SqliteState(unittest.TestCase):
    """Permissions save/high-risk confirm and recycle bin on in-memory SQLite."""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        use_dead_database()
        try:
            cls._open_sqlite(create_engine, StaticPool)
        except Exception:
            restore_household_database()
            raise

    @classmethod
    def _open_sqlite(cls, create_engine, StaticPool):
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        ext = cls.app.extensions["sqlalchemy"]
        ext._app_engines[cls.app][None] = engine
        db.session.remove()
        from app.builddb.table_household_activity import HouseholdActivity
        from app.builddb.table_households import Household
        from app.builddb.table_maya_bot import (HouseholdTrash, MayaBotAccount, MayaBotPermission,
                                                MayaBotPermLog)
        from app.builddb.table_reminders import Reminder
        from app.builddb.table_users import User

        tables = [m.__table__ for m in (Household, User, MayaBotAccount, MayaBotPermission, MayaBotPermLog,
                                        HouseholdTrash, HouseholdActivity, Reminder)]
        db.metadata.create_all(engine, tables=tables)
        h = Household(name="Test house", handle="testhouse")
        db.session.add(h)
        db.session.flush()
        cls.hid = h.id
        owner = User(household_id=h.id, username="owner", name="Owner", role="admin", is_leader=True,
                     is_bot=False, is_active=True)
        maya = User(household_id=h.id, username="grokbots", name="Maya Bot", role="member", is_leader=False,
                    is_bot=True, is_active=True)
        owner.set_password("Correct-horse-1")
        maya.set_password("Maya-only-test-9")
        db.session.add_all([owner, maya])
        db.session.flush()
        cls.owner_id, cls.maya_id = owner.id, maya.id
        ok, _ = maya_perms.set_maya(h.id, maya, by_user=owner)
        assert ok
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.remove()
            cls.ctx.pop()
        finally:
            restore_household_database()

    def _users(self):
        from app.builddb.table_users import User

        return db.session.get(User, self.owner_id), db.session.get(User, self.maya_id)

    def test_engine_is_sqlite(self):
        self.assertEqual(db.engine.dialect.name, "sqlite")

    def test_defaults_live(self):
        owner, maya = self._users()
        self.assertTrue(maya_perms.is_maya(maya))
        self.assertFalse(maya_perms.is_maya(owner))
        self.assertTrue(maya_perms.allowed(maya, "notes.create"))
        self.assertFalse(maya_perms.allowed(maya, "trash.purge"))
        self.assertFalse(maya_perms.allowed(maya, "keys.read"))
        self.assertFalse(maya_perms.allowed(owner, "notes.read"))

    def test_toggle_is_live_and_logged(self):
        from app.builddb.table_maya_bot import MayaBotPermLog

        owner, maya = self._users()
        changed, refused = maya_perms.save_state(self.hid, maya, {"notes.delete": False}, owner=owner,
                                                 confirmed_with=None)
        self.assertEqual((changed, refused), (["notes.delete"], []))
        self.assertFalse(maya_perms.allowed(maya, "notes.delete"))
        self.assertTrue(MayaBotPermLog.query.filter_by(perm="notes.delete", new_value=False).count())
        maya_perms.save_state(self.hid, maya, {"notes.delete": True}, owner=owner, confirmed_with=None)
        self.assertTrue(maya_perms.allowed(maya, "notes.delete"))

    def test_high_risk_needs_confirmation(self):
        owner, maya = self._users()
        changed, refused = maya_perms.save_state(self.hid, maya, {"trash.purge": True}, owner=owner,
                                                 confirmed_with=None)
        self.assertEqual(refused, ["trash.purge"])
        self.assertFalse(maya_perms.allowed(maya, "trash.purge"))
        changed, refused = maya_perms.save_state(self.hid, maya, {"trash.purge": True}, owner=owner,
                                                 confirmed_with="password")
        self.assertEqual(changed, ["trash.purge"])
        self.assertTrue(maya_perms.allowed(maya, "trash.purge"))
        # Turning off never needs confirmation.
        changed, _ = maya_perms.save_state(self.hid, maya, {"trash.purge": False}, owner=owner, confirmed_with=None)
        self.assertEqual(changed, ["trash.purge"])

    def test_unimplemented_cannot_be_turned_on(self):
        owner, maya = self._users()
        maya_perms.save_state(self.hid, maya, {"settings.security": True}, owner=owner, confirmed_with="totp")
        self.assertFalse(maya_perms.allowed(maya, "settings.security"))

    def test_bot_cannot_save_checklist(self):
        _owner, maya = self._users()
        with self.assertRaises(PermissionError):
            maya_perms.save_state(self.hid, maya, {"notes.read": False}, owner=maya, confirmed_with="password")
        self.assertFalse(maya_perms.is_owner(maya))
        self.assertIsNone(maya_perms.confirm_owner(maya, password="anything"))

    def test_confirm_owner_password(self):
        owner, _maya = self._users()
        if not hasattr(owner, "set_password"):
            self.skipTest("User has no set_password")
        with patch.object(type(owner), "is_authenticated", True, create=True):
            self.assertEqual(maya_perms.confirm_owner(owner, password="Correct-horse-1"), "password")
            self.assertIsNone(maya_perms.confirm_owner(owner, password="wrong"))

    def test_parse_expiry(self):
        from datetime import datetime, timedelta

        now = datetime(2026, 10, 4, 12, 0)
        self.assertIsNone(maya_perms.parse_expiry("none", 5, now=now))
        self.assertEqual(maya_perms.parse_expiry("hours", 3, now=now), now + timedelta(hours=3))
        self.assertEqual(maya_perms.parse_expiry("weeks", 2, now=now), now + timedelta(days=14))
        self.assertEqual(maya_perms.parse_expiry("months", 1, now=now), now + timedelta(days=30))
        for bad in (("days", 0), ("days", "x"), ("years", 1)):
            with self.assertRaises(ValueError):
                maya_perms.parse_expiry(*bad, now=now)

    def test_high_risk_gets_24h_timer_by_default(self):
        from datetime import datetime, timedelta

        owner, maya = self._users()
        maya_perms.save_state(self.hid, maya, {"vault.read": True}, owner=owner, confirmed_with="password")
        exp = maya_perms.perm_expiry(self.hid, maya.id)["vault.read"]
        self.assertAlmostEqual((exp - datetime.utcnow()).total_seconds(), 86400, delta=120)
        caps = maya_perms.capabilities(maya)
        entry = [p for g in caps["groups"] for p in g["permissions"] if p["id"] == "vault.read"][0]
        self.assertTrue(entry["expires_at"].endswith("Z"))
        self.assertTrue(entry["timer_required"])
        # Extending a high-risk timer without re-confirming is refused.
        _c, refused = maya_perms.save_state(self.hid, maya, {"vault.read": True}, owner=owner, confirmed_with=None,
                                            expiry={"vault.read": datetime.utcnow() + timedelta(days=30)})
        self.assertEqual(refused, ["vault.read"])
        maya_perms.save_state(self.hid, maya, {"vault.read": False}, owner=owner, confirmed_with=None)

    def test_normal_timer_optional_and_expiry_is_live(self):
        from datetime import datetime, timedelta

        from app.builddb.table_maya_bot import MayaBotPermission, MayaBotPermLog

        owner, maya = self._users()
        maya_perms.save_state(self.hid, maya, {"basket.read": True}, owner=owner, confirmed_with=None)
        self.assertNotIn("basket.read", maya_perms.perm_expiry(self.hid, maya.id))  # no expiry by default
        maya_perms.save_state(self.hid, maya, {"basket.read": True}, owner=owner, confirmed_with=None,
                              expiry={"basket.read": datetime.utcnow() + timedelta(hours=2)})
        self.assertIn("basket.read", maya_perms.perm_expiry(self.hid, maya.id))
        row = MayaBotPermission.query.filter_by(user_id=maya.id, perm="basket.read").first()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.assertFalse(maya_perms.perm_state(self.hid, maya.id, cleanup=False)["basket.read"])
        self.assertTrue(MayaBotPermission.query.filter_by(user_id=maya.id, perm="basket.read").first().enabled)
        self.assertFalse(maya_perms.allowed(maya, "basket.read"))  # lazy cleanup flips it
        db.session.expire_all()
        self.assertFalse(MayaBotPermission.query.filter_by(user_id=maya.id, perm="basket.read").first().enabled)
        self.assertTrue(MayaBotPermLog.query.filter_by(perm="basket.read", confirmed_with="auto-expired").count())
        maya_perms.save_state(self.hid, maya, {"basket.read": True}, owner=owner, confirmed_with=None)

    def test_cron_expire_due(self):
        from datetime import datetime, timedelta

        from app.builddb.table_maya_bot import MayaBotPermission

        owner, maya = self._users()
        maya_perms.save_state(self.hid, maya, {"logs.read": True}, owner=owner, confirmed_with=None,
                              expiry={"logs.read": datetime.utcnow() + timedelta(hours=1)})
        self.assertEqual(maya_perms.expire_due(now=datetime.utcnow() + timedelta(hours=2)), 1)
        self.assertFalse(MayaBotPermission.query.filter_by(user_id=maya.id, perm="logs.read").first().enabled)
        maya_perms.save_state(self.hid, maya, {"logs.read": True}, owner=owner, confirmed_with=None)

    def test_trash_and_restore(self):
        from datetime import datetime

        from app.builddb.table_maya_bot import HouseholdTrash
        from app.builddb.table_reminders import Reminder

        owner, maya = self._users()
        r = Reminder(household_id=self.hid, type="custom", title="Oil change", due_at=datetime(2026, 11, 1),
                     status="open", created_by=owner.id)
        db.session.add(r)
        db.session.commit()
        rid = r.id
        entry = maya_store.trash(hid=self.hid, label="Reminder: Oil change", rows=[(Reminder, r)], files=[],
                                 actor_id=maya.id, via="maya")
        db.session.commit()
        self.assertIsNone(db.session.get(Reminder, rid))
        self.assertEqual(HouseholdTrash.query.get(entry.id).via, "maya")
        ok, msg = maya_store.restore(entry, actor_id=owner.id)
        db.session.commit()
        self.assertTrue(ok, msg)
        back = db.session.get(Reminder, rid)
        self.assertIsNotNone(back)
        self.assertEqual(back.title, "Oil change")
        ok, _ = maya_store.restore(entry, actor_id=owner.id)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
