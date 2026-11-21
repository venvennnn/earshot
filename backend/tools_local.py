"""Tools served by the backend itself (sound, knowledge, risk, confirmation, learning).

Each tool is an async function (services, session, args) -> JSON-able dict, plus an OpenAI-format schema.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import plan_steps
from confirmations import open_confirmation
from mcp_client import ToolFailed
from services import Services
from sessions import Session

LocalTool = Callable[[Services, Session, dict[str, Any]], Awaitable[dict[str, Any]]]

LISTEN_TELL = "Tell the worker: hold the phone near it. Recording starts automatically after a beep."


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


_ASSET = {"asset_id": {"type": "string", "description": "Asset id, e.g. P-14"}}

SCHEMAS: list[dict[str, Any]] = [
    _fn("start_listening",
        "Open the phone recorder for a 10-second machine clip. Recording begins automatically. Use mode 'continuous' for running "
        "machines, 'tap' for tapping parts, 'alarm' for beeping boxes. Use purpose 'enroll' to record the "
        "healthy sound of a new machine, and 'verify' after a repair to check it sounds normal again (this closes "
        "the open job if it does). Returns immediately; the result arrives later as a system note.",
        {**_ASSET, "mode": {"type": "string", "enum": ["continuous", "tap", "alarm"]},
         "purpose": {"type": "string", "enum": ["check", "enroll", "verify"]}}, ["asset_id"]),
    _fn("analyze_sound", "Get the result of the latest recording of an asset: how unusual it sounds and the likely cause.",
        _ASSET, ["asset_id"]),
    _fn("enroll_baseline", "Check whether an asset has its healthy sound recorded, and when.", _ASSET, ["asset_id"]),
    _fn("search_knowledge", "Search manuals, safety procedures, asset histories and past cases.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("find_similar_cases", "Past cases that sounded like the latest recording of this asset, and matching work orders.",
        _ASSET, ["asset_id"]),
    _fn("assess_risk", "Risk of keeping the asset running, with a recommendation and the cost trade-off.",
        _ASSET, ["asset_id"]),
    _fn("request_confirmation",
        "Ask the worker to approve a plan before acting. Required before any action that stops a machine, takes it "
        "out of service, raises a stop-work order or holds a batch. List the tools you will call if they say yes.",
        {**_ASSET, "question": {"type": "string", "description": "Short spoken question, e.g. 'Stop P-14 at 10 PM and fix it?'"},
         "steps": {"type": "array", "description": "Every action you will take if they say yes, in order",
                   "items": {"type": "object", "properties": {
                       "text": {"type": "string", "description": "Plain words, e.g. 'Raise the repair job'"},
                       "tool": {"type": "string", "description": "The tool that does it, e.g. create_work_order"}},
                       "required": ["text", "tool"]}},
         "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool names you will call after a yes"}},
        ["asset_id", "question", "steps", "tools"]),
    _fn("schedule_follow_up",
        "Add a reminder that carries over to the next shift (dashboard, phone and shift report), e.g. 'check P-13 "
        "again tomorrow'. It is marked done automatically when the machine is checked again.",
        {**_ASSET, "when": {"type": "string", "description": "e.g. 'tomorrow morning', 'next shift'"},
         "note": {"type": "string"}}, ["asset_id", "when", "note"]),
    _fn("finish_tap_batch",
        "Finish a tap test (when the worker says they are done or says 'finish'): returns which parts were good, "
        "dull and not tapped.", _ASSET, ["asset_id"]),
    _fn("record_feedback", "Save the confirmed cause of a recording so future diagnoses improve.",
        {**_ASSET, "confirmed_cause": {"type": "string"}}, ["asset_id", "confirmed_cause"]),
]


def public_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Analysis without internal vectors, for the UI and the LLM."""
    return {k: v for k, v in analysis.items() if k not in ("embedding", "label_probs")}


def _latest(svc: Services, session: Session, asset_id: str) -> dict[str, Any] | None:
    analysis_id = session.last_analysis.get(asset_id)
    if analysis_id and analysis_id in svc.analyses:
        return svc.analyses[analysis_id]
    found = svc.state.analyses.get(asset_id)
    return svc.analyses.get(found["id"]) if found else None


