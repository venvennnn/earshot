"""Conversation sessions and the LLM loop.

Each voice session is keyed by its Agora channel. Our history is the source of truth: from each
Agora request we take only the newest user message; replies and agent-initiated speech are appended
here. Tools, policy and confirmations are added in Phase 3.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import APIError, AsyncOpenAI

from config import Settings

log = logging.getLogger("earshot.orchestrator")

SYSTEM_PROMPT = """You are EarShot, a voice assistant for maintenance and quality workers on a factory floor.
You speak like a calm, helpful senior technician.
- Use short spoken sentences. No lists, no markdown, no emojis: everything you write is read aloud.
- No jargon and no raw numbers for scores. Say "very unusual" or "fairly sure" instead.
- Answer in the language the worker uses.
- You can listen to machines when asked: the worker holds the phone near the machine for ten seconds.
  That capability is being connected; if asked to listen now, say it will be available shortly.
"""

GREETING = "Hi, I'm EarShot. Which machine are we checking?"
MAX_HISTORY = 40


@dataclass
class Session:
    channel: str
    language: str = "en"
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> None:
        if content.strip():
            self.history.append({"role": role, "content": content.strip()})
            del self.history[:-MAX_HISTORY]


def latest_user_text(messages: list[dict[str, Any]]) -> str | None:
    """Text of the newest user message in an OpenAI-format message list."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # content parts
            return " ".join(p.get("text", "") for p in content if isinstance(p, dict)).strip()
    return None


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value() or "unset",
            max_retries=1,
            timeout=30.0,
        )
        self.sessions: dict[str, Session] = {}

    def open(self, channel: str, language: str = "en") -> Session:
        session = Session(channel=channel, language=language)
        session.add("assistant", GREETING)
        self.sessions[channel] = session
        return session

    def get(self, channel: str) -> Session:
        # A session can be unknown if the backend restarted while an agent was still running.
        return self.sessions.get(channel) or self.open(channel)

    def close(self, channel: str) -> None:
        self.sessions.pop(channel, None)

    def _llm_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self._settings.llm_model, "temperature": 0.4, "max_tokens": 400}
        if self._settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = self._settings.llm_reasoning_effort
        return kwargs

    async def reply(self, channel: str, incoming: list[dict[str, Any]]) -> AsyncIterator[str]:
        """Stream the spoken reply to the newest user message for `channel`."""
        session = self.get(channel)
        user_text = latest_user_text(incoming)
        if user_text:
            session.add("user", user_text)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *session.history]

        spoken: list[str] = []
        try:
            stream = await self._llm.chat.completions.create(messages=messages, stream=True, **self._llm_kwargs())
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    spoken.append(delta)
                    yield delta
        except APIError as exc:
            log.error("LLM call failed for %s: %s", channel, exc)
            if not spoken:
                fallback = "Sorry, I couldn't think that through just now. Please say it again."
                spoken.append(fallback)
                yield fallback
        finally:
            # Also runs when Agora drops the stream because the worker interrupted.
            session.add("assistant", "".join(spoken))

    def record_agent_speech(self, channel: str, text: str) -> None:
        """Agent spoke outside a user turn (e.g. a sound result); keep history consistent."""
        self.get(channel).add("assistant", text)
