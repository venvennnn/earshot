"""EarShot backend: FastAPI app, routes and startup."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agora.convoai import AGENT_UID, AgentError, AgentManager, VoiceProfile
from agora.tokens import user_token
from config import get_settings, report_startup
from llm_endpoint import build_router
from murf import MurfClient, MurfError
from orchestrator import GREETING, Orchestrator

VERSION = "0.2.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("earshot")

settings = get_settings()
orchestrator = Orchestrator(settings)
agents = AgentManager(settings)
murf = MurfClient(settings)


@dataclass(frozen=True)
class Language:
    asr: str  # Agora ARES / turn-detection language
    murf_locales: tuple[str, ...]  # preferred Murf voice locales, in order


LANGUAGES: dict[str, Language] = {
    "en": Language(asr="en-IN", murf_locales=("en-IN", "en-US")),
    "hi": Language(asr="hi-IN", murf_locales=("hi-IN",)),
    "ta": Language(asr="ta-IN", murf_locales=("ta-IN",)),
}


async def voice_profile(lang: Language) -> VoiceProfile:
    if settings.murf_agent_voice:
        return VoiceProfile(lang.asr, settings.murf_agent_voice, lang.murf_locales[0])
    last_error: MurfError | None = None
    for locale in lang.murf_locales:
        try:
            return VoiceProfile(lang.asr, await murf.voice_for(locale), locale)
        except MurfError as exc:
            last_error = exc
    raise last_error or MurfError("No Murf voice available.")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    report_startup(settings)
    yield
    await agents.stop_all()
    await murf.close()


app = FastAPI(title="EarShot", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(build_router(settings, orchestrator))


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": VERSION,
        "demo_mode": settings.demo_mode,
        "integrations": settings.integrations(),
        "missing": settings.missing(),
    }


class SessionRequest(BaseModel):
    language: str = Field(default="en", pattern="^(en|hi|ta)$")


class SessionResponse(BaseModel):
    app_id: str
    channel: str
    uid: int
    token: str
    agent_uid: str


@app.post("/api/session")
async def create_session(req: SessionRequest) -> SessionResponse:
    """Create a channel, a token for the browser, and start the EarShot agent in it."""
    missing = settings.missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Voice is not set up yet. Missing: {', '.join(missing)}")
    channel = f"es-{secrets.token_hex(4)}"
    uid = secrets.randbelow(90_000_000) + 10_000_000
    try:
        voice = await voice_profile(LANGUAGES[req.language])
        orchestrator.open(channel, req.language)
        await agents.start(channel, uid, GREETING, voice)
    except (AgentError, MurfError) as exc:
        orchestrator.close(channel)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SessionResponse(
        app_id=settings.agora_app_id,
        channel=channel,
        uid=uid,
        token=user_token(settings, channel, uid),
        agent_uid=AGENT_UID,
    )


@app.delete("/api/session/{channel}", status_code=204, response_class=Response)
async def end_session(channel: str) -> Response:
    await agents.stop(channel)
    orchestrator.close(channel)
    return Response(status_code=204)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/session/{channel}/speak", status_code=202)
async def speak(channel: str, req: SpeakRequest) -> None:
    """Make the running agent say something without waiting for the worker (used by the listen flow)."""
    try:
        await agents.speak(channel, req.text)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    orchestrator.record_agent_speech(channel, req.text)
