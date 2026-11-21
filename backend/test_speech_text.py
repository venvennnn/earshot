"""The worker gets a real answer, and the voice can hear and speak Hindi and Tamil."""

import unittest

from speech_text import asr_languages, detect_language, match_assets, message_text, offline_reply, pick_voice

FACTORY = [
    {"id": "P-11", "name": "Pump P-11", "type": "pump", "modes": ["continuous"]},
    {"id": "P-12", "name": "Pump P-12", "type": "pump", "modes": ["continuous"]},
    {"id": "P-14", "name": "Pump P-14", "type": "pump", "modes": ["continuous"]},
    {"id": "CB-2231", "name": "Casting batch 2231", "type": "casting", "modes": ["tap"]},
]
RAIL = [
    {"id": "C-4401", "name": "Coach 4401", "type": "coach wheelset", "modes": ["tap"]},
    {"id": "C-4402", "name": "Coach 4402", "type": "coach wheelset", "modes": ["tap"]},
]
VOICES = [
    {"voiceId": "Aarav", "locale": "en-IN", "supportedLocales": ["en-IN", "hi-IN"]},
    {"voiceId": "Anisha", "locale": "en-IN", "supportedLocales": ["en-IN (English - India)", "hi-IN (Hindi - India)", "ta-IN (Tamil - India)"]},
    {"voiceId": "Kavya", "locale": "ta-IN", "supportedLocales": ["ta-IN"]},
]


class SpeechTextTest(unittest.TestCase):
    def test_a_coach_on_the_factory_line_is_named_as_missing(self) -> None:
        reply = offline_reply(FACTORY, "Checking the railway coach.", language="en", worker="Ravi")
        self.assertNotIn("think that through", reply)
        self.assertIn("don't have that", reply)
        self.assertIn("Pump P-14", reply)

    def test_a_coach_on_the_rail_line_asks_which_one(self) -> None:
        reply = offline_reply(RAIL, "Checking the railway coach.", worker="Arjun")
        self.assertIn("Coach 4401", reply)
        self.assertIn("Coach 4402", reply)

    def test_pump_14_is_one_machine(self) -> None:
        self.assertEqual([a["id"] for a in match_assets(FACTORY, "pump p-14")], ["P-14"])
        reply = offline_reply(FACTORY, "Checking pump P-14", worker="Ravi")
        self.assertIn("Pump P-14", reply)
        self.assertIn("Hold the phone", reply)

    def test_a_tap_asset_asks_for_taps(self) -> None:
        reply = offline_reply(FACTORY, "casting batch", worker="Ravi")
        self.assertIn("Casting batch 2231", reply)
        self.assertIn("Listen to machine", reply)

    def test_what_does_not_apologise(self) -> None:
        reply = offline_reply(FACTORY, "What?", worker="Ravi")
        self.assertIn("Ravi", reply)
        self.assertNotIn("think", reply)

    def test_hindi_and_tamil_are_answered_in_that_language(self) -> None:
        self.assertEqual(detect_language("पंप चेक करो"), "hi")
        self.assertEqual(detect_language("பம்பை பாருங்கள்"), "ta")
        self.assertEqual(detect_language("Checking the railway coach."), "en")
        hindi = offline_reply(FACTORY, "रेल कोच", worker="Ravi")
        self.assertIn("नहीं", hindi)
        tamil = offline_reply(FACTORY, "What?", language="ta", worker="Ravi")
        self.assertIn("Ravi", tamil)
        self.assertIn("இயந்திர", tamil)

    def test_asr_hears_all_three_with_the_session_language_first(self) -> None:
        self.assertEqual(asr_languages("hi-IN"), ["hi-IN", "en-IN", "ta-IN"])
        self.assertEqual(asr_languages("en-IN"), ["en-IN", "hi-IN", "ta-IN"])

    def test_the_agent_voice_speaks_english_hindi_and_tamil(self) -> None:
        voice, locale = pick_voice(VOICES, ["en-IN", "hi-IN", "ta-IN"])
        self.assertEqual(voice, "Anisha")
        self.assertEqual(locale, "en-IN")
        native, native_locale = pick_voice(VOICES, ["ta-IN"], 0)
        self.assertEqual((native, native_locale), ("Kavya", "ta-IN"))

    def test_message_text_ignores_thinking_parts(self) -> None:
        self.assertEqual(message_text(None), "")
        self.assertEqual(message_text([
            {"type": "reasoning", "text": "thinking"},
            {"type": "text", "text": "That's pump P-14."},
        ]), "That's pump P-14.")


if __name__ == "__main__":
    unittest.main()
