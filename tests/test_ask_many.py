"""One Ask message can contain several requests, and children can use the chat."""
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask import _identity_lines, _parse_actions, _parse_stock_jobs
from app.utils.ask_access import ask_can
from app.utils.ask_basket_language import basket_add_args
from app.utils.ask_many import split_requests
from app.utils.ask_plain import model_is_busy, plain_talk, sounds_confused


class SplitRequestTests(unittest.TestCase):
    def test_shopping_list_stays_one_request(self):
        text = "add milk, eggs, and bread to the basket"
        self.assertEqual(split_requests(text), [text])

    def test_basket_and_a_reminder_are_two_requests(self):
        parts = split_requests("add milk and eggs to the basket and remind me to take out the trash")
        self.assertEqual(
            parts,
            [
                "add milk and eggs to the basket",
                "remind me to take out the trash",
            ],
        )

    def test_a_question_and_a_chore_both_survive(self):
        parts = split_requests("what's 12 times 12 and add milk to the basket")
        self.assertEqual(parts, ["what's 12 times 12", "add milk to the basket"])

    def test_sentences_and_lines_split(self):
        parts = split_requests("What oil does the tundra take?\nAdd paper towels to the basket.")
        self.assertEqual(
            parts,
            ["What oil does the tundra take?", "Add paper towels to the basket."],
        )

    def test_numbered_jobs_split(self):
        parts = split_requests("1. add milk to the basket 2. remind me about soccer tomorrow")
        self.assertEqual(
            parts,
            ["add milk to the basket", "remind me about soccer tomorrow"],
        )

    def test_one_ordinary_sentence_stays_whole(self):
        text = "can you help me understand photosynthesis?"
        self.assertEqual(split_requests(text), [text])

    def test_one_question_with_and_tell_me_stays_whole(self):
        text = "find my gas gen and tell me what oil it needs"
        self.assertEqual(split_requests(text), [text])

    def test_one_stock_sentence_with_two_foods_stays_whole(self):
        text = (
            "please put the fried burritos that are in the pantry in the fridge please "
            "and make sure we show 2 french vanilla creamers"
        )
        self.assertEqual(split_requests(text), [text])

    def test_a_hanging_question_does_not_stay_inside_the_stock_move(self):
        parts = split_requests(
            "put the burritos that are in the pantry in the fridge and while you do that explain what a plea is"
        )
        self.assertEqual(len(parts), 2)
        self.assertIn("burritos", parts[0].lower())
        self.assertNotIn("plea", parts[0].lower())
        self.assertIn("plea", parts[1].lower())

    def test_tell_me_splits_unless_it_is_the_oil_question(self):
        parts = split_requests("remind me the court date is next thursday and tell me what to bring")
        self.assertEqual(len(parts), 2)
        self.assertNotIn("bring", parts[0].lower())
        self.assertIn("bring", parts[1].lower())
        checklist = split_requests(
            "add a reminder to change the oil in 6 months and tell me a short checklist for the next one"
        )
        self.assertEqual(len(checklist), 2)
        self.assertNotIn("checklist", checklist[0].lower())
        oil = split_requests(
            "find my gas gen and tell me what oil it needs, then remind me to check the spark plug sunday"
        )
        self.assertEqual(oil[0], "find my gas gen and tell me what oil it needs")
        self.assertTrue(oil[1].lower().startswith("remind me"))

    def test_a_percent_question_does_not_swallow_the_basket(self):
        parts = split_requests(
            "add milk, bread, and an oil filter to the basket, and what's 15 percent of 86 dollars"
        )
        self.assertEqual(parts[0], "add milk, bread, and an oil filter to the basket")
        self.assertIn("15", parts[1])

    def test_comma_and_did_i_save_is_its_own_question(self):
        parts = split_requests("hey what's on the shopping list, and did I already save that parking ticket")
        self.assertEqual(len(parts), 2)
        self.assertIn("shopping", parts[0].lower())
        self.assertIn("parking", parts[1].lower())

    def test_first_second_third_split_and_one_first_does_not(self):
        parts = split_requests(
            "I'm going to say a lot. first add paper towels to the basket. "
            "second remind me to mail the court letter tomorrow. "
            "third just tell me I'm doing fine"
        )
        self.assertEqual(
            parts,
            [
                "add paper towels to the basket",
                "remind me to mail the court letter tomorrow",
                "tell me I'm doing fine",
            ],
        )
        whole = "stay calm and tell me the first thing to check"
        self.assertEqual(split_requests(whole), [whole])

    def test_whether_comes_off_the_rear_diff_question(self):
        parts = split_requests(
            "two things: the rear diff oil on the tundra, and whether a fix-it ticket is a big deal"
        )
        self.assertEqual(len(parts), 2)
        self.assertIn("rear diff", parts[0].lower())
        self.assertNotIn("whether", parts[0].lower())
        self.assertIn("whether", parts[1].lower())

    def test_file_a_citation_is_its_own_sentence(self):
        parts = split_requests(
            "don't put the ticket in the groceries. it's a legal paper. file it as a citation from downtown"
        )
        self.assertTrue(any(part.lower().startswith("file it") for part in parts))


