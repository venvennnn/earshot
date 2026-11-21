"""What happens after a tool runs: plain-language timeline, live twin state, and Murf voice follow-ups
(multilingual briefings to people, floor announcements, the spoken shift report)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from mcp_client import ToolFailed
from murf import MurfError
from packs import LANGUAGE_NAMES
from services import Services

log = logging.getLogger("earshot.followups")


def _asset_name(svc: Services, asset_id: str) -> str:
    return svc.state.assets.get(str(asset_id).upper(), {}).get("name", str(asset_id))


def sentence(svc: Services, name: str, args: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Plain sentence for the 'What EarShot did' timeline (None = not worth showing)."""
    a = _asset_name(svc, args.get("asset_id", ""))
    match name:
        case "identify_asset":
            return f"Found {result['name']} on {result.get('line', 'the line')}" if result.get("found") else None
        case "start_listening":
            return f"Opened the recorder for {a}" if result.get("ok") else None
        case "get_asset_history":
            return f"Checked its history: last serviced {result['last_serviced']}" if "last_serviced" in result else None
        case "find_similar_cases":
            wos = result.get("matching_work_orders") or []
            return (f"Found a similar problem: {_asset_name(svc, wos[0]['asset_id'])}, {wos[0].get('when', '')}"
                    if wos else "Looked for similar past problems: none found")
        case "check_inventory":
            if not result.get("found"):
                return f"Looked for {args.get('part')}: not in the stores list"
            return f"Checked spares: {result['total']} {result['name']} in stock" if result["in_stock"] else \
                f"Checked spares: no {result['name']} in stock"
        case "reserve_part":
            return f"Set aside {result['quantity']} {result['name']} in {result['warehouse']}" if result.get("reserved") \
                else f"Could not set aside {args.get('part')}: out of stock"
        case "create_work_order":
            jira = f" · Jira {result['jira_key']}" if result.get("jira_key") else ""
            return f"Raised repair job {result['id']} for {a}, {result['priority']} priority{jira}"
        case "update_work_order":
            word = {"in_progress": "started", "done": "closed", "cancelled": "cancelled", "scheduled": "scheduled",
                    "open": "reopened"}.get(str(args.get("status")), "updated")
            return f"Job {result['id']} {word}" if result.get("ok") else None
        case "schedule_follow_up":
            return f"Reminder for {args.get('when', 'the next shift')}: {args.get('note', '')}"
        case "update_asset_status":
            return f"Marked {a} as {result['status']}"
        case "quarantine_batch":
            return f"Put {a} on hold"
        case "shutdown_line":
            return f"Shut down {args.get('line')}"
        case "request_purchase":
            return f"Raised purchase request {result['id']} for {args.get('part')}"
        case "notify_people":
            return f"Contacting {', '.join(args.get('people', []))}"
        case "announce_on_floor":
            return "Announced it on the floor"
        case "generate_report":
            return "Wrote the shift report"
        case "log_inspection":
            return f"Logged the result for {a}"
        case "register_asset":
            return f"Added {result['name']} to the asset list"
        case "record_feedback":
            return f"Learned the confirmed cause for {a}" if result.get("saved") else None
        case "search_knowledge" | "assess_risk" | "enroll_baseline" | "request_confirmation" | "analyze_sound":
            return None
    return None


def intent(svc: Services, name: str, args: dict[str, Any]) -> str:
    """What a tool call would do, as a plain phrase for a confirmation question."""
    a = _asset_name(svc, args.get("asset_id", ""))
    return {
        "create_work_order": f"raise a repair job for {a}",
        "update_asset_status": f"mark {a} as {args.get('status', 'changed')}",
        "quarantine_batch": f"put {a} on hold",
        "shutdown_line": f"shut down {args.get('line', 'the line')}",
        "request_purchase": f"buy {args.get('quantity', '')} {args.get('part', 'parts')}".replace("  ", " "),
    }.get(name, name.replace("_", " "))


def already_finished(svc: Services, session_id: str, tool: str) -> bool:
    """True when this tool's step on the latest approved plan is already done (don't run it twice)."""
    for conf in reversed(svc.state.confirmations):
        if conf["session"] != session_id or conf["status"] != "approved":
            continue
        matched = [s for s in conf["steps"] if s.get("tool") == tool]
        if not matched:
            continue
        if any(s.get("status") == "next" for s in matched):
            return False
        return any(s.get("status") == "done" for s in matched)
    return False


def tick_plan_step(svc: Services, session_id: str, tool: str, ok: bool, text: str | None,
                   detail: dict[str, Any]) -> bool:
    """If this tool carries out a step of an approved plan, mark that step done/failed (with what actually
    happened) instead of adding a separate timeline line."""
    for conf in reversed(svc.state.confirmations):
        if conf["session"] != session_id or conf["status"] != "approved":
            continue
        for step in conf["steps"]:
            if step.get("status") == "next" and step["tool"] == tool:
                step["status"] = "done" if ok else "failed"
                for item in svc.state.timeline:
                    if item["id"] == step["timeline_id"]:
                        item.update(status=step["status"], ts=time.time(), detail=detail,
                                    text=text if ok and text else (step["text"] if ok else f"{step['text']}: did not work"))
                return True
    return False


