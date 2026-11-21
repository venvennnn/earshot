"""Confirmations for tier 2/3 actions: opened by the LLM (or by the policy when it tries to act without one),
answered by a spoken yes/no, a tap on the phone or dashboard, or a second approver."""

from __future__ import annotations

import time
from typing import Any

from followups import brief_person
from policy import tier_for
from services import Services
from sessions import Session

OPEN = ("pending", "second_approval")


def pending_for(svc: Services, session_id: str) -> dict[str, Any] | None:
    return next((c for c in reversed(svc.state.confirmations) if c["session"] == session_id and c["status"] in OPEN), None)


def get(svc: Services, conf_id: str) -> dict[str, Any] | None:
    return next((c for c in svc.state.confirmations if c["id"] == conf_id), None)


async def open_confirmation(svc: Services, session: Session, asset_id: str, question: str, steps: list[str],
                            tools: list[str]) -> dict[str, Any]:
    st = svc.state
    for old in st.confirmations:  # a new question replaces an unanswered one in the same session
        if old["session"] == session.id and old["status"] in OPEN:
            old["status"] = "replaced"
            _resolve_timeline(svc, old, None)
    tier = max([tier_for(svc.pack, t, {}) for t in tools] or [2])
    approver = next((p.name for p in svc.pack.people if p.approver), None) if tier >= 3 else None
    conf = {
        "id": st.next_id("k"), "session": session.id, "asset_id": asset_id,
        "asset_name": st.assets.get(asset_id, {}).get("name", asset_id), "question": question, "steps": steps,
        "tools": tools, "tier": tier, "status": "pending", "worker": svc.pack.worker.name, "approver": approver,
        "created": time.time(), "timeline_ids": [],
    }
    conf["timeline_ids"].append(st.add_timeline(f"Waiting for {conf['worker']} to say yes", "waiting")["id"])
    for step in steps:
        conf["timeline_ids"].append(st.add_timeline(step, "next")["id"])
    st.confirmations.append(conf)
    svc.bus.changed()
    return conf


def _resolve_timeline(svc: Services, conf: dict[str, Any], waiting_text: str | None) -> None:
    """Turn the 'waiting' line into what happened and drop the 'next' lines (real actions log themselves)."""
    ids = set(conf.get("timeline_ids", []))
    kept = []
    for item in svc.state.timeline:
        if item["id"] not in ids:
            kept.append(item)
        elif item["status"] == "waiting" and waiting_text:
            kept.append({**item, "text": waiting_text, "status": "done", "ts": time.time()})
    svc.state.timeline[:] = kept


async def decide(svc: Services, session: Session, conf: dict[str, Any], decision: str, by: str) -> str:
    """Apply a yes/no and return a system note telling the LLM what to do next."""
    steps = "; ".join(conf["steps"]) or conf["question"]
    if decision == "no":
        conf["status"] = "declined"
        _resolve_timeline(svc, conf, f"{by} said not now")
        svc.bus.changed()
        return (f"{by} declined: '{conf['question']}'. Do not take those actions. Acknowledge in one sentence and "
                "say what happens instead (for example, check it again later).")

    if conf["tier"] >= 3 and conf["status"] == "pending" and conf["approver"]:
        conf["status"] = "second_approval"
        _resolve_timeline(svc, conf, f"{by} said yes; asking {conf['approver']} to approve")
        conf["timeline_ids"].append(svc.state.add_timeline(f"Waiting for {conf['approver']} to approve", "waiting")["id"])
        await brief_person(svc, conf["approver"], f"{conf['worker']} asks for approval: {conf['question']} Plan: {steps}",
                           conf["session"], approval_for=conf["id"])
        svc.bus.changed()
        return (f"{by} said yes, but this action also needs a second approver. EarShot has asked {conf['approver']}. "
                "Tell the worker briefly that you are waiting for that approval. Do not act yet.")

    conf["status"] = "approved"
    conf["approved_by"] = by
    session.grant(conf["tools"])
    _resolve_timeline(svc, conf, f"{by} said yes")
    svc.bus.changed()
    return (f"{by} approved: '{conf['question']}'. Carry out these steps now by calling the tools "
            f"{', '.join(conf['tools'])}: {steps}. Then confirm in one or two short sentences what you did.")
