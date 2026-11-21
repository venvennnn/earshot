"""EarShot backend: FastAPI app, routes and startup."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

import confirmations
import followups
import listen_flow
from agora.convoai import AGENT_UID, AgentError, AgentManager, VoiceProfile
from agora.tokens import user_token
from audio.store import AudioStore
from config import get_settings, report_startup
from events import EventBus, LiveState
from llm_endpoint import build_router
from mcp_client import EnterpriseTools, ToolFailed
from murf import LOCALES, LatencyMetrics, MurfClient, MurfError
from orchestrator import Orchestrator, greeting
from packs import available_packs, load_pack
from rag import KnowledgeBase
from services import Services
from sessions import SessionStore
from tools_local import public_analysis

VERSION = "1.0.0"
ASR_LANGUAGES = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("earshot")

settings = get_settings()
store_root = Path(settings.store_dir).resolve()
llm = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key.get_secret_value() or "unset",
                  max_retries=1, timeout=30.0)
metrics = LatencyMetrics()
state = LiveState()
svc = Services(
    settings=settings,
    llm=llm,
    state=state,
    bus=EventBus(state, metrics),
    enterprise=EnterpriseTools(settings.mcp_enterprise_url),
    kb=KnowledgeBase(llm, settings.embedding_model, store_root / "cache"),
    murf=MurfClient(settings, store_root / "media", metrics),
    metrics=metrics,
    agents=AgentManager(settings),
    audio_store=AudioStore(store_root),
    pack=load_pack(settings.default_pack),
)
sessions = SessionStore()
orchestrator = Orchestrator(svc, sessions)


def _load_engine() -> None:
    """Load CLAP once (slow: downloads the model on first run). The app serves requests meanwhile."""
    try:
        from audio.engine import AudioEngine, ClapEmbedder

        svc.engine = AudioEngine(svc.audio_store, ClapEmbedder())
    except Exception as exc:  # torch/transformers missing or model download failed
        svc.engine_error = f"The sound engine could not start: {exc}"
        log.error(svc.engine_error)


async def activate_pack(pack_id: str) -> None:
    svc.pack = load_pack(pack_id)
    state.load_pack(svc.pack, svc.audio_store.enrolled())
    try:
        await svc.enterprise.call("admin_load_pack", {"pack": pack_id})
    except ToolFailed as exc:
        log.error("Enterprise MCP server not reachable at %s: %s", settings.mcp_enterprise_url, exc)
    try:
        state.integrations = await svc.enterprise.call("admin_integrations", {})
    except ToolFailed:
        state.integrations = {}
    await svc.kb.build(svc.pack.knowledge)
    svc.bus.changed()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    report_startup(settings)
    svc.bus.start()
    await activate_pack(settings.default_pack)
    loader = asyncio.create_task(asyncio.to_thread(_load_engine))
    yield
    loader.cancel()
    await svc.agents.stop_all()
    await svc.murf.close()
    await svc.bus.stop()


app = FastAPI(title="EarShot", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])
app.include_router(build_router(settings, orchestrator))
(store_root / "media").mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=store_root / "media"), name="media")


# --- status ------------------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": VERSION,
        "demo_mode": settings.demo_mode,
        "integrations": settings.integrations(),
        "missing": settings.missing(),
        "pack": svc.pack.id,
        "sound_engine": "ready" if svc.engine else (svc.engine_error or "loading"),
        "knowledge": svc.kb.mode,
    }


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return svc.bus.snapshot()


@app.get("/api/metrics/tts")
async def tts_metrics() -> dict[str, Any]:
    return metrics.summary()


@app.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    await svc.bus.connect(ws)
    try:
        while True:
            await ws.receive_text()  # clients only listen; keep the socket open
    except WebSocketDisconnect:
        svc.bus.disconnect(ws)


# --- packs -------------------------------------------------------------------------------------
class PackRequest(BaseModel):
    id: str


@app.get("/api/packs")
async def packs() -> dict[str, Any]:
    return {"active": svc.pack.id, "packs": [{"id": p, "name": load_pack(p).name} for p in available_packs()]}


@app.post("/api/pack")
async def switch_pack(req: PackRequest) -> dict[str, str]:
    if req.id not in available_packs():
        raise HTTPException(status_code=404, detail="Unknown pack")
    await activate_pack(req.id)
    # The agent's prompt is built from the active pack on every turn; tell live callers about the switch.
    for s in sessions.all():
        if s.kind == "voice":
            await orchestrator.say(s, f"Switched to the {svc.pack.name} setup. Hi {svc.pack.worker.name}.")
    return {"active": svc.pack.id}


# --- sessions ----------------------------------------------------------------------------------
class SessionRequest(BaseModel):
    language: Literal["en", "hi", "ta"] = "en"
    kind: Literal["voice", "app"] = "voice"


async def voice_profile(language: str) -> VoiceProfile:
    locale = LOCALES[language]
    if settings.murf_agent_voice:
        return VoiceProfile(ASR_LANGUAGES[language], settings.murf_agent_voice, locale)
    voice, locale = await svc.murf.voice_for(locale, 0)
    return VoiceProfile(ASR_LANGUAGES[language], voice, locale)


@app.post("/api/session")
async def create_session(req: SessionRequest) -> dict[str, Any]:
    """Voice: create a channel + browser token and start the Agora agent. App/demo: a text/audio session."""
    if req.kind == "app" or settings.demo_mode:
        s = sessions.open(f"app-{secrets.token_hex(4)}", "demo" if settings.demo_mode else "app", req.language)
        state.sessions[s.id] = {"kind": s.kind, "worker": svc.pack.worker.name}
        svc.bus.changed()
        return {"kind": s.kind, "session": s.id, "greeting": greeting(svc)}
    missing = settings.missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Voice is not set up yet. Missing: {', '.join(missing)}")
    channel = f"es-{secrets.token_hex(4)}"
    uid = secrets.randbelow(90_000_000) + 10_000_000
    s = sessions.open(channel, "voice", req.language)
    try:
        await svc.agents.start(channel, uid, greeting(svc), await voice_profile(req.language))
    except (AgentError, MurfError) as exc:
        sessions.close(channel)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    s.add({"role": "assistant", "content": greeting(svc)})
    state.add_line(channel, "agent", greeting(svc))
    state.sessions[channel] = {"kind": "voice", "worker": svc.pack.worker.name}
    svc.bus.changed()
    return {"kind": "voice", "session": channel, "app_id": settings.agora_app_id, "channel": channel, "uid": uid,
            "token": user_token(settings, channel, uid), "agent_uid": AGENT_UID}


@app.delete("/api/session/{session_id}", status_code=204, response_class=Response)
async def end_session(session_id: str) -> Response:
    await svc.agents.stop(session_id)
    sessions.close(session_id)
    state.sessions.pop(session_id, None)
    svc.bus.changed()
    return Response(status_code=204)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/session/{session_id}/speak", status_code=202)
async def speak(session_id: str, req: SpeakRequest) -> None:
    """Make the running agent say something without waiting for the worker."""
    try:
        await svc.agents.speak(session_id, req.text)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sessions.get(session_id).add({"role": "assistant", "content": req.text})
    state.add_line(session_id, "agent", req.text)
    svc.bus.changed()


class ChatRequest(BaseModel):
    session: str
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """Text turn (demo mode, or typing instead of talking). The reply is also voiced with Murf when available."""
    s = sessions.find(req.session) or sessions.open(req.session, "app")
    return await orchestrator.turn_and_say(s, user_text=req.text)


# --- sound -------------------------------------------------------------------------------------
@app.post("/api/audio/clip")
async def upload_clip(
    file: UploadFile = File(...),
    asset_id: str = Form(...),
    mode: Literal["continuous", "tap", "alarm"] = Form("continuous"),
    purpose: Literal["check", "enroll", "verify"] = Form("check"),
    session: str = Form(""),
    part: int = Form(0),
) -> dict[str, Any]:
    """A recording from the phone. Enroll or analyse it, then EarShot explains the result out loud."""
    from audio.engine import decode_audio

    engine = svc.engine
    if engine is None:
        raise HTTPException(status_code=503, detail=svc.engine_error or "The sound engine is still loading. Try again in a minute.")
    asset = state.assets.get(asset_id.upper())
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Unknown machine {asset_id}")
    try:
        y = await asyncio.to_thread(decode_audio, await file.read())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read the recording.") from exc
    s = sessions.find(session) if session else None
    if s is None:
        s = sessions.open(session or f"app-{secrets.token_hex(4)}", "app")

    if purpose == "enroll":
        result, note = await listen_flow.enroll(svc, engine, asset, y, mode)
    elif purpose == "verify":
        result, note = await listen_flow.verify(svc, engine, s, asset, y)
    elif mode == "tap":
        result, note = await listen_flow.tap(svc, engine, asset, y, part)
    elif mode == "alarm":
        result, note = await listen_flow.alarm(svc, engine, asset, y)
    else:
        result, note = await listen_flow.analyze(svc, engine, s, asset, y)

    out: dict[str, Any] = {"session": s.id, "result": public_analysis(result)}
    if s.kind == "voice":
        orchestrator.background(s, note)  # the agent speaks the result when ready
    else:
        out |= await orchestrator.turn_and_say(s, note=note)
    return out


class NewAsset(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=40)


@app.post("/api/assets")
async def add_asset(req: NewAsset) -> dict[str, Any]:
    try:
        result = await svc.enterprise.call("register_asset", {"name": req.name, "asset_type": req.type,
                                                              "line": svc.pack.line})
    except ToolFailed as exc:
        raise HTTPException(status_code=502, detail="The asset register did not respond.") from exc
    await followups.apply(svc, "", "register_asset", {}, result, 0)
    return result


class FinishTap(BaseModel):
    session: str = ""


@app.post("/api/tap/{asset_id}/finish")
async def finish_tap(asset_id: str, req: FinishTap) -> dict[str, Any]:
    """Finish a tap-test batch: summary, then EarShot proposes the next step (spoken or as Murf audio)."""
    asset = state.assets.get(asset_id.upper())
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Unknown machine {asset_id}")
    summary, note = listen_flow.finish_tap(svc, asset)
    s = sessions.find(req.session) if req.session else None
    s = s or sessions.open(req.session or f"app-{secrets.token_hex(4)}", "app")
    if s.kind == "voice":
        orchestrator.background(s, note)
        return {"summary": summary}
    return {"summary": summary, **await orchestrator.turn_and_say(s, note=note)}


@app.post("/api/tap/{asset_id}/reset", status_code=204, response_class=Response)
async def reset_tap_batch(asset_id: str) -> Response:
    state.tap_batches.pop(asset_id.upper(), None)
    svc.bus.changed()
    return Response(status_code=204)


# --- confirmations, replies, report ------------------------------------------------------------
class Decision(BaseModel):
    decision: Literal["yes", "no"]


@app.post("/api/confirmations/{conf_id}")
async def answer_confirmation(conf_id: str, req: Decision) -> dict[str, Any]:
    """Approve / Not now from the phone's confirm sheet or the dashboard banner."""
    conf = confirmations.get(svc, conf_id)
    if conf is None or conf["status"] not in confirmations.OPEN:
        raise HTTPException(status_code=409, detail="This question has already been answered.")
    s = sessions.find(conf["session"]) or sessions.open(conf["session"], "app")
    by = conf["approver"] if conf["status"] == "second_approval" else svc.pack.worker.name
    note = await confirmations.decide(svc, s, conf, req.decision, by)
    if s.kind == "voice":
        orchestrator.background(s, note)
        return {"status": conf["status"]}
    return {"status": conf["status"], **await orchestrator.turn_and_say(s, note=note)}


