import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ai import complete


def _house():
    return SimpleNamespace(
        id=1,
        settings_json={
            "ai": {
                "provider": "gemini",
                "model": "gemini-3.6-flash",
                "api_key": "gem-key",
                "enabled": True,
                "chat": True,
                "backup": {
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                    "api_key": "gsk-test",
                },
            }
        },
    )


class FailoverTests(unittest.TestCase):
    def test_busy_gemini_uses_groq(self):
        def boom(*_a, **_k):
            raise RuntimeError("503 high demand")

        with patch("app.utils.ai.time.sleep"), patch("app.utils.ai._gemini", side_effect=boom), patch(
            "app.utils.ai._openai_compat", return_value="from groq"
        ):
            ok, text = complete("hi", household=_house(), household_only=True)
        self.assertTrue(ok)
        self.assertEqual(text, "from groq")

    def test_photo_on_groq_uses_qwen(self):
        seen = {}

        def boom(*_a, **_k):
            raise RuntimeError("503 overloaded")

        def groq(cfg, *_a, **_k):
            seen["model"] = cfg.get("model")
            seen["vision"] = cfg.get("vision")
            return "saw the photo"

        with patch("app.utils.ai.time.sleep"), patch("app.utils.ai._gemini", side_effect=boom), patch(
            "app.utils.ai._openai_compat", side_effect=groq
        ):
            ok, text = complete(
                "what is this",
                household=_house(),
                household_only=True,
                image_bytes=b"jpeg",
                image_mime="image/jpeg",
            )
        self.assertTrue(ok, text)
        self.assertEqual(text, "saw the photo")
        self.assertEqual(seen.get("model"), "qwen/qwen3.8-27b")
        self.assertTrue(seen.get("vision"))

    def test_no_backup_stays_busy(self):
        h = _house()
        h.settings_json["ai"].pop("backup")

        def boom(*_a, **_k):
            raise RuntimeError("503 high demand")

        with patch("app.utils.ai.time.sleep"), patch("app.utils.ai._gemini", side_effect=boom), patch(
            "app.utils.ai._openai_compat", return_value="should not run"
        ) as groq:
            ok, text = complete("hi", household=h, household_only=True)
        self.assertFalse(ok)
        self.assertIn("busy", text.lower())
        groq.assert_not_called()

    def test_groq_can_go_first(self):
        h = _house()
        h.settings_json["ai"]["try_order"] = "backup"
        gemini = patch("app.utils.ai._gemini", return_value="from gemini")
        with gemini as gem, patch("app.utils.ai._openai_compat", return_value="from groq"):
            ok, text = complete("hi", household=h, household_only=True)
        self.assertTrue(ok)
        self.assertEqual(text, "from groq")
        gem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
