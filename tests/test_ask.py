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
        turn = _parse_turn('{"tool":"place","args":{"what":"part","name":"brake pads"}}')
        self.assertEqual(turn["tool"], "place")
        turn = _parse_turn('{"tool":"member_add","args":{"name":"Sam"}}')
        self.assertEqual(turn["tool"], "member_add")
        self.assertEqual(turn["args"]["name"], "Sam")


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
        self.assertIn(b'id="ask-file"', home.data)
        self.assertIn(b'class="home-strip"', home.data)
        self.assertIn(b"/appearance/home-sheet", home.data)
        self.assertIn(b"/appearance/calendar-sheet", home.data)
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

    def _jpeg_b64(self):
        import base64
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (12, 8), (20, 40, 60)).save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()

    def _vehicle(self, name):
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_items import Item
            from app.builddb.table_users import User
            from app.builddb.table_vehicles import Vehicle

            user = User.query.filter_by(username=self.admin).first()
            item = Item(
                household_id=user.household_id,
                name=name,
                item_type="vehicle",
                created_by=user.id,
            )
            db.session.add(item)
            db.session.flush()
            db.session.add(Vehicle(item_id=item.id, household_id=user.household_id))
            db.session.commit()
            return item.id

    def test_photo_reaches_the_model(self):
        self.admin = f"ask_p_{self.suffix}"
        self._register(self.admin, household=f"AskP {self.suffix}", name="Pat")
        self._put_key(chat=True)
        seen = {}

        def fake_complete(*args, **kwargs):
            seen["image"] = kwargs.get("image_bytes")
            return True, '{"say":"That looks like a cordless drill."}'

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what tools do I have", "image": self._jpeg_b64(), "image_mime": "image/jpeg"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("drill", (resp.get_json() or {}).get("say") or "")
        self.assertTrue(seen.get("image"))
        self.assertGreater(len(seen["image"]), 20)

    def test_bad_photo_is_refused(self):
        import base64

        self.admin = f"ask_b_{self.suffix}"
        self._register(self.admin, household=f"AskB {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        resp = self.client.post(
            "/ask/message",
            json={
                "message": "file this",
                "image": base64.b64encode(b"not a photo").decode(),
                "image_mime": "image/jpeg",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("photo", (resp.get_json() or {}).get("error") or "")

    def test_place_tool_and_keep_the_photo(self):
        self.admin = f"ask_t_{self.suffix}"
        self._register(self.admin, household=f"AskT {self.suffix}", name="Pat")
        self._put_key(chat=True)
        replies = [
            (True, '{"tool":"place","args":{"what":"tool","name":"DeWalt drill","brand":"DeWalt","model":"DCD771"}}'),
            (True, '{"say":"Saved the DeWalt drill in tools."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "", "image": self._jpeg_b64(), "image_mime": "image/jpeg"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json().get("ok"), resp.get_json())
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_photo_notes import PhotoNote

            item = Item.query.filter_by(name="DeWalt drill", item_type="tool").order_by(Item.id.desc()).first()
            self.assertIsNotNone(item)
            self.assertEqual(item.tool.model, "DCD771")
            self.assertIsNotNone(PhotoNote.query.filter_by(item_id=item.id).first())

    def test_part_asks_which_vehicle(self):
        self.admin = f"ask_v2_{self.suffix}"
        self._register(self.admin, household=f"AskV2 {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._vehicle("Silverado")
        self._vehicle("Civic")
        seen = []

        def fake_complete(prompt, **kwargs):
            seen.append(prompt)
            if len(seen) == 1:
                return True, '{"tool":"place","args":{"what":"part","name":"front brake pads"}}'
            return True, '{"say":"Which vehicle should the pads go on?"}'

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "These are front brake pads"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("Which vehicle", seen[1])
        with self.app.app_context():
            from app.builddb.table_users import User
            from app.builddb.table_vehicle_parts import VehiclePart

            hid = User.query.filter_by(username=self.admin).first().household_id
            self.assertIsNone(
                VehiclePart.query.filter_by(household_id=hid, name="front brake pads").first()
            )

    def test_part_lands_on_the_only_vehicle(self):
        self.admin = f"ask_v1_{self.suffix}"
        self._register(self.admin, household=f"AskV1 {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._vehicle("Silverado")
        replies = [
            (True, '{"tool":"place","args":{"what":"part","name":"front brake pads","brand":"Wagner"}}'),
            (True, '{"say":"Pads are on the Silverado."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "front brake pads, no barcode"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json().get("ok"), resp.get_json())
        with self.app.app_context():
            from app.builddb.table_users import User
            from app.builddb.table_vehicle_parts import VehiclePart

            hid = User.query.filter_by(username=self.admin).first().household_id
            row = (
                VehiclePart.query.filter_by(household_id=hid, name="front brake pads")
                .order_by(VehiclePart.id.desc())
                .first()
            )
            self.assertIsNotNone(row)
            self.assertEqual(row.system, "brakes")
            self.assertEqual(row.slot, "pads_front")
            self.assertEqual(row.brand, "Wagner")

    def test_barcode_photo_becomes_inventory(self):
        self.admin = f"ask_g_{self.suffix}"
        self._register(self.admin, household=f"AskG {self.suffix}", name="Pat")
        self._put_key(chat=True)
        replies = [
            (True, '{"tool":"place","args":{"what":"","barcode":"012345678905"}}'),
            (True, '{"say":"Milk is in inventory."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        catalog = {
            "ok": True,
            "kind": "food",
            "kind_label": "Food",
            "suggested_type": "grocery",
            "name": "Whole milk",
            "brand": "Store",
            "barcode": "012345678905",
        }
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            with patch("app.utils.barcode_lookup.lookup_product", return_value=catalog):
                resp = self.client.post(
                    "/ask/message",
                    json={"message": "scan this", "image": self._jpeg_b64(), "image_mime": "image/jpeg"},
                    headers={"X-CSRF-Token": token},
                )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json().get("ok"), resp.get_json())
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            hid = User.query.filter_by(username=self.admin).first().household_id
            item = Item.query.filter_by(household_id=hid, barcode="012345678905").first()
            self.assertIsNotNone(item)
            self.assertEqual(item.item_type, "grocery")
            self.assertIn("milk", item.name.lower())

    def test_add_person_asks_then_creates_and_member_cannot(self):
        self.admin = f"ask_m_{self.suffix}"
        self._register(self.admin, household=f"AskM {self.suffix}", name="Pat")
        self._put_key(chat=True)
        seen = []

        def fake_need(prompt, **kwargs):
            seen.append(prompt)
            if len(seen) == 1:
                return True, '{"tool":"member_add","args":{"name":"Sam"}}'
            return True, '{"say":"Need a username that starts with a letter."}'

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_need):
            resp = self.client.post(
                "/ask/message",
                json={"message": "add a person named Sam"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("username", seen[1].lower())
        username = f"sam{self.suffix}"
        replies = [
            (True, '{"tool":"member_add","args":{"name":"Sam","username":"%s","role":"member"}}' % username),
            (True, '{"say":"Sam is in."}'),
        ]

        def fake_add(*args, **kwargs):
            return replies.pop(0)

        with patch("app.utils.ask.complete", side_effect=fake_add):
            resp = self.client.post(
                "/ask/message",
                json={"message": "username " + username},
                headers={"X-CSRF-Token": token},
            )
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200, data)
        self.assertIn("Password ", data.get("say") or "")
        self.assertIn(username, data.get("say") or "")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_users import User

            created = User.query.filter_by(username=username).first()
            self.assertIsNotNone(created)
            self.assertEqual(created.role, "member")
            self.assertFalse(created.is_leader)
            admin = User.query.filter_by(username=self.admin).first()
            admin.role = "member"
            admin.is_leader = False
            db.session.commit()
        blocked = []

        def fake_block(prompt, **kwargs):
            blocked.append(prompt)
            if len(blocked) == 1:
                return True, '{"tool":"member_add","args":{"name":"Riley","username":"riley%s"}}' % self.suffix
            return True, '{"say":"You cannot add people."}'

        with patch("app.utils.ask.complete", side_effect=fake_block):
            resp = self.client.post(
                "/ask/message",
                json={"message": "add Riley"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("cannot add a person", blocked[1].lower())
        with self.app.app_context():
            from app.builddb.table_users import User

            self.assertIsNone(User.query.filter_by(username=f"riley{self.suffix}").first())

    def test_saved_tundra_vin_is_answered_from_the_site(self):
        self.admin = f"ask_vin_{self.suffix}"
        self._register(self.admin, household=f"AskVin {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("April Black")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2006
            row.make = "Toyota"
            row.model = "Tundra"
            row.color = "Black"
            row.vin = "5TFBT54106X123456"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("the VIN is already saved")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "whats the 2006 tundra vin from my site"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("5TFBT54106X123456", say)
        self.assertNotIn("provide the VIN", say.lower())

    def test_add_that_saves_the_last_reply_on_the_vehicle(self):
        self.admin = f"ask_oil_{self.suffix}"
        self._register(self.admin, household=f"AskOil {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._vehicle("Silverado")
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", return_value=(True, '{"say":"Use 5W-30 full synthetic."}')):
            first = self.client.post(
                "/ask/message",
                json={"message": "what oil does the truck take"},
                headers={"X-CSRF-Token": token},
            )
        self.assertTrue(first.get_json().get("ok"), first.get_json())

        def fail_if_called(*_a, **_k):
            raise AssertionError("add that should not call the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            second = self.client.post(
                "/ask/message",
                json={"message": "add that to my truck"},
                headers={"X-CSRF-Token": token},
            )
        data = second.get_json()
        self.assertEqual(second.status_code, 200, data)
        self.assertIn("Silverado", data.get("say") or "")
        with self.app.app_context():
            from app.builddb.table_ask_turns import AskTurn
            from app.builddb.table_items import Item
            from app.builddb.table_notes import Note
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            item = Item.query.filter_by(household_id=user.household_id, name="Silverado").first()
            self.assertIsNotNone(item)
            self.assertIn("5W-30", item.vehicle.oil_needs or "")
            notes = Note.query.filter_by(item_id=item.id).all()
            self.assertTrue(any("5W-30" in (n.body or "") for n in notes))
            turns = AskTurn.query.filter_by(user_id=user.id).count()
            self.assertGreaterEqual(turns, 2)


if __name__ == "__main__":
    unittest.main()
