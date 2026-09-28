import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask import (
    _local_house_say,
    _parse_stock_jobs,
    _parse_turn,
    _plain_say,
    _speak_house,
    _trip_item_hint,
    _trip_local_say,
    _trip_miles_from,
    asked_to_list,
)
from app.utils.ask_rooms import help_text, normalize_room, room_from_path, slash_reply
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
    def test_vault_tools_are_not_model_calls(self):
        from app.utils.ask import TOOLS

        for tool in ("vault_unlock", "vault_list", "vault_open", "vault_save"):
            turn = _parse_turn('{"tool":"%s","args":{"password":"never-send"}}' % tool)
            self.assertNotEqual(turn.get("kind"), "tool", tool)
            self.assertNotIn(tool, TOOLS)

    def test_say_json(self):
        turn = _parse_turn('{"say":"Milk is in the fridge. /items/3"}')
        self.assertEqual(turn["kind"], "say")
        self.assertIn("fridge", turn["text"])

    def test_plain_answer_still_talks(self):
        turn = _parse_turn("Call the city water line: https://example.test/water")
        self.assertEqual(turn["kind"], "say")
        self.assertIn("https://example.test/water", turn["text"])

    def test_tool_result_json_is_spoken(self):
        turn = _parse_turn('{"ok": true, "kind": "tools", "lines": ["DeWalt drill · /items/4"], "count": 1}')
        self.assertEqual(turn["kind"], "say")
        self.assertIn("DeWalt drill", turn["text"])
        self.assertNotIn('{"ok"', turn["text"])

    def test_plain_say_strips_wrapped_json(self):
        text = _plain_say('{"say":"Milk is in the fridge. /items/3"}')
        self.assertEqual(text, "Milk is in the fridge. /items/3")
        dumped = _plain_say('{"ok": true, "items": ["Milk · grocery · /items/3"]}')
        self.assertIn("Milk", dumped)
        self.assertFalse(dumped.strip().startswith("{"))

    def test_lookup_and_tool_json(self):
        turn = _parse_turn('{"tool":"lookup","args":{"upc":"012345678905"}}')
        self.assertEqual(turn["tool"], "lookup")
        turn = _parse_turn('{"tool":"tool_save","args":{"name":"Drill","serial":"SN1"}}')
        self.assertEqual(turn["tool"], "tool_save")
        turn = _parse_turn('{"tool":"reminder_save","args":{"title":"Water","type":"bill","every":"monthly"}}')
        self.assertEqual(turn["tool"], "reminder_save")
        turn = _parse_turn('{"tool":"inventory","args":{"q":"milk","action":"restock"}}')
        self.assertEqual(turn["tool"], "inventory")
        turn = _parse_turn('{"tool":"vehicle_save","args":{"vin":"1HGCM82633A004352"}}')
        self.assertEqual(turn["tool"], "vehicle_save")
        turn = _parse_turn('{"tool":"house","args":{"kind":"tools"}}')
        self.assertEqual(turn["tool"], "house")
        turn = _parse_turn('{"tool":"place","args":{"what":"part","name":"brake pads"}}')
        self.assertEqual(turn["tool"], "place")
        turn = _parse_turn('{"tool":"member_add","args":{"name":"Sam"}}')
        self.assertEqual(turn["tool"], "member_add")
        self.assertEqual(turn["args"]["name"], "Sam")