class CasualTalkTests(unittest.TestCase):
    def test_hey_can_you_still_adds_the_whole_shopping_list(self):
        parts = split_requests("hey can you add milk, eggs, and bread to the basket please")
        self.assertEqual(len(parts), 1)
        self.assertEqual(basket_add_args(parts[0])["names"], ["milk", "eggs", "bread"])

    def test_out_of_milk_add_it_is_one_basket_add(self):
        text = "we're out of milk, can you add it to the basket"
        self.assertEqual(_parse_stock_jobs(text), [])
        self.assertEqual(split_requests(text), ["add milk to the basket"])

    def test_toss_onto_the_list_is_not_throwing_food_away(self):
        text = "could you toss some bananas and apples onto the grocery list for me"
        self.assertEqual(_parse_stock_jobs(text), [])
        self.assertEqual(basket_add_args(split_requests(text)[0])["names"], ["bananas", "apples"])

    def test_trash_tomorrow_does_not_swallow_the_reminder(self):
        text = "add milk and eggs to the basket and remind me to take out the trash tomorrow"
        self.assertEqual(_parse_stock_jobs(text), [])
        self.assertEqual(
            split_requests(text),
            [
                "add milk and eggs to the basket",
                "remind me to take out the trash tomorrow",
            ],
        )

    def test_common_filler_turns_into_a_command(self):
        self.assertEqual(
            plain_talk("don't let me forget to pick up the kids tomorrow"),
            "remind me to pick up the kids tomorrow",
        )
        self.assertTrue(plain_talk("um so we need oat milk and paper towels on the shopping list").lower().startswith("we need"))
        self.assertEqual(plain_talk("would you mind adding dish soap to the basket"), "add dish soap to the basket")
        self.assertEqual(plain_talk("what do we need from the store"), "what's on the shopping list")
        self.assertTrue(plain_talk("can you remind me to pay the water bill on friday").lower().startswith("remind me to"))
        self.assertEqual(
            plain_talk("can you cross the oat milk off the list if it's on there"),
            "cross the oat milk off the list",
        )
        from app.utils.ask_basket_language import basket_remove_args

        self.assertEqual(
            basket_remove_args(plain_talk("cross the oat milk off the list if it's on there"))["q"],
            "oat milk",
        )
        self.assertTrue(plain_talk("hey remind me the water bill is due friday").lower().startswith("remind me that"))
        from app.utils.ask import _local_inventory_query, _local_quantity_update_args

        self.assertEqual(_local_inventory_query("is there any milk left"), "milk")
        self.assertEqual(_local_inventory_query(plain_talk("hey do we have any eggs")), "eggs")
        self.assertEqual(_local_quantity_update_args(plain_talk("can you set the creamer count to 2"))["amount"], "2")

    def test_a_confused_reply_is_retried_and_a_real_answer_is_not(self):
        self.assertTrue(sounds_confused("I do not understand."))
        self.assertTrue(sounds_confused("I'm not sure what you mean."))
        self.assertFalse(sounds_confused("The model is busy right now. Try again later."))
        self.assertFalse(
            sounds_confused(
                "I don't understand the oil spec, so here is the saved 5W-30 for the truck and the filter number."
            )
        )
        self.assertTrue(model_is_busy("The model is busy right now."))
        self.assertFalse(model_is_busy("I do not understand."))


class IdentityTests(unittest.TestCase):
    def test_house_rules_are_stated_before_personal_notes_and_win(self):
        spoken = _identity_lines({
            "name": "Scout",
            "persona": "We keep horses.",
            "user_instructions": "Talk like a pirate.",
        })
        self.assertIn("Your name is Scout", spoken)
        self.assertLess(spoken.index("House rules"), spoken.index("This person's own instructions"))
        self.assertLess(spoken.index("We keep horses."), spoken.index("Talk like a pirate."))
        self.assertIn("follow the house rules", spoken)
        self.assertLess(spoken.index("Talk like a pirate."), spoken.index("follow the house rules"))


class LegalTalkTests(unittest.TestCase):
    def test_an_explicit_ticket_is_a_save_and_advice_is_not(self):
        from app.utils.ask_legal import legal_save_args, local_legal

        args = legal_save_args("save a parking ticket from the city, 45 dollars, due next friday")
        self.assertEqual(args["kind"], "ticket")
        self.assertEqual(args["title"], "Parking ticket")
        self.assertEqual(args["amount"], "45")
        self.assertRegex(args["due"], r"^\d{4}-\d{2}-\d{2}$")
        filed = legal_save_args("file it as a citation from downtown")
        self.assertEqual(filed["kind"], "citation")
        self.assertEqual(filed["location"], "downtown")
        self.assertIsNone(local_legal("what happens if I just ignore a parking ticket"))
        self.assertIsNone(local_legal("explain probate like we're sitting in the garage"))
        self.assertIsNone(legal_save_args("I'm not asking you to save anything"))


class ChildAskTests(unittest.TestCase):
    def _kid(self):
        return SimpleNamespace(
            role="child",
            is_authenticated=True,
            permissions_json=None,
            is_leader=False,
        )

    def test_child_can_do_everyday_chores_and_not_the_vault(self):
        kid = self._kid()
        self.assertTrue(ask_can("maintain", kid))
        self.assertTrue(ask_can("edit_grocery", kid))
        self.assertFalse(ask_can("vault", kid))
        self.assertFalse(ask_can("members", kid))
        self.assertFalse(ask_can("legal", kid))
        self.assertFalse(ask_can("edit_meta", kid))

    def test_several_tools_in_one_reply_all_count(self):
        raw = (
            '{"tool":"basket_add","args":{"names":["milk","eggs"]}}\n'
            '{"tool":"reminder_save","args":{"title":"soccer","type":"custom"}}'
        )
        actions = _parse_actions(raw)
        self.assertEqual([row["tool"] for row in actions], ["basket_add", "reminder_save"])


if __name__ == "__main__":
    unittest.main()
