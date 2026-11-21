"""Shared services, created once at startup and passed to the modules that need them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from agora.convoai import AgentManager
from config import Settings
from events import EventBus, LiveState
from mcp_client import EnterpriseTools
from murf import LatencyMetrics, MurfClient
from packs import Pack
from rag import KnowledgeBase

if TYPE_CHECKING:
    from audio.engine import AudioEngine
    from audio.store import AudioStore


@dataclass
class Services:
    settings: Settings
    llm: AsyncOpenAI
    state: LiveState
    bus: EventBus
    enterprise: EnterpriseTools
    kb: KnowledgeBase
    murf: MurfClient
    metrics: LatencyMetrics
    agents: AgentManager
    audio_store: AudioStore
    pack: Pack
    engine: AudioEngine | None = None  # set once CLAP has loaded
    engine_error: str = ""
    analyses: dict[str, dict[str, object]] = field(default_factory=dict)  # full analyses by id (with embedding)