class RoomTests(unittest.TestCase):
    def test_normalize_and_path(self):
        self.assertEqual(normalize_room("cars"), "vehicles")
        self.assertEqual(normalize_room("groceries"), "inventory")
        self.assertEqual(normalize_room("help"), "house")
        self.assertEqual(room_from_path("/vehicles/"), "vehicles")
        self.assertEqual(room_from_path("/groceries/"), "inventory")
        self.assertEqual(room_from_path("/groceries/list"), "basket")
        self.assertEqual(room_from_path("/ask/tools"), "tools")
        self.assertEqual(room_from_path("/ask/help"), "house")

    def test_help_lists_rooms_and_slashes(self):
        text = help_text("vehicles")
        self.assertIn("/help", text)
        self.assertIn("/ask/vehicles", text)
        self.assertIn("/inventory", text)
        self.assertIn("Vehicles", text)
        self.assertIn("home with 81650", text)

    def test_trip_hint_and_miles(self):
        start = "please start me a trip in my blue tundra, with 81200 miles from odessa to lubbock"
        self.assertEqual(_trip_item_hint(start, ending=False), "blue tundra")
        self.assertEqual(_trip_miles_from(start), "81200")
        self.assertEqual(_trip_item_hint("I'm home with 81650 miles", ending=True), "")
        self.assertEqual(_trip_miles_from("I'm home with 81650 miles"), "81650")
        self.assertIsNone(_trip_local_say("I'm home with the kids"))
        glued = "can you start a trip for my black tundra?284438 miles at start"
        self.assertEqual(_trip_item_hint(glued, ending=False), "black tundra")
        self.assertEqual(_trip_miles_from(glued), "284438")

    def test_unknown_slash(self):
        self.assertIn("/help", slash_reply("/nope", "house") or "")


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

    def test_usual_rooms(self):
        from app.utils.classify import usual_store_place

        self.assertEqual(usual_store_place("Peanut Butter"), "Pantry")
        self.assertEqual(usual_store_place("whole milk"), "Fridge")
        self.assertEqual(usual_store_place("ice cream"), "Freezer")
        self.assertEqual(usual_store_place("El Monterey Beef & Bean Burritos"), "Freezer")
        self.assertEqual(usual_store_place("Coffee Mate FV Creamer"), "Fridge")

    def test_stock_jobs_parse_move_and_count(self):
        msg = (
            "please put the fried burritos that are in the pantry in the fridge please "
            "and make sure we show 2 french vanilla creamers"
        )
        jobs = _parse_stock_jobs(msg)
        self.assertGreaterEqual(len(jobs), 2)
        self.assertIn("burrito", jobs[0]["q"].lower())
        self.assertEqual(jobs[0]["from"].lower(), "pantry")
        self.assertEqual(jobs[0]["place"].lower(), "fridge")
        self.assertEqual(jobs[1]["action"], "set")
        self.assertEqual(str(jobs[1]["amount"]), "2")
        self.assertIn("creamer", jobs[1]["q"].lower())
        self.assertIsNone(_local_house_say(msg))

    def test_sort_inventory_is_not_a_list(self):
        self.assertIsNone(_local_house_say("sort all the items in the inventory"))
        self.assertIsNone(_local_house_say("organize my pantry"))

    def test_talking_about_inventory_is_not_a_dump(self):
        self.assertFalse(asked_to_list("sort all the items in the inventory", "inventory"))
        self.assertFalse(asked_to_list("start a trip in my black tundra", "vehicles"))
        self.assertFalse(asked_to_list("can you update my inventory", "inventory"))
        self.assertFalse(asked_to_list("the oil for my tundra", "vehicles"))
        self.assertFalse(
            asked_to_list(
                "El Monterey burritos go in the freezer and show in the inventory 2 of these",
                "inventory",
            )
        )
        self.assertTrue(asked_to_list("open my inventory", "inventory"))
        self.assertTrue(asked_to_list("show me the inventory", "inventory"))
        self.assertTrue(asked_to_list("show me the vehicles", "vehicles"))
        self.assertTrue(asked_to_list("what's in my inventory", "inventory"))
        self.assertTrue(asked_to_list("can you look up what tools i have", "tools"))
        self.assertIsNone(_local_house_say("can you update my inventory"))
        self.assertIsNone(_local_house_say("start a trip in my black tundra"))

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

            cls.service_key = mint_service_pass(max_uses=80, days=30, label="ask-tests").code

    def setUp(self):
        with self.client.session_transaction() as sess:
            for key in list(sess.keys()):
                if key.startswith("family_ask_"):
                    sess.pop(key, None)

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

    def _yes(self, token):
        return self.client.post(
            "/ask/message",
            json={"message": "yes"},
            headers={"X-CSRF-Token": token},
        )

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

    def test_local_chat_bubble_and_app_edits_work_without_ai_key(self):
        self.admin = f"ask_local_{self.suffix}"
        self._register(self.admin, household=f"AskLocal {self.suffix}", name="Pat")
        home = self.client.get("/")
        self.assertIn(b'id="ask-root"', home.data)
        token = self._csrf(home.data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("deterministic operations must work without AI")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            added = self.client.post(
                "/ask/message",
                json={"message": "put coffee creamer on the basket"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(added.status_code, 200, added.get_json())
        self.assertIn("coffee creamer", (added.get_json() or {}).get("say", "").lower())
        if (added.get_json() or {}).get("confirm"):
            with patch("app.utils.ask.complete", side_effect=fail_if_called):
                added = self._yes(token)
            self.assertEqual(added.status_code, 200, added.get_json())

        with self.app.app_context():
            from app.builddb.table_grocery_list import GroceryListEntry
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            row = GroceryListEntry.query.filter_by(household_id=user.household_id, name="coffee creamer").first()
            self.assertIsNotNone(row)

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            chips = self.client.post(
                "/ask/message",
                json={"message": "add chips to my basket"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(chips.status_code, 200, chips.get_json())
        if (chips.get_json() or {}).get("confirm"):
            with patch("app.utils.ask.complete", side_effect=fail_if_called):
                chips = self._yes(token)
            self.assertEqual(chips.status_code, 200, chips.get_json())
        with self.app.app_context():
            from app.builddb.table_grocery_list import GroceryListEntry
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            row = GroceryListEntry.query.filter_by(household_id=user.household_id, name="chips").first()
            self.assertIsNotNone(row)

    def test_chat_local_edits_and_lists_when_ai_is_down(self):
        self.admin = f"ask_offline_{self.suffix}"
        self._register(self.admin, household=f"AskOffline {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._grocery("Milk")
        token = self._csrf(self.client.get("/").data)

        def ai_down(*_a, **_k):
            return False, "The model is busy right now."

        with patch("app.utils.ask.complete", side_effect=ai_down):
            response = self.client.post(
                "/ask/message",
                json={"message": "move the milk to the freezer"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn("freezer", (response.get_json() or {}).get("say", "").lower())
        if (response.get_json() or {}).get("confirm"):
            with patch("app.utils.ask.complete", side_effect=ai_down):
                response = self._yes(token)
            self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            hid = User.query.filter_by(username=self.admin).first().household_id
            milk = Item.query.filter_by(household_id=hid, name="Milk", item_type="grocery").first()
            self.assertIsNotNone(milk)
            self.assertIn("freezer", (milk.grocery.default_location or "").lower())

    def test_widget_follows_key_and_toggle(self):
        self.admin = f"ask_a_{self.suffix}"
        self._register(self.admin, household=f"Ask {self.suffix}", name="Pat")
        home = self.client.get("/")
        # Local household controls remain available without an AI key.
        self.assertIn(b'id="ask-root"', home.data)
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
        self.assertTrue((resp.get_json() or {}).get("confirm"), resp.get_json())
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            resp = self._yes(token)
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
        self.assertTrue((resp.get_json() or {}).get("confirm"), resp.get_json())
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            resp = self._yes(token)
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
        self.assertTrue((resp.get_json() or {}).get("confirm"), resp.get_json())
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            yes = self._yes(token)
        self.assertIn("cannot add", ((yes.get_json() or {}).get("say") or "").lower())
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
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            named = self.client.post(
                "/ask/message",
                json={"message": "the truck vin is named april are you looking in the right area"},
                headers={"X-CSRF-Token": token},
            )
        self.assertIn("5TFBT54106X123456", (named.get_json() or {}).get("say") or "")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.oil_needs = "5W-30 full synthetic"
            db.session.commit()
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            oil = self.client.post(
                "/ask/message",
                json={"message": "use the vin for the 2006 tundra to find the type of oil it needs"},
                headers={"X-CSRF-Token": token},
            )
        oil_say = (oil.get_json() or {}).get("say") or ""
        self.assertIn("5W-30", oil_say)
        self.assertIn("Tundra", oil_say)

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
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            item = Item.query.filter_by(household_id=user.household_id, name="Silverado").first()
            self.assertIsNotNone(item)
            self.assertIn("5W-30", item.vehicle.oil_needs or "")
            turns = AskTurn.query.filter_by(user_id=user.id).count()
            self.assertGreaterEqual(turns, 2)

    def _tool(self, name, **fields):
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_items import Item
            from app.builddb.table_tools import Tool
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            item = Item(
                household_id=user.household_id,
                name=name,
                item_type="tool",
                created_by=user.id,
            )
            db.session.add(item)
            db.session.flush()
            tool = Tool(item_id=item.id, household_id=user.household_id)
            for key, val in fields.items():
                setattr(tool, key, val)
            db.session.add(tool)
            db.session.commit()
            return item.id

    def _grocery(self, name):
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_grocery_items import GroceryItem
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            item = Item(
                household_id=user.household_id,
                name=name,
                item_type="grocery",
                created_by=user.id,
            )
            db.session.add(item)
            db.session.flush()
            db.session.add(
                GroceryItem(item_id=item.id, household_id=user.household_id, quantity=2, is_in_stock=True)
            )
            db.session.commit()
            return item.id

    def test_gas_gen_oil_when_saved(self):
        self.admin = f"ask_gen_{self.suffix}"
        self._register(self.admin, household=f"AskGen {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._tool("Honda generator", type="generator", power_source="gas", oil_needs="SAE 10W-30")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("oil is already saved on the generator")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "find my gas gen and tell me what oil it needs"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("10W-30", say)
        self.assertIn("Honda", say)

    def test_gas_gen_without_oil_asks_to_add(self):
        self.admin = f"ask_gen2_{self.suffix}"
        self._register(self.admin, household=f"AskGen2 {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._tool("Honda generator", type="generator", power_source="gas", model="EU2200i")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("a known generator is answered from the built-in guide")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what oil does my gas gen need"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("Honda", say)
        self.assertIn("10W-30", say)
        self.assertIn("save that", say.lower())
        self.assertFalse(say.strip().startswith("{"))

    def test_what_oil_i_have_lists_specs(self):
        self.admin = f"ask_oils_{self.suffix}"
        self._register(self.admin, household=f"AskOils {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("April Black")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2006
            row.make = "Toyota"
            row.model = "Tundra"
            row.oil_needs = "5W-30"
            db.session.commit()
        self._vehicle("Civic")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("overview should list saved oil without the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what kinda oil i have"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("5W-30", say)
        self.assertIn("Tundra", say)
        self.assertNotIn("Saved vehicles:", say)

    def test_json_reply_is_not_shown(self):
        self.admin = f"ask_json_{self.suffix}"
        self._register(self.admin, household=f"AskJson {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        with patch(
            "app.utils.ask.complete",
            return_value=(True, '{"ok": true, "kind": "tools", "lines": ["DeWalt drill · /items/4"], "count": 1}'),
        ):
            resp = self.client.post(
                "/ask/message",
                json={"message": "remind me what that last lookup was"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("DeWalt drill", say)
        self.assertFalse("{" in say)

    def test_delete_tool(self):
        self.admin = f"ask_del_{self.suffix}"
        self._register(self.admin, household=f"AskDel {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._tool("Old drill", type="drill")
        replies = [
            (True, '{"tool":"item_remove","args":{"q":"old drill"}}'),
            (True, '{"say":"Remove Old drill from tools? Say yes."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "delete the old drill"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIn("Old drill", (resp.get_json() or {}).get("say") or "")
        with self.app.app_context():
            from app.builddb.table_items import Item

            item = Item.query.get(item_id)
            self.assertIsNone(item.removed_at)
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            yes = self.client.post(
                "/ask/message",
                json={"message": "yes"},
                headers={"X-CSRF-Token": token},
            )
        self.assertIn("Old drill", (yes.get_json() or {}).get("say") or "")
        with self.app.app_context():
            from app.builddb.table_items import Item

            item = Item.query.get(item_id)
            self.assertIsNotNone(item.removed_at)

    def test_expire_save_and_list(self):
        from datetime import date, timedelta

        self.admin = f"ask_exp_{self.suffix}"
        self._register(self.admin, household=f"AskExp {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._grocery("Milk")
        day = (date.today() + timedelta(days=7)).isoformat()
        replies = [
            (True, '{"tool":"expire_save","args":{"q":"milk","date":"%s"}}' % day),
            (True, '{"say":"Milk is dated %s."}' % day),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "set milk to expire 2026-10-04"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertTrue((resp.get_json() or {}).get("confirm"), resp.get_json())
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            resp = self._yes(token)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem
            from app.utils.lots import soonest

            g = GroceryItem.query.filter_by(item_id=item_id).first()
            self.assertEqual(str(soonest(g)), day)
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("list is local"))):
            listed = self.client.post(
                "/ask/message",
                json={"message": "whats about to expire"},
                headers={"X-CSRF-Token": token},
            )
        listed_say = (listed.get_json() or {}).get("say") or ""
        self.assertIn("Milk", listed_say)
        self.assertIn(day, listed_say)
        self.assertNotIn('{"ok"', listed_say)

    def test_history_roundtrip(self):
        self.admin = f"ask_hist_{self.suffix}"
        self._register(self.admin, household=f"AskHist {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", return_value=(True, '{"say":"The drill is in tools."}')):
            self.client.post(
                "/ask/message",
                json={"message": "where is the drill"},
                headers={"X-CSRF-Token": token},
            )
        hist = self.client.get("/ask/history")
        self.assertEqual(hist.status_code, 200, hist.data)
        turns = (hist.get_json() or {}).get("turns") or []
        texts = " ".join(t.get("text") or "" for t in turns)
        self.assertIn("where is the drill", texts)
        self.assertIn("drill is in tools", texts)

        again = self.client.get("/")
        self.assertIn(b'data-room="house"', again.data)
        still = self.client.get("/ask/history?room=house")
        still_text = " ".join(t.get("text") or "" for t in (still.get_json() or {}).get("turns") or [])
        self.assertIn("where is the drill", still_text)

    def test_idle_chat_expires_after_two_weeks(self):
        from datetime import datetime, timedelta

        self.admin = f"ask_idle_{self.suffix}"
        self._register(self.admin, household=f"AskIdle {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", return_value=(True, '{"say":"Old chat."}')):
            self.client.post(
                "/ask/message",
                json={"message": "hello from last month"},
                headers={"X-CSRF-Token": token},
            )
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_ask_turns import AskTurn
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            old = datetime.utcnow() - timedelta(days=20)
            for row in AskTurn.query.filter_by(user_id=user.id).all():
                row.created_at = old
            db.session.commit()
        hist = self.client.get("/ask/history")
        self.assertEqual((hist.get_json() or {}).get("turns") or [], [])

    def test_slash_help_and_vehicles_skip_the_model(self):
        self.admin = f"ask_sl_{self.suffix}"
        self._register(self.admin, household=f"AskSl {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._vehicle("April Black")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("slash commands do not need the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            help_resp = self.client.post(
                "/ask/message",
                json={"message": "/help"},
                headers={"X-CSRF-Token": token},
            )
            listed = self.client.post(
                "/ask/message",
                json={"message": "/vehicles"},
                headers={"X-CSRF-Token": token},
            )
        help_say = (help_resp.get_json() or {}).get("say") or ""
        self.assertIn("/ask/vehicles", help_say)
        self.assertIn("/inventory", help_say)
        say = (listed.get_json() or {}).get("say") or ""
        self.assertIn("April Black", say)

    def test_rooms_keep_threads_apart(self):
        self.admin = f"ask_rm_{self.suffix}"
        self._register(self.admin, household=f"AskRm {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", return_value=(True, '{"say":"Tundra takes 5W-30."}')):
            self.client.post(
                "/ask/message",
                json={"message": "what oil does the tundra need", "room": "vehicles"},
                headers={"X-CSRF-Token": token},
            )
        with patch("app.utils.ask.complete", return_value=(True, '{"say":"Milk is in the fridge."}')):
            self.client.post(
                "/ask/message",
                json={"message": "where is the milk", "room": "inventory"},
                headers={"X-CSRF-Token": token},
            )
        cars = self.client.get("/ask/history?room=vehicles")
        food = self.client.get("/ask/history?room=inventory")
        car_text = " ".join(t.get("text") or "" for t in (cars.get_json() or {}).get("turns") or [])
        food_text = " ".join(t.get("text") or "" for t in (food.get_json() or {}).get("turns") or [])
        self.assertIn("tundra", car_text.lower())
        self.assertIn("5W-30", car_text)
        self.assertNotIn("milk", car_text.lower())
        self.assertIn("milk", food_text.lower())
        self.assertNotIn("tundra", food_text.lower())

    def test_ask_pages_render(self):
        self.admin = f"ask_pg_{self.suffix}"
        self._register(self.admin, household=f"AskPg {self.suffix}", name="Pat")
        self._put_key(chat=True)
        help_page = self.client.get("/ask/help")
        self.assertEqual(help_page.status_code, 200, help_page.data)
        self.assertIn(b"/vehicles", help_page.data)
        self.assertIn(b"/inventory", help_page.data)
        desk = self.client.get("/ask/vehicles")
        self.assertEqual(desk.status_code, 200, desk.data)
        self.assertIn(b'data-room="vehicles"', desk.data)
        self.assertIn(b'data-mode="desk"', desk.data)
        vehicles = self.client.get("/vehicles/")
        self.assertEqual(vehicles.status_code, 200, vehicles.data)
        self.assertIn(b"/ask/vehicles", vehicles.data)
        self.assertIn(b'data-room="house"', vehicles.data)
        self.assertIn(b"Close keeps this chat", vehicles.data)

    def test_oem_oil_lookup_then_add(self):
        self.admin = f"ask_oem_{self.suffix}"
        self._register(self.admin, household=f"AskOem {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("White Tundra")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2011
            row.make = "Toyota"
            row.model = "Tundra"
            row.color = "White"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("a known Tundra year is answered from the built-in guide")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "look up the oil for the white tundra 2011"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("Tundra", say)
        self.assertIn("0W-20", say)
        self.assertIn("save that", say.lower())

        def fail_if_called(*_a, **_k):
            raise AssertionError("yes should save the pending OEM spec")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            yes = self.client.post(
                "/ask/message",
                json={"message": "yes add it"},
                headers={"X-CSRF-Token": token},
            )
        yes_say = (yes.get_json() or {}).get("say") or ""
        self.assertIn("0W-20", yes_say)
        self.assertIn("White Tundra", yes_say)
        with self.app.app_context():
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            self.assertIn("0W-20", row.oil_needs or "")

    def test_generic_expirations_on_undated_food(self):
        self.admin = f"ask_genx_{self.suffix}"
        self._register(self.admin, household=f"AskGenx {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._grocery("Cereal")
        self._grocery("Rice")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("expire list and generic dates are local")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            listed = self.client.post(
                "/ask/message",
                json={"message": "whats the expirations on my food"},
                headers={"X-CSRF-Token": token},
            )
        listed_say = (listed.get_json() or {}).get("say") or ""
        self.assertIn("2 have no use-by", listed_say)
        self.assertIn("generic", listed_say.lower())
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            filled = self.client.post(
                "/ask/message",
                json={"message": "please add the generic expirations to it"},
                headers={"X-CSRF-Token": token},
            )
        filled_say = (filled.get_json() or {}).get("say") or ""
        self.assertIn("typical use-by", filled_say.lower())
        self.assertIn("Cereal", filled_say)
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem
            from app.builddb.table_items import Item
            from app.utils.lots import soonest

            hid = Item.query.filter_by(name="Cereal").first().household_id
            dated = 0
            for item in Item.query.filter_by(household_id=hid, item_type="grocery").all():
                if soonest(item.grocery):
                    dated += 1
            self.assertGreaterEqual(dated, 2)

    def test_add_missing_item_asks_where_then_creates(self):
        self.admin = f"ask_add_{self.suffix}"
        self._register(self.admin, household=f"AskAdd {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        replies = [
            (True, '{"tool":"inventory","args":{"q":"Peanut Butter","action":"create"}}'),
            (True, '{"say":"Peanut Butter isn’t on the site yet. Add it to inventory?" }'),
        ]

        def fake_complete(*_a, **_k):
            return replies.pop(0)

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            first = self.client.post(
                "/ask/message",
                json={"message": "add peanut butter to my inventory"},
                headers={"X-CSRF-Token": token},
            )
        say = (first.get_json() or {}).get("say") or ""
        self.assertTrue("site yet" in say or "isn’t on the site" in say or "isn't on the site" in say)
        self.assertIn("pantry", say.lower())
        self.assertNotIn("Where should it go", say)
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            self.assertIsNone(
                Item.query.filter_by(household_id=user.household_id, name="Peanut Butter").first()
            )

        def fail_if_called(*_a, **_k):
            raise AssertionError("yes plus where should not call the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            second = self.client.post(
                "/ask/message",
                json={"message": "yes"},
                headers={"X-CSRF-Token": token},
            )
        done = (second.get_json() or {}).get("say") or ""
        self.assertIn("peanut butter", done.lower())
        self.assertIn("inventory", done.lower())
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            item = Item.query.filter_by(household_id=user.household_id, name="Peanut Butter").first()
            self.assertIsNotNone(item)
            self.assertEqual(item.item_type, "grocery")
            self.assertEqual((item.grocery.default_location or "").lower(), "pantry")

    def test_delete_protein_bars_does_not_touch_the_truck(self):
        self.admin = f"ask_bars_{self.suffix}"
        self._register(self.admin, household=f"AskBars {self.suffix}", name="Pat")
        self._put_key(chat=True)
        truck_id = self._vehicle("White Tundra")
        bar_id = self._grocery("Quest Protein Bars")
        token = self._csrf(self.client.get("/").data)
        replies = [
            (True, '{"tool":"item_remove","args":{"q":"protein bars"}}'),
            (True, '{"say":"Remove Quest Protein Bars from inventory?" }'),
        ]

        def fake_complete(*_a, **_k):
            return replies.pop(0)

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            first = self.client.post(
                "/ask/message",
                json={"message": "delete the protein bars"},
                headers={"X-CSRF-Token": token},
            )
        say = (first.get_json() or {}).get("say") or ""
        self.assertIn("Protein Bars", say)
        self.assertNotIn("Tundra", say)
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("yes is local"))):
            yes = self.client.post(
                "/ask/message",
                json={"message": "yes"},
                headers={"X-CSRF-Token": token},
            )
        self.assertIn("Protein Bars", (yes.get_json() or {}).get("say") or "")
        with self.app.app_context():
            from app.builddb.table_items import Item

            bars = Item.query.get(bar_id)
            truck = Item.query.get(truck_id)
            self.assertIsNotNone(bars.removed_at)
            self.assertIsNone(truck.removed_at)

    def test_trip_start_and_home(self):
        self.admin = f"ask_trip_{self.suffix}"
        self._register(self.admin, household=f"AskTrip {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Blue Tundra")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2011
            row.make = "Toyota"
            row.model = "Tundra"
            row.color = "Blue"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("trip start/end should not need the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            start = self.client.post(
                "/ask/message",
                json={
                    "message": "please start me a trip in my blue tundra, with 81200 miles from odessa to lubbock"
                },
                headers={"X-CSRF-Token": token},
            )
        start_say = (start.get_json() or {}).get("say") or ""
        self.assertTrue((start.get_json() or {}).get("confirm"), start.get_json())
        self.assertIn("Odessa", start_say)
        self.assertIn("Lubbock", start_say)
        self.assertIn("81,200", start_say)
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            allowed = self._yes(token)
        start_done = (allowed.get_json() or {}).get("say") or ""
        self.assertIn("Trip started", start_done)
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            home = self.client.post(
                "/ask/message",
                json={"message": "I'm home with 81650 miles"},
                headers={"X-CSRF-Token": token},
            )
        self.assertTrue((home.get_json() or {}).get("confirm"), home.get_json())
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            home_ok = self._yes(token)
        home_say = (home_ok.get_json() or {}).get("say") or ""
        self.assertIn("450", home_say)
        self.assertIn("81,650", home_say)
        with self.app.app_context():
            from app.builddb.table_item_logs import ItemLog
            from app.builddb.table_vehicles import Vehicle
            from app.utils.item_log import log_stats

            v = Vehicle.query.filter_by(item_id=item_id).first()
            self.assertEqual(v.current_mileage, 81650)
            trip = (
                ItemLog.query.filter_by(item_id=item_id, kind="trip")
                .order_by(ItemLog.id.desc())
                .first()
            )
            self.assertIsNotNone(trip)
            extra = trip.extra_data or {}
            self.assertEqual(extra.get("status"), "done")
            self.assertEqual(int(extra.get("miles") or 0), 450)
            stats = log_stats(v.item)
            self.assertEqual(stats.get("year_trip_miles"), 450)
        log_page = self.client.get(f"/items/{item_id}?tab=log")
        self.assertEqual(log_page.status_code, 200)
        body = log_page.data.decode("utf-8", "replace")
        self.assertIn("Odessa", body)
        self.assertIn("Lubbock", body)
        self.assertIn("450", body)
        self.assertIn("81,200", body)
        self.assertIn("81,650", body)

    def test_always_allow_runs_a_trip(self):
        self.admin = f"ask_free_{self.suffix}"
        self._register(self.admin, household=f"AskFree {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._vehicle("Blue Tundra")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("mode and trip should not need the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            mode = self.client.post(
                "/ask/message",
                json={"message": "always allow"},
                headers={"X-CSRF-Token": token},
            )
        self.assertIn("simple", ((mode.get_json() or {}).get("say") or "").lower())
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            start = self.client.post(
                "/ask/message",
                json={"message": "please start me a trip in my blue tundra, with 81200 miles from odessa to lubbock"},
                headers={"X-CSRF-Token": token},
            )
        data = start.get_json() or {}
        self.assertFalse(data.get("confirm"))
        self.assertIn("Trip started", data.get("say") or "")

    def test_no_cancels_a_write(self):
        self.admin = f"ask_no_{self.suffix}"
        self._register(self.admin, household=f"AskNo {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Blue Tundra")
        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("local"))):
            start = self.client.post(
                "/ask/message",
                json={"message": "please start me a trip in my blue tundra, with 81200 miles from odessa to lubbock"},
                headers={"X-CSRF-Token": token},
            )
        self.assertTrue((start.get_json() or {}).get("confirm"))
        with patch("app.utils.ask.complete", side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("local"))):
            nope = self.client.post(
                "/ask/message",
                json={"message": "no"},
                headers={"X-CSRF-Token": token},
            )
        self.assertIn("left", ((nope.get_json() or {}).get("say") or "").lower())
        with self.app.app_context():
            from app.builddb.table_item_logs import ItemLog

            self.assertIsNone(ItemLog.query.filter_by(item_id=item_id, kind="trip").first())

    def test_put_sentence_does_not_create_an_item(self):
        self.admin = f"ask_putsent_{self.suffix}"
        self._register(self.admin, household=f"AskPutSent {self.suffix}", name="Pat")
        self._put_key(chat=True)
        burrito_id = self._grocery("El Monterey Beef & Bean Burritos")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_grocery_items import GroceryItem

            GroceryItem.query.filter_by(item_id=burrito_id).first().default_location = "Pantry"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)
        msg = "please put the fried burritos that are in the pantry in the fridge please"

        def fail_if_called(*_a, **_k):
            raise AssertionError("put in fridge should not hit the model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            first = self.client.post(
                "/ask/message",
                json={"message": msg},
                headers={"X-CSRF-Token": token},
            )
        data = first.get_json() or {}
        say = data.get("say") or ""
        self.assertNotIn("isn’t on the site", say)
        self.assertNotIn("isn't on the site", say)
        self.assertNotIn("I’ll put it in Fridge", say)
        if data.get("confirm"):
            with patch("app.utils.ask.complete", side_effect=fail_if_called):
                first = self._yes(token)
            say = (first.get_json() or {}).get("say") or ""
        self.assertNotIn("isn’t on the site", say)
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem
            from app.builddb.table_items import Item
            from app.builddb.table_users import User

            user = User.query.filter_by(username=self.admin).first()
            fake = Item.query.filter(
                Item.household_id == user.household_id,
                Item.name.ilike("please put the fried%"),
            ).first()
            self.assertIsNone(fake)
            g = GroceryItem.query.filter_by(item_id=burrito_id).first()
            self.assertEqual((g.default_location or "").lower(), "fridge")

    def test_put_pantry_burritos_in_fridge_and_set_creamer(self):
        self.admin = f"ask_move_{self.suffix}"
        self._register(self.admin, household=f"AskMove {self.suffix}", name="Pat")
        self._put_key(chat=True)
        burrito_id = self._grocery("El Monterey Beef & Bean Burritos")
        cream_id = self._grocery("Coffee Mate FV Creamer")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_grocery_items import GroceryItem

            b = GroceryItem.query.filter_by(item_id=burrito_id).first()
            b.default_location = "Pantry"
            c = GroceryItem.query.filter_by(item_id=cream_id).first()
            c.default_location = "Fridge"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)
        msg = (
            "please put the fried burritos that are in the pantry in the fridge please "
            "and make sure we show 2 french vanilla creamers"
        )

        def fail_if_called(*_a, **_k):
            raise AssertionError("stock jobs should not dump inventory")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            first = self.client.post(
                "/ask/message",
                json={"message": msg},
                headers={"X-CSRF-Token": token},
            )
        data = first.get_json() or {}
        say = data.get("say") or ""
        self.assertNotIn("isn’t on the site", say)
        self.assertNotIn("isn't on the site", say)
        self.assertNotIn("Inventory in this house", say)
        if data.get("confirm"):
            self.assertIn("burrito", say.lower())
            with patch("app.utils.ask.complete", side_effect=fail_if_called):
                first = self._yes(token)
            say = (first.get_json() or {}).get("say") or ""
        self.assertNotIn("isn’t on the site", say)
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem

            b = GroceryItem.query.filter_by(item_id=burrito_id).first()
            c = GroceryItem.query.filter_by(item_id=cream_id).first()
            self.assertEqual((b.default_location or "").lower(), "fridge")
            self.assertEqual(int(c.quantity or 0), 2)

    def test_named_food_goes_in_a_room_without_dumping(self):
        self.admin = f"ask_put_{self.suffix}"
        self._register(self.admin, household=f"AskPut {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._grocery("El Monterey Beef & Bean Burritos")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("put in freezer should not dump inventory")

        msg = (
            "El Monterey Beef & Bean Burritos close those go in the freezer "
            "and make sure we show in the inventory 2 of these"
        )
        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            first = self.client.post(
                "/ask/message",
                json={"message": msg},
                headers={"X-CSRF-Token": token},
            )
        data = first.get_json() or {}
        say = data.get("say") or ""
        self.assertNotIn("Inventory in this house", say)
        if data.get("confirm"):
            with patch("app.utils.ask.complete", side_effect=fail_if_called):
                first = self._yes(token)
            say = (first.get_json() or {}).get("say") or ""
        self.assertNotIn("Inventory in this house", say)
        self.assertRegex(say.lower(), r"freezer")
        self.assertIn("2", say)
        with self.app.app_context():
            from app.builddb.table_grocery_items import GroceryItem

            g = GroceryItem.query.filter_by(item_id=item_id).first()
            self.assertEqual((g.default_location or "").lower(), "freezer")
            self.assertEqual(int(g.quantity or 0), 2)

    def test_sort_inventory_files_rooms_not_a_dump(self):
        self.admin = f"ask_sort_{self.suffix}"
        self._register(self.admin, household=f"AskSort {self.suffix}", name="Pat")
        self._put_key(chat=True)
        self._grocery("Milk")
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("sort inventory should not need the chat model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            first = self.client.post(
                "/ask/message",
                json={"message": "sort all the items in the inventory"},
                headers={"X-CSRF-Token": token},
            )
        data = first.get_json() or {}
        say = data.get("say") or ""
        self.assertTrue(data.get("confirm"), data)
        self.assertNotIn("Inventory in this house", say)
        self.assertIn("room", say.lower())
        with patch("app.utils.ask.complete", side_effect=fail_if_called), patch(
            "app.utils.classify.parse_pantry_places",
            return_value={"used_ai": False, "lines": ["Fridge: Milk"], "moved": 1, "error": None},
        ):
            yes = self._yes(token)
        done = (yes.get_json() or {}).get("say") or ""
        self.assertIn("Fridge", done)
        self.assertIn("Milk", done)
        self.assertNotIn("Inventory in this house", done)


    def test_rear_diff_oil_asks_the_model_not_engine_oil(self):
        self.admin = f"ask_diff_{self.suffix}"
        self._register(self.admin, household=f"AskDiff {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Blue Tundra")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2006
            row.make = "Toyota"
            row.model = "Tundra"
            row.oil_needs = "0W-20"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("a known Tundra rear diff is answered from the built-in guide")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what kinda rear diff oil does my 06 tundra take"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("75W-90", say)
        self.assertIn("rear", say.lower())
        self.assertNotIn("0W-20", say)

    def test_due_lists_overdue_oil_change_without_the_model(self):
        self.admin = f"ask_due_{self.suffix}"
        self._register(self.admin, household=f"AskDue {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Work Tundra")
        with self.app.app_context():
            from datetime import date, timedelta

            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.next_oil_due_date = date.today() - timedelta(days=9)
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("what's due is answered locally, no model needed")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what's due"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("Oil change", say)
        self.assertIn("Work Tundra", say)
        self.assertIn("overdue", say)

    def test_oil_change_past_due_reaches_the_due_list(self):
        self.admin = f"ask_due2_{self.suffix}"
        self._register(self.admin, household=f"AskDue2 {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Ranch Tundra")
        with self.app.app_context():
            from datetime import date, timedelta

            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.next_oil_due_date = date.today() - timedelta(days=30)
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("'oil change past due' must not go to the model or the spec reply")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "is my oil change past due?"},
                headers={"X-CSRF-Token": token},
            )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("Oil change", say)
        self.assertIn("Ranch Tundra", say)
        self.assertIn("overdue", say)

    def test_missing_oil_schedule_offers_then_saves_six_month_reminder(self):
        from datetime import date

        from app.utils.oil import add_months

        self.admin = f"ask_oil_due_offer_{self.suffix}"
        self._register(self.admin, household=f"AskOilDueOffer {self.suffix}", name="Pat")
        self._put_key(chat=False)
        item_id = self._vehicle("Work Tundra")
        token = self._csrf(self.client.get("/").data)

        with patch("app.utils.ask.complete", side_effect=AssertionError("oil due checks are local")):
            offer = self.client.post(
                "/ask/message",
                json={"message": "is the oil due on my Work Tundra?"},
                headers={"X-CSRF-Token": token},
            )
        data = offer.get_json() or {}
        self.assertTrue(data.get("confirm"), data)
        self.assertIn("No oil-change due date is saved", data.get("say") or "")
        self.assertIn(add_months(date.today(), 6).strftime("%B %-d, %Y"), data.get("say") or "")
        with self.app.app_context():
            from app.builddb.table_reminders import Reminder
            from app.builddb.table_users import User

            hid = User.query.filter_by(username=self.admin).first().household_id
            self.assertEqual(Reminder.query.filter_by(household_id=hid, linked_item_id=item_id, type="oil_change").count(), 0)

        with patch("app.utils.ask.complete", side_effect=AssertionError("confirmation is local")), patch(
            "app.utils.notify.announce_reminder"
        ):
            confirmed = self._yes(token)
        self.assertTrue((confirmed.get_json() or {}).get("ok"), confirmed.get_json())
        with self.app.app_context():
            from app.builddb.table_reminders import Reminder
            from app.builddb.table_users import User

            hid = User.query.filter_by(username=self.admin).first().household_id
            row = Reminder.query.filter_by(household_id=hid, linked_item_id=item_id, type="oil_change").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.due_at.date(), add_months(date.today(), 6))
            self.assertEqual(row.recurrence, "180d")

    def test_confirmation_updates_undated_legacy_oil_reminder(self):
        from app.builddb.builddb import db
        from app.builddb.table_reminders import Reminder
        from app.builddb.table_users import User

        self.admin = f"ask_oil_due_update_{self.suffix}"
        self._register(self.admin, household=f"AskOilDueUpdate {self.suffix}", name="Pat")
        self._put_key(chat=False)
        item_id = self._vehicle("Old Tundra")
        with self.app.app_context():
            hid = User.query.filter_by(username=self.admin).first().household_id
            legacy = Reminder(
                household_id=hid,
                title="Oil change — Old Tundra",
                type="custom",
                due_at=None,
                status="open",
            )
            db.session.add(legacy)
            db.session.commit()
            legacy_id = legacy.id
        token = self._csrf(self.client.get("/").data)

        with patch("app.utils.ask.complete", side_effect=AssertionError("oil due checks are local")):
            offer = self.client.post(
                "/ask/message",
                json={"message": "when is the oil due for Old Tundra?"},
                headers={"X-CSRF-Token": token},
            )
        data = offer.get_json() or {}
        self.assertTrue(data.get("confirm"), data)
        self.assertIn("Update reminder", data.get("say") or "")

        with patch("app.utils.ask.complete", side_effect=AssertionError("confirmation is local")), patch(
            "app.utils.notify.announce_reminder"
        ):
            confirmed = self._yes(token)
        self.assertTrue((confirmed.get_json() or {}).get("ok"), confirmed.get_json())
        with self.app.app_context():
            row = Reminder.query.filter_by(household_id=hid, id=legacy_id).first()
            self.assertEqual(row.type, "oil_change")
            self.assertEqual(row.linked_item_id, item_id)
            self.assertIsNotNone(row.due_at)
            self.assertEqual(row.recurrence, "180d")

    def test_log_oil_change_then_asks_reminder_choice(self):
        from datetime import date

        today = date.today().isoformat()
        self.admin = f"ask_oillog_{self.suffix}"
        self._register(self.admin, household=f"AskOilLog {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Red Tundra")
        token = self._csrf(self.client.get("/").data)
        replies = [
            (
                True,
                '{"tool":"oil_save","args":{"item":"Red Tundra","in_it":"5W-30 full synthetic",'
                f'"last_date":"{today}","last_miles":"78000","interval_months":"6","interval_miles":"5000"'
                "}}",
            ),
            (True, '{"say":"Got the oil change logged."}'),
            (
                True,
                '{"say":"Oil change saved on Red Tundra at 78,000 miles. Want the reminder in 6 months or at 83,000 miles?"}',
            ),
        ]

        def fake_complete(*_a, **_k):
            return replies.pop(0)

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            first = self.client.post(
                "/ask/message",
                json={"message": "add an oil change to my red tundra with 5w-30 full synthetic at 78000 miles"},
                headers={"X-CSRF-Token": token},
            )
        data = first.get_json() or {}
        self.assertTrue(data.get("confirm"), data)
        self.assertIn("oil", (data.get("say") or "").lower())

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            yes = self._yes(token)
        done = (yes.get_json() or {}).get("say") or ""
        self.assertIn("reminder", done.lower())
        self.assertIn("6 months", done.lower())
        self.assertNotIn("{\"", done)
        with self.app.app_context():
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            self.assertEqual(int(row.last_oil_change_mileage or 0), 78000)
            self.assertEqual(str(row.oil_type or ""), "5W-30 full synthetic")
            self.assertEqual(int(row.next_oil_due_mileage or 0), 83000)
            self.assertIsNotNone(row.next_oil_due_date)
    def test_research_tool_answers_with_sources(self):
        self.admin = f"ask_res_{self.suffix}"
        self._register(self.admin, household=f"AskRes {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Blue Tundra")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle

            vehicle = Vehicle.query.filter_by(item_id=item_id).first()
            vehicle.year = 2006
            vehicle.make = "Toyota"
            vehicle.model = "Tundra"
            db.session.commit()
        token = self._csrf(self.client.get("/").data)
        prompts = []
        web_prompts = []

        def fake_complete(prompt, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                return True, '{"tool":"research","args":{"q":"2006 toyota tundra rear differential oil spec"}}'
            return True, '{"say":"The 2006 Tundra rear differential takes 75W-85 GL-5, about 2.6 qt."}'

        def fake_web(prompt, **kwargs):
            web_prompts.append(prompt)
            return True, (
                "75W-85 GL-5 gear oil, roughly 2.6 quarts",
                [{"title": "Toyota 2006 Tundra Owner's Manual", "uri": "https://toyota.com/manual"}],
            )

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            with patch("app.utils.ai.complete_web", side_effect=fake_web):
                resp = self.client.post(
                    "/ask/message",
                    json={"message": "search online for the rear diff oil my 06 tundra takes"},
                    headers={"X-CSRF-Token": token},
                )
        data = resp.get_json() or {}
        self.assertTrue(data.get("ok"), data)
        say = data.get("say") or ""
        self.assertIn("75W-85", say)
        self.assertIn("Owner's Manual", say)
        self.assertIn("https://toyota.com/manual", say)
        self.assertIn("Want me to save", say)
        self.assertIn("rear differential", web_prompts[0].lower())

        def fail_if_called(*_a, **_k):
            raise AssertionError("accepting a research save offer should be local")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            saved = self.client.post(
                "/ask/message",
                json={"message": "yes"},
                headers={"X-CSRF-Token": token},
            )
        saved_data = saved.get_json() or {}
        self.assertTrue(saved_data.get("ok"), saved_data)
        self.assertIn("rear differential", (saved_data.get("say") or "").lower())
        with self.app.app_context():
            from app.builddb.table_vehicles import Vehicle

            vehicle = Vehicle.query.filter_by(item_id=item_id).first()
            self.assertEqual(
                (vehicle.extra_data or {}).get("fluids", {}).get("rear_diff"),
                "75W-85 GL-5 gear oil, roughly 2.6 quarts",
            )
            self.assertEqual(vehicle.oil_needs or "", "")

    def test_fluid_saved_answers_locally(self):
        self.admin = f"ask_fs_{self.suffix}"
        self._register(self.admin, household=f"AskFS {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Diff Tundra")
        with self.app.app_context():
            from app.builddb.builddb import db
            from app.builddb.table_vehicles import Vehicle
            from app.utils.oil import set_fluid

            row = Vehicle.query.filter_by(item_id=item_id).first()
            row.year = 2006
            row.make = "Toyota"
            row.model = "Tundra"
            set_fluid(row, "rear_diff", "75W-85 GL-5")
            db.session.commit()
        token = self._csrf(self.client.get("/").data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("a saved fluid spec must answer locally, no model")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            resp = self.client.post(
                "/ask/message",
                json={"message": "what rear diff oil does my tundra take"},
                headers={"X-CSRF-Token": token},
            )
        data = resp.get_json() or {}
        self.assertTrue(data.get("ok"), data)
        say = data.get("say") or ""
        self.assertIn("75W-85", say)
        self.assertNotIn("motor oil", say.lower())

    def test_oil_save_fluid_writes_extra_data(self):
        self.admin = f"ask_fsave_{self.suffix}"
        self._register(self.admin, household=f"AskFSave {self.suffix}", name="Pat")
        self._put_key(chat=True)
        item_id = self._vehicle("Fluid Tundra")
        token = self._csrf(self.client.get("/").data)
        replies = [
            (True, '{"tool":"oil_save","args":{"item":"Fluid Tundra","fluid":"rear_diff","value":"80W-90 GL-5"}}'),
            (True, '{"say":"Saved the rear diff spec."}'),
        ]

        def fake_complete(*_a, **_k):
            return replies.pop(0)

        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "save 80w-90 gl-5 as the rear diff oil on my fluid tundra"},
                headers={"X-CSRF-Token": token},
            )
        data = resp.get_json() or {}
        self.assertTrue(data.get("ok"), data)
        self.assertTrue(data.get("confirm"), data)

        def fail_if_called(*_a, **_k):
            raise AssertionError("yes is applied locally")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            yes = self._yes(token)
        done = (yes.get_json() or {})
        self.assertTrue(done.get("ok"), done)
        with self.app.app_context():
            from app.builddb.table_vehicles import Vehicle

            row = Vehicle.query.filter_by(item_id=item_id).first()
            fluids = (row.extra_data or {}).get("fluids") or {}
            self.assertEqual(fluids.get("rear_diff"), "80W-90 GL-5")
            self.assertEqual(row.oil_needs or "", "")


class FluidHelperTests(unittest.TestCase):
    def test_fluid_key_matches_phrases(self):
        from app.utils.oil import fluid_key

        self.assertEqual(fluid_key("what kinda rear diff oil does my 06 tundra take"), "rear_diff")
        self.assertEqual(fluid_key("rear differential"), "rear_diff")
        self.assertEqual(fluid_key("transmission fluid"), "transmission")
        self.assertEqual(fluid_key("transfer case oil"), "transfer_case")
        self.assertEqual(fluid_key("coolant type"), "coolant")
        self.assertEqual(fluid_key("brake fluid"), "brake_fluid")
        self.assertEqual(fluid_key("power steering fluid"), "power_steering")
        self.assertEqual(fluid_key("what motor oil does it take"), "")
        self.assertEqual(fluid_key(""), "")

    def test_set_and_get_fluids_roundtrip(self):
        from types import SimpleNamespace as NS

        from app.utils.oil import get_fluids, set_fluid

        host = NS(extra_data={"already": "here"})
        self.assertTrue(set_fluid(host, "rear_diff", "75W-90 GL-5"))
        self.assertTrue(set_fluid(host, "transmission", "WS ATF"))
        self.assertEqual(get_fluids(host), {"rear_diff": "75W-90 GL-5", "transmission": "WS ATF"})
        self.assertEqual(host.extra_data["already"], "here")
        self.assertTrue(set_fluid(host, "rear_diff", ""))
        self.assertEqual(get_fluids(host), {"transmission": "WS ATF"})
        self.assertFalse(set_fluid(host, "engine", "nope"))

    def test_fluids_show_on_item_card(self):
        from types import SimpleNamespace as NS

        from app.utils.ask import _oil_fields

        host = NS(
            extra_data={"fluids": {"rear_diff": "75W-90 GL-5"}},
            oil_needs="0W-20",
            oil_type="",
            oil_capacity="",
            last_oil_change_date=None,
            last_oil_date=None,
            next_oil_due_date=None,
            next_oil_due_mileage=None,
            next_oil_due_hours=None,
            oil_interval_miles=None,
            oil_interval_hours=None,
            oil_interval_months=None,
        )
        item = NS(vehicle=host, tool=None)
        fields = _oil_fields(item)
        self.assertEqual(fields["fluids"], {"Rear differential": "75W-90 GL-5"})
        self.assertEqual(fields["needs"], "0W-20")


class CompleteWebTests(unittest.TestCase):
    def test_gemini_grounding_parses_sources(self):
        from unittest.mock import MagicMock, patch

        import app.utils.ai as ai

        cfg = {
            "provider": "gemini",
            "kind": "gemini",
            "api_key": "k",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-2.5-flash",
        }
        body = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "75W-85 GL-5 gear oil"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "Toyota Manual", "uri": "https://toyota.com/manual"}},
                            {"web": {"uri": "https://example.org/spec"}},
                        ]
                    },
                }
            ]
        }
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"x"
        resp.json.return_value = body
        cfg = dict(cfg, chain=[])
        with patch.object(ai.requests, "post", return_value=resp) as post:
            with patch.object(ai, "get_ai_config", return_value=cfg):
                ok, payload = ai.complete_web(
                    "rear diff oil for a 2006 tundra",
                    system="Research.",
                    household=NS2(settings_json=None),
                )
        self.assertTrue(ok)
        text, sources = payload
        self.assertIn("75W-85", text)
        self.assertEqual(sources[0]["title"], "Toyota Manual")
        self.assertEqual(sources[1]["title"], "spec")
        sent = post.call_args.kwargs["json"]
        self.assertIn("google_search", sent["tools"][0])

    def test_complete_web_needs_a_key(self):
        import app.utils.ai as ai

        with patch.object(ai, "get_ai_config", return_value={"api_key": "", "chain": []}):
            ok, err = ai.complete_web("q", household=NS2(settings_json=None))
        self.assertFalse(ok)
        self.assertIn("No AI key", err)


class NS2(SimpleNamespace):
    pass


class AgentUxTests(AskHttpTests):
    def test_slash_help_lists_agent_and_rooms(self):
        self.admin = f"ask_help_{self.suffix}"
        self._register(self.admin, household=f"AskHelp {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        resp = self.client.post(
            "/ask/message",
            json={"message": "/help"},
            headers={"X-CSRF-Token": token},
        )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("/help", say)
        self.assertIn("/reminders", say)
        self.assertIn("/notes", say)
        self.assertIn("/vault", say)
        self.assertIn("/people", say)
        self.assertIn("/ask/vault", say)
        self.assertIn("search online", say)

    def test_basket_remove_and_reminder_done_flow(self):
        self.admin = f"ask_par_{self.suffix}"
        self._register(self.admin, household=f"AskPar {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        # Explicit local writes use the same confirmation flow without the model.
        def fail_if_called(*_a, **_k):
            raise AssertionError("basket and reminder commands are deterministic")

        with patch("app.utils.ask.complete", side_effect=fail_if_called):
            self.client.post(
                "/ask/message", json={"message": "add paper towels to the basket"}, headers={"X-CSRF-Token": token}
            )
            self.client.post(
                "/ask/message", json={"message": "yes"}, headers={"X-CSRF-Token": token}
            )
            self.client.post(
                "/ask/message", json={"message": "add a reminder for water bill due 2026-10-01"}, headers={"X-CSRF-Token": token}
            )
            self.client.post(
                "/ask/message", json={"message": "yes"}, headers={"X-CSRF-Token": token}
            )
        # Local /reminders snapshot must show it.
        resp = self.client.post("/ask/message", json={"message": "/reminders"}, headers={"X-CSRF-Token": token})
        self.assertIn("water bill", ((resp.get_json() or {}).get("say") or "").lower())
        # Mark it done by name. Like every other write, Ask holds it for a "yes" —
        # the "local" part is that the confirmation runs the tool without the model.
        replies2 = [(True, '{"tool":"reminder_done","args":{"q":"Water bill"}}')]

        def fake_complete2(*_a, **_k):
            return replies2.pop(0) if replies2 else (True, '{"say":"Done."}')

        with patch("app.utils.ask.complete", side_effect=fake_complete2):
            resp = self.client.post(
                "/ask/message", json={"message": "mark water bill done"}, headers={"X-CSRF-Token": token}
            )
            held = (resp.get_json() or {}).get("say") or ""
            self.assertIn("done", held.lower())
            # Confirming must not need the model at all.
            with patch(
                "app.utils.ask.complete",
                side_effect=AssertionError("confirming reminder_done must not call the model"),
            ):
                resp = self.client.post(
                    "/ask/message", json={"message": "yes"}, headers={"X-CSRF-Token": token}
                )
        say = (resp.get_json() or {}).get("say") or ""
        self.assertIn("done", say.lower())
        with self.app.app_context():
            from app.builddb.table_reminders import Reminder
            from app.builddb.table_users import User

            # scoped() reads household_id() off the request, which is not there in a
            # bare app context — scope by the household directly like the other tests.
            hid = User.query.filter_by(username=self.admin).first().household_id
            rows = Reminder.query.filter_by(household_id=hid, status="done").all()
            self.assertTrue(any("water bill" in (r.title or "").lower() for r in rows))

    def test_agent_rename_and_persona(self):
        from app.utils.household_ai import agent_identity

        self.admin = f"ask_name_{self.suffix}"
        self._register(self.admin, household=f"AskName {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        resp = self.client.post(
            "/ask/message",
            json={"message": "call you Jarvis from now on"},
            headers={"X-CSRF-Token": token},
        )
        data = resp.get_json() or {}
        self.assertTrue(data.get("ok"), data)
        self.assertIn("Jarvis", data.get("say") or "")
        with self.app.app_context():
            from app.builddb.table_users import User

            u = User.query.filter_by(username=self.admin).first()
            ident = agent_identity(u.household)
            self.assertEqual(ident["name"], "Jarvis")
        # The bubble picks the new name up on the next render.
        home = self.client.get("/")
        self.assertIn(b">Jarvis<", home.data)

    def test_agent_persona_set_in_chat(self):
        from app.utils.household_ai import agent_identity

        self.admin = f"ask_pers_{self.suffix}"
        self._register(self.admin, household=f"AskPers {self.suffix}", name="Pat")
        self._put_key(chat=True)
        token = self._csrf(self.client.get("/").data)
        resp = self.client.post(
            "/ask/message",
            json={"message": "your details are: we run a ranch; check the diesel level before trips"},
            headers={"X-CSRF-Token": token},
        )
        data = resp.get_json() or {}
        self.assertTrue(data.get("ok"), data)
        with self.app.app_context():
            from app.builddb.table_users import User

            u = User.query.filter_by(username=self.admin).first()
            ident = agent_identity(u.household)
            self.assertIn("ranch", ident["persona"])

    def test_agent_settings_form_saves_name(self):
        self.admin = f"ask_form_{self.suffix}"
        self._register(self.admin, household=f"AskForm {self.suffix}", name="Pat")
        self._put_key(chat=True)
        page = self.client.get("/members/sheet/ai")
        token = self._csrf(page.data)
        resp = self.client.post(
            "/members/ai",
            data={
                "ai_chat": "1",
                "ask_confirm": "ask",
                "agent_name": "Ranch Hand",
                "agent_persona": "We keep horses.",
                "csrf_token": token,
            },
            headers={"X-CSRF-Token": token},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        from app.utils.household_ai import agent_identity

        with self.app.app_context():
            from app.builddb.table_users import User

            u = User.query.filter_by(username=self.admin).first()
            ident = agent_identity(u.household)
        self.assertEqual(ident["name"], "Ranch Hand")
        self.assertIn("horses", ident["persona"])


class NS3(SimpleNamespace):
    pass


if __name__ == "__main__":
    unittest.main()
