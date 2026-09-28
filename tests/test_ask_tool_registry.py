"""The tool registry must stay in sync with what run_tool actually implements.

TOOLS is the parser's allow-list: a model turn naming a tool that is not in TOOLS is
discarded and the user gets "I didn't catch that." Four write tools were in that state,
so "mark the water bill done" silently did nothing.
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ask import TOOLS, WRITE_TOOLS, _parse_turn
from app.utils.ask_confirm import _clean_agent_name


def _run_tool_keys():
    with open(os.path.join(ROOT, "app", "utils", "ask.py"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("def run_tool"):]
    return set(re.findall(r'key == "([a-z_]+)"', body))


class ToolRegistryTests(unittest.TestCase):
    def test_every_implemented_tool_is_parsable(self):
        missing = sorted(_run_tool_keys() - set(TOOLS))
        self.assertEqual(missing, [], f"run_tool handles these but _parse_turn rejects them: {missing}")

    def test_every_declared_tool_is_implemented(self):
        missing = sorted(set(TOOLS) - _run_tool_keys())
        self.assertEqual(missing, [], f"TOOLS advertises these but run_tool has no handler: {missing}")

    def test_write_tools_are_parsable(self):
        missing = sorted(set(WRITE_TOOLS) - set(TOOLS))
        self.assertEqual(missing, [], f"WRITE_TOOLS names tools the parser cannot accept: {missing}")

    def test_the_four_regressed_tools_round_trip(self):
        for name, args in (
            ("reminder_done", {"q": "Water bill"}),
            ("basket_remove", {"q": "paper towels"}),
            ("note_delete", {"title": "Wifi"}),
            ("person_update", {"username": "pat", "name": "Pat"}),
            ("item_update", {"q": "truck", "name": "family truck"}),
        ):
            turn = _parse_turn('{"tool":"%s","args":%s}' % (name, json.dumps(args)))
            self.assertEqual(turn["kind"], "tool", name)
            self.assertEqual(turn["tool"], name)


class AgentNameCleanupTests(unittest.TestCase):
    def test_qualifiers_come_off_the_name(self):
        for phrase, want in (
            ("Jarvis", "Jarvis"),
            ("Jarvis from now on", "Jarvis"),
            ("from now on Jarvis", "Jarvis"),
            ("just the Jarvis", "Jarvis"),
            ("Jarvis, thanks", "Jarvis"),
            ("the Jarvis please", "Jarvis"),
            ("Jarvis going forward", "Jarvis"),
            ("Jarvis from now on thanks", "Jarvis"),
            ("Jarvis.", "Jarvis"),
            ('"Jarvis"', "Jarvis"),
        ):
            self.assertEqual(_clean_agent_name(phrase), want, phrase)

    def test_a_real_name_survives(self):
        for phrase in ("Ranch Hand", "Jarvis the Second", "Assistant"):
            self.assertEqual(_clean_agent_name(phrase), phrase)


if __name__ == "__main__":
    unittest.main()
