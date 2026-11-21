"""EarShot's brain: the LLM tool loop with the risk policy, confirmations and plain-language replies.

Initiate -> Understand -> Execute -> Confirm -> Follow up:
- the worker's words (from Agora ASR, or the text box in demo mode) start a turn;
- the LLM uses tools (local + enterprise MCP) to understand and act;
- tier 2/3 tools only run after a yes (enforced here, not by the prompt);
- results are spoken back (Agora agent, or Murf audio in the browser) and logged live.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, BadRequestError

import confirmations
import followups
import plan_steps
from mcp_client import ToolFailed
from packs import LANGUAGE_NAMES
from policy import spoken_decision, tier_for
from services import Services
from sessions import Session, SessionStore
from speech_text import language_update, match_assets, message_text, offline_reply
from tools_local import SCHEMAS as LOCAL_SCHEMAS
from tools_local import TOOLS as LOCAL_TOOLS

log = logging.getLogger("earshot.orchestrator")

MAX_TOOL_ROUNDS = 8
NOTE_PREFIX = "[EarShot system note, not the worker speaking]"
TAP_BASELINE = re.compile(
    r"^(?:(?:hey\s+)?earshot[\s,:]+)?(?:please\s+)?(?:can you\s+)?"
    r"(?:(?:create|make|set(?: up)?|start recording|record|replace|re[ -]?record)\s+)?"
    r"(?:(?:a|the)\s+)?(?:(?:tap|tapping|wheel)\s+)?(?:baseline|reference)"
    r"(?:\s+(?:for|on|of))?(?:\s+(?P<asset>.+))?$",
    re.IGNORECASE,
)
START_CAPTURE = re.compile(
    r"^(?:(?:hey\s+)?earshot[\s,:]+)?(?:please\s+)?(?:can you\s+)?"
    r"(?:start|begin) (?P<action>recording|listening)"
    r"(?:\s+(?:(?:to|for)\s+)?(?:the\s+)?(?P<asset>.+))?$",
    re.IGNORECASE,
)
MACHINE_CHECK = re.compile(
    r"^(?:(?:hey\s+)?earshot[\s,:]+)?(?:please\s+)?"
    r"(?:(?P<tap>tap(?:[ -]test(?:ing)?)?)|check(?:ing)?|listen to)"
    r"(?:\s+(?:(?:the|on|for)\s+)?(?:sound of\s+)?|$)",
    re.IGNORECASE,
)
SPEECH_LEAD = re.compile(
    r"^(?:(?:uh+|um+|first|okay|ok|well|no)[, ]+|(?:let's|let us|i want you to)\s+)+",
    re.IGNORECASE,
)
TAP_ACTIVITY = re.compile(r"^(?:do\s+)?(?:the\s+)?(?:(railway|railways)\s+)?tap[ -]test(?:ing)?$", re.IGNORECASE)
TAP_SELECTION = re.compile(r"^(?:do\s+)?(?:use|select|choose)\s+(?:the\s+)?(.+)$", re.IGNORECASE)
NEW_CASTING_BATCH = re.compile(
    r"^(?:start|create|register)\s+(?:a\s+)?new\s+(?:casting\s+)?batch"
    r"(?:\s+(?:number\s+)?(?P<number>\d{3,12}))?$", re.IGNORECASE,
)
BATCH_NUMBER = re.compile(r"^(?:(?:casting )?batch\s+)?(?:([0-9]{1,12})[.,\s]+)?([0-9]{3,12})$", re.IGNORECASE)
FALLBACK = "Sorry, I couldn't think that through just now. Please say it again."


def greeting(svc: Services) -> str:
    return f"Hi {svc.pack.worker.name}, I'm EarShot. Which machine are we checking?"


def system_prompt(svc: Services, session: Session) -> str:
    p = svc.pack
    assets = "; ".join(
        f"{a['id']} {a['name']} ({a['type']}, {a['label'].lower()})" for a in svc.state.assets.values()
    )
    people = "; ".join(f"{x.name}: {x.role}, speaks {LANGUAGE_NAMES.get(x.language, x.language)}" for x in p.people)
    words = "; ".join(f"say '{v}' for {k.replace('_', ' ')}" for k, v in p.vocabulary.items())
    pending = confirmations.pending_for(svc, session.id)
    return f"""You are EarShot, a voice assistant for maintenance and quality workers. You are talking with \
{p.worker.name}, a {p.worker.role}, at {p.plant}, {p.line}, {p.shift}.
You speak like a calm, helpful senior technician. Everything you write is spoken aloud by a voice.

