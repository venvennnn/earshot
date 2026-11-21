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
        self.assertIn("tap Start recording", reply)
        self.emit.assert_any_await(
            "capture_start", session=self.session.id, asset_id="P-14", mode="continuous", purpose="check"
        )

    async def test_missing_baseline_guides_setup_without_opening_capture(self):
        self.enrolled.return_value = set()
        reply = await self.orchestrator.run_turn(self.session, user_text="Check pump P-14.")
        self.assertIn("needs a healthy recording first", reply)
        self.assertEqual(self.session.focus_asset, "P-14")
        self.assertFalse(any(call.args[0] == "capture_start" for call in self.emit.await_args_list))
