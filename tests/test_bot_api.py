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