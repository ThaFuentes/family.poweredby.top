"""The Ask composer lets an adult talk their message in (speech to text)."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class AskVoiceTests(unittest.TestCase):
    def test_composer_has_a_mic_next_to_send(self):
        partial = _read("app", "templates", "partials", "ask.html")
        self.assertIn('id="ask-mic"', partial)
        self.assertLess(
            partial.index('id="ask-mic"'),
            partial.index('id="ask-send"'),
            "the Mic button should sit right next to Send",
        )

    def test_ask_js_dictates_speech_into_the_message_box(self):
        js = _read("app", "static", "js", "ask.js")
        self.assertIn("SpeechRecognition", js)
        self.assertIn("webkitSpeechRecognition", js)
        self.assertIn("micSetup()", js)

    def test_mic_is_styled(self):
        css = _read("app", "static", "css", "family.css")
        self.assertIn(".ask-mic", css)


if __name__ == "__main__":
    unittest.main()
