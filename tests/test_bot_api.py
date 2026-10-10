"""Bot API end-to-end: key pair, exchange, scopes, rate limits, revocation.

Uses the local schema like the other flow tests. Mail is captured with a
patch, so nothing leaves the box and the raw keys are readable in the test.
"""
from __future__ import annotations

import json
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
from app.builddb.table_bot_api_audit import BotApiAudit
from app.builddb.table_bot_api_keys import BotApiKey
from app.builddb.table_users import User
from app.utils import bot_api_keys as keys
from app.utils import twofa


class BotApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        # The test client speaks plain HTTP. Everything else about the API is
        # exercised for real; only this one gate is stood down.
        cls.app.config["BOT_API_ALLOW_INSECURE"] = True
        cls.app.config["BOT_API_SESSION_TTL"] = 3600
        # The suite does far more exchanges in one minute than a real bot.
        cls.app.config["BOT_API_EXCHANGE_RATE"] = 5000
        cls.app.config["BOT_API_READ_RATE"] = 5000
        cls.app.config["BOT_API_WRITE_RATE"] = 5000
        cls.app.config["BOT_API_IP_RATE"] = 20000
        cls.suffix = os.urandom(3).hex()
        cls.secret = twofa.new_totp_secret()
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=80, days=30, label="botapi-tests").code

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()

    # ------------------------------------------------------------- helpers

    def _web(self):
        """A logged-out client for the People UI."""
        return self.app.test_client()

    def _csrf(self, client) -> str:
        r = client.get("/", follow_redirects=True)
        text = r.data.decode("utf-8", "replace")
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        if m:
            return m.group(1)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
        return m.group(1) if m else ""

    def _post(self, client, url, data=None, **kw):
        payload = dict(data or {})
        payload.setdefault("csrf_token", self._csrf(client))
        return client.post(url, data=payload, **kw)

    def _logged_in(self, client) -> bool:
        return client.get("/").status_code == 200

    def _register_founder(self, house: str = "a") -> str:
        """Idempotent. `house` picks which household this founder owns."""
        client = self._web()
        u = f"botapi_founder_{house}_{self.suffix}"
        client.post("/auth/login", data={"username": u, "password": "FamilyTest1!"})
        if self._logged_in(client):
            return u
        client.post(
            "/auth/register",
            data={
                "name": "Bot API Founder",
                "username": u,
                "email": f"{u}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"BotApi House {house} {self.suffix}",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )
        self.assertTrue(self._logged_in(client))
        return u

    def _add_bot(self, slug: str, *, leader=False, house: str = "a", role: str = "") -> str:
        """A bot with 2FA on and three different inboxes, in one household."""
        u = f"botapi_{house}_{slug}_{self.suffix}"
        client = self._web()
        founder = self._register_founder(house)
        client.post("/auth/login", data={"username": founder, "password": "FamilyTest1!"})
        self.assertTrue(self._logged_in(client))
        r = self._post(
            client,
            "/members/add",
            data={
                "person_name": f"Bot {slug}",
                "username": u,
                "email": f"{u}@family.test",
                "role": role or ("admin" if leader else "member"),
                "password": "BotPass123!",
                "is_bot": "1",
                "security_email": f"{u}.codes@family.test",
                "reset_email": f"{u}.resets@family.test",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200, r.data[-300:])
        with self.app.app_context():
            user = User.query.filter_by(username=u).first()
            self.assertIsNotNone(user, f"bot {u} not created")
            self.assertTrue(user.is_bot)
            twofa.save_twofa(user, method="app", secret=self.secret)
            db.session.commit()
        return u

    def _issue(self, username: str, scope: str = "fos_bot_") -> dict:
        """Mint the permanent login key, then a one-hour 2FA key for the tests."""
        sent: list[tuple[str, str, str]] = []

        def fake_send(to, subject, body, **kw):
            sent.append((to, subject, body))
            return True, "ok"

        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            hh = user.household
            with patch("app.utils.mail.send_mail", side_effect=fake_send):
                ok, detail, pair = keys.issue_keys(
                    user, scope, household=hh, base_url="https://family.poweredby.top"
                )
            self.assertTrue(ok, detail)
            self.assertEqual(len(sent), 1, sent)
            row = BotApiKey.query.filter_by(key_hash=keys.hash_key(pair["primary"])).one()
            _two, raw = keys.mint_twofa(row)
            db.session.commit()
            pair["twofa"] = raw
            return {"pair": pair, "sent": sent}

    def _exchange(self, primary: str, second: str) -> str:
        r = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {primary}", "X-FOS-2FA": second},
        )
        self.assertEqual(r.status_code, 200, r.data[:400])
        return json.loads(r.data)["token"]

    def _get_post(self, url, *, headers=None, method="get", json_body=None):
        c = self.app.test_client()
        kw = {"headers": dict(headers or {})}
        if json_body is not None:
            kw["json"] = json_body
        return getattr(c, method)(url, **kw)

    def _api(self, token: str, url: str, method="get", json_body=None):
        return self._get_post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method=method,
            json_body=json_body,
        )

    # --------------------------------------------------------------- tests

    def test_01_login_key_is_permanent_and_2fa_lasts_an_hour(self):
        u = self._add_bot("mail")
        issued = self._issue(u)
        pair = issued["pair"]
        self.assertTrue(pair["primary"].startswith("fos_bot_"), pair["primary"])
        self.assertTrue(pair["twofa"].startswith("fos_bot_"), pair["twofa"])
        self.assertNotEqual(pair["primary"], pair["twofa"])
        inboxes = {t for t, _, _ in issued["sent"]}
        self.assertEqual(inboxes, {f"{u}@family.test"})
        login_body = issued["sent"][0][2]
        self.assertIn(pair["primary"], login_body)
        self.assertNotIn(pair["twofa"], login_body)
        self.assertIn("does not expire", login_body)
        with self.app.app_context():
            rows = {
                r.key_role: r
                for r in BotApiKey.query.filter_by(
                    user_id=User.query.filter_by(username=u).first().id, revoked_at=None
                ).all()
            }
            self.assertIsNone(rows["primary"].expires_at)
            left = (keys._naive(rows["twofa"].expires_at) - keys._utcnow()).total_seconds()
            self.assertGreater(left, 3500)
            self.assertLess(left, 3700)

    def test_01b_present_emails_a_one_hour_key_and_exchange_spends_it(self):
        u = self._add_bot("present")
        sent: list[tuple[str, str, str]] = []

        def fake_send(to, subject, body, **kw):
            sent.append((to, subject, body))
            return True, "ok"

        with self.app.app_context():
            user = User.query.filter_by(username=u).first()
            with patch("app.utils.mail.send_mail", side_effect=fake_send):
                ok, detail, pair = keys.issue_keys(
                    user, "fos_bot_", household=user.household, base_url="https://family.poweredby.top"
                )
            self.assertTrue(ok, detail)
        sent.clear()
        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            presented = self._get_post(
                "/api/v1/auth/present",
                method="post",
                headers={"Authorization": f"Bearer {pair['primary']}"},
            )
        self.assertEqual(presented.status_code, 200, presented.data[:400])
        payload = json.loads(presented.data)
        self.assertTrue(payload["sent"])
        self.assertEqual(payload["expires_in"], 3600)
        self.assertEqual(len(sent), 1, sent)
        self.assertEqual(sent[0][0], f"{u}.codes@family.test")
        self.assertNotIn(pair["primary"], sent[0][2])
        raw = next(line.strip() for line in sent[0][2].splitlines() if line.strip().startswith("fos_"))
        self.assertNotIn(raw, presented.get_data(as_text=True))
        token = self._exchange(pair["primary"], raw)
        self.assertTrue(token.startswith("fos_s1_"))
        again = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {pair['primary']}", "X-FOS-2FA": raw},
        )
        self.assertEqual(again.status_code, 401, again.data[:300])
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 200)

    def test_01c_helper_lists_routes_and_me_is_whoami(self):
        u = self._add_bot("map")
        pair = self._issue(u)["pair"]
        token = self._exchange(pair["primary"], pair["twofa"])
        missing = self._get_post("/api/v1/helper")
        self.assertEqual(missing.status_code, 401, missing.data[:200])

        helper = self._api(token, "/api/v1/helper")
        self.assertEqual(helper.status_code, 200, helper.data[:400])
        body = json.loads(helper.data)
        self.assertTrue(body["ok"])
        self.assertIn("glad you're looking", body["greeting"])
        lines = body["data"]["lines"]
        self.assertIn("GET /api/v1/me", "\n".join(lines))
        self.assertIn("GET /api/v1/vehicles", "\n".join(lines))
        self.assertIn("POST /api/v1/tools", "\n".join(lines))
        self.assertIn("POST /api/v1/items/<id>/oil", "\n".join(lines))
        self.assertIn("GET /api/v1/vault", "\n".join(lines))
        guide = body["data"]["guide"]
        self.assertIn("5W-30", guide)
        self.assertIn("scope_denied", guide)
        self.assertIn("Gas generator", guide)
        same = json.loads(self._api(token, "/api/v1/help").data)
        self.assertEqual(same["data"]["lines"], lines)

        me = json.loads(self._api(token, "/api/v1/me").data)
        who = json.loads(self._api(token, "/api/v1/whoami").data)
        self.assertEqual(me["bot"], u)
        self.assertEqual(me["bot"], who["bot"])
        self.assertEqual(me["me"], "GET /api/v1/me")
        self.assertEqual(me["helper"], "GET /api/v1/helper")

        vault_user = self._add_bot("mapv", house="b")
        vault_pair = self._issue(vault_user, "fos_vault_")["pair"]
        vault_token = self._exchange(vault_pair["primary"], vault_pair["twofa"])
        vault_lines = "\n".join(json.loads(self._api(vault_token, "/api/v1/helper").data)["data"]["lines"])
        self.assertIn("GET /api/v1/vault", vault_lines)
        self.assertNotIn("POST /api/v1/vehicles", vault_lines)
        self.assertNotIn("GET /api/v1/notes", vault_lines)
        vault_body = json.loads(self._api(vault_token, "/api/v1/helper").data)
        self.assertIn("cannot change the house", vault_body["data"]["guide"])
        self.assertNotIn("POST /api/v1/tools", vault_body["data"]["guide"])

    def test_02_only_hashes_are_stored(self):
        u = self._add_bot("hash")
        pair = self._issue(u)["pair"]
        with self.app.app_context():
            rows = BotApiKey.query.filter_by(user_id=User.query.filter_by(username=u).first().id).all()
            self.assertEqual(len(rows), 2)
            stored = " ".join(r.key_hash for r in rows)
            self.assertNotIn(pair["primary"], stored)
            self.assertNotIn(pair["twofa"], stored)
            self.assertIn(keys.hash_key(pair["primary"]), [r.key_hash for r in rows])

    def test_03_exchange_then_read_and_write(self):
        u = self._add_bot("core")
        pair = self._issue(u)["pair"]
        token = self._exchange(pair["primary"], pair["twofa"])

        me = self._api(token, "/api/v1/whoami")
        self.assertEqual(me.status_code, 200, me.data[:300])
        payload = json.loads(me.data)
        self.assertEqual(payload["scope"], "fos_bot_")
        self.assertEqual(payload["bot"], u)

        made = self._api(token, "/api/v1/vehicles", method="post", json_body={
            "name": "API Tundra", "year": 2006, "make": "Toyota", "model": "Tundra",
            "oil_needs": "5W-30", "current_mileage": 78000,
        })
        self.assertEqual(made.status_code, 201, made.data[:400])
        truck = json.loads(made.data)["vehicle"]
        self.assertEqual(truck["name"], "API Tundra")
        self.assertEqual(truck["vehicle"]["oil_needs"], "5W-30")
        self.assertEqual(truck["vehicle"]["current_mileage"], 78000)

        patched = self._api(token, f"/api/v1/vehicles/{truck['id']}", method="patch",
                            json_body={"current_mileage": 79000, "plate": "TND-1"})
        self.assertEqual(patched.status_code, 200, patched.data[:300])
        self.assertEqual(json.loads(patched.data)["vehicle"]["vehicle"]["current_mileage"], 79000)

        listed = self._api(token, "/api/v1/vehicles")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(v["id"] == truck["id"] for v in json.loads(listed.data)["vehicles"]))

    def test_04_notes_inventory_records(self):
        u = self._add_bot("docs")
        token = self._exchange(*self._pair_of(u))

        note = self._api(token, "/api/v1/notes", method="post", json_body={
            "title": "Winter tires", "body": "Mount before the first freeze", "visibility": "household",
        })
        self.assertEqual(note.status_code, 201, note.data[:300])
        note_id = json.loads(note.data)["note"]["id"]
        self.assertEqual(json.loads(note.data)["note"]["title"], "Winter tires")

        item = self._api(token, "/api/v1/inventory", method="post", json_body={
            "name": "Milk", "item_type": "grocery", "quantity": 2, "location": "fridge",
        })
        self.assertEqual(item.status_code, 201, item.data[:300])
        item_id = json.loads(item.data)["item"]["id"]
        self.assertEqual(json.loads(item.data)["item"]["grocery"]["quantity"], 2.0)

        counted = self._api(token, f"/api/v1/inventory/{item_id}", method="patch", json_body={"quantity": 1})
        self.assertEqual(counted.status_code, 200, counted.data[:300])
        self.assertEqual(json.loads(counted.data)["item"]["grocery"]["quantity"], 1.0)
        self.assertTrue(json.loads(counted.data)["item"]["grocery"]["needs_restock"])

        rec = self._api(token, "/api/v1/records", method="post", json_body={
            "title": "Parking ticket", "kind": "ticket", "issued_on": "2026-03-01",
            "due_on": "2026-04-01", "amount": "45.00",
        })
        self.assertEqual(rec.status_code, 201, rec.data[:300])
        rec_id = json.loads(rec.data)["record"]["id"]
        self.assertEqual(json.loads(rec.data)["record"]["title"], "Parking ticket")

        listed = self._api(token, f"/api/v1/records/{rec_id}")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(json.loads(listed.data)["record"]["amount"], 45.0)
        self.assertEqual(note_id > 0, True)

        import io

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        added = self.app.test_client().post(
            f"/api/v1/records/{rec_id}/files",
            data={"caption": "Paid receipt", "file": (io.BytesIO(png), "receipt.png")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(added.status_code, 201, added.data[:400])
        uploaded = json.loads(added.data)
        self.assertEqual(uploaded["file"]["caption"], "Paid receipt")
        self.assertEqual(len(uploaded["record"]["files"]), 1)
        fid = uploaded["file"]["id"]
        got = self._api(token, f"/api/v1/records/{rec_id}/files/{fid}")
        self.assertEqual(got.status_code, 200, got.data[:120])
        self.assertTrue(got.data.startswith(b"\x89PNG"))
        paid = self.app.test_client().patch(
            f"/api/v1/records/{rec_id}",
            data={
                "status": "paid",
                "outcome": "Paid at the window",
                "file": (io.BytesIO(png), "second.png"),
            },
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(paid.status_code, 200, paid.data[:400])
        paid_body = json.loads(paid.data)["record"]
        self.assertEqual(paid_body["status"], "paid")
        self.assertEqual(paid_body["outcome"], "Paid at the window")
        self.assertEqual(len(paid_body["files"]), 2)
        rejected = self.app.test_client().post(
            f"/api/v1/records/{rec_id}/files",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(rejected.status_code, 400, rejected.data[:300])
        child = self._add_bot("receiptkid", role="child")
        ctoken = self._exchange(*self._pair_of(child))
        denied = self.app.test_client().post(
            f"/api/v1/records/{rec_id}/files",
            data={"file": (io.BytesIO(png), "nope.png")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {ctoken}"},
        )
        self.assertEqual(denied.status_code, 403, denied.data[:300])
        other = self._add_bot("receiptb", house="b")
        otoken = self._exchange(*self._pair_of(other))
        missing = self._api(otoken, f"/api/v1/records/{rec_id}/files")
        self.assertEqual(missing.status_code, 404, missing.data[:300])

    def test_05_no_token_and_bad_token_are_refused(self):
        u = self._add_bot("auth")
        anon = self._api("", "/api/v1/vehicles")
        self.assertEqual(anon.status_code, 401)

        garbage = self._api("fos_s1_not_a_real_token", "/api/v1/vehicles")
        self.assertEqual(garbage.status_code, 401)

        # A raw API key is not a session token.
        pair = self._issue(u)["pair"]
        raw_key = self._api(pair["primary"], "/api/v1/vehicles")
        self.assertEqual(raw_key.status_code, 401)

    def test_06_house_key_stays_inside_the_account(self):
        u = self._add_bot("scope")
        token = self._exchange(*self._pair_of(u))
        me = json.loads(self._api(token, "/api/v1/whoami").data)
        self.assertEqual(me["account"]["role"], "member")
        self.assertTrue(me["account"]["can"]["legal"])
        self.assertTrue(me["account"]["can"]["vault"])
        self.assertFalse(me["account"]["can"]["members"])
        # A member may open the vault with the house key. The list is empty here.
        vault = self._api(token, "/api/v1/vault")
        self.assertEqual(vault.status_code, 200, vault.data[:300])
        self.assertEqual(json.loads(vault.data)["entries"], [])

        child = self._add_bot("child", role="child")
        ctoken = self._exchange(*self._pair_of(child))
        denied = self._api(ctoken, "/api/v1/records")
        self.assertEqual(denied.status_code, 403, denied.data[:300])
        self.assertEqual(json.loads(denied.data)["code"], "forbidden")
        truck = self._api(ctoken, "/api/v1/vehicles", method="post", json_body={"name": "Nope"})
        self.assertEqual(truck.status_code, 403, truck.data[:300])
        child_vault = self._api(ctoken, "/api/v1/vault")
        self.assertEqual(child_vault.status_code, 403, child_vault.data[:300])
        self.assertEqual(json.loads(child_vault.data)["code"], "vault_forbidden")
        # A child can still see the house and add a basket line.
        self.assertEqual(self._api(ctoken, "/api/v1/vehicles").status_code, 200)
        basket = self._api(ctoken, "/api/v1/basket", method="post", json_body={"name": "Milk"})
        self.assertEqual(basket.status_code, 201, basket.data[:300])
        self.assertEqual(json.loads(basket.data)["entry"]["name"], "Milk")
        self.assertEqual(self._api(token, "/api/v1/reminders").status_code, 200)
        self.assertEqual(self._api(token, "/api/v1/tools").status_code, 200)
        self.assertEqual(self._api(token, "/api/v1/house").status_code, 200)
        people = self._api(token, "/api/v1/people")
        self.assertEqual(people.status_code, 200, people.data[:300])
        person = json.loads(people.data)["people"][0]
        self.assertNotIn("password", person)
        self.assertNotIn("security_email", person)
        self.assertEqual(self._api(ctoken, "/api/v1/people").status_code, 403)
        self.assertEqual(self._api(ctoken, "/api/v1/activity").status_code, 403)
        due = self._api(ctoken, "/api/v1/reminders", method="post", json_body={"title": "Nope"})
        self.assertEqual(due.status_code, 403, due.data[:300])

    def test_07_vault_bot_reads_only_its_own_house(self):
        u = self._add_bot("vault", leader=True)
        with self.app.app_context():
            from app.utils.password_vault import encrypt_vault_text

            user = User.query.filter_by(username=u).first()
            hid = int(user.household_id)
            entry_id = self._seed_vault(hid, user.id, encrypt_vault_text)
        pair = self._issue(u, "fos_vault_")["pair"]
        self.assertTrue(pair["primary"].startswith("fos_vault_"), pair["primary"])
        token = self._exchange(pair["primary"], pair["twofa"])

        me = self._api(token, "/api/v1/whoami")
        self.assertEqual(json.loads(me.data)["scope"], "fos_vault_")

        listed = self._api(token, "/api/v1/vault")
        self.assertEqual(listed.status_code, 200, listed.data[:300])
        entries = json.loads(listed.data)["entries"]
        self.assertTrue(any(e["id"] == entry_id for e in entries))
        # The list must not carry any secret.
        self.assertNotIn("secret", entries[0])
        self.assertNotIn("API-Vault-Secret", listed.data.decode("utf-8", "replace"))

        opened = self._api(token, f"/api/v1/vault/{entry_id}")
        self.assertEqual(opened.status_code, 200, opened.data[:300])
        card = json.loads(opened.data)["entry"]
        self.assertEqual(card["secret"], "API-Vault-Secret")
        self.assertEqual(card["login"], "house@example.test")

        # Read-only: a house write route and any DELETE are both refused.
        self.assertEqual(self._api(token, "/api/v1/vehicles").status_code, 403)
        self.assertEqual(
            self._api(token, f"/api/v1/vault/{entry_id}", method="patch", json_body={}).status_code,
            405,
        )

    def _seed_vault(self, hid: int, uid: int, encrypt) -> int:
        from app.builddb.table_vault_entries import VaultEntry

        entry = VaultEntry(
            household_id=hid,
            created_by=uid,
            kind="password",
            share_mode="household",
            title=encrypt("Streaming", hid),
            login=encrypt("house@example.test", hid),
            secret=encrypt("API-Vault-Secret", hid),
            url=encrypt("stream.example.test", hid),
        )
        db.session.add(entry)
        db.session.commit()
        return int(entry.id)

    def _pair_of(self, username: str) -> tuple[str, str]:
        pair = self._issue(username)["pair"]
        return pair["primary"], pair["twofa"]

    def test_08_cross_household_isolation(self):
        bot_a = self._add_bot("tenant_a", house="a")
        bot_b = self._add_bot("tenant_b", house="b")
        token_a = self._exchange(*self._pair_of(bot_a))
        created = self._api(token_a, "/api/v1/inventory", method="post",
                            json_body={"name": "A-only milk"})
        self.assertEqual(created.status_code, 201, created.data[:300])
        item_id = json.loads(created.data)["item"]["id"]

        token_b = self._exchange(*self._pair_of(bot_b))
        self.assertEqual(self._api(token_b, f"/api/v1/inventory/{item_id}").status_code, 404)
        listed = json.loads(self._api(token_b, "/api/v1/inventory").data)
        self.assertFalse(any(i["id"] == item_id for i in listed["items"]))

    def test_09_reset_kills_the_old_keys_and_their_sessions(self):
        u = self._add_bot("reset")
        old = self._issue(u)["pair"]
        token = self._exchange(old["primary"], old["twofa"])
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 200)

        fresh = self._issue(u)["pair"]
        self.assertNotEqual(old["primary"], fresh["primary"])
        # The old session is dead the moment the pair is replaced.
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 401)
        # The old pair cannot be exchanged again.
        again = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {old['primary']}", "X-FOS-2FA": old["twofa"]},
        )
        self.assertEqual(again.status_code, 401, again.data[:300])
        # The new one works.
        self.assertEqual(
            self._api(self._exchange(fresh["primary"], fresh["twofa"]), "/api/v1/whoami").status_code, 200
        )

    def test_10_halves_from_two_different_bots_do_not_pair(self):
        a = self._add_bot("mix_a")
        b = self._add_bot("mix_b")
        pa = self._issue(a)["pair"]
        pb = self._issue(b)["pair"]
        r = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {pa['primary']}", "X-FOS-2FA": pb["twofa"]},
        )
        self.assertEqual(r.status_code, 401)

    def test_11_swapped_halves_are_refused(self):
        u = self._add_bot("swap")
        pair = self._issue(u)["pair"]
        r = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {pair['twofa']}", "X-FOS-2FA": pair["primary"]},
        )
        self.assertEqual(r.status_code, 401)

    def test_12_one_key_cannot_stand_in_for_itself(self):
        u = self._add_bot("double")
        pair = self._issue(u)["pair"]
        r = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={"Authorization": f"Bearer {pair['primary']}", "X-FOS-2FA": pair["primary"]},
        )
        self.assertEqual(r.status_code, 401)

    def test_13_https_is_required(self):
        u = self._add_bot("https")
        token = self._exchange(*self._pair_of(u))
        self.app.config["BOT_API_ALLOW_INSECURE"] = False
        try:
            c = self.app.test_client()
            auth = {"Authorization": f"Bearer {token}"}
            blocked = c.get("/api/v1/whoami", headers=auth, base_url="http://localhost")
            self.assertEqual(blocked.status_code, 403, blocked.data[:300])
            self.assertEqual(json.loads(blocked.data)["code"], "https_required")
            # The test client speaks HTTPS by default. That must be allowed.
            direct = c.get("/api/v1/whoami", headers=auth)
            self.assertEqual(direct.status_code, 200, direct.data[:300])
            local = c.get(
                "/api/v1/whoami",
                headers={**auth, "X-Forwarded-Proto": "https"},
                base_url="http://localhost",
            )
            self.assertEqual(local.status_code, 200, local.data[:300])
            cf = c.get(
                "/api/v1/whoami",
                headers={**auth, "CF-Visitor": '{"scheme":"https"}'},
                base_url="http://localhost",
                environ_base={"REMOTE_ADDR": "104.16.1.1"},
            )
            self.assertEqual(cf.status_code, 200, cf.data[:300])
            # HostM/Cloudflare: the socket address is the visitor, and the
            # proxy says the visitor used https. That must be allowed.
            visitor = c.get(
                "/api/v1/whoami",
                headers={
                    **auth,
                    "X-Forwarded-For": "203.0.113.9",
                    "X-Forwarded-Proto": "https",
                    "CF-Ray": "a447f3f5ed66f2f6-DFW",
                    "CF-Visitor": '{"scheme":"https"}',
                },
                base_url="http://localhost",
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            )
            self.assertEqual(visitor.status_code, 200, visitor.data[:300])
            # A later hop appends its own clear-text scheme. Cloudflare's
            # visitor scheme still counts.
            appended = c.get(
                "/api/v1/whoami",
                headers={**auth, "X-Forwarded-Proto": "https, http"},
                base_url="http://localhost",
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            )
            self.assertEqual(appended.status_code, 200, appended.data[:300])
            plain = c.get(
                "/api/v1/whoami",
                headers={**auth, "X-Forwarded-Proto": "http"},
                base_url="http://localhost",
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            )
            self.assertEqual(plain.status_code, 403, plain.data[:300])
            self.assertEqual(json.loads(plain.data)["code"], "https_required")
        finally:
            self.app.config["BOT_API_ALLOW_INSECURE"] = True

    def test_13b_curl_on_the_bot_api_is_not_blocked(self):
        u = self._add_bot("curlbot")
        token = self._exchange(*self._pair_of(u))
        r = self._get_post(
            "/api/v1/whoami",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "curl/8.7.1"},
        )
        self.assertEqual(r.status_code, 200, r.data[:300])
        posted = self._get_post(
            "/api/v1/auth/exchange",
            method="post",
            headers={
                "Authorization": "Bearer fos_bot_not-a-real-key",
                "X-FOS-2FA": "nope",
                "User-Agent": "python-requests/2.32.0",
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertNotEqual(posted.status_code, 403, posted.data[:300])
        self.assertEqual(posted.status_code, 401, posted.data[:300])

    def test_14_rate_limit_stops_a_run(self):
        u = self._add_bot("rate")
        token = self._exchange(*self._pair_of(u))
        old = self.app.config.get("BOT_API_READ_RATE")
        self.app.config["BOT_API_READ_RATE"] = 3
        try:
            codes = [self._api(token, "/api/v1/whoami").status_code for _ in range(6)]
            self.assertIn(429, codes, codes)
        finally:
            self.app.config["BOT_API_READ_RATE"] = old or 5000

    def test_15_every_call_is_audited(self):
        u = self._add_bot("audit")
        token = self._exchange(*self._pair_of(u))
        self._api(token, "/api/v1/vehicles")
        self._api(token, "/api/v1/nope")
        with self.app.app_context():
            uid = User.query.filter_by(username=u).first().id
            rows = BotApiAudit.query.filter_by(user_id=uid).all()
            events = {r.event for r in rows}
            self.assertIn("exchange", events)
            self.assertIn("call", rows[-1].event)
            paths = {r.path for r in rows if r.event == "call"}
            self.assertIn("/api/v1/vehicles", paths)

    def test_16_a_vault_read_is_audited_separately(self):
        u = self._add_bot("audit_vault", leader=True)
        with self.app.app_context():
            from app.utils.password_vault import encrypt_vault_text

            user = User.query.filter_by(username=u).first()
            entry_id = self._seed_vault(int(user.household_id), user.id, encrypt_vault_text)
        pair = self._issue(u, "fos_vault_")["pair"]
        token = self._exchange(pair["primary"], pair["twofa"])
        self._api(token, f"/api/v1/vault/{entry_id}")
        with self.app.app_context():
            uid = User.query.filter_by(username=u).first().id
            rows = BotApiAudit.query.filter_by(user_id=uid, event="vault.read").all()
            self.assertTrue(rows)
            self.assertEqual(rows[-1].outcome, "revealed")

    def test_17_revoke_ends_a_session(self):
        u = self._add_bot("logout")
        token = self._exchange(*self._pair_of(u))
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 200)
        gone = self._api(token, "/api/v1/auth/revoke", method="post")
        self.assertEqual(gone.status_code, 200, gone.data[:300])
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 401)

    def test_17b_session_can_replace_the_login_key(self):
        u = self._add_bot("rotate")
        primary, twofa = self._pair_of(u)
        token = self._exchange(primary, twofa)
        helper = self._api(token, "/api/v1/helper")
        self.assertIn("POST /api/v1/auth/reset", helper.get_data(as_text=True))
        sent: list[tuple[str, str, str]] = []

        def fake_send(to, subject, body, **kw):
            sent.append((to, subject, body))
            return True, "ok"

        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            reset = self._api(token, "/api/v1/auth/reset", method="post")
        self.assertEqual(reset.status_code, 200, reset.data[:400])
        body = json.loads(reset.data)
        self.assertTrue(body["reset"])
        self.assertEqual(body["expires"], "never")
        text = reset.get_data(as_text=True)
        self.assertNotIn(primary, text)
        self.assertEqual(len(sent), 1, sent)
        self.assertEqual(sent[0][0], f"{u}@family.test")
        self.assertNotIn(f"{u}.codes@family.test", sent[0][2])
        self.assertIn("does not expire", sent[0][2])
        self.assertIn("/api/v1/auth/reset", sent[0][2])
        fresh = next(line.strip() for line in sent[0][2].splitlines() if line.strip().startswith("fos_bot_"))
        self.assertNotEqual(fresh, primary)
        self.assertNotIn(fresh, text)
        self.assertEqual(self._api(token, "/api/v1/whoami").status_code, 401)
        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            old = self._get_post(
                "/api/v1/auth/present",
                method="post",
                headers={"Authorization": f"Bearer {primary}"},
            )
        self.assertEqual(old.status_code, 401, old.data[:300])
        with self.app.app_context():
            row = BotApiKey.query.filter_by(key_hash=keys.hash_key(fresh)).one()
            self.assertIsNone(row.expires_at)
            self.assertIsNone(row.revoked_at)
            self.assertEqual(row.key_role, "primary")
        denied = self._get_post(
            "/api/v1/auth/reset",
            method="post",
            headers={"Authorization": f"Bearer {fresh}"},
        )
        self.assertEqual(denied.status_code, 401, denied.data[:300])

        def fail_send(to, subject, body, **kw):
            return False, "down"

        sent_twofa: list[tuple[str, str, str]] = []

        def fake_twofa(to, subject, body, **kw):
            sent_twofa.append((to, subject, body))
            return True, "ok"

        with patch("app.utils.mail.send_mail", side_effect=fake_twofa):
            presented = self._get_post(
                "/api/v1/auth/present",
                method="post",
                headers={"Authorization": f"Bearer {fresh}"},
            )
        self.assertEqual(presented.status_code, 200, presented.data[:300])
        code = next(line.strip() for line in sent_twofa[0][2].splitlines() if line.strip().startswith("fos_"))
        token2 = self._exchange(fresh, code)
        with patch("app.utils.mail.send_mail", side_effect=fail_send):
            failed = self._api(token2, "/api/v1/auth/reset", method="post")
        self.assertEqual(failed.status_code, 502, failed.data[:400])
        self.assertNotIn(fresh, failed.get_data(as_text=True))
        self.assertEqual(self._api(token2, "/api/v1/whoami").status_code, 200)

    def test_18_a_bot_without_its_inboxes_cannot_get_a_key(self):
        u = self._add_bot("noinbox")
        with self.app.app_context():
            from app.utils.access import mint_service_pass  # noqa: F401

            user = User.query.filter_by(username=u).first()
            user.security_email = user.email  # same as login again
            db.session.commit()
            ok, msg, _pair = keys.mint_pair(user, "fos_bot_")
        self.assertFalse(ok)
        self.assertIn("2FA email", msg)

    def test_19_a_non_bot_never_gets_an_api_key(self):
        u = f"botapi_plain_{self.suffix}"
        client = self._web()
        founder = self._register_founder()
        client.post("/auth/login", data={"username": founder, "password": "FamilyTest1!"})
        self._post(client, "/members/add", data={
            "person_name": "Regular Human", "username": u,
            "email": f"{u}@family.test", "role": "member", "password": "HumanPass1!",
        }, follow_redirects=True)
        with self.app.app_context():
            user = User.query.filter_by(username=u).first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_bot)
            ok, msg, _pair = keys.mint_pair(user, "fos_bot_")
        self.assertFalse(ok)
        self.assertIn("BOT", msg)

    def test_20_no_delete_in_v1(self):
        u = self._add_bot("nodelete")
        token = self._exchange(*self._pair_of(u))
        made = self._api(token, "/api/v1/inventory", method="post", json_body={"name": "Doomed"})
        item_id = json.loads(made.data)["item"]["id"]
        for url in (f"/api/v1/inventory/{item_id}", "/api/v1/vehicles/1", "/api/v1/notes/1"):
            r = self._api(token, url, method="delete")
            self.assertEqual(r.status_code, 405, f"{url} -> {r.status_code}")
        # And the row is still there.
        self.assertEqual(self._api(token, f"/api/v1/inventory/{item_id}").status_code, 200)

    # --------------------------------------------------------- the People UI

    def _leader_client(self):
        client = self._web()
        founder = self._register_founder()
        client.post("/auth/login", data={"username": founder, "password": "FamilyTest1!"})
        self.assertTrue(self._logged_in(client))
        return client

    def test_21_leader_sends_keys_from_people(self):
        u = self._add_bot("people")
        uid = self._uid_of(u)
        client = self._leader_client()
        sent: list[tuple[str, str, str]] = []

        def fake_send(to, subject, body, **kw):
            sent.append((to, subject, body))
            return True, "ok"

        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            r = self._post(
                client,
                f"/members/{uid}/bot-api",
                data={"scope": "fos_bot_", "do": "issue"},
                follow_redirects=True,
            )
        self.assertEqual(r.status_code, 200, r.data[-400:])
        self.assertIn(b"does not expire", r.data)
        self.assertIn(b"1 hour", r.data)
        self.assertEqual(len(sent), 1, sent)
        with self.app.app_context():
            pair = (
                BotApiKey.query.filter_by(
                    user_id=uid, scope="fos_bot_", revoked_at=None
                )
                .all()
            )
            self.assertEqual(len(pair), 1)
            self.assertEqual(pair[0].key_role, "primary")
            self.assertIsNone(pair[0].expires_at)

    def test_22_leader_revoke_kills_the_pair(self):
        u = self._add_bot("revoke_ui")
        uid = self._uid_of(u)
        self._issue(u)
        with self.app.app_context():
            row = BotApiKey.query.filter_by(user_id=uid, revoked_at=None).first()
            pair_id = row.pair_id
        client = self._leader_client()
        r = self._post(
            client,
            f"/members/{uid}/bot-api/revoke",
            data={"pair_id": pair_id},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200, r.data[-300:])
        self.assertIn(b"are dead", r.data)
        with self.app.app_context():
            live = BotApiKey.query.filter_by(user_id=uid, revoked_at=None).count()
        self.assertEqual(live, 0)

    def test_23_leader_cannot_grant_keys_to_a_human(self):
        u = f"botapi_human_{self.suffix}"
        client = self._leader_client()
        self._post(
            client,
            "/members/add",
            data={
                "person_name": "Just A Human", "username": u,
                "email": f"{u}@family.test", "role": "member", "password": "HumanPass1!",
            },
            follow_redirects=True,
        )
        with self.app.app_context():
            uid = User.query.filter_by(username=u).first().id
        with patch("app.utils.mail.send_mail", side_effect=lambda *a, **k: (True, "ok")):
            r = self._post(
                client,
                f"/members/{uid}/bot-api",
                data={"scope": "fos_bot_", "do": "issue"},
                follow_redirects=True,
            )
        self.assertIn(b"not a BOT account", r.data)
        with self.app.app_context():
            self.assertEqual(BotApiKey.query.filter_by(user_id=uid).count(), 0)

    def test_24_bot_can_re_send_its_own_keys(self):
        u = self._add_bot("self_send")
        first = self._issue(u)["pair"]
        client = self._web()
        client.post("/auth/login", data={"username": u, "password": "BotPass123!"})
        # Password alone only reaches the 2FA challenge; finish it properly.
        self._allow_totp_reuse(u)
        self._post(client, "/auth/2fa", data={"code": twofa.totp_at(self.secret)})
        dash = client.get("/")
        self.assertEqual(dash.status_code, 200)
        self.assertIn(b"Bot API keys", dash.data)
        # The keys themselves are never rendered on the page.
        self.assertNotIn(first["primary"].encode(), dash.data)
        self.assertNotIn(first["twofa"].encode(), dash.data)

        sent: list[tuple[str, str, str]] = []

        def fake_send(to, subject, body, **kw):
            sent.append((to, subject, body))
            return True, "ok"

        with patch("app.utils.mail.send_mail", side_effect=fake_send):
            unproved = self._post(
                client, "/auth/bot/api-keys",
                data={"scope": "fos_bot_", "current_password": "wrong"},
                follow_redirects=True,
            )
            self.assertIn(b"Prove it is you", unproved.data)
            self.assertEqual(len(sent), 0)

            with self.app.app_context():
                self._allow_totp_reuse(u)
            proved = self._post(
                client, "/auth/bot/api-keys",
                data={"scope": "fos_bot_", "twofa_code": twofa.totp_at(self.secret)},
                follow_redirects=True,
            )
        self.assertIn(b"does not expire", proved.data)
        self.assertEqual(len(sent), 1, sent)
        with self.app.app_context():
            live = BotApiKey.query.filter_by(
                user_id=User.query.filter_by(username=u).first().id, revoked_at=None
            ).all()
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].key_role, "primary")

    def test_25_list_endpoints_page(self):
        # Its own household: the shared one already holds rows from other tests.
        u = self._add_bot("paging", house="paging")
        token = self._exchange(*self._pair_of(u))
        for n in range(5):
            self._api(token, "/api/v1/inventory", method="post",
                      json_body={"name": f"Paged {n}"})
        first = json.loads(self._api(token, "/api/v1/inventory?limit=2").data)
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["has_more"])
        self.assertGreaterEqual(first["total"], 5)
        last = json.loads(self._api(token, "/api/v1/inventory?limit=2&offset=4").data)
        self.assertEqual(len(last["items"]), 1)
        self.assertFalse(last["has_more"])

    def test_26_a_house_key_finishes_the_work(self):
        u = self._add_bot("work")
        token = self._exchange(*self._pair_of(u))

        made = self._api(token, "/api/v1/tools", method="post", json_body={
            "name": "Gas generator", "oil_needs": "10W-30", "oil_capacity": "0.4 qt",
            "power_source": "gas",
        })
        self.assertEqual(made.status_code, 201, made.data[:400])
        tool = json.loads(made.data)["tool"]
        self.assertEqual(tool["name"], "Gas generator")
        self.assertEqual(tool["oil_needs"], "10W-30")
        one = json.loads(self._api(token, f"/api/v1/tools/{tool['id']}").data)
        self.assertEqual(one["tool"]["power_source"], "gas")

        oil = self._api(token, f"/api/v1/items/{tool['id']}/oil", method="post", json_body={
            "needs": "10W-30", "capacity": "0.5 qt",
        })
        self.assertEqual(oil.status_code, 200, oil.data[:400])
        self.assertEqual(json.loads(oil.data)["needs"], "10W-30")
        self.assertEqual(json.loads(oil.data)["capacity"], "0.5 qt")

        place = self._api(token, "/api/v1/house", method="post", json_body={
            "name": "Pool pump", "category": "pool",
        })
        self.assertEqual(place.status_code, 201, place.data[:400])
        house_id = json.loads(place.data)["place"]["id"]
        bare = self._api(token, f"/api/v1/items/{house_id}/oil", method="post", json_body={"needs": "5W-30"})
        self.assertEqual(bare.status_code, 400, bare.data[:300])
        not_a_truck = self._api(token, f"/api/v1/items/{house_id}/parts", method="post", json_body={"name": "Filter"})
        self.assertEqual(not_a_truck.status_code, 404, not_a_truck.data[:300])

        truck = json.loads(self._api(token, "/api/v1/vehicles", method="post", json_body={"name": "Work Truck"}).data)
        vid = truck["vehicle"]["id"]
        part = self._api(token, f"/api/v1/items/{vid}/parts", method="post", json_body={
            "name": "Oil filter", "system": "engine", "slot": "oil_filter", "brand": "Wix",
        })
        self.assertEqual(part.status_code, 201, part.data[:400])
        self.assertEqual(json.loads(part.data)["part"]["name"], "Oil filter")
        fluid = self._api(token, f"/api/v1/items/{vid}/oil", method="post", json_body={
            "fluid": "rear_diff", "value": "75W-90",
        })
        self.assertEqual(fluid.status_code, 200, fluid.data[:400])
        self.assertEqual(json.loads(fluid.data)["fluids"].get("rear_diff"), "75W-90")

        rem = json.loads(self._api(token, "/api/v1/reminders", method="post", json_body={
            "title": "Change generator oil", "type": "oil_change",
        }).data)
        patched = self._api(
            token,
            f"/api/v1/reminders/{rem['reminder']['id']}",
            method="patch",
            json_body={"notes": "after 50 hours", "status": "open"},
        )
        self.assertEqual(patched.status_code, 200, patched.data[:400])
        listed = json.loads(self._api(token, "/api/v1/reminders").data)["reminders"]
        match = next(row for row in listed if row["id"] == rem["reminder"]["id"])
        self.assertEqual(match["notes"], "after 50 hours")

        case = self._api(token, "/api/v1/cases", method="post", json_body={
            "title": "The ticket", "summary": "Follow the paper.",
        })
        self.assertEqual(case.status_code, 201, case.data[:400])
        opened = json.loads(case.data)["case"]
        self.assertEqual(opened["title"], "The ticket")
        self.assertTrue(opened["label"].startswith("Case #"))

        vault_user = self._add_bot("workv", house="workv")
        vault_pair = self._issue(vault_user, "fos_vault_")["pair"]
        vault_token = self._exchange(vault_pair["primary"], vault_pair["twofa"])
        denied = self._api(vault_token, "/api/v1/tools", method="post", json_body={"name": "Nope"})
        self.assertEqual(denied.status_code, 403, denied.data[:300])
        self.assertEqual(json.loads(denied.data)["code"], "scope_denied")

    def test_27_crawl_every_call_without_a_server_error(self):
        """Every listed route, a child, a vault key, and hostile bodies. No 500s."""
        import io
        from contextlib import redirect_stdout

        from sqlalchemy import inspect

        from app.utils.bot_api_help import HELP_CALLS

        buf = io.StringIO()
        problems: list[str] = []
        with redirect_stdout(buf):
            with self.app.app_context():
                length = getattr(
                    next(c for c in inspect(db.engine).get_columns("bot_api_audit") if c["name"] == "scope")["type"],
                    "length",
                    0,
                )
            if not length or int(length) < 64:
                problems.append(f"bot_api_audit.scope is {length}, want 64")

            house = self._exchange(*self._pair_of(self._add_bot("crawl")))
            child = self._exchange(*self._pair_of(self._add_bot("crawlk", role="child")))
            vault_user = self._add_bot("crawlv", house="crawlv")
            vault_pair = self._issue(vault_user, "fos_vault_")["pair"]
            vault = self._exchange(vault_pair["primary"], vault_pair["twofa"])

            def hit(token, method, url, json_body=None):
                try:
                    if token:
                        response = self._api(token, url, method=method, json_body=json_body)
                    else:
                        response = self._get_post(url, method=method, json_body=json_body)
                except Exception as exc:
                    problems.append(f"{method} {url} raised {type(exc).__name__}: {exc}")
                    return None
                if response.status_code >= 500:
                    problems.append(f"{method} {url} -> {response.status_code} {response.data[:180]!r}")
                elif response.status_code == 404:
                    body = response.get_json(silent=True) or {}
                    if body.get("code") != "not_found":
                        problems.append(f"{method} {url} is not a registered route ({response.data[:120]!r})")
                return response

            bare = hit(None, "get", "/api/v1/helper")
            if bare is not None and bare.status_code != 401:
                problems.append(f"helper without a token -> {bare.status_code}")

            skip_session_kill = {"/api/v1/auth/reset", "/api/v1/auth/revoke"}
            for method, path, call_scope, _needs, _what in HELP_CALLS:
                url = re.sub(r"<[^>]+>", "999999", path)
                if path == "/api/v1/find":
                    url = "/api/v1/find?q=oil"
                if path in skip_session_kill:
                    continue
                body = {} if method in ("POST", "PATCH") else None
                hit(house, method.lower(), url, body)
                if call_scope == "fos_bot_":
                    hit(vault, method.lower(), url, body)
                    hit(child, method.lower(), url, body)
                hit(None, method.lower(), url, body)
                if "<id>" in path or path.startswith("/api/v1/vehicles"):
                    hit(house, "delete", url)

            hostile = (
                ("post", "/api/v1/tools", {"name": ""}),
                ("post", "/api/v1/tools", []),
                ("post", "/api/v1/house", {"name": None, "notes": {"no": "pe"}}),
                ("post", "/api/v1/items/999999/oil", {"needs": ["5W-30"], "fluids": "nope"}),
                ("post", "/api/v1/items/999999/parts", {
                    "name": "x", "system": "nope", "slot": "nope", "cost": "nope", "installed_on": "yesterday",
                }),
                ("patch", "/api/v1/reminders/999999", {"due_at": "tomorrow", "status": "deleted", "type": "nope"}),
                ("post", "/api/v1/cases", {"title": "", "status": "nope"}),
                ("post", "/api/v1/records", {"title": "", "kind": "nope", "amount": "lots", "due_on": "tomorrow"}),
                ("post", "/api/v1/reminders", {"title": "x", "due_at": "not-a-date"}),
                ("post", "/api/v1/basket", {}),
                ("get", "/api/v1/find", None),
                ("get", "/api/v1/find?q=" + ("a" * 400), None),
                ("get", "/api/v1/vehicles?limit=foo&offset=-5", None),
                ("get", "/api/v1/photos?item_id=abc", None),
                ("get", "/api/v1/inventory?limit=0", None),
                ("delete", "/api/v1/tools/1", None),
                ("delete", "/api/v1/house/1", None),
                ("delete", "/api/v1/cases/1", None),
                ("delete", "/api/v1/reminders/1", None),
                ("delete", "/api/v1/items/1/oil", None),
                ("delete", "/api/v1/items/1/parts", None),
            )
            for method, url, payload in hostile:
                hit(house, method, url, payload)

            spare = self._exchange(*self._pair_of(self._add_bot("crawlend")))
            hit(spare, "post", "/api/v1/auth/revoke", {})
            revoked = hit(spare, "get", "/api/v1/whoami")
            if revoked is not None and revoked.status_code != 401:
                problems.append(f"revoked session still answered {revoked.status_code}")
            other = self._exchange(*self._pair_of(self._add_bot("crawlreset")))
            with patch("app.utils.mail.send_mail", return_value=(True, "ok")):
                reset = hit(other, "post", "/api/v1/auth/reset", {})
            if reset is not None and reset.status_code != 200:
                problems.append(f"reset -> {reset.status_code} {reset.data[:180]!r}")
            dead = hit(other, "get", "/api/v1/me")
            if dead is not None and dead.status_code != 401:
                problems.append(f"reset session still answered {dead.status_code}")

        noise = buf.getvalue()
        for needle in ("audit write failed", "Data too long", "Traceback"):
            if needle in noise:
                problems.append(f"log contains {needle}")
        with self.app.app_context():
            row = (
                BotApiAudit.query.filter_by(path="/api/v1/helper", outcome="missing_token")
                .order_by(BotApiAudit.id.desc())
                .first()
            )
            if row is None or row.scope != "fos_bot_,fos_vault_":
                problems.append(f"missing-token audit scope is {getattr(row, 'scope', None)!r}")
        self.assertEqual(problems, [])

    def test_28_the_key_guide_is_a_page_and_a_child_can_open_ask(self):
        from types import SimpleNamespace

        from app.utils.bot_api_help import call_allowed

        child_role = SimpleNamespace(role="child", is_authenticated=True, permissions_json=None, is_leader=False)
        member_role = SimpleNamespace(role="member", is_authenticated=True, permissions_json=None, is_leader=False)
        self.assertFalse(call_allowed(child_role, "legal"))
        self.assertTrue(call_allowed(member_role, "legal"))
        self.assertFalse(call_allowed(child_role, "maintain or edit_meta"))
        self.assertTrue(call_allowed(member_role, "maintain or edit_meta"))
        self.assertFalse(call_allowed(child_role, "vault, never a child"))
        self.assertTrue(call_allowed(child_role, "scan or edit_grocery"))

        bot = self._add_bot("guide")
        client = self._web()
        client.post("/auth/login", data={"username": bot, "password": "BotPass123!"})
        self._allow_totp_reuse(bot)
        self._post(client, "/auth/2fa", data={"code": twofa.totp_at(self.secret)})
        page = client.get("/bot-api/guide")
        self.assertEqual(page.status_code, 200, page.data[:300])
        self.assertIn(b"What this key can do", page.data)
        self.assertIn(b"POST /api/v1/tools", page.data)
        self.assertIn(b"5W-30", page.data)
        self.assertIn(b"This account can.", page.data)
        vault = client.get("/bot-api/guide?scope=fos_vault_")
        self.assertEqual(vault.status_code, 200, vault.data[:300])
        self.assertIn(b"cannot change the house", vault.data)
        self.assertNotIn(b"POST /api/v1/tools", vault.data)
        dash = client.get("/")
        self.assertIn(b"What this key can do", dash.data)

        human = self._web()
        founder = f"botapi_founder_a_{self.suffix}"
        human.post("/auth/login", data={"username": founder, "password": "FamilyTest1!"})
        self.assertEqual(human.get("/bot-api/guide").status_code, 404)
        with self.app.app_context():
            uid = User.query.filter_by(username=bot).first().id
        led = human.get(f"/members/{uid}/bot-api/guide")
        self.assertEqual(led.status_code, 200, led.data[:300])
        self.assertIn(b"Gas generator", led.data)

        kid_name = f"botapi_kid_{self.suffix}"
        self._post(human, "/members/add", data={
            "person_name": "Kid Guide",
            "username": kid_name,
            "email": f"{kid_name}@family.test",
            "role": "child",
            "password": "KidPass123!",
        }, follow_redirects=True)
        kid = self._web()
        kid.post("/auth/login", data={"username": kid_name, "password": "KidPass123!"})
        home = kid.get("/")
        self.assertEqual(home.status_code, 200, home.data[:300])
        self.assertIn(b'href="/ask/"', home.data)
        self.assertNotIn(b'href="/vault/"', home.data)
        self.assertNotIn(b'href="/legal/"', home.data)
        desk = kid.get("/ask/")
        self.assertEqual(desk.status_code, 200, desk.data[:300])
        self.assertIn(b"ask-root", desk.data)

    def test_29_chat_and_api_finish_the_same_household_jobs(self):
        """The tools Ask calls, and the house key, both finish the page's jobs."""
        from flask_login import login_user

        from app.utils.ask import run_tool

        bot = self._add_bot("cover")
        token = self._exchange(*self._pair_of(bot))

        truck = json.loads(self._api(token, "/api/v1/vehicles", method="post", json_body={"name": "Cover Truck"}).data)
        vid = truck["vehicle"]["id"]
        started = self._api(token, f"/api/v1/items/{vid}/trips", method="post", json_body={
            "action": "start", "reading": 1000, "origin": "Home", "dest": "Store",
        })
        self.assertEqual(started.status_code, 201, started.data[:400])
        self.assertEqual(json.loads(started.data)["trip"]["reading"], 1000)
        ended = self._api(token, f"/api/v1/items/{vid}/trips", method="post", json_body={
            "action": "end", "reading": 1012,
        })
        self.assertEqual(ended.status_code, 201, ended.data[:400])
        self.assertEqual(json.loads(ended.data)["trip"]["action"], "end")

        case = json.loads(self._api(token, "/api/v1/cases", method="post", json_body={
            "title": "Cover case", "summary": "From the key.",
        }).data)["case"]
        note = self._api(token, f"/api/v1/cases/{case['id']}/followups", method="post", json_body={
            "kind": "note", "body": "Called the clerk.",
        })
        self.assertEqual(note.status_code, 201, note.data[:400])
        self.assertEqual(json.loads(note.data)["followup"]["body"], "Called the clerk.")
        closed = self._api(token, f"/api/v1/cases/{case['id']}", method="patch", json_body={"status": "closed"})
        self.assertEqual(closed.status_code, 200, closed.data[:300])
        self.assertEqual(json.loads(closed.data)["case"]["status"], "closed")
        paper = json.loads(self._api(token, "/api/v1/records", method="post", json_body={
            "title": "Cover ticket", "kind": "ticket",
        }).data)["record"]
        tied = self._api(token, f"/api/v1/records/{paper['id']}", method="patch", json_body={"case_id": case["id"]})
        self.assertEqual(tied.status_code, 200, tied.data[:300])
        self.assertEqual(json.loads(tied.data)["record"]["case_id"], case["id"])
        file_fu = self._api(token, f"/api/v1/cases/{case['id']}/followups", method="post", json_body={"kind": "file"})
        self.assertEqual(file_fu.status_code, 400, file_fu.data[:300])

        milk = json.loads(self._api(token, "/api/v1/inventory", method="post", json_body={"name": "Cover milk", "quantity": 1}).data)["item"]
        dated = self._api(token, f"/api/v1/inventory/{milk['id']}", method="patch", json_body={"expires_on": "2026-11-01"})
        self.assertEqual(dated.status_code, 200, dated.data[:400])
        self.assertEqual(json.loads(dated.data)["item"]["grocery"]["expires_on"], "2026-11-01")
        bad_day = self._api(
            token,
            f"/api/v1/inventory/{milk['id']}",
            method="patch",
            json_body={"name": "Should not stick", "expires_on": "nope"},
        )
        self.assertEqual(bad_day.status_code, 400, bad_day.data[:300])
        still = json.loads(self._api(token, f"/api/v1/inventory/{milk['id']}").data)
        self.assertEqual(still["item"]["name"], "Cover milk")
        self.assertEqual(still["item"]["grocery"]["expires_on"], "2026-11-01")
        line = json.loads(self._api(token, "/api/v1/basket", method="post", json_body={"name": "Cover milk"}).data)["entry"]
        matched = self._api(token, f"/api/v1/basket/{line['id']}/match", method="post", json_body={"item_id": milk["id"]})
        self.assertEqual(matched.status_code, 200, matched.data[:400])
        self.assertEqual(json.loads(matched.data)["entry"]["status"], "done")
        gone = self._api(token, f"/api/v1/inventory/{milk['id']}", method="delete")
        self.assertEqual(gone.status_code, 405, gone.data[:200])

        with self.app.test_request_context():
            user = User.query.filter_by(username=bot).one()
            login_user(user)
            opened = run_tool("case_save", {"title": "Chat case", "summary": "Asked in chat"})
            self.assertTrue(opened.get("ok"), opened)
            followed = run_tool("case_save", {"action": "followup", "id": opened["id"], "body": "Left a message."})
            self.assertTrue(followed.get("ok"), followed)
            filed = run_tool("legal_save", {"title": "Chat ticket", "kind": "ticket"})
            self.assertTrue(filed.get("ok"), filed)
            updated = run_tool("legal_save", {
                "action": "update",
                "id": filed["id"],
                "status": "paid",
                "outcome": "Paid at the window",
                "caption": "Paid receipt",
            })
            self.assertTrue(updated.get("ok"), updated)
            self.assertEqual(updated.get("did"), "updated")
            self.assertEqual(updated.get("id"), filed["id"])
            self.assertEqual(updated.get("status"), "paid")
            again = run_tool("legal_save", {"action": "update", "q": "Chat ticket", "caption": "Paid receipt"})
            self.assertEqual(again.get("id"), filed["id"])
            second = run_tool("legal_save", {"title": "Chat ticket", "kind": "ticket"})
            self.assertNotEqual(second.get("id"), filed["id"])
            both = run_tool("legal_save", {"action": "update", "q": "Chat ticket"})
            self.assertFalse(both.get("ok"))
            self.assertIn("id", both.get("need") or [])
            from app.utils.ask_photo import attach_pending, stash_ask_photo

            self.assertTrue(stash_ask_photo(user.household_id, b"\xff\xd8\xff" + b"receipt-bytes", "image/jpeg"))
            self.assertTrue(attach_pending("legal_save", updated))
            from app.builddb.table_legal_files import LegalFile

            shots = LegalFile.query.filter_by(record_id=filed["id"]).all()
            self.assertEqual(len(shots), 1)
            self.assertEqual(shots[0].caption, "Paid receipt")
            attached = run_tool("case_save", {"action": "attach", "id": opened["id"], "record_id": filed["id"]})
            self.assertTrue(attached.get("ok"), attached)
            saved = run_tool("vehicle_save", {"name": "Chat Truck"})
            self.assertTrue(saved.get("ok"), saved)
            trip = run_tool("trip_save", {"item": "Chat Truck", "action": "start", "reading": "5000", "origin": "Home", "dest": "Work"})
            self.assertTrue(trip.get("ok"), trip)
            home = run_tool("trip_save", {"item": "Chat Truck", "action": "end", "reading": "5040"})
            self.assertTrue(home.get("ok"), home)
            noted = run_tool("note_save", {"title": "Cover note", "body": "In the drawer."})
            self.assertTrue(noted.get("ok"), noted)
            basket = run_tool("basket_add", {"names": ["Cover oats"]})
            self.assertTrue(basket.get("ok"), basket)
            due = run_tool("reminder_save", {"title": "Cover water bill", "type": "bill"})
            self.assertTrue(due.get("ok"), due)
            pull = run_tool("item_remove", {"q": "Cover milk"})
            self.assertIn("confirm", pull.get("need") or [], pull)

    def _uid_of(self, username: str) -> int:
        with self.app.app_context():
            return int(User.query.filter_by(username=username).first().id)

    def _allow_totp_reuse(self, username: str) -> None:
        with self.app.app_context():
            user = User.query.filter_by(username=username).first()
            twofa.save_twofa(user, last_totp_step=-999)
            db.session.commit()


if __name__ == "__main__":
    unittest.main()