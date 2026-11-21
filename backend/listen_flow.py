"""The listen flow: a clip arrives from the phone -> enroll or analyse it -> update the twin -> a system note
for the orchestrator, which then explains the result to the worker."""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

import followups
import plan_steps
from audio.engine import AudioEngine
from confirmations import open_confirmation
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
    word = "wheel" if "wheel" in asset["type"] else "part"
    result["spoken"] = (f"Got a good {word} for {asset['name']}. Tap the rest when you're ready." if mode == "tap"
                        else f"{asset['name']} is set up. I'll notice when it sounds different.")
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
    finding = plan_steps.finding_text(asset, public, None)
    log_result = {"normal": "pass", "slightly unusual": "watch", "very unusual": "fail"}.get(analysis["band"], "fail")
    logged = await _record_inspection(svc, session.id, asset["id"], log_result, finding)
    logged_bit = "The inspection is already logged." if logged else "Logging the inspection failed; try log_inspection once."
    note = (f"Sound analysis ready for {asset['name']} ({asset['id']}): {finding}. {logged_bit} "
            "Call analyze_sound, get_asset_history and find_similar_cases")
    if analysis["band"] == "very unusual":
        question = await _open_fault_plan(svc, session, asset, finding, is_tap=False)
        note += (". assess_risk, and check_inventory for the part the likely cause needs. "
                 f"A question is already on screen: '{question}'. Explain what you heard and ask that question. "
                 "Do not call create_work_order, update_asset_status or notify_people until they say yes, "
                 "and do not call log_inspection again.")
        if analysis["confidence"] == "not sure":
            note += " You are not sure of the cause: say so and offer to call a person."
    elif analysis["band"] == "slightly unusual":
        note += (", assess_risk, and check_inventory. Tell the worker what you heard and schedule a follow-up. "
                 "Do not stop the machine.")
    else:
        note += ". Tell the worker it sounds normal. Do not raise a job."
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
        result["spoken"] = result.get("tip") or "I didn't hear a tap. Tap again, close to the phone."
        return result, f"The tap test on {asset['name']} did not work ({result['issue']}). Tell the worker: {result['tip']}"
    st = svc.state
    batch = st.tap_batches.setdefault(asset["id"], {"asset_id": asset["id"], "total": asset.get("parts") or 12,
                                                     "parts": [], "good_decay_ms": result["good_decay_ms"],
                                                     "good_envelope": result["good_envelope"]})
    batch["good_url"] = result["good_url"]
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
    result["spoken"] = _tap_spoken(word, numbers, left)
    note = (f"Tap test on {asset['name']}: {heard}. So far {good} good, {len(dull)} need a look, {left} left. "
            "Tell the worker in one or two sentences. Do not raise a job until they finish the batch.")
    if any(p["result"] == "dull" for p in numbers):
        note += " For a dull part, suggest tapping it once more to double-check."
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


def _tap_spoken(word: str, numbers: list[dict[str, Any]], left: int) -> str:
    bits = [f"{word} {p['n']} {'sounds dull' if p['result'] == 'dull' else 'rings well'}" for p in numbers]
    line = "I heard " + ", ".join(bits) + "."
    dull = [p for p in numbers if p["result"] == "dull"]
    if dull:
        line += f" Tap {word.lower()} {dull[-1]['n']} once more to check."
    elif left:
        line += f" {left} to go."
    else:
        line += " That's the last one. Say finish and I'll log it."
    return line


def finish_tap(svc: Services, asset: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Close a tap-test batch: a fixed summary (not left to the LLM) and a note asking for the next step."""
    st = svc.state
    batch = st.tap_batches.get(asset["id"])
    word = "wheel" if "wheel" in asset["type"] else "part"
    if batch and batch.get("finished"):
        summary = dict(batch.get("summary") or {"finished": True, "asset_id": asset["id"]})
        summary["already"] = True
        return summary, (f"The tap test on {asset['name']} is already finished and the next step is already on screen. "
                         "Do not finish it again. If a question is waiting, ask it.")
    if not batch or not batch["parts"]:
        return {"finished": False}, f"No {word}s of {asset['name']} have been tapped yet. Tell the worker to start tapping."
    tested = {p["n"]: p["result"] for p in batch["parts"]}
    good = [n for n, r in tested.items() if r == "good"]
    dull = [n for n, r in tested.items() if r == "dull"]
    untested = [n for n in range(1, batch["total"] + 1) if n not in tested]
    batch["finished"] = True
    summary = {"finished": True, "asset_id": asset["id"], "good": good, "dull": dull, "not_tapped": untested,
               "total": batch["total"]}
    batch["summary"] = summary
    dull_text = f"{len(dull)} dull ({word} {', '.join(map(str, dull))})" if dull else "none dull"
    st.add_timeline(f"Finished tap test on {asset['name']}: {len(good)} good, {dull_text}, {len(untested)} not tapped",
                    "done", {"tool": "finish_tap_batch", "args": {"asset_id": asset["id"]}, "result": summary})
    svc.bus.changed()
    note = (f"The worker finished the tap test on {asset['name']} ({asset['id']}): good {word}s {good or 'none'}, dull "
            f"{word}s {dull or 'none'}, not tapped {untested or 'none'}.")
    return summary, note


async def close_tap_batch(svc: Services, session: Session, asset: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Finish the batch, log the inspection, and (when something is dull) open the job for a yes."""
    summary, note = finish_tap(svc, asset)
    if not summary.get("finished") or summary.get("already"):
        return summary, note, ""
    finding = plan_steps.finding_text(asset, None, svc.state.tap_batches.get(asset["id"]))
    dull = summary.get("dull") or []
    logged = await _record_inspection(svc, session.id, asset["id"], "fail" if dull else "pass",
                                      finding if dull else f"Tap test passed ({summary.get('good') or 'none'} good)")
    if not dull:
        spoken = f"All tapped {'wheels' if 'wheel' in asset['type'] else 'parts'} ring well. I logged the inspection as passed."
        if not logged:
            spoken = f"All tapped {'wheels' if 'wheel' in asset['type'] else 'parts'} ring well. I couldn't save the inspection log."
        return summary, spoken + " Tell the worker. Do not raise a job.", spoken
    question = await _open_fault_plan(svc, session, asset, finding, is_tap=True)
    saved = "I logged the failed inspection." if logged else "I couldn't save the inspection log."
    spoken = f"{saved} {question}"
    note = (f"{note} {saved} A question is already on screen: '{question}'. Ask the worker that. "
            "Do not call create_work_order, update_asset_status, quarantine_batch or notify_people until they say yes. "
            "Do not call finish_tap_batch or log_inspection again.")
    return summary, note, spoken


async def _record_inspection(svc: Services, session_id: str, asset_id: str, result: str, notes: str) -> bool:
    try:
        out = await svc.enterprise.call("log_inspection", {"asset_id": asset_id, "result": result, "notes": notes})
    except ToolFailed:
        svc.state.add_timeline(f"Could not log the inspection of {asset_id}: the system did not respond", "failed")
        svc.bus.changed()
        return False
    await followups.apply(svc, session_id, "log_inspection", {"asset_id": asset_id, "result": result, "notes": notes}, out, 0)
    return bool(out.get("logged", True))


async def _open_fault_plan(svc: Services, session: Session, asset: dict[str, Any], finding: str, *, is_tap: bool) -> str:
    people = [p.name for p in svc.pack.people]
    question, steps = plan_steps.fault_steps(asset, svc.pack.vocabulary, people, finding, is_tap=is_tap)
    await open_confirmation(svc, session, asset["id"], question, steps, [s["tool"] for s in steps])
    return question

