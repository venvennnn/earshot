"""Conversation sessions. A voice session is keyed by its Agora channel; app sessions are created for the
phone's Listen button and text (demo) mode."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

MAX_MESSAGES = 40
GRANT_SECONDS = 600  # an approved action stays allowed for 10 minutes


@dataclass
class Session:
    id: str
    kind: str = "voice"  # "voice" (Agora call) | "app" (phone without a call) | "demo" (text box)
    language: str = "en"
    messages: list[dict[str, Any]] = field(default_factory=list)
    focus_asset: str | None = None
    last_analysis: dict[str, str] = field(default_factory=dict)  # asset_id -> analysis id
    granted: dict[str, float] = field(default_factory=dict)  # tool -> allowed until (epoch s)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Set while a person is waiting to be heard, so a sound-result turn lets the conversation through.
    preempt: asyncio.Event = field(default_factory=asyncio.Event)
    created_at: float = field(default_factory=time.time)

    def add(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if len(self.messages) > MAX_MESSAGES:
            # Trim from the front, but always restart at a user message so no tool result is orphaned.
            cut = len(self.messages) - MAX_MESSAGES
            while cut < len(self.messages) and self.messages[cut].get("role") != "user":
                cut += 1
            del self.messages[:cut]

    def grant(self, tools: list[str]) -> None:
        until = time.time() + GRANT_SECONDS
        for t in tools:
            self.granted[t] = until

    def is_granted(self, tool: str) -> bool:
        return self.granted.get(tool, 0) > time.time()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def open(self, session_id: str, kind: str, language: str = "en") -> Session:
        session = Session(id=session_id, kind=kind, language=language)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str, kind: str = "voice") -> Session:
        # Unknown ids happen if the backend restarted while an agent was still running.
        return self._sessions.get(session_id) or self.open(session_id, kind)

    def find(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def all(self) -> list[Session]:
        return list(self._sessions.values())
