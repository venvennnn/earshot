"""OpenAI-compatible `/v1/chat/completions` that Agora's Conversational AI agent calls as its LLM.

Agora sends OpenAI chat-completions requests (style "openai"). We identify the conversation from the
`session` query parameter (or the X-EarShot-Session header), run our orchestrator, and return only the
final spoken text: tool calls are resolved inside the orchestrator and never returned to Agora.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agora.convoai import SESSION_HEADER
from config import Settings
from orchestrator import Orchestrator

_SENTENCE = re.compile(r"(?<=[.!?।])\s+")


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


def _chunk(completion_id: str, model: str, delta: dict[str, str], finish: str | None = None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_router(settings: Settings, orchestrator: Orchestrator) -> APIRouter:
    router = APIRouter()

    def authorize(authorization: str | None) -> None:
        expected = f"Bearer {settings.agent_llm_key.get_secret_value()}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @router.post("/v1/chat/completions", response_model=None)
    async def chat_completions(
        request: Request,
        session: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        session_header: str | None = Header(default=None, alias=SESSION_HEADER),
    ) -> StreamingResponse | JSONResponse:
        authorize(authorization)
        body: dict[str, Any] = await request.json()
        channel = session or session_header
        if not channel:
            raise HTTPException(status_code=400, detail="Missing session")
        user_text = latest_user_text(body.get("messages") or [])
        model = str(body.get("model") or settings.llm_model)
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        session = orchestrator.sessions.get(channel, "voice")

        if not body.get("stream", False):
            text = await orchestrator.run_turn(session, user_text=user_text)
            return JSONResponse(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                    ],
                }
            )

        async def events() -> AsyncIterator[str]:
            yield _chunk(completion_id, model, {"role": "assistant"})
            text = await orchestrator.run_turn(session, user_text=user_text)
            for sentence in _SENTENCE.split(text):  # sentence chunks let Agora start speaking sooner
                yield _chunk(completion_id, model, {"content": sentence + " "})
            yield _chunk(completion_id, model, {}, finish="stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
