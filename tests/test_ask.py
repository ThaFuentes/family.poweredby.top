import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask import _local_house_say, _parse_turn, _speak_house
from app.utils.household_ai import ask_available, chat_on, household_config


class ChatFlagTests(unittest.TestCase):
    def test_chat_on_by_default(self):
        h = SimpleNamespace(settings_json=None)
        self.assertTrue(chat_on(h))
        h = SimpleNamespace(settings_json={"ai": {"api_key": "x"}})
        self.assertTrue(chat_on(h))

    def test_chat_off_when_they_uncheck(self):
        h = SimpleNamespace(settings_json={"ai": {"chat": False, "api_key": "x"}})
        self.assertFalse(chat_on(h))

    def test_ask_needs_key(self):
        adult = SimpleNamespace(role="member", is_authenticated=True)
        empty = SimpleNamespace(settings_json={})
        self.assertFalse(ask_available(empty, adult))
        ready = SimpleNamespace(settings_json={"ai": {"api_key": "house-key", "provider": "gemini"}})
        self.assertTrue(ask_available(ready, adult))
        kid = SimpleNamespace(role="child", is_authenticated=True)
        self.assertFalse(ask_available(ready, kid))

    def test_household_config_exposes_chat(self):
        h = SimpleNamespace(settings_json={"ai": {"api_key": "k"}})
        cfg = household_config(h)
        self.assertTrue(cfg["chat"])
        h2 = SimpleNamespace(settings_json={"ai": {"api_key": "k", "chat": False}})
        self.assertFalse(household_config(h2)["chat"])


class ParseTests(unittest.TestCase):
    def test_tool_json(self):
        turn = _parse_turn('{"tool":"vault_save","args":{"title":"Netflix","login":"a"}}')
        self.assertEqual(turn["kind"], "tool")
        self.assertEqual(turn["tool"], "vault_save")
        self.assertEqual(turn["args"]["title"], "Netflix")

    def test_say_json(self):
        turn = _parse_turn('{"say":"Milk is in the fridge. /items/3"}')
        self.assertEqual(turn["kind"], "say")
        self.assertIn("fridge", turn["text"])

    def test_plain_answer_still_talks(self):
        turn = _parse_turn("Call the city water line: https://example.test/water")
        self.assertEqual(turn["kind"], "say")
        self.assertIn("https://example.test/water", turn["text"])

    def test_lookup_and_tool_json(self):
        turn = _parse_turn('{"tool":"lookup","args":{"upc":"012345678905"}}')
        self.assertEqual(turn["tool"], "lookup")
        turn = _parse_turn('{"tool":"tool_save","args":{"name":"Drill","serial":"SN1"}}')
        self.assertEqual(turn["tool"], "tool_save")
        turn = _parse_turn('{"tool":"reminder_save","args":{"title":"Water","type":"bill","every":"monthly"}}')
        self.assertEqual(turn["tool"], "reminder_save")
        turn = _parse_turn('{"tool":"inventory","args":{"q":"milk","action":"restock"}}')
        self.assertEqual(turn["tool"], "inventory")
        turn = _parse_turn('{"tool":"vault_unlock","args":{"password":"x"}}')
        self.assertEqual(turn["tool"], "vault_unlock")
        turn = _parse_turn('{"tool":"vehicle_save","args":{"vin":"1HGCM82633A004352"}}')
        self.assertEqual(turn["tool"], "vehicle_save")
        turn = _parse_turn('{"tool":"house","args":{"kind":"tools"}}')
        self.assertEqual(turn["tool"], "house")


class LocalHouseTests(unittest.TestCase):
    def test_tools_question_hits_local(self):
        with patch("app.utils.ask._find_items", return_value=[
            type("I", (), {"id": 4, "name": "DeWalt drill", "item_type": "tool", "grocery": None})()
        ]):
            with patch("app.utils.ask._path", return_value="/items/4"):
                say = _local_house_say("can you look up what tools i have")
        self.assertIsNotNone(say)
        self.assertIn("DeWalt drill", say)
        self.assertIn("/items/4", say)

    def test_save_tool_is_not_a_list(self):
        self.assertIsNone(_local_house_say("save a tool named hammer"))

    def test_speak_empty(self):
        text = _speak_house({"kind": "tools", "lines": [], "empty": "No tools saved yet."})
        self.assertIn("No tools", text)


