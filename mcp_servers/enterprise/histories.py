"""Past issues for each machine, including which numbered part they were on."""

from __future__ import annotations

import re
from typing import Any

_PART = re.compile(r"(?:part|wheel|position)\s*(\d+)", re.IGNORECASE)


def part_number(*texts: str) -> int | None:
    """The part or wheel number named in a job title or an inspection note."""
    for text in texts:
        found = _PART.search(text or "")
        if found:
            return int(found.group(1))
    return None


def build_histories(
    assets: dict[str, dict[str, Any]],
    work_orders: list[dict[str, Any]],
    inspections: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """One record per asset: last service, its own jobs, and inspections logged this shift."""
    out: dict[str, dict[str, Any]] = {}
    for asset_id, asset in assets.items():
        issues = []
        for order in work_orders:
            if str(order.get("asset_id", "")).upper() != asset_id.upper():
                continue
            issue = dict(order)
            if "part" not in issue:
                named = part_number(str(issue.get("title", "")), str(issue.get("summary", "")))
                if named is not None:
                    issue["part"] = named
            issues.append(issue)
        checks = []
        for entry in inspections:
            if str(entry.get("asset_id", "")).upper() != asset_id.upper():
                continue
            check = dict(entry)
            if "part" not in check:
                named = part_number(str(check.get("notes", "")))
                if named is not None:
                    check["part"] = named
            checks.append(check)
        out[asset_id] = {
            "last_serviced": asset.get("last_serviced", ""),
            "notes": asset.get("notes", ""),
            "status": asset.get("status", ""),
            "issues": issues,
            "inspections": checks,
        }
    return out
