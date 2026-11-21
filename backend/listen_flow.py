"""The listen flow: a clip arrives from the phone -> enroll or analyse it -> update the twin -> a system note
for the orchestrator, which then explains the result to the worker."""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

import followups
from audio.engine import AudioEngine
from mcp_client import ToolFailed
from services import Services
from sessions import Session
from tools_local import public_analysis


async def enroll(svc: Services, engine: AudioEngine, asset: dict[str, Any], y: np.ndarray, mode: str) -> tuple[dict[str, Any], str]:
    result = await asyncio.to_thread(engine.enroll, asset["id"], y, mode)
    if not result["enrolled"]:
        return result, (f"Recording the healthy sound of {asset['name']} did not work ({result['issue']}). "
                        f"Ask the worker to try again. Tip: {result['tip']}")
    svc.state.set_asset_state(asset["id"], "normal", "Sounds normal" if mode != "tap" else "Good part recorded")
    recorded = f"Recorded a good part's ring for {asset['name']}" if mode == "tap" else \
        f"Recorded how {asset['name']} sounds when healthy"
    svc.state.add_timeline(recorded, "done",
                           {"tool": "enroll_baseline", "args": {"asset_id": asset["id"], "mode": mode}, "result": result})
    svc.bus.changed()
    what = "a good tap" if mode == "tap" else f"{result.get('seconds', 10)} seconds of healthy sound"
    return result, (f"Recorded {what} for {asset['name']}. Tell the worker it is set up and EarShot will now notice "
                    "when it sounds different. Offer to listen again to test it.")


async def analyze(svc: Services, engine: AudioEngine, session: Session, asset: dict[str, Any], y: np.ndarray) -> tuple[dict[str, Any], str]:
    st = svc.state
    analysis = await asyncio.to_thread(engine.analyze, asset["id"], asset["type"], y, svc.pack)
    if not analysis["ok"]:
        return analysis, (f"The recording of {asset['name']} could not be used ({analysis['issue']}). Ask the worker to "
                          f"record again and give this tip: {analysis['tip']}")
    svc.analyses[analysis["id"]] = analysis
    session.last_analysis[asset["id"]] = analysis["id"]
    session.focus_asset = asset["id"]
    public = public_analysis(analysis)
    st.analyses[asset["id"]] = public
    st.checked.add(asset["id"])
    st.resolve_followups(asset["id"])
    label = analysis["label"]
    if analysis["band"] == "very unusual":
        st.problems.add(asset["id"])
        st.set_asset_state(asset["id"], "problem", label[2:].capitalize() if label.startswith("a ") else label.capitalize())
    elif analysis["band"] == "slightly unusual":
        st.set_asset_state(asset["id"], "watch", "Sounds a little different")
    else:
        st.set_asset_state(asset["id"], "normal")
    facts = st.facts.setdefault(asset["id"], {})
    facts.update({"most_likely": label, "how_sure": analysis["confidence"]})
    st.add_timeline(f"Listened to {asset['name']} for 10 seconds: {analysis['band']}", "done",
                    {"tool": "analyze_sound", "args": {"asset_id": asset["id"]}, "result": public})
    svc.bus.changed()
    note = (f"Sound analysis ready for {asset['name']} ({asset['id']}). Call analyze_sound, get_asset_history and "
            "find_similar_cases")
    if analysis["band"] != "normal":
        note += (", assess_risk, and check_inventory for the part the likely cause needs. Then tell the worker what you "
                 "heard, why, what you recommend and what you will do if they say yes; if the plan stops the machine or "
                 "takes it out of service, call request_confirmation before asking.")
        if analysis["confidence"] == "not sure":
            note += " You are not sure of the cause: say so and offer to call a person."
    else:
        note += ", then tell the worker it sounds normal and log the inspection."
    if analysis["band"] == "slightly unusual":
        note += " Schedule a follow-up to check it again."
    return analysis, note


async def verify(svc: Services, engine: AudioEngine, session: Session, asset: dict[str, Any], y: np.ndarray) -> tuple[dict[str, Any], str]:
    """Re-listen after a repair. Sounds normal -> close the job (and its Jira ticket), back in service, learn the cause."""
    analysis, note = await analyze(svc, engine, session, asset, y)
    if not analysis["ok"]:
        return analysis, note
    st = svc.state
    job = next((j for j in reversed(st.jobs) if j["asset_id"] == asset["id"] and j["status"] not in ("done", "cancelled")), None)
    if analysis["band"] != "normal":
        if job:
            await _job(svc, session.id, job["id"], "in_progress", f"Re-listened after the repair: still {analysis['band']}.")
        return analysis, (f"After the repair, {asset['name']} still sounds {analysis['band']}. Tell the worker the job stays "
                          "open and suggest what to check next. Do not close it.")
    cause = (job or {}).get("cause_label")  # the diagnosis the job was raised for
    if job:
        await _job(svc, session.id, job["id"], "done", "Re-listened after the repair: sounds normal again. Closed by EarShot.")
    try:
        result = await svc.enterprise.call("update_asset_status", {"asset_id": asset["id"], "status": "running",
                                                                   "reason": "repaired; sounds normal"})
        await followups.apply(svc, session.id, "update_asset_status", {"asset_id": asset["id"]}, result, 0)
    except ToolFailed:
        pass
    if cause:
        # The repair fixed it, so the unusual recording that led to the job is a confirmed example of `cause`.
        before = next((a for a in reversed(list(svc.analyses.values()))
                       if a["asset_id"] == asset["id"] and a.get("band") in ("slightly unusual", "very unusual")), None)
        if before:
            engine.record_feedback(before, asset["type"], cause)
    if job:
        closed = f"job {job['id']}" + (f" (Jira {job['jira_key']})" if job.get("jira_key") else "")
    else:
        closed = "no open job"
    learned = f" and learned that the cause was {cause}" if cause else ""
    return analysis, (f"After the repair, {asset['name']} sounds normal again. EarShot closed {closed}, put it back in "
                      f"service{learned}. Tell the worker in one or two sentences.")