class Reply(BaseModel):
    reply: str = Field(min_length=1, max_length=200)


@app.post("/api/contacts/{contact_id}/reply")
async def contact_reply(contact_id: str, req: Reply) -> dict[str, str]:
    """A supervisor / stores reply from the recipient page (Approve, Decline, or a short message)."""
    contact = next((c for c in state.contacts if c["id"] == contact_id), None)
    if contact is None:
        raise HTTPException(status_code=404, detail="Unknown message")
    contact["reply"] = req.reply
    contact["status"] = {"approved": "Approved", "declined": "Declined"}.get(req.reply.lower(), "Replied")
    if contact.get("notification_id"):
        try:
            await svc.enterprise.call("record_reply", {"notification_id": contact["notification_id"], "reply": req.reply})
        except ToolFailed:
            log.warning("Could not record reply in the enterprise system")
    state.add_timeline(f"{contact['name']} replied: {req.reply}", "done")
    svc.bus.changed()
    s = sessions.find(contact.get("session", ""))
    conf = confirmations.get(svc, contact.get("approval_for", ""))
    if conf and conf["status"] == "second_approval" and req.reply.lower() in ("approved", "declined"):
        s = s or sessions.open(conf["session"], "app")
        note = await confirmations.decide(svc, s, conf, "yes" if req.reply.lower() == "approved" else "no", contact["name"])
        orchestrator.background(s, note)
    elif s:
        orchestrator.background(s, f"{contact['name']} replied: '{req.reply}'. Tell the worker in one short sentence "
                                   "and adapt the plan if needed.")
    return {"status": contact["status"]}


