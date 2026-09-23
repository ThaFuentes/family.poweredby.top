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

    def test_rejected_groq_model_tries_gpt_oss(self):
        h = SimpleNamespace(
            settings_json={
                "ai": {
                    "chat": True,
                    "enabled": True,
                    "default_id": "g",
                    "keys": [
                        {
                            "id": "g",
                            "provider": "groq",
                            "model": "llama-3.3-70b-versatile",
                            "api_key": "gsk-test",
                            "on": True,
                            "order": 0,
                        }
                    ],
                }
            }
        )
        seen = []

        def groq(cfg, *_a, **_k):
            seen.append(cfg.get("model"))
            if "llama" in (cfg.get("model") or ""):
                raise RuntimeError("The model does not exist or you do not have access to it.")
            return "from gpt-oss"

        with patch("app.utils.ai._openai_compat", side_effect=groq):
            ok, text = complete("hi", household=h, household_only=True)
        self.assertTrue(ok, text)
        self.assertEqual(text, "from gpt-oss")
        self.assertEqual(seen[0], "llama-3.3-70b-versatile")
        self.assertEqual(seen[1], "openai/gpt-oss-20b")

    def test_saved_keys_keep_their_own_provider(self):
        from app.utils.household_ai import household_config

        h = SimpleNamespace(
            settings_json={
                "ai": {
                    "chat": True,
                    "enabled": True,
                    "default_id": "grok",
                    "keys": [
                        {"id": "gem", "provider": "gemini", "model": "gemini-3.6-flash", "api_key": "gem-key", "on": True, "order": 2},
                        {"id": "grok", "provider": "xai", "model": "grok-4.5", "api_key": "xai-key", "on": True, "order": 0},
                        {"id": "off", "provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-key", "on": False, "order": 1},
                    ],
                }
            }
        )
        cfg = household_config(h)
        self.assertEqual([slot["provider"] for slot in cfg["chain"]], ["xai", "gemini"])
        self.assertEqual([row["provider"] for row in cfg["saved_keys"]], ["xai", "gemini", "openai"])
        self.assertTrue(cfg["saved_keys"][0]["default"])
        self.assertFalse(cfg["saved_keys"][2]["on"])


if __name__ == "__main__":
    unittest.main()