async def start_listening(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args["asset_id"].upper()
    mode = args.get("mode") or "continuous"
    purpose = args.get("purpose") or "check"
    if asset_id not in svc.state.assets:
        return {"ok": False, "message": f"{asset_id} is not on this line. Use identify_asset or register_asset first."}
    if mode == "tap":
        if purpose != "enroll" and (session.tap_baseline_asset or session.awaiting_batch_number):
            return {"ok": False, "message": "Finish recording the new baseline before running a tap test."}
        if purpose == "enroll" and svc.state.tap_batches.get(asset_id, {}).get("parts"):
            return {"ok": False, "message": "This batch already has results. Say start a new batch with its new batch number to record a fresh baseline."}
        if purpose == "enroll":
            session.tap_baseline_asset = asset_id
    enrolled = (svc.state.assets[asset_id].get("tap_reference_url") if mode == "tap"
                else purpose == "enroll" or mode == "alarm" or asset_id in svc.audio_store.enrolled())
    if purpose != "enroll" and not enrolled:
        return {"ok": False, "not_enrolled": True,
                "message": "No healthy sound is recorded for this machine yet. Offer to record it now with purpose 'enroll'."}
    session.focus_asset = asset_id
    await svc.bus.emit("capture_start", session=session.id, asset_id=asset_id, asset=svc.state.assets[asset_id], mode=mode, purpose=purpose)
    return {"ok": True, "status": "listening_started", "instruction": LISTEN_TELL}


async def analyze_sound(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    analysis = _latest(svc, session, args["asset_id"].upper())
    if analysis is None:
        return {"ok": False, "message": "No recording of this asset yet. Call start_listening."}
    return public_analysis(analysis) | {"spectrum": "shown on screen"}


async def enroll_baseline(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    baseline = svc.audio_store.load_baseline(args["asset_id"].upper())
    if baseline is None:
        return {"enrolled": False, "message": "Not set up yet. Call start_listening with purpose 'enroll'."}
    meta = baseline[1]
    return {"enrolled": True, "mode": meta["mode"],
            "recorded": time.strftime("%d %b %H:%M", time.localtime(meta["enrolled_at"]))}


async def search_knowledge(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    return {"results": await svc.kb.search(args["query"], k=4), "retrieval": svc.kb.mode}


async def find_similar_cases(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args["asset_id"].upper()
    analysis = _latest(svc, session, asset_id)
    asset = svc.state.assets.get(asset_id, {})
    label = analysis.get("label", "") if analysis else ""
    sound_cases = svc.engine.similar_cases(analysis, asset.get("type", "")) if (svc.engine and analysis) else []
    try:
        history = await svc.enterprise.call("get_asset_history", {"asset_id": asset_id})
    except ToolFailed:
        history = {}
    cause_words = set(label.replace("a ", "").split())
    work_orders = [w for w in history.get("same_type_work_orders", []) + history.get("work_orders", [])
                   if cause_words & set(str(w.get("cause", "")).split())]
    knowledge = await svc.kb.search(f"past case {asset.get('type', '')} {label}", k=2)
    if work_orders:
        w = work_orders[0]
        svc.state.facts.setdefault(asset_id, {})["seen_before"] = f"{w['asset_id']}, {w.get('when', '')}".strip(", ")
        svc.bus.changed()
    return {"sound_cases": [{k: c[k] for k in ("asset_id", "cause", "similarity")} for c in sound_cases],
            "matching_work_orders": work_orders[:3], "knowledge": knowledge}


async def assess_risk(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args["asset_id"].upper()
    analysis = _latest(svc, session, asset_id)
    if analysis is None or not analysis.get("ok"):
        return {"risk": "unknown", "message": "No usable recording yet."}
    band = analysis["band"]
    knowledge = await svc.kb.search(f"{analysis['label']} what to do downtime repair time", k=2)
    if band == "very unusual":
        risk, advice = "high", "Plan a stop within this shift and repair it before it fails."
    elif band == "slightly unusual":
        risk, advice = "medium", "Keep it running, check again tomorrow, and plan the repair at the next stop."
    else:
        risk, advice = "low", "No action needed."
    return {"risk": risk, "recommendation": advice, "label": analysis["label"],
            "confidence": analysis["confidence"], "evidence": knowledge}


async def request_confirmation(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args["asset_id"].upper()
    steps = list(args.get("steps") or [])
    tools = list(args.get("tools") or [])
    asset = svc.state.assets.get(asset_id, {})
    # A fault plan must raise the job and record the hold, even if the model left them out.
    if asset_id in svc.state.problems:
        batch = svc.state.tap_batches.get(asset_id)
        finding = plan_steps.finding_text(asset, svc.state.analyses.get(asset_id), batch)
        steps, tools = plan_steps.ensure_issue_steps(
            steps, tools, asset, svc.pack.vocabulary, [p.name for p in svc.pack.people], finding,
            is_tap=bool(batch and batch.get("parts")))
    conf = await open_confirmation(svc, session, asset_id, args["question"], steps, tools)
    return {"status": "waiting_for_yes", "confirmation_id": conf["id"],
            "instruction": "Ask the worker the question and tell them what you will do if they say yes."}


async def schedule_follow_up(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    item = svc.state.add_followup(args["asset_id"].upper(), args.get("when", "next shift"), args.get("note", ""))
    svc.bus.changed()
    return {"scheduled": True, "id": item["id"]}


async def finish_tap_batch(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    from listen_flow import close_tap_batch  # local import: listen_flow imports this module

    asset = svc.state.assets.get(args["asset_id"].upper())
    if asset is None:
        return {"finished": False, "message": "Unknown asset."}
    summary, note, spoken = await close_tap_batch(svc, session, asset)
    return {**summary, "instruction": note, "say": spoken}


async def record_feedback(svc: Services, session: Session, args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args["asset_id"].upper()
    analysis = _latest(svc, session, asset_id)
    if analysis is None or svc.engine is None:
        return {"saved": False, "message": "No recording of this asset to learn from."}
    svc.engine.record_feedback(analysis, svc.state.assets.get(asset_id, {}).get("type", ""), args["confirmed_cause"])
    return {"saved": True, "message": "Saved. Future diagnoses of this kind of machine will use it."}


TOOLS: dict[str, LocalTool] = {
    "start_listening": start_listening,
    "analyze_sound": analyze_sound,
    "enroll_baseline": enroll_baseline,
    "search_knowledge": search_knowledge,
    "find_similar_cases": find_similar_cases,
    "assess_risk": assess_risk,
    "request_confirmation": request_confirmation,
    "schedule_follow_up": schedule_follow_up,
    "finish_tap_batch": finish_tap_batch,
    "record_feedback": record_feedback,
}
