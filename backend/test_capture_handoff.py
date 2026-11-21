"""A direct machine check hands off to the browser without using the LLM."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from events import LiveState
from orchestrator import Orchestrator
from packs import load_pack
from sessions import SessionStore


class CaptureHandoffTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pack = load_pack("manufacturing")
        state = LiveState()
        state.load_pack(pack, set())
        self.emit = AsyncMock()
        self.enrolled = Mock(return_value={"P-14"})
        services = SimpleNamespace(
            pack=pack, state=state, bus=SimpleNamespace(emit=self.emit, changed=Mock()),
            audio_store=SimpleNamespace(enrolled=self.enrolled), metrics=Mock(),
        )
        sessions = SessionStore()
        self.session = sessions.open("test-session", "demo")
        self.orchestrator = Orchestrator(services, sessions)

    async def test_direct_pump_check_prepares_the_phone_recorder(self):
        reply = await self.orchestrator.run_turn(self.session, user_text="Check pump P-14.")
        self.assertIn("Recording starts after the beep", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="P-14", mode="continuous", purpose="check"
        )

    async def test_missing_baseline_guides_setup_without_opening_capture(self):
        self.enrolled.return_value = set()
        reply = await self.orchestrator.run_turn(self.session, user_text="Check pump P-14.")
        self.assertIn("needs a healthy recording first", reply)
        self.assertEqual(self.session.focus_asset, "P-14")
        self.assertFalse(any(call.args[0] == "capture_start" for call in self.emit.await_args_list))

    async def test_railway_tap_request_opens_reference_for_the_wheelset(self):
        pack = load_pack("railways")
        self.orchestrator.svc.pack = pack
        self.orchestrator.svc.state.load_pack(pack, set())
        self.enrolled.return_value = set()
        reply = await self.orchestrator.run_turn(self.session, user_text="Tap test Coach 4401.")
        self.assertIn("baseline for Coach 4401", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="C-4401", mode="tap", purpose="enroll"
        )

    async def test_railway_tap_request_checks_an_enrolled_wheelset(self):
        pack = load_pack("railways")
        self.orchestrator.svc.pack = pack
        self.orchestrator.svc.state.load_pack(pack, {"C-4402"})
        self.orchestrator.svc.state.assets["C-4402"]["tap_reference_url"] = "/media/clips/test.wav"
        reply = await self.orchestrator.run_turn(self.session, user_text="Tap test Coach 4402.")
        self.assertIn("Coach 4402 is ready", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="C-4402", mode="tap", purpose="check"
        )


    async def test_baseline_command_can_re_record_focused_wheelset(self):
        pack = load_pack("railways")
        self.orchestrator.svc.pack = pack
        state = self.orchestrator.svc.state
        state.load_pack(pack, {"C-4402"})
        state.assets["C-4402"]["tap_reference_url"] = "/media/clips/test.wav"
        self.session.focus_asset = "C-4402"
        reply = await self.orchestrator.run_turn(self.session, user_text="Can you set the tap baseline?")
        self.assertIn("baseline for Coach 4402", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="C-4402", mode="tap", purpose="enroll"
        )


    async def test_start_listening_records_focused_asset(self):
        self.session.focus_asset = "P-14"
        reply = await self.orchestrator.run_turn(self.session, user_text="Start listening.")
        self.assertIn("Recording starts after the beep", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="P-14", mode="continuous", purpose="check"
        )

    async def test_start_recording_enrolls_unset_focused_asset(self):
        self.session.focus_asset = "P-14"
        self.enrolled.return_value = set()
        reply = await self.orchestrator.run_turn(self.session, user_text="Start recording.")
        self.assertIn("healthy baseline", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="P-14", mode="continuous", purpose="enroll"
        )
