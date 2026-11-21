"""The actions EarShot takes after a fault, built in code.

The model is asked to call these tools, but a spoken "yes" still has to raise the job and
log the result when the model forgets a step. These helpers are the source of those arguments.
"""

from __future__ import annotations

from typing import Any


def finding_text(asset: dict[str, Any], analysis: dict[str, Any] | None, batch: dict[str, Any] | None) -> str:
    """One short phrase for what was found, used in the job, the log and the question."""
    word = "wheel" if "wheel" in str(asset.get("type", "")) else "part"
    dull = [p["n"] for p in (batch or {}).get("parts") or [] if p.get("result") == "dull"]
    if dull:
        shown = ", ".join(str(n) for n in dull)
        return f"{word} {shown} sounds dull"
    label = (analysis or {}).get("label") or ""
    band = (analysis or {}).get("band") or ""
    if label and band and band != "normal":
        return f"sounds {band}, likely {label}"
    if label:
        return f"likely {label}"
    return "a problem was found"


def _job_word(vocabulary: dict[str, str]) -> str:
    return vocabulary.get("work_order") or "repair job"


def _hold_step(asset: dict[str, Any], vocabulary: dict[str, str], is_tap: bool) -> tuple[str, str]:
    """(spoken action, tool name) for taking a bad tap or a bad machine out of use."""
    if is_tap and "wheel" not in str(asset.get("type", "")):
        text = vocabulary.get("quarantine") or "hold the batch"
        return text, "quarantine_batch"
    text = vocabulary.get("out_of_service") or "take it out of service"
    return text, "update_asset_status"


def fault_steps(
    asset: dict[str, Any],
    vocabulary: dict[str, str],
    people: list[str],
    finding: str,
    *,
    is_tap: bool,
) -> tuple[str, list[dict[str, str]]]:
    """Question plus the steps a yes should carry out: raise the job, hold the asset, tell people."""
    action, tool = _hold_step(asset, vocabulary, is_tap)
    job = _job_word(vocabulary)
    name = asset.get("name") or asset.get("id") or "this machine"
    question = f"{name}: {finding}. Shall I {action} and raise a {job}?"
    steps = [
        {"text": f"Raise the {job}", "tool": "create_work_order"},
        {"text": action[:1].upper() + action[1:], "tool": tool},
    ]
    if people:
        steps.append({"text": f"Tell {', '.join(people)}", "tool": "notify_people"})
    return question, steps


def ensure_issue_steps(
    steps: list[Any],
    tools: list[str],
    asset: dict[str, Any],
    vocabulary: dict[str, str],
    people: list[str],
    finding: str,
    *,
    is_tap: bool,
) -> tuple[list[Any], list[str]]:
    """Add the job, the hold and the notification when a fault plan is missing them."""
    steps = list(steps)
    tools = list(tools)
    names = {t for t in tools if t} | {s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool")}
    if "create_work_order" not in names:
        steps.append({"text": f"Raise the {_job_word(vocabulary)}", "tool": "create_work_order"})
        tools.append("create_work_order")
    if not names & {"update_asset_status", "quarantine_batch", "shutdown_line"}:
        action, tool = _hold_step(asset, vocabulary, is_tap)
        steps.append({"text": action[:1].upper() + action[1:], "tool": tool})
        tools.append(tool)
    if people and "notify_people" not in names:
        steps.append({"text": f"Tell {', '.join(people)}", "tool": "notify_people"})
        tools.append("notify_people")
    return steps, tools


def args_for(
    asset: dict[str, Any],
    analysis: dict[str, Any] | None,
    batch: dict[str, Any] | None,
    vocabulary: dict[str, str],
    people: list[str],
    fault_parts: dict[str, str],
    tool: str,
    finding: str,
) -> dict[str, Any] | None:
    """Arguments for one plan step. None when the step needs details only the model has."""
    asset_id = str(asset.get("id", ""))
    name = asset.get("name") or asset_id
    if tool == "create_work_order":
        title = f"{name}: {finding}"
        return {"asset_id": asset_id, "title": title[:140], "priority": "high", "description": finding}
    if tool == "log_inspection":
        failed = "dull" in finding or "unusual" in finding
        return {"asset_id": asset_id, "result": "fail" if failed else "pass", "notes": finding}
    if tool == "update_asset_status":
        words = (vocabulary.get("out_of_service") or "").lower()
        status = "sick" if "sick" in words else "out of service"
        return {"asset_id": asset_id, "status": status, "reason": finding}
    if tool == "quarantine_batch":
        parts = [int(p["n"]) for p in (batch or {}).get("parts") or [] if p.get("result") == "dull"]
        return {"asset_id": asset_id, "parts": parts or [1], "reason": finding}
    if tool == "notify_people":
        if not people:
            return None
        return {"people": people, "message": f"{name}: {finding}.", "urgency": "high"}
    if tool == "announce_on_floor":
        return {"message": f"{name}: {finding}.", "at": "now"}
    if tool == "reserve_part":
        part = fault_parts.get(str((analysis or {}).get("label") or ""))
        if not part:
            return None
        return {"part": part, "quantity": 1}
    if tool == "shutdown_line":
        line = asset.get("line") or ""
        if not line:
            return None
        return {"line": line, "reason": finding}
    return None