async def _job(svc: Services, session_id: str, job_id: str, status: str, note: str) -> None:
    try:
        result = await svc.enterprise.call("update_work_order", {"work_order_id": job_id, "status": status, "note": note})
        await followups.apply(svc, session_id, "update_work_order", {"work_order_id": job_id, "status": status}, result, 1)
    except ToolFailed:
        svc.state.add_timeline(f"Could not update job {job_id}: the system did not respond", "failed")
        svc.bus.changed()


async def tap(svc: Services, engine: AudioEngine, asset: dict[str, Any], y: np.ndarray, part: int) -> tuple[dict[str, Any], str]:
    result = await asyncio.to_thread(engine.tap_test, asset["id"], y)
    if not result["ok"]:
        return result, f"The tap test on {asset['name']} did not work ({result['issue']}). Tell the worker: {result['tip']}"
    st = svc.state
    batch = st.tap_batches.setdefault(asset["id"], {"asset_id": asset["id"], "total": asset.get("parts") or 12,
                                                     "parts": [], "good_decay_ms": result["good_decay_ms"],
                                                     "good_envelope": result["good_envelope"]})
    numbers = []
    taps = result["taps"][:1] if part else result["taps"]  # a re-tap of one part counts only its first tap
    for t in taps:
        n = part or len(batch["parts"]) + 1
        if n > batch["total"]:
            break
        entry = {"n": n, **t}
        batch["parts"] = [p for p in batch["parts"] if p["n"] != n] + [entry]
        numbers.append(entry)
    batch["parts"].sort(key=lambda p: p["n"])
    dull = [p["n"] for p in batch["parts"] if p["result"] == "dull"]
    good = sum(1 for p in batch["parts"] if p["result"] == "good")
    left = batch["total"] - len(batch["parts"])
    st.checked.add(asset["id"])
    word = "Wheel" if "wheel" in asset["type"] else "Part"
    if dull:
        st.problems.add(asset["id"])
        st.set_asset_state(asset["id"], "problem", f"{word} {dull[-1]} sounds dull")
    else:
        st.set_asset_state(asset["id"], "normal", "All good so far")
    heard = ", ".join(f"{word.lower()} {p['n']} {p['result']}" + (f" ({p['reason']})" if p["reason"] else "") for p in numbers)
    st.add_timeline(f"Tap test on {asset['name']}: {heard}", "done",
                    {"tool": "tap_test", "args": {"asset_id": asset["id"]}, "result": {"taps": numbers}})
    svc.bus.changed()
    note = (f"Tap test on {asset['name']}: {heard}. So far {good} good, {len(dull)} need a look, {left} left. "
            "Tell the worker in one or two sentences.")
    if any(p["result"] == "dull" for p in numbers):
        note += (" For a dull part, suggest tapping it once more to double-check. If it was already re-tapped and is "
                 "still dull, recommend taking it out of service / holding it (needs request_confirmation first) and "
                 "notifying the right people.")
    return result, note


async def alarm(svc: Services, engine: AudioEngine, asset: dict[str, Any], y: np.ndarray) -> tuple[dict[str, Any], str]:
    result = engine.alarm(y, svc.pack)
    if not result["ok"]:
        return result, f"No clear beeps were heard from {asset['name']}. Tell the worker: {result['tip']}"
    svc.state.add_timeline(f"Heard alarm beeps on {asset['name']}: {result['pattern']}", "done",
                           {"tool": "alarm", "args": {"asset_id": asset["id"]}, "result": result})
    svc.bus.changed()
    if result["known"]:
        return result, (f"Alarm on {asset['name']}: beeps '{result['pattern']}' mean '{result['meaning']}'. Recommended "
                        f"action: {result['action']}. Tell the worker plainly and offer to raise a job.")
    return result, (f"Alarm on {asset['name']}: beep pattern '{result['pattern']}' is not in the alarm list. Say you "
                    "don't recognise it and offer to call a person.")
