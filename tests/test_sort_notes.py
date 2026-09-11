import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.sort_notes import dest_of, guess_dest, heuristic_items, split_dump


DUMP = """Maya — 9/10/26, 8:02 PM
need milk and paper towels

Dad — 9/10/26, 8:03 PM
replaced the battery on the truck at AutoZone $140 keep the receipt

Maya — 9/11/26, 9:00 AM
parking ticket downtown $75
"""


class SortNotesTests(unittest.TestCase):
    def test_discord_split(self):
        chunks = split_dump(DUMP)
        self.assertGreaterEqual(len(chunks), 3)
        blob = " ".join(chunks).lower()
        self.assertIn("milk", blob)
        self.assertIn("battery", blob)
        self.assertIn("ticket", blob)

    def test_guesses(self):
        self.assertEqual(guess_dest("parking ticket downtown $75"), "legal")
        self.assertEqual(guess_dest("need milk and paper towels"), "basket")
        self.assertEqual(guess_dest("replaced the battery on the truck at AutoZone"), "vehicle_part")
        self.assertEqual(guess_dest("HVAC filter is due"), "house_part")
        self.assertEqual(guess_dest("oil change next week"), "reminder")
        self.assertEqual(guess_dest("deck rebuild ideas"), "note")

    def test_heuristic_dump(self):
        items = heuristic_items(DUMP)
        dests = {i["dest"] for i in items}
        self.assertIn("basket", dests)
        self.assertIn("vehicle_part", dests)
        self.assertIn("legal", dests)

    def test_dest_aliases(self):
        self.assertEqual(dest_of("records"), "legal")
        self.assertEqual(dest_of("groceries"), "basket")
        self.assertEqual(dest_of("car"), "vehicle_part")
        self.assertEqual(dest_of("nope"), "note")


if __name__ == "__main__":
    unittest.main()
