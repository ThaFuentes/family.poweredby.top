"""The per-key AI budget stops one fast turn from bursting past a rate limit."""
import os
import unittest
from unittest.mock import patch

from app.utils import ai_budget


class EstimateTests(unittest.TestCase):
    def test_rounds_up_at_four_characters_per_token(self):
        self.assertEqual(ai_budget.estimate(None), 1)
        self.assertEqual(ai_budget.estimate(""), 1)
        self.assertEqual(ai_budget.estimate("abcd"), 1)
        self.assertEqual(ai_budget.estimate("abcde"), 2)


class CheckTests(unittest.TestCase):
    def setUp(self):
        ai_budget.reset()

    def test_allows_then_blocks_over_the_token_budget(self):
        ok, wait = ai_budget.check("k", 3000, rpm=10, tpm=5000)
        self.assertTrue(ok)
        self.assertEqual(wait, 0)
        ok, wait = ai_budget.check("k", 3000, rpm=10, tpm=5000)
        self.assertFalse(ok)
        self.assertGreaterEqual(wait, 1)

    def test_blocks_over_the_request_budget(self):
        for _ in range(3):
            self.assertTrue(ai_budget.check("r", 1, rpm=3, tpm=100000)[0])
        self.assertFalse(ai_budget.check("r", 1, rpm=3, tpm=100000)[0])

    def test_one_huge_call_still_goes_through(self):
        # Never wedge forever on a single call bigger than the whole budget.
        self.assertTrue(ai_budget.check("big", 999999, rpm=10, tpm=5000)[0])

    def test_each_key_has_its_own_window(self):
        ai_budget.check("a", 4000, rpm=10, tpm=5000)
        self.assertTrue(ai_budget.check("b", 4000, rpm=10, tpm=5000)[0])

    def test_spend_raises_when_over(self):
        ai_budget.spend("s", "p" * 400, "s" * 400, 600, rpm=10, tpm=5000)
        with self.assertRaises(ai_budget.AIBudget):
            ai_budget.spend("s", "x" * 40000, "y" * 40000, 600, rpm=10, tpm=5000)


class LimitTests(unittest.TestCase):
    _ENV = ("AI_MAX_TOKENS_PER_CALL", "AI_REQUESTS_PER_MINUTE", "AI_TOKENS_PER_MINUTE")

    def test_defaults_when_nothing_is_configured(self):
        with patch.dict(os.environ):
            for key in self._ENV:
                os.environ.pop(key, None)
            with patch("app.utils.platform_settings.get_setting", return_value=""):
                self.assertEqual(ai_budget.limits(), (700, 15, 12000))

    def test_env_override_respects_bounds(self):
        with patch.dict(
            os.environ,
            {"AI_TOKENS_PER_MINUTE": "6000", "AI_MAX_TOKENS_PER_CALL": "5"},
        ):
            per_call, _rpm, tpm = ai_budget.limits()
        self.assertEqual(tpm, 6000)
        self.assertEqual(per_call, 64)  # clamped to the low bound


if __name__ == "__main__":
    unittest.main()