@app.post("/api/report")
async def report() -> dict[str, Any]:
    """Write and voice the shift report (also available to the LLM as the generate_report tool)."""
    return await followups.write_report(svc)


class JobStatus(BaseModel):
    status: Literal["scheduled", "in_progress", "done", "cancelled"]
    note: str = Field(default="", max_length=300)


@app.post("/api/jobs/{job_id}/status")
async def job_status(job_id: str, req: JobStatus) -> dict[str, Any]:
    """Move a job through its stages from the phone (synced to Jira when configured)."""
    try:
        result = await svc.enterprise.call("update_work_order", {"work_order_id": job_id, "status": req.status,
                                                                 "note": req.note or f"Set to {req.status} from the EarShot app."})
    except ToolFailed as exc:
        raise HTTPException(status_code=502, detail="The maintenance system did not respond.") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "Unknown job"))
    await followups.apply(svc, "", "update_work_order", {"work_order_id": job_id, "status": req.status}, result, 1)
    return result


class FailRequest(BaseModel):
    tool: str
    times: int = Field(default=2, ge=1, le=5)


@app.post("/api/debug/fail-next")
async def fail_next(req: FailRequest) -> dict[str, Any]:
    """Demo helper: make the next calls to a mock enterprise tool fail, to show EarShot's error handling."""
    return await svc.enterprise.call("admin_inject_failure", {"tool": req.tool, "times": req.times})
