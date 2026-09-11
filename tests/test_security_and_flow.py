"""SQLi, tenant isolation, photos, and a few household flows against the live schema."""
from __future__ import annotations

import io
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from app import create_app
from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_users import User
from app.routes.items import resolve_photo_file
from flask import abort


def _png() -> bytes:
    # 1x1 PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


SQLI = [
    "' OR 1=1 --",
    "\" OR \"1\"=\"1",
    "1; DROP TABLE items;--",
    "1' UNION SELECT * FROM users --",
    "FAM:1:1' OR '1'='1",
    "admin'--",
    "'; WAITFOR DELAY '0:0:5'--",
]


class FamilySecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.suffix = os.urandom(3).hex()
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=80, days=30, label="tests").code

    def _csrf(self, html: bytes | str) -> str:
        text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _register(self, username, household=None, invite="", name=None, email=None):
        self._logout()
        r = self.client.get("/auth/register")
        self.assertIn(r.status_code, (200, 302))
        if r.status_code == 302:
            self._logout()
            r = self.client.get("/auth/register")
        self.assertEqual(r.status_code, 200, r.data[-300:] if r.data else r.status)
        data = {
            "name": name or username,
            "username": username,
            "email": email or f"{username}@family.test",
            "password": "FamilyTest1!",
            "household_name": household or "",
            "family_key": invite,
            "invite_code": invite,
            "service_key": "" if invite else self.service_key,
        }
        return self.client.post("/auth/register", data=data, follow_redirects=True)

    def _login(self, username, password="FamilyTest1!"):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def _logout(self):
        return self.client.get("/auth/logout", follow_redirects=True)

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json().get("ok"))

    def test_landing_and_manifest(self):
        self._logout()
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8", "replace")
        self.assertIn("Family key", body)
        self.assertIn("Service key", body)
        self.assertIn("FAM-", body)
        self.assertIn("SRV-", body)
        self.assertNotIn("Traceback", body)
        man = self.client.get("/manifest.webmanifest")
        self.assertEqual(man.status_code, 200)
        data = man.get_json()
        self.assertEqual(data.get("display"), "standalone")
        self.assertEqual(data.get("start_url"), "/")
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn(b"family-static", sw.data)

    def test_service_gate_blocks_strangers(self):
        self._logout()
        user = f"stranger_{self.suffix}"
        r = self.client.post(
            "/auth/register",
            data={
                "name": "Stranger",
                "username": user,
                "email": f"{user}@nope.test",
                "password": "FamilyTest1!",
                "household_name": "Nope house",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"friends and family", r.data.lower())
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(username=user).first())

    def test_trusted_email_skips_service_key(self):
        addr = f"trusted_{self.suffix}@family.test"
        user = f"trust_{self.suffix}"
        with self.app.app_context():
            from app.utils.access import add_trusted_email

            ok, _msg, _row = add_trusted_email(email=addr, note="test")
            self.assertTrue(ok)
        self._logout()
        r = self.client.post(
            "/auth/register",
            data={
                "name": "Trusted",
                "username": user,
                "email": addr,
                "password": "FamilyTest1!",
                "household_name": f"Trusted House {self.suffix}",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Home", r.data)
        with self.app.app_context():
            self.assertIsNotNone(User.query.filter_by(username=user).first())

    def test_login_sqli_does_not_auth(self):
        for payload in SQLI:
            r = self.client.post(
                "/auth/login",
                data={"username": payload, "password": payload},
                follow_redirects=True,
            )
            self.assertIn(r.status_code, (200, 400, 401, 429))
            self.assertNotIn(b"Home", r.data.split(b"<h1>")[1] if b"<h1>" in r.data else b"")
            # still on login
            self.assertTrue(
                b"Sign in" in r.data or b"Invalid" in r.data or b"password" in r.data.lower()
            )

    def test_two_households_isolation_and_scan_sqli(self):
        a_user = f"sqli_a_{self.suffix}"
        b_user = f"sqli_b_{self.suffix}"
        ra = self._register(a_user, household=f"House A {self.suffix}")
        self.assertEqual(ra.status_code, 200, ra.data[-500:])
        # invite a member into A
        html = self.client.get("/members/").data
        token = self._csrf(html)
        inv = self.client.post(
            "/members/invite",
            data={"role": "member", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(inv.status_code, 200)
        m = re.search(r"Family key ([A-Z0-9-]+)", inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(m, inv.data[-800:])
        code = m.group(1)
        self._logout()
        member = f"sqli_am_{self.suffix}"
        rm = self._register(member, invite=code, name="Member A")
        self.assertEqual(rm.status_code, 200)
        self._logout()

        rb = self._register(b_user, household=f"House B {self.suffix}")
        self.assertEqual(rb.status_code, 200)

        # B creates an item
        page = self.client.get("/items/new")
        token = self._csrf(page.data)
        created = self.client.post(
            "/items/create",
            data={
                "name": "B secret milk",
                "item_type": "grocery",
                "quantity": "3",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(created.status_code, 200)
        with self.app.app_context():
            b_item = Item.query.filter_by(name="B secret milk").order_by(Item.id.desc()).first()
            self.assertIsNotNone(b_item)
            b_id = b_item.id

        # SQLi barcodes should not 500
        for payload in SQLI:
            r = self.client.post(
                "/scan/apply",
                json={"barcode": payload, "action": "check"},
                headers={"X-CSRF-Token": token, "Content-Type": "application/json"},
            )
            self.assertIn(r.status_code, (200, 400, 403), payload)
            if r.status_code == 200:
                body = r.get_json() or {}
                self.assertNotIn("sql", str(body).lower())

        lookup = self.client.get(
            "/api/lookup/product",
            query_string={"barcode": "' OR 1=1 --"},
        )
        self.assertIn(lookup.status_code, (200, 400, 401, 403))

        self._logout()
        self._login(a_user)
        page = self.client.get("/items/new")
        token = self._csrf(page.data)
        # A must not see B's item
        sneak = self.client.get(f"/items/{b_id}")
        self.assertEqual(sneak.status_code, 404)
        # A grocery add with SQLi name should store as literal, not explode
        r = self.client.post(
            "/items/create",
            data={
                "name": "Milk ' OR 1=1 --",
                "item_type": "grocery",
                "quantity": "1",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Milk", r.data)

    def test_photo_path_traversal_blocked(self):
        class Row:
            household_id = 1
            image_path = "../../etc/passwd"

        with self.app.app_context():
            with self.app.test_request_context("/"):
                with self.assertRaises(Exception):
                    resolve_photo_file(Row())

    def test_photo_upload_and_quick_battery(self):
        user = f"photo_{self.suffix}"
        r = self._register(user, household=f"Photo House {self.suffix}")
        self.assertEqual(r.status_code, 200)
        page = self.client.get("/vehicles/")
        token = self._csrf(page.data)
        veh = self.client.post(
            "/vehicles/lookup",
            data={
                "name": "Gray truck",
                "make": "Ford",
                "model": "F-150",
                "year": "2018",
                "csrf_token": token,
                "photo": (io.BytesIO(_png()), "truck.png"),
                "caption": "The actual truck",
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(veh.status_code, 200)
        with self.app.app_context():
            truck = (
                Item.query.filter_by(item_type="vehicle", name="Gray truck")
                .order_by(Item.id.desc())
                .first()
            )
            self.assertIsNotNone(truck)
            truck_id = truck.id

        q = self.client.post(
            "/api/items/quick",
            data={
                "name": "DieHard Gold Group 35",
                "item_type": "grocery",
                "kind": "car_battery",
                "kind_label": "Car battery",
                "linked_item_id": str(truck_id),
                "action": "restock",
                "photo": (io.BytesIO(_png()), "battery.png"),
                "caption": "Terminals / connectors",
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(q.status_code, 200, q.data)
        body = q.get_json()
        self.assertTrue(body.get("ok"))
        item_id = body["item_id"]
        detail = self.client.get(f"/items/{item_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Gray truck", detail.data)
        self.assertIn(b"DieHard", detail.data)
        systems = self.client.get(f"/items/{truck_id}?tab=systems")
        self.assertEqual(systems.status_code, 200)
        self.assertIn(b"Electrical", systems.data)
        self.assertIn(b"Engine", systems.data)
        self.assertIn(b"Electronics", systems.data)
        self.assertIn(b"Body", systems.data)
        self.assertIn(b"DieHard", systems.data)
        token = self._csrf(systems.data)
        added = self.client.post(
            f"/vehicles/{truck_id}/parts",
            data={
                "system": "electrical",
                "slot": "alternator",
                "name": "Motorcraft 130A",
                "spec": "130A 3-pin",
                "brand": "Motorcraft",
                "status": "installed",
                "source": "AutoZone",
                "cost": "189.00",
                "notes": "Just replaced the alternator. Old one was dying.",
                "csrf_token": token,
                "receipt": (io.BytesIO(_png()), "az-receipt.png"),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(added.status_code, 200)
        self.assertIn(b"Motorcraft 130A", added.data)
        self.assertIn(b"AutoZone", added.data)
        self.assertIn(b"Just replaced the alternator", added.data)
        rad = self.client.post(
            f"/items/{truck_id}/parts",
            data={
                "system": "cooling",
                "slot": "radiator",
                "name": "Spectra radiator",
                "source": "RockAuto",
                "notes": "Replaced the radiator.",
                "status": "installed",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(rad.status_code, 200)
        self.assertIn(b"Spectra radiator", rad.data)
        self.assertIn(b"RockAuto", rad.data)
        # photo route
        with self.app.app_context():
            from app.builddb.table_photo_notes import PhotoNote

            photo = PhotoNote.query.filter_by(item_id=item_id).first()
            self.assertIsNotNone(photo)
            pid = photo.id
        img = self.client.get(f"/items/photo/{pid}")
        self.assertEqual(img.status_code, 200)
        self.assertTrue(img.data.startswith(b"\x89PNG") or len(img.data) > 8)

        # maintenance with photo
        mpage = self.client.get(f"/items/{truck_id}/maintenance")
        token = self._csrf(mpage.data)
        logged = self.client.post(
            f"/items/{truck_id}/maintenance",
            data={
                "type": "oil_change",
                "date": "2026-09-01",
                "mileage_or_hours": "87200",
                "notes": "Filter housing",
                "caption": "Filter housing",
                "photo": (io.BytesIO(_png()), "filter.png"),
                "csrf_token": token,
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(logged.status_code, 200)

    def test_pages_render_for_admin(self):
        user = f"pages_{self.suffix}"
        self._register(user, household=f"Pages {self.suffix}")
        for path in (
            "/",
            "/scan/",
            "/groceries/",
            "/groceries/list",
            "/tools/",
            "/vehicles/",
            "/notes/",
            "/reminders/",
            "/members/",
            "/appearance/",
            "/items/new",
            "/find/",
            "/items/labels",
            "/legal/",
            "/sort/",
        ):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} -> {r.status_code}")
            self.assertNotIn(b"Traceback", r.data)
            self.assertNotIn(b"Internal Server Error", r.data)
        home = self.client.get("/")
        body = home.data.decode("utf-8", "replace")
        self.assertIn("What this household needs", body)
        self.assertIn("House", body)
        self.assertIn('action="/find/"', body)
        find = self.client.get("/find/?q=milk")
        self.assertEqual(find.status_code, 200)
        self.assertNotIn(b"Traceback", find.data)
        house = self.client.get("/house/", follow_redirects=True)
        self.assertEqual(house.status_code, 200)
        self.assertIn(b"Systems", house.data)
        self.assertIn(b"HVAC", house.data)
        members = self.client.get("/members/")
        self.assertIn(b"Where things live", members.data)
        plat = self.client.get("/platform/login")
        self.assertEqual(plat.status_code, 200)
        self.assertNotIn(b"Bootstrap token", plat.data)
        self.assertNotIn(b"PLATFORM_BOOTSTRAP", plat.data)
        rem = self.client.get("/reminders/")
        self.assertIn(b"Oil change", rem.data)
        self.assertIn(b"Every 6 months", rem.data)
        self.assertNotIn(b"placeholder=\"oil_change\"", rem.data)
        basket = self.client.get("/groceries/list")
        self.assertIn(b"basket-live", basket.data)
        self.assertIn(b'FAMILY_SCAN_KIND = "basket"', basket.data)
        js = self.client.get("/groceries/list.json")
        self.assertEqual(js.status_code, 200)
        self.assertIn("rows", js.get_json())

    def test_register_without_household_name(self):
        user = f"noname_{self.suffix}"
        r = self._register(user, household="", name="Maya")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8", "replace").replace("&#39;", "'")
        self.assertIn("You're in, Maya", body)
        self.assertIn("side-nav", body)
        self.assertIn("Records", body)
        with self.app.app_context():
            u = User.query.filter_by(username=user).first()
            self.assertIsNotNone(u)
            self.assertEqual(u.household.name, "Maya's house")

    def test_family_key_note_and_legal_record(self):
        admin = f"rec_a_{self.suffix}"
        self._register(admin, household=f"Records {self.suffix}", name="Admin")
        page = self.client.get("/members/")
        token = self._csrf(page.data)
        inv = self.client.post(
            "/members/invite",
            data={"role": "member", "label": "Cousin Mike", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(inv.status_code, 200)
        self.assertIn(b"Cousin Mike", inv.data)
        m = re.search(r"Family key ([A-Z0-9-]+)", inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(m, inv.data[-800:])

        legal = self.client.get("/legal/")
        self.assertEqual(legal.status_code, 200)
        self.assertIn(b"Citations, notices", legal.data)
        token = self._csrf(legal.data)
        added = self.client.post(
            "/legal/add",
            data={
                "title": "Parking ticket downtown",
                "kind": "citation",
                "agency": "Springfield",
                "case_number": "T-99",
                "location": "Main St",
                "issued_on": "2026-09-01",
                "amount": "75.00",
                "status": "open",
                "body": "Left on the wiper.",
                "csrf_token": token,
                "file": (io.BytesIO(_png()), "ticket.png"),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(added.status_code, 200, added.data[-400:])
        self.assertIn(b"Parking ticket downtown", added.data)
        self.assertIn(b"Springfield", added.data)
        self.assertIn(b"T-99", added.data)
        find = self.client.get("/find/?q=Springfield")
        self.assertEqual(find.status_code, 200)
        self.assertIn(b"Parking ticket downtown", find.data)
        with self.app.app_context():
            from app.builddb.table_legal_records import LegalRecord
            from app.builddb.table_legal_files import LegalFile

            rec = None
            for row in LegalRecord.query.order_by(LegalRecord.id.desc()).limit(40).all():
                if row.title == "Parking ticket downtown":
                    rec = row
                    break
            self.assertIsNotNone(rec)
            rec_id = rec.id
            frow = LegalFile.query.filter_by(record_id=rec_id).first()
            self.assertIsNotNone(frow)
            fid = frow.id
        img = self.client.get(f"/legal/file/{fid}")
        self.assertEqual(img.status_code, 200)
        self.assertTrue(img.data.startswith(b"\x89PNG") or len(img.data) > 8)

        html = self.client.get("/members/").data
        token = self._csrf(html)
        child_inv = self.client.post(
            "/members/invite",
            data={"role": "child", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        cm = re.search(r"Family key ([A-Z0-9-]+)", child_inv.data.decode("utf-8", "replace"))
        self.assertIsNotNone(cm)
        child = f"rec_kid_{self.suffix}"
        self._register(child, invite=cm.group(1), name="Kid")
        blocked = self.client.get("/legal/")
        self.assertEqual(blocked.status_code, 403)
        sneak = self.client.get(f"/legal/{rec_id}")
        self.assertEqual(sneak.status_code, 403)


if __name__ == "__main__":
    unittest.main()
