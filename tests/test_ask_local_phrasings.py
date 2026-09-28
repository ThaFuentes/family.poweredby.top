"""Local Ask phrasing coverage: stock, due, trip, and sort.

The bug class here is a handler that matches one spelling of a request and silently
returns None on every other one, so the turn falls through to the model or worse,
answers a different question. These lock the phrasings people actually type.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask import (
    _SORT_INV,
    _is_due_ask,
    _is_mile_log_ask,
    _mile_log_parts,
    _parse_stock_jobs,
    _local_day,
    _local_recurrence,
    _local_update_args,
    _local_explicit_list_kind,
    _local_quantity_update_args,
    _local_command_say,
    _local_inventory_read,
    _local_inventory_query,
)


def _job(text, **want):
    jobs = _parse_stock_jobs(text)
    if not jobs:
        return False
    j = jobs[0]
    return all(j.get(k) == v for k, v in want.items())


class StockMoveTests(unittest.TestCase):
    def test_in_and_to_both_work(self):
        for text in (
            "put the milk in the fridge",
            "put the milk into the fridge",
            "move the burritos to the freezer",
            "move the milk to the pantry",
            "move the milk from the fridge to the pantry",
            "keep the butter in the pantry",
        ):
            self.assertTrue(_job(text, action="place"), text)

    def test_goes_in_still_works(self):
        self.assertTrue(_job("milk goes in the fridge", action="place"))


class StockDiscardTests(unittest.TestCase):
    def test_consume_phrasings(self):
        for text in (
            "toss the yogurt",
            "throw out the expired bread",
            "get rid of the old mustard",
            "i'm out of eggs",
            "we ran out of milk",
            "we finished the OJ",
            "we used up the milk",
        ):
            self.assertTrue(_job(text, action="used"), text)

    def test_hard_deletes_stay_off_the_local_path(self):
        # delete/remove go through item_remove, which has its own guard rails.
        for text in ("delete the protein bars", "remove the milk", "toss it", "bin the trash"):
            self.assertEqual(_parse_stock_jobs(text), [], text)


class DueTests(unittest.TestCase):
    def test_due_phrasings(self):
        for text in (
            "whats due",
            "what's due",
            "anything due",
            "what bills are due",
            "what oil changes are due",
            "show me the reminders",
            "due this week",
            "my oil change is past due",
            "tell me whats due soon",
            "what do we have coming up",
            "anything coming up this week",
            "what needs doing",
            "bills due soon",
            "reminders coming up",
            "what maintenance is coming up",
        ):
            self.assertTrue(_is_due_ask(text), text)

    def test_commands_and_unrelated_are_not_due_asks(self):
        for text in (
            "add a reminder for water",
            "remind me to water plants",
            "delete the protein bars",
            "set a reminder",
            "whats the weather",
            "what tools do i have",
            "what oil does the tundra take",
            "what rear diff oil does the tundra take",
        ):
            self.assertFalse(_is_due_ask(text), text)


class MileLogTests(unittest.TestCase):
    def test_readings_are_pulled_out(self):
        for text, want in (
            ("i drove 340 miles", ("340", "")),
            ("we drove 1,200 miles", ("1200", "")),
            ("add 118000 miles to the tundra", ("118000", "")),
            ("record 95000 on the tundra", ("95000", "tundra")),
            ("the tundra has 50000 miles", ("50000", "tundra")),
        ):
            self.assertEqual(_mile_log_parts(text), want, text)

    def test_service_sentences_are_not_mile_logs(self):
        for text in (
            "add an oil change to my red tundra with 5w-30 full synthetic at 78000 miles",
            "log an oil change at 78000 miles",
            "change the oil at 80000 miles",
            "remind me to change the oil at 80000 miles",
            "service the tundra at 90000",
        ):
            self.assertFalse(_is_mile_log_ask(text), text)

    def test_trip_words_go_to_the_trip_handler(self):
        for text in ("start a trip", "end the trip", "finish the trip at 120000", "trip start 118000", "i'm home"):
            self.assertFalse(_is_mile_log_ask(text), text)


class LocalWritePhrasingTests(unittest.TestCase):
    def test_basket_add_accepts_everyday_chat_phrasing(self):
        from unittest.mock import patch

        cases = {
            "add chips to my basket": ["chips"],
            "can you add chips to my basket": ["chips"],
            "I'd like you to add chips to my basket please": ["chips"],
            "put chips on the shopping list": ["chips"],
            "add chips to my list": ["chips"],
            "grab chips and salsa for the basket": ["chips", "salsa"],
            "add chips and salsa to the basket from Costco": ["chips", "salsa"],
        }
        for phrase, names in cases.items():
            with self.subTest(phrase=phrase), patch("app.utils.ask._local_write", return_value={"ok": True}) as write:
                self.assertIsNotNone(_local_command_say(phrase), phrase)
                self.assertEqual(write.call_args.args[0], "basket_add", phrase)
                self.assertEqual(write.call_args.args[1]["names"], names, phrase)
        with patch("app.utils.ask._local_write", return_value={"ok": True}) as write:
            _local_command_say("add chips and salsa to the basket from Costco")
            self.assertEqual(write.call_args.args[1]["store"], "Costco")

    def test_basket_lists_accept_conversational_requests(self):
        for phrase in (
            "what's on my basket",
            "what's in my list",
            "list my basket",
            "can you show me what's on the shopping list please",
            "tell me what is in our grocery list",
        ):
            self.assertEqual(_local_explicit_list_kind(phrase), "basket", phrase)

    def test_item_updates_cover_common_forms(self):
        cases = {
            "rename the blue tundra to Family Truck": {"q": "blue tundra", "name": "Family Truck"},
            "change the model for the blue tundra to Tundra": {"q": "blue tundra", "model": "Tundra"},
            "update the blue tundra's color to black": {"q": "blue tundra", "color": "black"},
            "set the blue tundra year to 2006": {"q": "blue tundra", "year": "2006"},
            "change the drill's serial number to SN-41": {"q": "drill", "serial": "SN-41"},
        }
        for phrase, expected in cases.items():
            self.assertEqual(_local_update_args(phrase), expected, phrase)

    def test_everyday_list_questions_are_recognized_conservatively(self):
        expected = {
            "what's on the shopping list": "basket",
            "what reminders are open": "reminders",
            "what bills are due": "due",
            "who is in this household": "people",
            "what notes are saved": "notes",
            "can you show all my tools": "tools",
            "what do we have in the pantry": "inventory",
        }
        for phrase, kind in expected.items():
            self.assertEqual(_local_explicit_list_kind(phrase), kind, phrase)
        for phrase in ("is the drill in the garage?", "tell me about the water bill", "what should I buy?"):
            self.assertIsNone(_local_explicit_list_kind(phrase), phrase)

    def test_stock_count_changes_require_an_explicit_count(self):
        cases = {
            "set the count of milk to 4": {"q": "milk", "action": "set", "amount": "4"},
            "update paper towels quantity to 1,200 on hand": {"q": "paper towels", "action": "set", "amount": "1200"},
            "change cereal to 3 in stock": {"q": "cereal", "action": "set", "amount": "3"},
        }
        for phrase, expected in cases.items():
            self.assertEqual(_local_quantity_update_args(phrase), expected, phrase)
        for phrase in ("we need 3 milks", "show 2 of these in inventory", "change the truck to 3"):
            self.assertIsNone(_local_quantity_update_args(phrase), phrase)

    def test_item_stock_questions_have_a_narrow_local_parser(self):
        for phrase in (
            "how much milk do we have",
            "do we have any milk?",
            "what's the quantity of milk in the pantry?",
        ):
            self.assertIsNotNone(_local_inventory_query(phrase), phrase)
        self.assertIsNone(_local_inventory_query("what do you think about milk?"))
        self.assertIsNone(_local_inventory_read("what do you think about milk?"))

    def test_conversational_due_dates_and_repeat_intervals(self):
        from datetime import date, timedelta

        today = date.today()
        self.assertEqual(_local_day("tomorrow"), today + timedelta(days=1))
        self.assertEqual(_local_day("in 2 weeks"), today + timedelta(days=14))
        self.assertEqual(_local_day(today.strftime("%m/%d/%Y")), today)
        self.assertEqual(_local_recurrence("every six months"), ("180d", ""))
        self.assertEqual(_local_recurrence("every 5,000 miles"), ("5000mi", ""))
        self.assertTrue(_local_recurrence("every 5 miles")[1])


class SortTests(unittest.TestCase):
    def test_sort_phrasings(self):
        for text in (
            "sort the inventory",
            "organize the pantry",
            "file the groceries",
            "re-file all inventory",
            "sort everything",
            "put all the food away",
        ):
            self.assertTrue(_SORT_INV.search(text), text)

    def test_unrelated_is_not_a_sort(self):
        self.assertIsNone(_SORT_INV.search("what oil does the tundra take"))


if __name__ == "__main__":
    unittest.main()
