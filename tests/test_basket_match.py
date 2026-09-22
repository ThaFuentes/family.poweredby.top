import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.basket_match import score_names
from app.utils.ai import complete, get_ai_config


class ScoreTests(unittest.TestCase):
    def test_placeholder_matches_real_name(self):
        self.assertGreaterEqual(
            score_names("coffee creamer", "International Delight French Vanilla Coffee Creamer"),
            0.99,
        )

    def test_unrelated_stays_apart(self):
        self.assertLess(score_names("coffee creamer", "Charmin ultra soft toilet paper"), 0.5)


class TenantAiTests(unittest.TestCase):
    def test_complete_refuses_other_household(self):
        from dotenv import load_dotenv
        from flask_login import login_user

        load_dotenv(os.path.join(ROOT, ".env"))
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            from app.builddb.table_users import User

            user = User.query.filter(User.household_id.isnot(None)).first()
            if user is None:
                self.skipTest("no household user in local db")
            other = SimpleNamespace(
                id=int(user.household_id) + 99991,
                settings_json={"ai": {"api_key": "other-house-key", "provider": "gemini", "enabled": True}},
            )
            with app.test_request_context("/"):
                login_user(user)
                ok, msg = complete("ping", household=other, household_only=True)
                self.assertFalse(ok)
                self.assertIn("household", (msg or "").lower())
                cfg = get_ai_config(other, household_only=True)
                self.assertFalse(cfg.get("has_key"))


class BasketHttpTests(unittest.TestCase):
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

            cls.service_key = mint_service_pass(max_uses=8, days=30, label="basket-match").code

    def _csrf(self, html):
        import re

        text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', text)
        return m.group(1) if m else ""

    def _register(self, username):
        self.client.get("/auth/logout", follow_redirects=True)
        data = {
            "name": "Pat",
            "username": username,
            "email": f"{username}@family.test",
            "password": "FamilyTest1!",
            "household_name": f"Basket {self.suffix}",
            "family_key": "",
            "invite_code": "",
            "service_key": self.service_key,
        }
        return self.client.post("/auth/register", data=data, follow_redirects=True)

    def test_ask_adds_placeholders_and_scan_clears_them(self):
        admin = f"bask_{self.suffix}"
        self._register(admin)
        with self.app.app_context():
            from app.builddb.table_households import Household
            from app.builddb.table_users import User
            from app.utils.household_ai import save_household_ai

            u = User.query.filter_by(username=admin).first()
            save_household_ai(Household.query.get(u.household_id), provider="gemini", api_key="test-key")
        replies = [
            (True, '{"tool":"basket_add","args":{"names":["coffee creamer","paper towels"],"store":"Sam\'s"}}'),
            (True, '{"say":"On the basket from Sam\'s."}'),
        ]

        def fake_complete(*args, **kwargs):
            return replies.pop(0)

        token = self._csrf(self.client.get("/").data)
        with patch("app.utils.ask.complete", side_effect=fake_complete):
            resp = self.client.post(
                "/ask/message",
                json={"message": "From Sam's: coffee creamer, paper towels"},
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        with self.app.app_context():
            from app.builddb.table_grocery_list import GroceryListEntry
            from app.builddb.table_users import User
            from app.routes.items import quick_create_item
            from app.utils.basket_match import suggest_for_item
            from app.utils.scan import _with_basket_match

            u = User.query.filter_by(username=admin).first()
            rows = GroceryListEntry.query.filter_by(household_id=u.household_id, status="open").all()
            names = {r.name for r in rows}
            self.assertIn("coffee creamer", names)
            cream = [r for r in rows if r.name == "coffee creamer"][0]
            self.assertEqual(cream.note, "Sam's")
            self.assertIsNone(cream.item_id)
            item, _status = quick_create_item(
                hid=u.household_id,
                user_id=u.id,
                name="International Delight French Vanilla Coffee Creamer",
                item_type="grocery",
                barcode=f"012{self.suffix[:8]}",
                quantity=1,
                action="restock",
            )
            hit = suggest_for_item(u.household_id, item)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["id"], cream.id)
            from flask_login import login_user

            with self.app.test_request_context("/"):
                login_user(u)
                payload = _with_basket_match(
                    {"action": "into", "message": "Got more.", "on_list": False},
                    u.household_id,
                    item,
                )
            self.assertTrue(payload.get("basket_cleared"))
            cream = GroceryListEntry.query.get(cream.id)
            self.assertEqual(cream.status, "done")
            self.assertEqual(cream.item_id, item.id)


if __name__ == "__main__":
    unittest.main()
