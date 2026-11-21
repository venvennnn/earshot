"""Start, stop and speak through Agora Conversational AI agents (official `agora-agents` SDK).

Pipeline per agent: Agora ARES ASR -> our custom LLM endpoint -> Murf Falcon TTS (Agora built-in vendor).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from agora_agent import AresSTT, Area, AsyncAgora, CustomLLM, MurfTTS
from agora_agent.agentkit import Agent
from agora_agent.agentkit.agent_session import AsyncAgentSession

from config import Settings

log = logging.getLogger("earshot.convoai")

AGENT_UID = "1000"
IDLE_TIMEOUT_SECONDS = 120
SESSION_HEADER = "X-EarShot-Session"


class AgentError(RuntimeError):
    """Raised with a plain message when an agent cannot be started or reached."""


@dataclass(frozen=True)
class VoiceProfile:
    """What the agent hears and how it sounds."""

    asr_language: str  # e.g. "en-IN", "hi-IN", "ta-IN" (Agora turn-detection / ARES language)
    murf_voice_id: str
    murf_locale: str


class AgentManager:
    """Keeps one running Agora agent per channel."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncAgora(
            area=Area[settings.agora_area],
            app_id=settings.agora_app_id,
            app_certificate=settings.agora_app_certificate.get_secret_value(),
        )
        self._sessions: dict[str, AsyncAgentSession] = {}

    def llm_url(self, channel: str) -> str:
        base = self._settings.public_backend_url.rstrip("/")
        return f"{base}/v1/chat/completions?{urlencode({'session': channel})}"

    def build_agent(self, channel: str, greeting: str, voice: VoiceProfile) -> Agent:
        s = self._settings
        return (
            Agent(
                client=self._client,
                turn_detection={"language": voice.asr_language},
                interruption={"enable": True, "mode": "start_of_speech"},
                # RTM data channel: live transcripts, agent state and metrics in the browser.
                advanced_features={"enable_rtm": True},
                parameters={"data_channel": "rtm", "enable_metrics": True, "enable_error_message": True},
            )
            .with_stt(AresSTT())
            .with_llm(
                CustomLLM(
                    base_url=self.llm_url(channel),
                    api_key=s.agent_llm_key.get_secret_value(),
                    model=s.llm_model,
                    headers={SESSION_HEADER: channel},
                    greeting_message=greeting,
                    failure_message="Sorry, I lost my train of thought. Could you say that again?",
                )
            )
            .with_tts(
                MurfTTS(
                    key=s.murf_api_key.get_secret_value(),
                    voice_id=voice.murf_voice_id,
                    locale=voice.murf_locale,
                    model="FALCON",
                )
            )
        )

    async def start(self, channel: str, user_uid: int, greeting: str, voice: VoiceProfile) -> str:
        if not self._settings.public_backend_url.startswith("https://"):
            raise AgentError("PUBLIC_BACKEND_URL must be a public https URL that Agora can reach.")
        agent = self.build_agent(channel, greeting, voice)
        session = agent.create_async_session(
            channel=channel,
            agent_uid=AGENT_UID,
            remote_uids=[str(user_uid)],
            name=f"earshot-{channel}",
            idle_timeout=IDLE_TIMEOUT_SECONDS,
        )
        try:
            agent_id = await session.start()
        except Exception as exc:  # SDK raises typed API errors; surface a plain message
            log.error("Agora agent start failed for %s: %s", channel, exc)
            raise AgentError(f"Could not start the voice agent: {exc}") from exc
        self._sessions[channel] = session
        log.info("Agent %s started in %s", agent_id, channel)
        return agent_id

    async def speak(self, channel: str, text: str) -> None:
        """Make a running agent say `text` now, outside a user turn."""
        session = self._sessions.get(channel)
        if session is None:
            raise AgentError("No voice agent is running for this session.")
        await session.say(text, priority="INTERRUPT", interruptable=True)

    async def stop(self, channel: str) -> None:
        session = self._sessions.pop(channel, None)
        if session is None:
            return
        try:
            await session.stop()
        except Exception as exc:  # agent may already have left after idle timeout
            log.warning("Agent stop for %s reported: %s", channel, exc)

    async def stop_all(self) -> None:
        await asyncio.gather(*(self.stop(c) for c in list(self._sessions)))
