"""VIN-aware fluid answers stay local and never hit NHTSA during tests."""
import os
import re
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils import ask_vin

VIN = "5TFBT54106X123456"


def decoded(*, drive="4x4", displacement="5.7", engine="V8 5.7L", transmission="Automatic"):
    return {
        "ok": True,
        "vin": VIN,
        "name": "2007 Toyota Tundra SR5",
        "facts": {
            "year": "2007",
            "make": "Toyota",
            "model": "Tundra",
            "trim": "SR5",
            "drive_type": drive,
            "fuel_type": "Gasoline",
            "engine": engine,
            "displacement_l": displacement,
            "cylinders": "8",
            "transmission": transmission,
        },
    }


class AskVinGuideTests(unittest.TestCase):
    def _app(self):
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test-session"
        return app

    def _answer(self, question, decode_result=None):
        app = self._app()
        with app.test_request_context("/"):
            with patch.object(ask_vin, "decode_vin", return_value=decode_result or decoded()), patch.object(
                ask_vin, "_household_vin", return_value=None
            ):
                return ask_vin.vin_fluid_say(f"{question} {VIN}")

    def test_rear_diff_answers_with_rear_diff_spec_not_engine_oil(self):
        say = self._answer("what rear diff oil does this VIN take")["say"]
        self.assertIn("Rear differential", say)
        self.assertIn("75W-90", say)
        self.assertNotIn("0W-20", say)
        self.assertNotIn("engine oil", say.lower())

    def test_displacement_selects_the_57_capacity_alternative(self):
        say = self._answer("what engine oil does this VIN take")["say"]
        self.assertIn("8.0 qt (5.7L)", say)
        self.assertNotIn("6.9 qt (4.7L)", say)
        self.assertNotIn("both choices", say)

    def test_4x2_does_not_suggest_front_diff_or_transfer_case_service(self):
        facts = decoded(drive="4x2")
        front = self._answer("what front diff fluid does this VIN take", facts)
        transfer = self._answer("what transfer case fluid does this VIN take", facts)
        for say in (front["say"], transfer["say"]):
            self.assertIn("2WD", say)
            self.assertNotIn("75W-90", say)
            self.assertNotIn("Toyota WS ATF", say)

    def test_4wd_includes_transfer_case_spec(self):
        say = self._answer("what transfer case fluid does this VIN take", decoded(drive="4WD"))["say"]
        self.assertIn("Transfer case", say)
        self.assertIn("Toyota WS ATF", say)

    def test_explicit_web_search_bypasses_vin_guide(self):
        with patch.object(ask_vin, "decode_vin", side_effect=AssertionError("must not decode")):
            self.assertIsNone(ask_vin.vin_fluid_say(f"search online for rear diff oil for VIN {VIN}"))

    def test_named_saved_vehicle_uses_its_stored_vin(self):
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test-session"
        vehicle = type("Vehicle", (), {"vin": VIN})()
        item = type("Item", (), {
            "id": 87,
            "name": "Blue Tundra",
            "vehicle": vehicle,
            "item_type": "vehicle",
            "notes": "",
            "category": "vehicle",
            "barcode": "",
            "tool": None,
            "grocery": None,
        })()
        with app.test_request_context("/"):
            with patch("app.utils.ask._oil_targets", return_value=[item]), patch.object(
                ask_vin, "decode_vin", return_value=decoded()
            ):
                result = ask_vin.vin_fluid_say("what rear diff oil does my Blue Tundra take")
        self.assertIn("75W-90", result["say"])
        self.assertIn("/items/87", result["say"])


class AskVinPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(ROOT)
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            from app.utils.access import mint_service_pass

            cls.service_key = mint_service_pass(max_uses=80, days=30, label="ask-vin-tests").code

    def setUp(self):
        self.client = self.app.test_client()
        self.username = "vin_" + os.urandom(4).hex()
        response = self.client.post(
            "/auth/register",
            data={
                "name": "VIN test",
                "username": self.username,
                "email": f"{self.username}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"VIN test {self.username}",
                "family_key": "",
                "invite_code": "",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200, response.data)
        html = self.client.get("/").data.decode("utf-8", "replace")
        token = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        if not token:
            token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertIsNotNone(token, "CSRF token missing from app page")
        self.csrf = token.group(1)

    def _post(self, message):
        return self.client.post(
            "/ask/message",
            json={"message": message},
            headers={"X-CSRF-Token": self.csrf},
        )

    def _vehicle(self, vin=VIN, name="Tundra", *, other_user=None):
        from app.builddb.builddb import db
        from app.builddb.table_items import Item
        from app.builddb.table_users import User
        from app.builddb.table_vehicles import Vehicle

        user = User.query.filter_by(username=other_user or self.username).first()
        item = Item(
            household_id=user.household_id,
            item_type="vehicle",
            name=name,
            created_by=user.id,
        )
        db.session.add(item)
        db.session.flush()
        db.session.add(
            Vehicle(
                item_id=item.id,
                household_id=user.household_id,
                year=2007,
                make="Toyota",
                model="Tundra",
                vin=vin,
                drive_type="4WD",
            )
        )
        db.session.commit()
        return item.id

    def test_same_household_vin_uses_existing_vehicle_without_duplicate(self):
        with self.app.app_context():
            item_id = self._vehicle(name="Blue Tundra")
            from app.builddb.table_vehicles import Vehicle

            self.assertEqual(Vehicle.query.filter_by(item_id=item_id).first().vin, VIN)
        with patch("app.utils.ask.complete", side_effect=AssertionError("guide needs no AI key")), patch.object(
            ask_vin, "decode_vin", return_value=decoded()
        ):
            response = self._post(f"what rear diff fluid does this VIN take {VIN}")
        say = (response.get_json() or {}).get("say", "")
        self.assertIn("Rear differential", say)
        self.assertIn(f"/items/{item_id}", say)
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_users import User
            from app.builddb.table_vehicles import Vehicle

            hid = User.query.filter_by(username=self.username).first().household_id
            self.assertEqual(
                Item.query.join(Vehicle, Vehicle.item_id == Item.id)
                .filter(Item.household_id == hid, Vehicle.vin == VIN).count(),
                1,
            )

    def test_vin_only_in_another_household_is_not_matched(self):
        username = "other_" + os.urandom(4).hex()
        other_client = self.app.test_client()
        response = other_client.post(
            "/auth/register",
            data={
                "name": "Other household",
                "username": username,
                "email": f"{username}@family.test",
                "password": "FamilyTest1!",
                "household_name": f"Other {username}",
                "family_key": "",
                "invite_code": "",
                "service_key": self.service_key,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200, response.data)
        with self.app.app_context():
            foreign_id = self._vehicle(name="Foreign Tundra", other_user=username)
        with patch.object(ask_vin, "decode_vin", return_value=decoded()):
            response = self._post(f"what rear diff fluid does this VIN take {VIN}")
        say = (response.get_json() or {}).get("say", "")
        self.assertIn("75W-90", say)
        self.assertNotIn(f"/items/{foreign_id}", say)

    def test_save_that_then_yes_saves_vin_and_fluid_bundle(self):
        with patch.object(ask_vin, "decode_vin", return_value=decoded()), patch(
            "app.utils.ask.complete", side_effect=AssertionError("guide and confirmation are local")
        ):
            first = self._post(f"what rear diff oil does this VIN take {VIN}")
            plan = first.get_json() or {}
            self.assertEqual(first.status_code, 200, plan)
            self.assertIn("save that", plan.get("say", "").lower())
            followup = self._post("save that")
            self.assertTrue((followup.get_json() or {}).get("confirm"), followup.get_json())
            with self.app.app_context():
                from app.builddb.table_items import Item
                from app.builddb.table_users import User

                hid = User.query.filter_by(username=self.username).first().household_id
                self.assertEqual(Item.query.filter_by(household_id=hid, item_type="vehicle").count(), 0)
            accepted = self._post("yes")
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        self.assertTrue((accepted.get_json() or {}).get("ok"), accepted.get_json())
        self.assertIn("Saved the VIN", (accepted.get_json() or {}).get("say", ""), accepted.get_json())
        with self.app.app_context():
            from app.builddb.table_items import Item
            from app.builddb.table_users import User
            from app.builddb.table_vehicles import Vehicle
            from app.utils.oil import get_fluids

            hid = User.query.filter_by(username=self.username).first().household_id
            item = (
                Item.query.join(Vehicle, Vehicle.item_id == Item.id)
                .filter(Item.household_id == hid, Vehicle.vin == VIN).first()
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.vehicle.year, 2007)
            self.assertEqual(item.vehicle.make, "Toyota")
            self.assertEqual(item.vehicle.model, "Tundra")
            self.assertIn("0W-20", item.vehicle.oil_needs)
            fluids = get_fluids(item.vehicle)
            self.assertIn("75W-90", fluids["rear_diff"])
            self.assertIn("Toyota WS ATF", fluids["transfer_case"])
