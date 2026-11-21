"""Confirmations for tier 2/3 actions and the plan they approve.

A plan is a question plus steps; each step is plain text and (usually) the tool that carries it out. Steps are
tracked on the timeline: next -> done when their tool succeeds, failed when it fails (see followups.tick_plan_step),
and skipped if the turn after the yes ends without them. Opened by the LLM (or by the policy when it acts without one) and answered by
a spoken yes/no, a tap on the phone or dashboard, or a second approver.
"""

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


def normalise_steps(raw: list[Any], tools: list[str]) -> list[dict[str, Any]]:
    """Accept steps as strings or {text, tool} objects; attach listed tools to untagged steps in order."""
    steps = []
    for s in raw:
        if isinstance(s, dict):
            steps.append({"text": str(s.get("text", "")).strip(), "tool": s.get("tool") or None})
        else:
            steps.append({"text": str(s).strip(), "tool": None})
    untagged = [t for t in tools if t not in {s["tool"] for s in steps}]
    for s in steps:
        if s["tool"] is None and untagged:
            s["tool"] = untagged.pop(0)
    return [s for s in steps if s["text"]]


async def open_confirmation(svc: Services, session: Session, asset_id: str, question: str, steps: list[Any],
                            tools: list[str]) -> dict[str, Any]:
    st = svc.state
    for old in st.confirmations:  # a new question replaces an unanswered one in the same session
        if old["session"] == session.id and old["status"] in OPEN:
            old["status"] = "replaced"
            _drop_steps(svc, old)
            st.set_timeline_status(old["waiting_id"], "skipped", "Question replaced by a new one")
    plan = normalise_steps(steps, tools)
    tools = sorted(set(tools) | {s["tool"] for s in plan if s["tool"]})
    tier = max([tier_for(svc.pack, t, {}) for t in tools] or [2])
    approver = next((p.name for p in svc.pack.people if p.approver), None) if tier >= 3 else None
    conf = {
        "id": st.next_id("k"), "session": session.id, "asset_id": asset_id,
        "asset_name": st.assets.get(asset_id, {}).get("name", asset_id), "question": question, "steps": plan,
        "tools": tools, "tier": tier, "status": "pending", "worker": svc.pack.worker.name, "approver": approver,
        "created": time.time(), "finalized": False,
    }
    conf["waiting_id"] = st.add_timeline(f"Waiting for {conf['worker']} to say yes", "waiting")["id"]
    for step in plan:
        step["timeline_id"] = st.add_timeline(step["text"], "next", {"tool": step["tool"]})["id"]
        step["status"] = "next"
    st.confirmations.append(conf)
    svc.bus.changed()
    return conf


def _drop_steps(svc: Services, conf: dict[str, Any]) -> None:
    ids = {s["timeline_id"] for s in conf["steps"] if s.get("status") == "next"}
    svc.state.timeline[:] = [t for t in svc.state.timeline if t["id"] not in ids]


def finalize(svc: Services, session_id: str) -> None:
    """After the turn that acted on a yes: any promised step that did not happen is shown as not done."""
    for conf in svc.state.confirmations:
        if conf["session"] == session_id and conf["status"] == "approved" and not conf["finalized"]:
            conf["finalized"] = True
            for step in conf["steps"]:
                if step.get("status") == "next":
                    step["status"] = "skipped"
                    svc.state.set_timeline_status(step["timeline_id"], "skipped", f"{step['text']}: not done")
    svc.bus.changed()


async def decide(svc: Services, session: Session, conf: dict[str, Any], decision: str, by: str) -> str:
    """Apply a yes/no and return a system note telling the LLM what to do next."""
    st = svc.state
    plan = "; ".join(f"{s['text']} ({s['tool']})" if s["tool"] else s["text"] for s in conf["steps"]) or conf["question"]
    if decision == "no":
        conf["status"] = "declined"
        _drop_steps(svc, conf)
        st.set_timeline_status(conf["waiting_id"], "done", f"{by} said not now")
        st.add_followup(conf["asset_id"], "next shift", f"Decide on: {conf['question']}")
        svc.bus.changed()
        return (f"{by} declined: '{conf['question']}'. Do not take those actions. A reminder for the next shift has been "
                "added. Acknowledge in one sentence and say what happens instead.")

    if conf["tier"] >= 3 and conf["status"] == "pending" and conf["approver"]:
        conf["status"] = "second_approval"
        st.set_timeline_status(conf["waiting_id"], "done", f"{by} said yes")
        conf["waiting_id"] = st.add_timeline(f"Waiting for {conf['approver']} to approve", "waiting")["id"]
        await brief_person(svc, conf["approver"], f"{conf['worker']} asks for approval: {conf['question']} Plan: {plan}",
                           conf["session"], approval_for=conf["id"])
        svc.bus.changed()
        return (f"{by} said yes, but this action also needs a second approver. EarShot has asked {conf['approver']}. "
                "Tell the worker briefly that you are waiting for that approval. Do not act yet.")

    conf["status"] = "approved"
    conf["approved_by"] = by
    session.grant(conf["tools"])
    st.set_timeline_status(conf["waiting_id"], "done", f"{by} said yes")
    svc.bus.changed()
    return (f"{by} approved: '{conf['question']}'. Carry out every step now by calling its tool: {plan}. "
            "Then confirm in one or two short sentences what you did, and mention anything that did not work.")