How you speak:
- Short spoken sentences, at most about 60 words per reply. No lists, markdown, emojis, ids read letter by letter, or raw numbers for scores.
- Say "normal", "slightly unusual" or "very unusual", and "not sure", "fairly sure" or "very sure". Never say a score.
- Always present a likely cause as a suggestion ("it sounds like", "most likely").
- After a diagnosis always say: what you heard, why you think so, what you recommend, and exactly what you will do if they say yes.
- The worker's language for this turn is {LANGUAGE_NAMES.get(session.language, "English")}. Answer only in that language, in one or two short sentences. \
If their words are Hindi, answer in Hindi. If they are Tamil, answer in Tamil. Words for this site: {words}.
- If they name a machine that is not on this line, say so and name the machines you can check. Do not apologise, and do not ask them to say it again.

How you work:
- Use identify_asset to resolve spoken machine names to ids. Machines here: {assets}.
- To check a machine by ear: call start_listening, then tell the worker to hold the phone near it and wait for the beep. \
The result arrives later as a system note; then call analyze_sound, get_asset_history and find_similar_cases (and assess_risk if unusual), and check spares for the likely part.
- If no healthy sound is recorded for a machine, offer to record it now (start_listening with purpose 'enroll').
- To add a new machine: register_asset, then start_listening with purpose 'enroll'.
- Lookups and logging you just do. Reserving a part and notifying people you do and then mention.
- Anything that stops a machine, takes it out of service, raises a stop-work order, holds a batch, shuts a line, or buys above the limit: \
first call request_confirmation with the question, the steps and the tool names, then ask the worker. Never act on these without their yes. \
A line shutdown or a large purchase also needs a second approver.
- People you can notify (each is briefed in their own language): {people}. Floor announcements go to the floor speakers.
- In request_confirmation list every action as a step with its tool, including tier 1 ones (reserve_part, notify_people, \
announce_on_floor), so the worker sees the whole plan and each step is tracked.
- Jobs move through stages with update_work_order: scheduled, in_progress, done. When the worker says a machine is fixed, \
call start_listening with purpose 'verify'; if it sounds normal EarShot closes the job and returns the machine to service.
- Tap tests: results arrive as system notes. When the worker says they are finished, call finish_tap_batch.
- If something should be checked again later (slightly unusual, or the worker says not now), call schedule_follow_up.
- If a spare is out of stock, offer another warehouse or a purchase request. If a recording is unclear, ask for a re-record and give the tip.
- If you are not sure of the cause, say so and offer to call a person. If a tool fails twice, explain in plain words and offer another way.
- Use search_knowledge for procedures (for example lockout/tagout before hands-on work) and mention the key safety step.
{"- There is a question waiting for the worker's answer: '" + pending["question"] + "'." if pending else ""}"""


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_#`>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class Orchestrator:
    def __init__(self, svc: Services, sessions: SessionStore) -> None:
        self.svc = svc
        self.sessions = sessions
        self._token_key = "max_tokens"
        self._effort_rejected = False

    async def tool_schemas(self) -> list[dict[str, Any]]:
        try:
            enterprise = await self.svc.enterprise.schemas()
        except Exception as exc:  # MCP server down: keep talking with local tools only
            log.error("Enterprise tools unavailable: %s", exc)
            enterprise = []
        return LOCAL_SCHEMAS + enterprise

    # --- one turn --------------------------------------------------------------------------
    async def run_turn(self, session: Session, user_text: str | None = None, note: str | None = None,
                       background: bool = False) -> str:
        """Run the LLM with tools until it produces a spoken reply. Returns the reply text.

        A background turn (a sound result) steps aside as soon as the worker speaks, so the
        conversation is not stuck behind the tool loop.
        """
        svc = self.svc
        if not background:
            session.preempt.set()
        try:
            async with session.lock:
                if background and session.preempt.is_set():
                    if note:
                        session.add({"role": "user", "content": f"{NOTE_PREFIX} {note}"})
                    return ""
                if not background:
                    session.preempt.clear()
                pending = None
                if user_text:
                    heard = language_update(user_text)
                    if heard:
                        session.language = heard
                    session.add({"role": "user", "content": user_text})
                    svc.state.add_line(session.id, "worker", user_text)
                    svc.bus.changed()
                    pending = confirmations.pending_for(svc, session.id)
                    decision = spoken_decision(user_text) if pending and pending["status"] == "pending" else None
                    if pending and decision:
                        note = await confirmations.decide(svc, session, pending, decision, svc.pack.worker.name)
                done = await self._carry_out(session)
                if done:
                    note = ((note + " ") if note else "") + (
                        "Already done, do not call these tools again: " + "; ".join(done)
                        + ". Tell the worker what you did in one or two sentences."
                    )
                if note:
                    session.add({"role": "user", "content": f"{NOTE_PREFIX} {note}"})

                started = time.perf_counter()
                reply = await self._machine_check(session, user_text) if user_text and not note else ""
                if not reply:
                    reply = await self._loop(session, background)
                if background and session.preempt.is_set():
                    return ""
                svc.metrics.add_llm(time.perf_counter() - started)
                confirmations.finalize(svc, session.id)  # promised steps that did not happen show as "not done"
                reply = _clean_for_speech(reply)
                if reply in {FALLBACK, "Sorry, I lost my train of thought. Could you say that again?"}:
                    reply = ""
                if not reply:
                    if background:
                        return ""
                    log.warning("No model reply for %s; answering from the machines on this line", session.id)
                    reply = offline_reply(
                        list(svc.state.assets.values()), user_text or "",
                        language=session.language, worker=svc.pack.worker.name,
                    )
                session.add({"role": "assistant", "content": reply})
                svc.state.add_line(session.id, "agent", reply)
                svc.bus.changed()
                return reply
        finally:
            if not background:
                session.preempt.clear()

    async def _machine_check(self, session: Session, text: str) -> str:
        """Handle direct requests to listen even if the model or its tool schema is unavailable."""
        text = text.strip().rstrip(" .!?").replace("’", "'")
        original = text
        text = SPEECH_LEAD.sub("", text)
        assets = self.svc.state.assets
        tap_assets = {key: asset for key, asset in assets.items() if "tap" in asset.get("modes", [])}
        offered = tap_assets.get(session.offered_tap_asset or "")
        session.offered_tap_asset = None

        if session.tap_baseline_asset and text.casefold() in {"cancel baseline", "cancel the baseline"}:
            session.tap_baseline_asset = None
            session.awaiting_batch_number = False
            return "Baseline setup cancelled. The previous reference is still available if one was saved."

        if self.svc.pack.id == "manufacturing":
            new_batch = NEW_CASTING_BATCH.fullmatch(text)
            number = BATCH_NUMBER.fullmatch(text)
            if new_batch:
                session.awaiting_batch_number = True
                if new_batch["number"]:
                    return await self._record_casting_batch(session, new_batch["number"])
                return "What is the new casting batch number? The current batch and its results will stay saved."
            if session.awaiting_batch_number:
                if original.casefold() in {"cancel", "never mind", "stop"}:
                    session.awaiting_batch_number = False
                    session.tap_baseline_asset = None
                    return "Okay, keeping the current batch."
                if number and (not number[1] or number[2].startswith(number[1])):
                    return await self._record_casting_batch(session, number[2])
                return "I need the new casting batch number before I can record its baseline. Say the full number, or say cancel."
            if number and (session.tap_baseline_asset or session.focus_asset in tap_assets):
                return "To record a new casting batch, say start a new batch followed by its number."

        activity = TAP_ACTIVITY.fullmatch(text)
        selection = TAP_SELECTION.fullmatch(text)
        if selection:
            matches = match_assets(list(tap_assets.values()), selection[1])
        else:
            matches = [asset for asset in tap_assets.values()
                       if text.casefold() in (asset["name"].casefold(), asset["id"].casefold())]
        if len(matches) == 1:
            return self._select_tap_asset(session, matches[0])
        if offered and spoken_decision(original) == "yes" and not confirmations.pending_for(self.svc, session.id):
            return self._select_tap_asset(session, offered)
        if offered and original.casefold() in {"no", "nope", "not now"}:
            return "Okay. Which wheelset or batch should we use?"
        if activity:
            railway_requested = bool(activity[1])
            if railway_requested and self.svc.pack.id != "railways":
                switch = "Railway wheelsets are in the Railways industry. Switch to Railways on the dashboard to test a coach."
                if len(tap_assets) == 1:
                    alternative = next(iter(tap_assets.values()))
                    session.offered_tap_asset = alternative["id"]
                    return f"{switch} Use {alternative['name']} here instead?"
                return switch
            if focused := tap_assets.get(session.focus_asset or ""):
                return self._select_tap_asset(session, focused)
            if len(tap_assets) == 1:
                alternative = next(iter(tap_assets.values()))
                session.offered_tap_asset = alternative["id"]
                return f"Use {alternative['name']} for the tap test?"
            names = ", ".join(asset["name"] for asset in list(tap_assets.values())[:4])
            return f"Which wheelset or batch should we use? Choose {names}." if names else "There are no tap-test assets in this industry."

        baseline = TAP_BASELINE.fullmatch(text)
        start = START_CAPTURE.fullmatch(text)
        command = MACHINE_CHECK.match(text)
        if not baseline and not command and not start:
            return ""
        tap_requested = bool(baseline or (command and command.group("tap")))
        if tap_requested:
            assets = tap_assets
        direct = baseline or start
        target = (direct.group("asset") or "") if direct else text[command.end():]
        if target.lower() in {"", "it", "that", "this machine", "this coach"}:
            focused = assets.get(session.focus_asset or "")
            matches = [focused] if focused else list(assets.values()) if direct else []
        else:
            matches = match_assets(list(assets.values()), target)
            if baseline and (digits := re.findall(r"\d+", target)):
                matches = [asset for asset in matches if digits[-1] in re.findall(r"\d+", f"{asset['id']} {asset['name']}")]
                if not matches:
                    return f"I can't find that batch or wheelset. To register a new casting batch, say start a new batch {digits[-1]}."
        if len(matches) != 1:
            if start and not tap_requested:
                return "Which machine should I record? Say start listening to, followed by its name."
            if tap_requested:
                options = matches or list(assets.values())
                names = ", ".join(asset["name"] for asset in options[:4])
                return f"Which wheelset or batch? Choose {names}." if names else "There are no tap-test assets in this industry."
            return ""
        asset = matches[0]
        mode = "tap" if tap_requested else (asset.get("modes") or ["continuous"])[0]
        if mode == "tap" and (baseline or not asset.get("tap_reference_url")):
            return await self._record_tap_baseline(session, asset)
        result = await self.execute(session, "start_listening", {"asset_id": asset["id"], "mode": mode})
        if result.get("ok"):
            if mode == "tap":
                return f"{asset['name']} is ready. Tap each part once after the beep."
            return f"That's {asset['name']}. Hold the phone near it. Recording starts after the beep."
        if result.get("not_enrolled"):
            if start and start.group("action").lower() == "recording":
                enrolled = await self.execute(session, "start_listening", {
                    "asset_id": asset["id"], "mode": mode, "purpose": "enroll",
                })
                if enrolled.get("ok"):
                    return f"Recording the healthy baseline for {asset['name']}. Make sure it is running normally."
                return str(enrolled.get("message") or enrolled.get("error") or "I couldn't open the recorder.")
            return (f"{asset['name']} needs a healthy recording first. "
                    "When it's running normally, say start recording.")
        return str(result.get("message") or result.get("error") or "Tap Listen to machine to try again.")

    async def _record_casting_batch(self, session: Session, number: str) -> str:
        name = f"Casting batch {number}"
        asset = next((a for a in self.svc.state.assets.values() if a["name"].casefold() == name.casefold()), None)
        if asset is None:
            result = await self.execute(session, "register_asset", {
                "name": name, "asset_type": "casting", "line": self.svc.pack.line,
            })
            asset = self.svc.state.assets.get(result.get("asset_id", ""))
            if asset is None:
                return f"I couldn't register {name}. Say its number again to retry."
        session.awaiting_batch_number = False
        return await self._record_tap_baseline(session, asset)

    async def _record_tap_baseline(self, session: Session, asset: dict[str, Any]) -> str:
        session.tap_baseline_asset = asset["id"]
        result = await self.execute(session, "start_listening", {
            "asset_id": asset["id"], "mode": "tap", "purpose": "enroll",
        })
        if result.get("ok"):
            part = "wheel" if "wheel" in asset["type"] else "part"
            return f"Recording the baseline for {asset['name']}. Tap one known-good {part} after the beep."
        return str(result.get("message") or result.get("error") or "Open Tap test to try again.")

    def _select_tap_asset(self, session: Session, asset: dict[str, Any]) -> str:
        session.focus_asset = asset["id"]
        self.svc.state.sessions.setdefault(session.id, {})["focus"] = asset["id"]
        self.svc.bus.changed()
        if asset.get("tap_reference_url"):
            return f"{asset['name']} is selected. Say start recording to test it, or create a baseline to replace the reference."
        return f"{asset['name']} is selected. Say create a baseline when you have a known-good part ready."

    async def _carry_out(self, session: Session) -> list[str]:
        """Run every approved step that is still waiting, so a yes raises the job even if the model skips it."""
        svc = self.svc
        lines: list[str] = []
        for conf in svc.state.confirmations:
            if conf["session"] != session.id or conf["status"] != "approved" or conf.get("finalized"):
                continue
            asset = svc.state.assets.get(conf["asset_id"], {})
            analysis = svc.state.analyses.get(conf["asset_id"])
            batch = svc.state.tap_batches.get(conf["asset_id"])
            finding = plan_steps.finding_text(asset, analysis, batch)
            people = [p.name for p in svc.pack.people]
            for step in conf["steps"]:
                tool = step.get("tool")
                if step.get("status") != "next" or not tool:
                    continue
                args = plan_steps.args_for(asset, analysis, batch, svc.pack.vocabulary, people,
                                           svc.pack.fault_parts, tool, finding)
                if args is None:
                    continue
                result = await self.execute(session, tool, args)
                if result.get("error") or result.get("status") == "needs_confirmation":
                    lines.append(f"{step['text']} did not work")
                    continue
                try:
                    lines.append(followups.sentence(svc, tool, args, result) or step["text"])
                except Exception:
                    lines.append(step["text"])
        return lines

    async def _loop(self, session: Session, background: bool = False) -> str:
        tools = await self.tool_schemas()
        for _ in range(MAX_TOOL_ROUNDS):
            if background and session.preempt.is_set():
                return ""
            messages = [{"role": "system", "content": system_prompt(self.svc, session)}, *session.messages]
            try:
                res = await self._complete(session, background, messages, tools, tokens=2048)
            except BadRequestError as exc:
                # The provider rejected the request (often a tool schema). Answer from the plain text.
                log.error("LLM rejected the request for %s (answering without tools): %s", session.id, exc)
                return await self._plain(session, background, messages)
            except (APITimeoutError, APIConnectionError) as exc:
                log.error("LLM call failed for %s: %s", session.id, exc)
                return ""
            except APIError as exc:
                log.error("LLM call failed for %s: %s", session.id, exc)
                return await self._plain(session, background, messages)
            if res is None:
                return ""
            msg = res.choices[0].message
            text = message_text(msg.content)
            if not msg.tool_calls:
                if text:
                    return text
                # Gemini thinking can spend the whole token budget and leave the spoken text empty.
                log.warning("Empty model reply for %s (finish=%s); retrying without tools",
                            session.id, getattr(res.choices[0], "finish_reason", None))
                return await self._plain(session, background, messages, effort="minimal")
            # Keep provider extras (e.g. Gemini thought signatures) so the next call accepts the history.
            assistant = msg.model_dump(exclude_none=True)
            assistant.setdefault("content", "")
            session.add(assistant)
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await self.execute(session, call.function.name, args)
                session.add({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
        return "I've done several steps but need a moment. Ask me again what's next."

    async def _plain(self, session: Session, background: bool, messages: list[dict[str, Any]],
                     effort: str | None = None) -> str:
        # Tool-call history can be what was rejected, so keep only plain user/assistant text.
        plain = [m for m in messages if m["role"] in ("system", "user")
                 or (m["role"] == "assistant" and not m.get("tool_calls"))]
        try:
            res = await self._complete(session, background, plain, None, tokens=2048, effort=effort)
        except (APIError, BadRequestError) as exc:
            log.error("LLM call without tools also failed: %s", exc)
            return ""
        if res is None:
            return ""
        return message_text(res.choices[0].message.content)

    def _effort(self, override: str | None = None) -> str | None:
        """Gemini thinks by default and can return an empty reply. Keep that thinking small."""
        if self._effort_rejected:
            return None
        if override:
            return override
        if self.svc.settings.llm_reasoning_effort:
            return self.svc.settings.llm_reasoning_effort
        if "gemini" in self.svc.settings.llm_model.lower():
            return "low"
        return None

    async def _complete(self, session: Session, background: bool, messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None, *, tokens: int, effort: str | None = None):
        """One completion. Retries once if the provider rejects the token or reasoning field."""
        use_effort = self._effort(effort)
        token_key = self._token_key
        last_error: BadRequestError | None = None
        for _ in range(3):
            kwargs: dict[str, Any] = {
                "model": self.svc.settings.llm_model,
                "messages": messages,
                "temperature": 0.3,
                token_key: tokens,
            }
            if tools:
                kwargs["tools"] = tools
            if use_effort:
                kwargs["reasoning_effort"] = use_effort
            try:
                return await self._invoke(session, background, kwargs)
            except BadRequestError as exc:
                last_error = exc
                detail = str(exc).lower()
                if use_effort and ("reasoning_effort" in detail or "thinking" in detail):
                    self._effort_rejected = True
                    use_effort = None
                    continue
                if token_key == "max_tokens" and "max_tokens" in detail:
                    token_key = "max_completion_tokens"
                    self._token_key = token_key
                    continue
                raise
        if last_error:
            raise last_error
        return None

    async def _invoke(self, session: Session, background: bool, kwargs: dict[str, Any]):
        """One completion. A background turn is cancelled as soon as the worker speaks."""
        task = asyncio.create_task(self.svc.llm.chat.completions.create(**kwargs))
        if not background:
            return await task
        waiter = asyncio.create_task(session.preempt.wait())
        try:
            done, _pending = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not waiter.done():
                waiter.cancel()
        if task not in done:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return None
        return await task

    # --- tools -----------------------------------------------------------------------------
    async def execute(self, session: Session, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool under the risk policy. Never raises: failures come back as plain results."""
        svc = self.svc
        if followups.already_finished(svc, session.id, name):
            return {"already_done": True, "instruction": "Already done. Tell the worker and do not call it again."}
        tier = tier_for(svc.pack, name, args)
        if tier >= 2 and not session.is_granted(name):
            pending = confirmations.pending_for(svc, session.id)
            if pending is None or name not in pending["tools"]:
                asset_id = str(args.get("asset_id", session.focus_asset or "")).upper()
                action = followups.intent(svc, name, args)
                await confirmations.open_confirmation(svc, session, asset_id, f"Shall I {action}?",
                                                      [{"text": action[:1].upper() + action[1:], "tool": name}], [name])
            await svc.bus.emit("tool", session=session.id, name=name, status="needs_confirmation")
            return {"status": "needs_confirmation", "tier": tier,
                    "instruction": "This needs the worker's yes" + (" and a second approver" if tier >= 3 else "")
                    + ". Ask them now; do not repeat the call until they agree."}

        if args.get("asset_id"):
            session.focus_asset = str(args["asset_id"]).upper()
            svc.state.sessions.setdefault(session.id, {})["focus"] = session.focus_asset
        try:
            if name in LOCAL_TOOLS:
                result = await LOCAL_TOOLS[name](svc, session, args)
            else:
                args = followups.enrich(svc, session.id, name, args)
                result = await svc.enterprise.call(name, args)
        except ToolFailed as exc:
            detail = {"tool": name, "args": args, "error": str(exc), "tier": tier}
            if not followups.tick_plan_step(svc, session.id, name, False, None, detail):
                svc.state.add_timeline(f"Could not {name.replace('_', ' ')}: the system did not respond", "failed", detail)
            svc.bus.changed()
            return {"error": "The system did not respond after a retry. Explain this plainly and offer another way."}
        except Exception as exc:  # bad arguments or a bug: tell the LLM, keep the conversation alive
            log.exception("Tool %s failed", name)
            return {"error": f"That did not work ({exc.__class__.__name__}). Try different details or another way."}

        await followups.apply(svc, session.id, name, args, result, tier)
        if tier == 1:
            result = {**result, "note": "Mention this to the worker."}
        return result

    # --- delivery --------------------------------------------------------------------------
    async def say(self, session: Session, text: str, priority: str = "INTERRUPT") -> str | None:
        """Speak outside a user turn: through the Agora agent if a call is live, else as Murf audio in the app.
        Returns the audio URL when Murf was used."""
        svc = self.svc
        if session.kind == "voice":
            try:
                await svc.agents.speak(session.id, text, priority=priority)
                return None
            except Exception as exc:  # agent gone (idle timeout): fall back to Murf in the browser
                log.warning("Agent speak failed for %s (%s); using Murf audio", session.id, exc)
        try:
            audio = await svc.murf.synthesize(text, session.language, kind="reply", role=0)
        except Exception as exc:
            log.error("Murf reply failed: %s", exc)
            return None
        await svc.bus.emit("play_audio", target="session", session=session.id, url=audio["url"], text=text)
        return audio["url"]

    async def turn_and_say(self, session: Session, user_text: str | None = None, note: str | None = None) -> dict[str, Any]:
        reply = await self.run_turn(session, user_text=user_text, note=note)
        audio = await self.say(session, reply)
        return {"reply": reply, "audio_url": audio}

    def background(self, session: Session, note: str) -> None:
        """Run a turn from a system note and speak it, without blocking the caller."""
        async def run() -> None:
            try:
                reply = await self.run_turn(session, note=note, background=True)
                if reply:
                    await self.say(session, reply)
            except Exception:
                log.exception("Background turn failed for %s", session.id)

        asyncio.create_task(run())

    def remember_and_speak(self, session: Session, note: str, spoken: str) -> None:
        """Keep a sound result in the conversation and say it, without a tool loop that would block speech."""
        async def run() -> None:
            try:
                async with session.lock:
                    session.add({"role": "user", "content": f"{NOTE_PREFIX} {note}"})
                    session.add({"role": "assistant", "content": spoken})
                    self.svc.state.add_line(session.id, "agent", spoken)
                    self.svc.bus.changed()
                await self.say(session, spoken, priority="APPEND")
            except Exception:
                log.exception("Could not speak a result to %s", session.id)

        asyncio.create_task(run())
