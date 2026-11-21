"""Live state of the shift and the WebSocket bus that pushes it to the dashboard and the phone app.

Every change marks the state dirty; a snapshot is broadcast at most every 150 ms. One-off signals
(start capturing, play this audio) are sent immediately as events.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Any

from fastapi import WebSocket

from packs import Pack

log = logging.getLogger("earshot.events")

MAX_TIMELINE = 60
MAX_TRANSCRIPT = 120

# Plain-language asset states shown to workers.
ASSET_STATES = {
    "normal": "Sounds normal",
    "watch": "Keep an eye on it",
    "problem": "Problem found",
    "unset": "Not set up yet",
    "out": "Out of service",
}


class LiveState:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.pack: Pack | None = None
        self.reset_shift()

    def next_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    def reset_shift(self) -> None:
        self.assets: dict[str, dict[str, Any]] = {}
        self.analyses: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, str]] = {}
        self.timeline: list[dict[str, Any]] = []
        self.confirmations: list[dict[str, Any]] = []
        self.contacts: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.tap_batches: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.report: dict[str, Any] | None = None
        self.followups: list[dict[str, Any]] = []  # reminders that carry over to the next shift
        self.histories: dict[str, dict[str, Any]] = {}  # past issues per asset, from the enterprise record
        self.integrations: dict[str, Any] = {}  # optional systems, e.g. {"jira": True, "jira_project": "EAR"}
        self.checked: set[str] = set()
        self.problems: set[str] = set()
        self.actions_done = 0

    def load_pack(self, pack: Pack, enrolled: set[str]) -> None:
        self.pack = pack
        self.reset_shift()
        for a in pack.assets:
            self.assets[a.id] = {
                **a.model_dump(),
                "state": "normal" if a.id in enrolled else "unset",
                "label": ASSET_STATES["normal" if a.id in enrolled else "unset"],
            }

    # --- mutations -------------------------------------------------------------------------
    def set_asset_state(self, asset_id: str, state: str, label: str | None = None) -> None:
        asset = self.assets.get(asset_id)
        if asset is None:
            return
        asset["state"] = state
        asset["label"] = label or ASSET_STATES[state]

    def add_asset(self, asset: dict[str, Any]) -> None:
        self.assets[asset["id"]] = {**asset, "state": "unset", "label": ASSET_STATES["unset"]}

    def add_timeline(self, text: str, status: str = "done", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        item = {"id": self.next_id("t"), "ts": time.time(), "text": text, "status": status, "detail": detail or {}}
        self.timeline.append(item)
        del self.timeline[:-MAX_TIMELINE]
        return item

    def set_timeline_status(self, item_id: str, status: str, text: str | None = None) -> None:
        for item in self.timeline:
            if item["id"] == item_id:
                item["status"] = status
                item["ts"] = time.time()
                if text:
                    item["text"] = text

    def add_followup(self, asset_id: str, when: str, note: str) -> dict[str, Any]:
        item = {"id": self.next_id("f"), "asset_id": asset_id,
                "asset_name": self.assets.get(asset_id, {}).get("name", asset_id), "when": when, "note": note,
                "status": "open", "created": time.time()}
        self.followups.append(item)
        return item

    def resolve_followups(self, asset_id: str) -> None:
        """A new check of the machine answers its open reminders."""
        for f in self.followups:
            if f["asset_id"] == asset_id and f["status"] == "open":
                f["status"] = "done"

    def add_line(self, session: str, who: str, text: str, line_id: str | None = None) -> str:
        """Add or update a transcript line (worker or agent)."""
        if line_id:
            for line in self.transcript:
                if line["id"] == line_id:
                    line["text"] = text
                    return line_id
        new_id = line_id or self.next_id("l")
        self.transcript.append({"id": new_id, "session": session, "who": who, "text": text, "ts": time.time()})
        del self.transcript[:-MAX_TRANSCRIPT]
        return new_id

    def tiles(self) -> dict[str, Any]:
        hours = self.pack.hours_saved_per_early_catch if self.pack else 0.0
        waiting = sum(1 for c in self.confirmations if c["status"] in ("pending", "second_approval"))
        return {
            "machines_checked": len(self.checked),
            "problems_caught": len(self.problems),
            "problem_assets": sorted(self.problems),
            "hours_saved_estimate": round(len(self.problems) * hours, 1),
            "jobs_done": self.actions_done,
            "waiting_for_yes": waiting,
        }

    def snapshot(self, tts: dict[str, Any]) -> dict[str, Any]:
        return {
            "pack": self.pack.summary() if self.pack else None,
            "assets": list(self.assets.values()),
            "analyses": self.analyses,
            "facts": self.facts,
            "timeline": self.timeline,
            "confirmations": self.confirmations,
            "contacts": self.contacts,
            "transcript": self.transcript,
            "jobs": self.jobs,
            "tap_batches": self.tap_batches,
            "sessions": self.sessions,
            "report": self.report,
            "followups": self.followups,
            "histories": self.histories,
            "integrations": self.integrations,
            "tiles": self.tiles(),
            "tts": tts,
        }


class EventBus:
    def __init__(self, state: LiveState, tts_metrics: Any) -> None:
        self.state = state
        self._tts = tts_metrics
        self._clients: set[WebSocket] = set()
        self._dirty = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def snapshot(self) -> dict[str, Any]:
        return self.state.snapshot(self._tts.summary())

    def changed(self) -> None:
        self._dirty.set()

    async def emit(self, kind: str, **data: Any) -> None:
        """Send a one-off event (not part of the snapshot) to every client."""
        await self._send_all({"type": "event", "event": {"kind": kind, **data}})

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        await ws.send_json({"type": "state", "state": self.snapshot()})

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _send_all(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:  # client went away mid-send
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _flush_loop(self) -> None:
        while True:
            await self._dirty.wait()
            await asyncio.sleep(0.15)
            self._dirty.clear()
            try:
                await self._send_all({"type": "state", "state": self.snapshot()})
            except Exception:
                log.exception("Broadcast failed")
