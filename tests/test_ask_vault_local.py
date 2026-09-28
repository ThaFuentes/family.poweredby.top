"""Ask handles vault lookups locally and never persists or forwards secrets."""
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask_vault import is_vault_request, local_vault_say


class AskVaultIntentTests(unittest.TestCase):
    def test_explicit_credentials_and_vault_room_are_local(self):
        for text in (
            "What is the Netflix password?",
            "Show my bank login",
            "Open the vault",
            "FamilyTest1!",
        ):
            self.assertTrue(is_vault_request(text), text)
        self.assertTrue(is_vault_request("", "vault"))

    def test_general_password_help_stays_with_ai(self):
        for text in (
            "How do I reset my Netflix password?",
            "How do I change my account password?",
            "What makes a good password?",
        ):
            self.assertFalse(is_vault_request(text), text)

    def test_saved_credential_requests_are_local(self):
        for text in (
            "Can you show me the password for Netflix?",
            "What is my Netflix password?",
            "What is my Netflix login?",
            "What is my bank PIN?",
        ):
            self.assertTrue(is_vault_request(text), text)

    def test_pasted_secret_is_caught_before_model_and_transcript(self):
        from flask import Flask

        from app.utils import ask

        app = Flask(__name__)
        app.secret_key = "test"
        user = type("User", (), {"household_id": 1, "is_authenticated": True})()
        household = type("Household", (), {"id": 1})()
        with app.test_request_context("/"):
            with patch.object(ask, "current_user", user), patch.object(ask, "ask_ready", return_value=True), patch.object(
                ask, "_load_turns", return_value=[]
            ), patch.object(ask, "_turn_user", return_value=None), patch.object(ask, "clear_history") as clear_history, patch.object(
                ask, "_clear_turns"
            ) as clear_turns, patch.object(ask, "_save_history") as save_history, patch.object(
                ask, "complete", side_effect=AssertionError("secret must not reach AI")
            ):
                response = ask.run_ask("FamilyTest1!", household=household)
        self.assertTrue(response.get("volatile"))
        self.assertTrue(response.get("clear_history"))
        self.assertEqual([call.args for call in clear_history.call_args_list], [("house",), ("vault",)])
        self.assertFalse(clear_turns.called)
        self.assertFalse(save_history.called)
        self.assertTrue(is_vault_request("My password is Local-Secret-99"))
        self.assertTrue(is_vault_request("password: Local-Secret-99"))

    def test_vault_request_clears_house_and_vault_transcripts(self):
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test"
        with app.test_request_context("/"):
            with patch("app.utils.ask.clear_history") as clear_history, patch(
                "app.utils.ask._vault_guard", return_value={"need": "vault_unlock", "error": "locked"}
            ):
                result = local_vault_say("What is the Netflix password?", "house")
        self.assertTrue(result["volatile"])
        self.assertEqual(clear_history.call_args_list[0].args, ("house",))
        self.assertEqual(clear_history.call_args_list[1].args, ("vault",))

    def test_unrelated_requests_continue_to_normal_ask(self):
        self.assertFalse(is_vault_request("Where is the drill?"))
        self.assertFalse(is_vault_request("What oil does my Tundra take?"))


class AskVaultLocalTests(unittest.TestCase):
    def _run(self, text, *, room="house", guard=None, entries=None, card=None, has_photo=False):
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test"
        with app.test_request_context("/"):
            with patch("app.utils.ask.clear_history") as clear_history, patch(
                "app.utils.ask._vault_guard", return_value=guard
            ), patch("app.utils.ask.tool_vault_list", return_value={"entries": entries or []}) as list_cards, patch(
                "app.utils.ask.tool_vault_open", return_value=card or {"ok": True}
            ) as open_card:
                result = local_vault_say(text, room, has_photo=has_photo)
                return result, clear_history, list_cards, open_card

    def test_locked_vault_routes_to_reauthentication_page(self):
        result, _clear, list_cards, open_card = self._run(
            "What is the Netflix password?",
            guard={"ok": False, "need": "vault_unlock", "error": "Vault is locked."},
        )
        self.assertTrue(result["vault_locked"])
        self.assertTrue(result["volatile"])
        self.assertEqual(result["redirect_url"], "/vault/?next=%2Fask%2Fvault")
        self.assertNotIn("password", result["say"].lower())
        list_cards.assert_not_called()
        open_card.assert_not_called()

    def test_unlocked_password_lookup_is_local_and_volatile(self):
        result, _clear, list_cards, open_card = self._run(
            "What is the Netflix password?",
            entries=[{"id": 17, "title": "Netflix", "href": "/vault/17"}],
            card={"ok": True, "title": "Netflix", "secret": "Local-Secret-99", "href": "/vault/17"},
        )
        self.assertIn("Local-Secret-99", result["say"])
        self.assertTrue(result["volatile"])
        self.assertTrue(result["clear_history"])
        list_cards.assert_called_once_with("netflix")
        open_card.assert_called_once_with(17)

    def test_login_request_does_not_return_password(self):
        result, _clear, _list, _open = self._run(
            "What is the Netflix login?",
            entries=[{"id": 17, "title": "Netflix", "href": "/vault/17"}],
            card={"ok": True, "title": "Netflix", "login": "family@example.test", "secret": "Local-Secret-99", "href": "/vault/17"},
        )
        self.assertIn("family@example.test", result["say"])
        self.assertNotIn("Local-Secret-99", result["say"])

    def test_ambiguous_card_asks_which_one_without_opening_secret(self):
        result, _clear, _list, open_card = self._run(
            "What is my password?",
            entries=[{"id": 1, "title": "Home WiFi"}, {"id": 2, "title": "Work WiFi"}],
        )
        self.assertIn("Which vault card", result["say"])
        open_card.assert_not_called()

    def test_photo_is_not_sent_through_vault_room(self):
        result, _clear, _list, open_card = self._run("", room="vault", has_photo=True)
        self.assertTrue(result["volatile"])
        self.assertIn("photo", result["say"].lower())
        open_card.assert_not_called()


if __name__ == "__main__":
    unittest.main()
