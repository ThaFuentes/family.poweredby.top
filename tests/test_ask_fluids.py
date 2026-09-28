"""Local (no-API) handling of non-engine fluids: rear diff, transmission, coolant…

The bug these lock down: a "rear diff fluid" question used to come back with the
engine oil spec in front of it, or as a bare vehicle card, because the engine-oil
columns and the fluid phrases were read from two different places.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils import ask
from app.utils.fluid_specs import engine_oil_for, spec_for
from app.utils.oil import fluid_asked, fluid_key


def _vehicle(idx, name, year, make, model, vin="", plate="", oil_needs="", fluids=None):
    host = SimpleNamespace(
        id=100 + idx, year=year, make=make, model=model, trim="", color="",
        vin=vin, plate=plate, oil_needs=oil_needs, oil_type="",
        oil_capacity=None, last_oil_change_date=None, last_oil_change_mileage=None,
        oil_interval_miles=None, oil_interval_months=None, next_oil_due_date=None,
        next_oil_due_mileage=None, next_oil_due_hours=None,
        extra_data={"fluids": fluids or {}},
    )
    return SimpleNamespace(
        id=200 + idx, name=name, notes="", category="vehicle", item_type="vehicle",
        vehicle=host, tool=None, qty=None, place=None, expires=None, barcode=None,
    )


ITEMS = [
    _vehicle(1, "Tundra", 2006, "Toyota", "Tundra", vin="5TFBT17F06X123456",
             oil_needs="5W-30 synthetic", fluids={"rear_diff": "Synthetic 75W-90 GL-5, 4.4 qt"}),
    _vehicle(2, "Tacoma", 2019, "Toyota", "Tacoma", oil_needs="0W-20 synthetic",
             fluids={"transmission": "Toyota WS-FL"}),
    _vehicle(3, "Van", 2002, "Ford", "Econoline"),
]


def _find(q, item_type=None, limit=8):
    rows = ITEMS
    if item_type:
        rows = [r for r in rows if r.item_type == item_type]
    if q:
        needle = str(q).strip().lower()
        rows = [r for r in rows if needle in (r.name or "").lower()]
    return sorted(rows, key=lambda r: r.name.lower())[:limit]


USER = SimpleNamespace(id=1, household_id=1, is_authenticated=True, role="member")


class FluidPhraseTests(unittest.TestCase):
    """Every way a person says "the rear diff" lands on the same key."""

    def test_rear_diff_phrasings(self):
        for phrase in (
            "what rear diff fluid does the 06 tundra take",
            "rear diff fluid for an 06 tundra in my vehicles",
            "what oil goes in the rear end of my 06 tundra",
            "what fluid does the rear diff on the tundra need",
            "gear oil in the back end of the tundra",
            "what does the tundra rear axle take",
            "what gear oil for the tundra",
            "whats the tundra diff fluid",
            "ring and pinion oil tundra",
        ):
            self.assertEqual(fluid_key(phrase), "rear_diff", phrase)

    def test_front_diff_stays_front(self):
        self.assertEqual(fluid_key("front diff fluid for the tacoma"), "front_diff")

    def test_one_f_dif_typing_still_lands_on_the_diff(self):
        # People type "dif" with one f — that used to fall through every handler.
        for phrase in (
            "what kinda rear dif oil does it take",
            "what rear dif fluid does the 06 tundra take",
            "rear dif oil tundra",
            "whats the tundra dif fluid",
            "front dif fluid for the tacoma",
        ):
            self.assertEqual(fluid_key(phrase), "rear_diff" if "front" not in phrase else "front_diff", phrase)

    def test_other_fluids(self):
        cases = {
            "what trans fluid for the tacoma": "transmission",
            "what atf does the tacoma need": "transmission",
            "what coolant does the tundra take": "coolant",
            "what antifreeze does the tacoma take": "coolant",
            "brake fluid for the tundra": "brake_fluid",
            "what power steering fluid does the 06 tundra use": "power_steering",
            "what transfer case fluid for the tundra": "transfer_case",
        }
        for phrase, key in cases.items():
            self.assertEqual(fluid_asked(phrase)[0], key, phrase)

    def test_engine_oil_is_not_a_fluid(self):
        for phrase in (
            "what oil does the tundra take",
            "what engine oil does the tacoma take",
            "5W-30 motor oil",
            "add an oil change for the tundra at 150000 miles",
        ):
            self.assertEqual(fluid_key(phrase), "", phrase)


class LocalFluidAnswerTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(ask, "current_user", USER),
            patch.object(ask, "_find_items", _find),
            patch.object(ask, "_path", lambda *a, **k: "/x"),
            patch.object(ask, "_ask_has_ai", lambda: False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_saved_rear_diff_never_shows_the_engine_oil(self):
        for phrase in (
            "what rear diff fluid does the 06 tundra take",
            "rear diff fluid for an 06 tundra in my vehicles",
            "what oil goes in the rear end of my 06 tundra",
            "gear oil in the back end of the tundra",
            "whats the tundra diff fluid",
        ):
            say = ask._fluid_saved_say(phrase) or ""
            self.assertIn("75W-90", say, phrase)
            self.assertNotIn("5W-30", say, phrase)

    def test_saved_transmission_never_shows_the_engine_oil(self):
        say = ask._fluid_saved_say("what atf does the tacoma need") or ""
        self.assertIn("WS-FL", say)
        self.assertNotIn("0W-20", say)

    def test_engine_oil_question_still_answers_with_the_engine_oil(self):
        say = ask._oil_local_say("what oil does the 06 tundra take") or ""
        self.assertIn("5W-30", say)

    def test_unsaved_fluid_on_a_known_truck_comes_from_the_table(self):
        # The 2006 Tundra is in the built-in guide, so coolant is answered with the
        # OEM spec instead of the old “add an AI key” dead end.
        say = ask._fluid_unsaved_say("what coolant does the tundra take") or ""
        self.assertIn("Coolant on Tundra", say)
        self.assertIn("Toyota Long Life", say)
        self.assertNotIn("5W-30", say)
        self.assertIn("save that", say.lower())

    def test_unsaved_fluid_on_an_unknown_machine_still_says_not_saved(self):
        # The 2002 Econoline is not in the guide and there is no AI key.
        say = ask._fluid_unsaved_say("what coolant does the van take") or ""
        self.assertIn("No coolant saved", say)
        self.assertIn("AI key", say)
        self.assertNotIn("5W-30", say)

    def test_ambiguous_machine_asks_which_one(self):
        say = ask._fluid_unsaved_say("what rear diff fluid do my vehicles take") or ""
        self.assertIn("Which vehicle", say)
        self.assertIn("Tundra", say)

    def test_fluids_overview_lists_what_is_on_file(self):
        say = ask._fluids_overview_say("what fluids does the tundra take") or ""
        self.assertIn("5W-30", say)
        self.assertIn("75W-90", say)

    def test_a_named_fluid_beats_the_overview(self):
        # "what fluids" must not swallow "rear diff".
        self.assertIsNone(ask._fluids_overview_say("what rear diff fluids do I have"))

    def test_logging_an_oil_change_is_not_a_fluid_lookup(self):
        for fn in (ask._fluid_saved_say, ask._fluid_unsaved_say, ask._fluids_overview_say):
            self.assertIsNone(fn("add rear diff oil to the tundra at 150000 miles"))

    def test_model_prompt_warns_engine_oil_is_the_wrong_answer(self):
        # No "oil" in the sentence, but the model still needs steering.
        note = ask._oil_inspect_note("what coolant does the tundra take")
        self.assertIsNotNone(note)
        self.assertIn("ENGINE oil only", note["result"]["hint"])


def _veh(idx, name, year="", make="", model=""):
    host = SimpleNamespace(
        id=900 + idx, year=year, make=make, model=model, trim="", color="",
        vin="", plate="", oil_needs="", oil_type="", oil_capacity=None,
        last_oil_change_date=None, last_oil_change_mileage=None,
        oil_interval_miles=None, oil_interval_months=None, next_oil_due_date=None,
        next_oil_due_mileage=None, next_oil_due_hours=None, extra_data={"fluids": {}},
    )
    return SimpleNamespace(
        id=800 + idx, name=name, notes="", category="vehicle", item_type="vehicle",
        vehicle=host, tool=None, qty=None, place=None, expires=None, barcode=None,
    )


class BuiltinGuideTests(unittest.TestCase):
    """The built-in OEM table answers common machines with no AI key at all."""

    def test_06_tundra_rear_diff(self):
        item = _veh(1, "Tundra", year="2006", make="Toyota", model="Tundra")
        spec = spec_for(item)
        self.assertIsNotNone(spec)
        self.assertIn("75W-90", spec["rear_diff"])
        self.assertNotIn("5W-30", spec["rear_diff"])

    def test_name_only_06_tundra(self):
        spec = spec_for(_veh(2, "06 Tundra"))
        self.assertIsNotNone(spec)
        self.assertIn("75W-90", spec["rear_diff"])

    def test_badge_twins(self):
        self.assertIsNotNone(spec_for(_veh(3, "Silverado", year="2004", make="Chevrolet", model="Silverado")))
        self.assertIsNotNone(spec_for(_veh(4, "Sierra", year="2004", make="GMC", model="Sierra")))
        self.assertIsNotNone(spec_for(_veh(5, "Suburban", year="2004", make="Chevrolet", model="Suburban")))

    def test_non_machines_get_nothing(self):
        for name in ("weather", "minivan", "pool pump", "birthday"):
            self.assertIsNone(spec_for(_veh(6, name)), name)

    def test_engine_oil_spec(self):
        oem = engine_oil_for(_veh(7, "Tundra", year="2006", make="Toyota", model="Tundra"))
        self.assertIsNotNone(oem)
        self.assertIn("5W-30", oem["needs"])
        self.assertTrue(oem.get("capacity"))

    def test_tools_answer(self):
        tool = SimpleNamespace(
            id=810, name="gas generator", notes="", category="tool", item_type="tool",
            vehicle=None,
            tool=SimpleNamespace(type="generator", model="", serial_number="", power_source="", fuel_type=""),
        )
        oem = engine_oil_for(tool)
        self.assertIsNotNone(oem)
        self.assertIn("10W-30", oem["needs"])


class LocalTableAnswerTests(unittest.TestCase):
    """Local chat answers unsaved fluids from the guide — never a dead end."""

    def setUp(self):
        self._patches = [
            patch.object(ask, "current_user", USER),
            patch.object(ask, "_find_items", _find),
            patch.object(ask, "_path", lambda *a, **k: "/x"),
            patch.object(ask, "_ask_has_ai", lambda: False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_unsaved_rear_diff_comes_from_the_table(self):
        items = [
            _vehicle(9, "Ranger", 2011, "Ford", "Ranger", vin="", plate=""),
        ]
        with patch.object(ask, "_find_items", lambda q, t=None, limit=8: items if not q or "ranger" in q.lower() else []):
            say = ask._fluid_unsaved_say("what rear diff oil does the ranger take") or ""
        self.assertIn("75W-90", say)
        self.assertNotIn("AI key", say)
        self.assertIn("save that", say.lower())

    def test_unsaved_engine_oil_comes_from_the_table(self):
        items = [_vehicle(10, "Tundra", 2006, "Toyota", "Tundra", oil_needs="")]
        with patch.object(ask, "_find_items", lambda q, t=None, limit=8: items if not q or "tundra" in q.lower() else []):
            say = ask._oil_local_say("what oil does the tundra take") or ""
        self.assertIn("5W-30", say)
        self.assertIn("Built-in guide", say)

    def test_dif_pronoun_ask_finds_the_only_vehicle(self):
        # One truck in the house, named nothing like "rear" or "dif":
        # "what kinda rear dif oil does it take" must answer for THAT truck.
        items = [_vehicle(11, "Gray truck", 2018, "Ford", "F-150")]
        with patch.object(ask, "_find_items", lambda q, t=None, limit=8: items if not q or "truck" in q.lower() else []):
            say = ask._fluid_unsaved_say("what kinda rear dif oil does it take") or ""
        self.assertIn("Rear differential", say)
        self.assertIn("75W", say)
        self.assertNotIn("5W-30", say)
        self.assertNotIn("AI key", say)
        self.assertIn("save that", say.lower())

    def test_engine_oil_pronoun_ask_answers_for_the_only_vehicle(self):
        items = [_vehicle(14, "Gray truck", 2018, "Ford", "F-150", oil_needs="")]
        with patch.object(ask, "_find_items", lambda q, t=None, limit=8: items if not q or "truck" in q.lower() else []):
            say = ask._oil_local_say("what kinda oil does it take") or ""
        self.assertIn("Built-in guide", say)
        self.assertIn("5W-30", say)

    def test_pronoun_ask_with_two_vehicles_does_not_guess(self):
        items = [
            _vehicle(12, "A truck", 2018, "Ford", "F-150"),
            _vehicle(13, "B truck", 2006, "Toyota", "Tundra"),
        ]
        with patch.object(ask, "_find_items", lambda q, t=None, limit=8: items if not q else []):
            self.assertIsNone(ask._fluid_unsaved_say("what kinda rear dif oil does it take"))


if __name__ == "__main__":
    unittest.main()
