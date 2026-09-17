import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.builddb.table_legal_cases import case_label
from app.builddb.table_legal_followups import FOLLOWUP_KINDS


class CaseLabelTests(unittest.TestCase):
    def test_number(self):
        self.assertEqual(case_label(SimpleNamespace(number=1)), "Case #1")
        self.assertEqual(case_label(SimpleNamespace(number=12)), "Case #12")

    def test_none(self):
        self.assertEqual(case_label(None), "")

    def test_bad_number(self):
        self.assertEqual(case_label(SimpleNamespace(number=None)), "Case")


class FollowupKindTests(unittest.TestCase):
    def test_kinds(self):
        self.assertIn("note", FOLLOWUP_KINDS)
        self.assertIn("link", FOLLOWUP_KINDS)
        self.assertIn("email", FOLLOWUP_KINDS)
        self.assertIn("file", FOLLOWUP_KINDS)


class SearchEmptyHasCases(unittest.TestCase):
    def test_empty_result_includes_case_rows(self):
        from app.utils.search import search_household

        out = search_household(1, "x", user_id=1)
        self.assertIn("case_rows", out)
        self.assertEqual(out["legal_rows"], [])
        self.assertEqual(out["case_rows"], [])


if __name__ == "__main__":
    unittest.main()
