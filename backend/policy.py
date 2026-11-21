"""Risk policy: which actions EarShot may take on its own and which need a yes.

Tier 0: run silently (lookups, scoring, logging)
Tier 1: run, then mention it (reserve a part, notify people)
Tier 2: needs the worker's spoken "yes" or a tap on Confirm
Tier 3: also needs a second approver (shut down a line, purchase above the limit)
"""

from __future__ import annotations

import re
from typing import Any

from packs import Pack

DEFAULT_TIER = 2  # unknown actions are treated as needing a yes

_YES = re.compile(
    r"^\s*(yes|yeah|yep|yup|ok|okay|sure|go ahead|do it|please do|approve|approved|confirm|confirmed|"
    r"haan|haa|han|haanji|ji haan|theek hai|thik hai|sari|seri|aamam|aama|"
    r"हाँ|हां|जी हाँ|ठीक है|ஆம்|சரி)\b",
    re.IGNORECASE,
)
_NO = re.compile(
    r"^\s*(no|nope|not now|don't|do not|wait|stop|cancel|nahi|nahin|mat karo|illai|vendam|"
    r"नहीं|मत|இல்லை|வேண்டாம்)\b",
    re.IGNORECASE,
)


def tier_for(pack: Pack, tool: str, args: dict[str, Any]) -> int:
    tier = pack.policy.tiers.get(tool, 0 if tool in LOCAL_TIER0 else DEFAULT_TIER)
    if tool == "request_purchase":
        total = int(args.get("quantity", 1)) * int(args.get("unit_cost_inr", 0))
        if total > pack.policy.purchase_limit_inr:
            return 3
    return tier


def spoken_decision(text: str) -> str | None:
    """'yes' / 'no' when the worker's words are a clear answer, else None."""
    cleaned = text.strip().strip(".!?,").lower()
    if _NO.match(cleaned):
        return "no"
    if _YES.match(cleaned):
        return "yes"
    return None


# Local (backend) tools never need confirmation.
LOCAL_TIER0 = {
    "start_listening",
    "analyze_sound",
    "enroll_baseline",
    "search_knowledge",
    "find_similar_cases",
    "assess_risk",
    "request_confirmation",
    "schedule_follow_up",
    "finish_tap_batch",
    "record_feedback",
}