def enrich(svc: Services, session_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Add the evidence and the approver to a new work order (shown in the CMMS and the Jira ticket)."""
    if name != "create_work_order":
        return args
    asset_id = str(args.get("asset_id", "")).upper()
    analysis = svc.state.analyses.get(asset_id) or {}
    facts = svc.state.facts.get(asset_id, {})
    parts = []
    if analysis.get("ok"):
        parts.append(f"{analysis['band']}, likely {analysis['label']} ({analysis['confidence']})")
        if analysis.get("explanation"):
            parts.append(analysis["explanation"])
        if analysis.get("clip_url") and svc.settings.public_backend_url:
            parts.append(f"Recording: {svc.settings.public_backend_url.rstrip('/')}{analysis['clip_url']}")
    if facts.get("seen_before"):
        parts.append(f"Similar case: {facts['seen_before']}")
    approved = next((c for c in reversed(svc.state.confirmations)
                     if c["session"] == session_id and c["status"] == "approved"), None)
    return {**args, "evidence": " ".join(parts), "approved_by": approved.get("approved_by", "") if approved else ""}


_HISTORY_TOOLS = {"create_work_order", "update_work_order", "log_inspection", "update_asset_status", "quarantine_batch"}


async def refresh_histories(svc: Services) -> None:
    """Reload past issues so the dashboard shows a job as soon as it is raised."""
    try:
        data = await svc.enterprise.call("admin_histories", {})
    except ToolFailed as exc:
        log.warning("Could not load past issues: %s", exc)
        return
    svc.state.histories = data.get("assets") or {}
    svc.bus.changed()


async def apply(svc: Services, session_id: str, name: str, args: dict[str, Any], result: dict[str, Any], tier: int) -> None:
    """Update the twin and trigger voice follow-ups after a successful tool call."""
    st = svc.state
    text = sentence(svc, name, args, result)
    detail = {"tool": name, "args": args, "result": result, "tier": tier}
    if not tick_plan_step(svc, session_id, name, True, text, detail) and text:
        st.add_timeline(text, "done", detail)
    if tier >= 1:
        st.actions_done += 1
    asset_id = str(args.get("asset_id", "")).upper()
    facts = st.facts.setdefault(asset_id, {}) if asset_id else {}

    match name:
        case "get_asset_history" if "last_serviced" in result:
            facts["last_serviced"] = result["last_serviced"]
        case "check_inventory" if result.get("found"):
            focus = asset_id or (st.sessions.get(session_id, {}).get("focus") or "")
            if focus:
                st.facts.setdefault(focus, {})["spare"] = f"{result['total']} in stock" if result["in_stock"] else "out of stock"
        case "update_work_order" if result.get("ok"):
            st.jobs[:] = [{**j, **result} if j["id"] == result["id"] else j for j in st.jobs]  # keep cause_label
        case "create_work_order":
            label = st.analyses.get(asset_id, {}).get("label")
            st.jobs.append({**result, "cause_label": label if label and label != "running normally" else None})
            asset = st.assets.get(asset_id)
            if asset and asset["state"] == "problem":
                asset["label"] = f"{asset['label'].split(' · ')[0]} · job raised"
        case "update_asset_status":
            status = str(result.get("status", "")).lower()
            if any(w in status for w in ("out of service", "sick", "stopped", "locked", "shut")):
                st.set_asset_state(asset_id, "out", result["status"].capitalize())
            elif "running" in status or "fit" in status:
                st.set_asset_state(asset_id, "normal")
            else:
                st.set_asset_state(asset_id, "problem", result["status"].capitalize())
        case "quarantine_batch":
            st.set_asset_state(asset_id, "out", "On hold")
        case "register_asset":
            casting = result["type"] == "casting"
            st.add_asset({"id": result["asset_id"], "name": result["name"], "type": result["type"],
                          "line": result.get("line", ""), "modes": ["tap"] if casting else ["continuous"],
                          "parts": 12 if casting else 0})
        case "notify_people":
            for n in result.get("notifications", []):
                asyncio.create_task(brief_person(svc, n["person"], n["message"], session_id, notification_id=n["id"]))
        case "announce_on_floor":
            asyncio.create_task(announce(svc, args["message"], args.get("at", "now")))
        case "generate_report":
            asyncio.create_task(write_report(svc, notes=args.get("summary", ""), file=False))
    if name in _HISTORY_TOOLS:
        await refresh_histories(svc)
    svc.bus.changed()


async def complete(svc: Services, system: str, user: str) -> str:
    """One plain LLM completion (no tools)."""
    started = time.perf_counter()
    res = await svc.llm.chat.completions.create(
        model=svc.settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=600,
    )
    svc.metrics.add_llm(time.perf_counter() - started)
    return (res.choices[0].message.content or "").strip()


async def brief_person(svc: Services, person_name: str, message: str, session_id: str, notification_id: str = "",
                       approval_for: str = "") -> dict[str, Any]:
    """Brief one person in their own language: a Murf Falcon voice message, shown on their recipient page."""
    person = svc.pack.person(person_name)
    language = person.language if person else "en"
    contact = {
        "id": svc.state.next_id("c"), "name": person.name if person else person_name,
        "role": person.role if person else "", "language": language,
        "language_name": LANGUAGE_NAMES.get(language, language), "kind": "call", "status": "Calling…",
        "message": message, "text": "", "audio_url": None, "reply": None, "notification_id": notification_id,
        "approval_for": approval_for, "session": session_id, "ts": time.time(),
    }
    svc.state.contacts.append(contact)
    svc.bus.changed()
    try:
        contact["text"] = await complete(
            svc,
            "You write short spoken voice messages from EarShot, a maintenance assistant, to factory or depot staff. "
            f"Write in {LANGUAGE_NAMES.get(language, 'English')} only, in natural spoken style, under 60 words. "
            "Say who is calling, what happened, and what you need from them. No markdown.",
            f"Recipient: {contact['name']} ({contact['role']}). Worker on the floor: {svc.pack.worker.name}. "
            f"Message: {message}" + (" Ask them to approve or decline." if approval_for else
                                     " Ask them to reply if they need to."),
        )
        audio = await svc.murf.synthesize(contact["text"], language, kind="briefing", role=2)
        contact["audio_url"] = audio["url"]
        contact["status"] = "Waiting for reply" if approval_for else "Told"
    except Exception as exc:  # LLM or Murf failed: keep whatever text we have
        log.error("Briefing for %s failed: %s", person_name, exc)
        contact["text"] = contact["text"] or message
        contact["status"] = "Sent as text"
    svc.bus.changed()
    await svc.bus.emit("briefing", name=contact["name"], contact_id=contact["id"])
    return contact


async def announce(svc: Services, message: str, at: str) -> None:
    lang = svc.pack.announcement_language
    contact = {"id": svc.state.next_id("c"), "name": "Floor speakers", "role": "Announcement", "language": lang,
               "language_name": LANGUAGE_NAMES.get(lang, lang), "kind": "announcement", "status": f"At {at}",
               "message": message, "text": message, "audio_url": None, "reply": None, "ts": time.time()}
    svc.state.contacts.append(contact)
    try:
        audio = await svc.murf.synthesize(f"Attention please. {message}", lang, kind="announcement", role=3)
        contact["audio_url"] = audio["url"]
        await svc.bus.emit("play_audio", target="dashboard", url=audio["url"], label="Floor announcement")
    except MurfError as exc:
        log.error("Announcement voice failed: %s", exc)
        contact["status"] = "Text only (voice failed)"
    svc.bus.changed()


async def write_report(svc: Services, notes: str = "", file: bool = True) -> dict[str, Any]:
    """Compose the shift report from what happened, read it with Murf, and keep it for the dashboard.
    `file=False` when the LLM already filed it through the generate_report tool."""
    st = svc.state
    events = "\n".join(f"- {time.strftime('%H:%M', time.localtime(t['ts']))} {t['text']}" for t in st.timeline
                       if t["status"] == "done")
    tiles = st.tiles()
    text = await complete(
        svc,
        "You write the spoken handover report for the next shift. Plain spoken English, about 120 words, no lists or "
        "markdown. Cover: machines checked, problems found and what was done, which jobs are still open (say ticket "
        "numbers), what is waiting, and the reminders the next shift must do first. Only use the facts given.",
        f"{svc.pack.plant}, {svc.pack.line}, {svc.pack.shift}.\nCounts: {tiles}\nWhat happened:\n{events or '- nothing'}\n"
        f"Jobs: {[(j['id'], j.get('jira_key'), j['title'], j['status']) for j in st.jobs]}\n"
        f"Reminders for the next shift: {[(f['asset_name'], f['when'], f['note']) for f in st.followups if f['status'] == 'open']}\n"
        f"Notes from the worker: {notes}",
    )
    report: dict[str, Any] = {"text": text, "audio_url": None, "ts": time.time()}
    if file:
        try:
            await svc.enterprise.call("generate_report", {"summary": text})
        except Exception as exc:
            log.warning("Report filing failed: %s", exc)
    try:
        audio = await svc.murf.synthesize(text, "en", kind="report", role=1)
        report["audio_url"] = audio["url"]
    except MurfError as exc:
        log.error("Report voice failed: %s", exc)
    st.report = report
    svc.bus.changed()
    return report