class AskHttpTests(unittest.TestCase):
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

            cls.service_key = mint_service_pass(max_uses=20, days=30, label="ask-tests").code

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

    def _register(self, username, household=None, name=None):
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
            "family_key": "",
            "invite_code": "",
            "service_key": self.service_key,
        }
        return self.client.post("/auth/register", data=data, follow_redirects=True)

    def _put_key(self, chat=True):
        with self.app.app_context():
            from app.builddb.table_households import Household
            from app.builddb.table_users import User
            from app.utils.household_ai import save_household_ai

            u = User.query.filter_by(username=self.admin).first()
            h = Household.query.get(u.household_id)
            save_household_ai(
                h,
                provider="gemini",
                api_key="test-house-key",
                chat=chat,
            )

    def test_widget_follows_key_and_toggle(self):
        self.admin = f"ask_a_{self.suffix}"
        self._register(self.admin, household=f"Ask {self.suffix}", name="Pat")
        home = self.client.get("/")
        self.assertNotIn(b'id="ask-root"', home.data)
        self._put_key(chat=True)
        home = self.client.get("/")
        self.assertIn(b'id="ask-root"', home.data)
        self.assertIn(b"Ask", home.data)
        self._put_key(chat=False)
        home = self.client.get("/")
        self.assertNotIn(b'id="ask-root"', home.data)

    def test_ask_creates_vault_card_when_unlocked(self):
        self.admin = f"ask_v_{self.suffix}"
        self._register(self.admin, household=f"AskV {self.suffix}", name="Pat")
        self._put_key(chat=True)
        page = self.client.get("/vault/")
        token = self._csrf(page.data)
        self.client.post(
            "/vault/unlock",
            data={"username": self.admin, "password": "FamilyTest1!", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        replies = [
            (True, '{"tool":"vault_save","args":{"kind":"password","title":"Netflix house","login":"family@house.test","secret":"WatchIt-99","url":"https://netflix.com"}}'),
            (True, '{"say":"Saved Netflix house in the vault. /vault/"}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "Create a Netflix password family@house.test WatchIt-99"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("Netflix", data.get("say") or "")
        with self.app.app_context():
            from app.builddb.table_vault_entries import VaultEntry
            from app.utils.password_vault import open_fields

            row = VaultEntry.query.order_by(VaultEntry.id.desc()).first()
            self.assertIsNotNone(row)
            opened = open_fields(row)
            self.assertEqual(opened["title"], "Netflix house")
            self.assertEqual(opened["login"], "family@house.test")
            self.assertEqual(opened["secret"], "WatchIt-99")
            self.assertNotIn("WatchIt-99", row.secret or "")

    def test_vault_save_refuses_while_locked(self):
        self.admin = f"ask_l_{self.suffix}"
        self._register(self.admin, household=f"AskL {self.suffix}", name="Pat")
        self._put_key(chat=True)
        replies = [
            (True, '{"tool":"vault_save","args":{"title":"Bank","login":"pat","secret":"nope"}}'),
            (True, '{"say":"Vault is locked. Open /vault/ first."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "Save a bank password"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("vault_locked"))
        self.assertIn("/vault/", data.get("say") or "")

    def test_ask_creates_bill_schedule_and_tool(self):
        self.admin = f"ask_w_{self.suffix}"
        self._register(self.admin, household=f"AskW {self.suffix}", name="Pat")
        self._put_key(chat=True)
        replies = [
            (True, '{"tool":"reminder_save","args":{"title":"City water","type":"bill","due":"2026-10-01","every":"monthly"}}'),
            (True, '{"tool":"tool_save","args":{"name":"DeWalt drill","type":"drill","serial":"SN-441"}}'),
            (True, '{"say":"Water bill is due monthly. Drill is in tools."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "Add a monthly city water bill and save my DeWalt drill SN-441"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data)
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_reminders import Reminder

            bill = Reminder.query.filter_by(title="City water").order_by(Reminder.id.desc()).first()
            self.assertIsNotNone(bill)
            self.assertEqual(bill.type, "bill")
            self.assertEqual(bill.recurrence, "30d")
            drill = Item.query.filter_by(name="DeWalt drill", item_type="tool").first()
            self.assertIsNotNone(drill)
            self.assertEqual(drill.tool.serial_number, "SN-441")

    def test_ask_unlocks_vault_with_password(self):
        self.admin = f"ask_u_{self.suffix}"
        self._register(self.admin, household=f"AskU {self.suffix}", name="Pat")
        self._put_key(chat=True)
        replies = [
            (True, '{"tool":"vault_unlock","args":{"password":"FamilyTest1!"}}'),
            (True, '{"tool":"vault_save","args":{"kind":"password","title":"Wifi","login":"house","secret":"Blue-Sky"}}'),
            (True, '{"say":"Wifi is in the vault."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "Unlock with FamilyTest1! and save wifi house Blue-Sky"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data)
        self.assertFalse(data.get("vault_locked"))
        with self.app.app_context():
            from app.builddb.table_vault_entries import VaultEntry
            from app.utils.password_vault import open_fields

            from app.builddb.table_users import User

            uid = User.query.filter_by(username=self.admin).first().id
            row = VaultEntry.query.filter_by(created_by=uid).order_by(VaultEntry.id.desc()).first()
            self.assertIsNotNone(row)
            self.assertEqual(open_fields(row)["title"], "Wifi")


if __name__ == "__main__":
    unittest.main()
