"""EarShot mock enterprise systems as one MCP server (streamable HTTP).

Mock CMMS (work orders), stores inventory, asset register, people notifications, floor announcements and
shift reports. Data is seeded from data.json per industry pack and kept in memory: this is MOCK data for the
demo, not a real enterprise system. Tools prefixed `admin_` are for the EarShot backend, not for the LLM.

Run:  python server.py            (listens on $HOST:$PORT, default 0.0.0.0:8101, path /mcp; use HOST=:: on Railway)
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

DATA_FILE = Path(__file__).with_name("data.json")
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_env_file() -> None:
    """When run from the repo, pick up optional settings (e.g. JIRA_*) from the root .env. Real env vars win."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env_file()
from histories import build_histories, part_number  # noqa: E402
from jira_sync import Jira  # noqa: E402  (reads JIRA_* after .env is loaded)

jira = Jira()
SEED: dict[str, Any] = json.loads(DATA_FILE.read_text())

server = MCPServer(
    name="earshot-enterprise",
    instructions="Mock enterprise systems for EarShot: assets, work orders, inventory, notifications, reports.",
)


class Store:
    """In-memory state for the active pack."""

    def __init__(self) -> None:
        self.load("manufacturing")

    def load(self, pack: str) -> None:
        if pack not in SEED:
            raise ValueError(f"Unknown pack '{pack}'. Known: {', '.join(SEED)}")
        self.pack = pack
        data = copy.deepcopy(SEED[pack])
        self.assets: dict[str, dict[str, Any]] = data["assets"]
        self.work_orders: list[dict[str, Any]] = data["work_orders"]
        self.inventory: list[dict[str, Any]] = data["inventory"]
        self.reservations: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.announcements: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []
        self.inspections: list[dict[str, Any]] = []
        self.purchases: list[dict[str, Any]] = []
        self.failures: dict[str, int] = {}
        self._ids = itertools.count(1)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{2400 + next(self._ids)}"

    def maybe_fail(self, tool: str) -> None:
        """Injected failure for demoing error handling (see admin_inject_failure)."""
        left = self.failures.get(tool, 0)
        if left > 0:
            self.failures[tool] = left - 1
            raise RuntimeError(f"{tool}: the maintenance system did not respond (injected failure)")

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        return self.assets.get(asset_id.strip().upper())

    def find_part(self, part: str) -> dict[str, Any] | None:
        q = part.strip().lower()
        for item in self.inventory:
            if q in (item["code"].lower(), item["name"].lower()):
                return item
        scored = [
            (max((len(k) for k in item["keywords"] if k in q or q in k), default=0), item) for item in self.inventory
        ]
        scored = [s for s in scored if s[0] > 0]
        return max(scored, key=lambda s: s[0])[1] if scored else None


store = Store()


def _unknown(asset_id: str) -> dict[str, Any]:
    return {"ok": False, "message": f"There is no asset with id {asset_id}. Use identify_asset first."}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@server.tool()
def identify_asset(query: str) -> dict[str, Any]:
    """Find a machine or batch by id or spoken name (e.g. 'pump 14', 'P-14', 'coach 4401')."""
    store.maybe_fail("identify_asset")
    q = query.strip().lower()
    digits = re.findall(r"\d+", q)
    matches = []
    for asset_id, a in store.assets.items():
        hay = f"{asset_id} {a['name']} {a['type']}".lower()
        id_digits = re.findall(r"\d+", asset_id)
        if asset_id.lower() == q or a["name"].lower() == q:
            return {"found": True, "asset_id": asset_id, **a}
        if digits and id_digits and digits[-1] == id_digits[-1] and any(w in hay for w in q.split() if not w.isdigit()):
            matches.append((3, asset_id, a))
        elif digits and id_digits and digits[-1] == id_digits[-1]:
            matches.append((2, asset_id, a))
        elif q in hay:
            matches.append((1, asset_id, a))
    if not matches:
        return {"found": False, "message": f"No asset matches '{query}'."}
    matches.sort(key=lambda m: -m[0])
    best = [m for m in matches if m[0] == matches[0][0]]
    if len(best) > 1:
        return {"found": False, "ambiguous": [b[1] for b in best], "message": "More than one asset matches."}
    return {"found": True, "asset_id": best[0][1], **best[0][2]}


@server.tool()
def get_asset_history(asset_id: str) -> dict[str, Any]:
    """Status, last service and past work orders for an asset, plus past work orders on the same type of asset."""
    store.maybe_fail("get_asset_history")
    a = store.asset(asset_id)
    if a is None:
        return _unknown(asset_id)
    own = [w for w in store.work_orders if w["asset_id"] == asset_id.upper()]
    same_type_ids = {i for i, x in store.assets.items() if x["type"] == a["type"]}
    related = [w for w in store.work_orders if w["asset_id"] in same_type_ids and w["asset_id"] != asset_id.upper()]
    return {"asset_id": asset_id.upper(), **a, "work_orders": own, "same_type_work_orders": related}


@server.tool()
def check_inventory(part: str) -> dict[str, Any]:
    """Stock of a spare part in every warehouse. `part` can be a name ('bearing') or a stores code."""
    store.maybe_fail("check_inventory")
    item = store.find_part(part)
    if item is None:
        return {"found": False, "message": f"No spare part matches '{part}'."}
    total = sum(item["stock"].values())
    return {
        "found": True,
        "code": item["code"],
        "name": item["name"],
        "stock": item["stock"],
        "total": total,
        "in_stock": total > 0,
        "unit_cost_inr": item["unit_cost_inr"],
    }


@server.tool()
def reserve_part(part: str, quantity: int = 1, warehouse: str = "", work_order_id: str = "") -> dict[str, Any]:
    """Set spare parts aside for a job. Picks the first warehouse with stock unless `warehouse` is given."""
    store.maybe_fail("reserve_part")
    item = store.find_part(part)
    if item is None:
        return {"reserved": False, "message": f"No spare part matches '{part}'."}
    options = [warehouse] if warehouse else list(item["stock"])
    for wh in options:
        if item["stock"].get(wh, 0) >= quantity:
            item["stock"][wh] -= quantity
            res = {"id": store.next_id("RS"), "code": item["code"], "name": item["name"], "quantity": quantity,
                   "warehouse": wh, "work_order_id": work_order_id, "at": _now()}
            store.reservations.append(res)
            return {"reserved": True, **res, "left_in_warehouse": item["stock"][wh]}
    return {"reserved": False, "out_of_stock": True, "code": item["code"], "name": item["name"], "stock": item["stock"],
            "message": "Not enough stock in any warehouse."}


@server.tool()
async def create_work_order(
    asset_id: str, title: str, priority: str = "high", description: str = "", scheduled_for: str = "",
    evidence: str = "", approved_by: str = "",
) -> dict[str, Any]:
    """Raise a maintenance work order (repair job) in the CMMS. Also creates a Jira issue when Jira is configured."""
    store.maybe_fail("create_work_order")
    if store.asset(asset_id) is None:
        return _unknown(asset_id)
    wo = {"id": store.next_id("WO"), "asset_id": asset_id.upper(), "title": title, "priority": priority,
          "status": "scheduled" if scheduled_for else "open", "when": "now", "scheduled_for": scheduled_for,
          "summary": description, "approved_by": approved_by, "at": _now()}
    named = part_number(title, description, evidence)
    if named is not None:
        wo["part"] = named
    details = [description, f"What EarShot heard: {evidence}" if evidence else "",
               f"Scheduled for: {scheduled_for}" if scheduled_for else "",
               f"Approved by: {approved_by}" if approved_by else ""]
    wo.update(await jira.create(wo, details))
    store.work_orders.append(wo)
    return {"created": True, **wo}


@server.tool()
async def update_work_order(work_order_id: str, status: str, note: str = "") -> dict[str, Any]:
    """Move a work order through its stages: scheduled, in_progress, done or cancelled (synced to Jira if configured)."""
    store.maybe_fail("update_work_order")
    wo = next((w for w in store.work_orders if w["id"] == work_order_id.upper()), None)
    if wo is None:
        return {"ok": False, "message": f"No work order {work_order_id}."}
    if status not in ("open", "scheduled", "in_progress", "done", "cancelled"):
        return {"ok": False, "message": "Status must be open, scheduled, in_progress, done or cancelled."}
    wo["status"] = status
    if note:
        wo.setdefault("notes", []).append({"at": _now(), "note": note})
    wo.update(await jira.update(wo.get("jira_key", ""), status, note))
    return {"ok": True, **wo}


@server.tool()
def update_asset_status(asset_id: str, status: str, reason: str = "") -> dict[str, Any]:
    """Change an asset's status, e.g. 'out of service' (lockout), 'running', 'stop scheduled 22:00', 'sick'."""
    store.maybe_fail("update_asset_status")
    a = store.asset(asset_id)
    if a is None:
        return _unknown(asset_id)
    previous = a["status"]
    a["status"] = status
    a["status_reason"] = reason
    return {"updated": True, "asset_id": asset_id.upper(), "previous": previous, "status": status, "reason": reason}


@server.tool()
def quarantine_batch(asset_id: str, parts: list[int], reason: str = "") -> dict[str, Any]:
    """Put a batch (or specific parts) on hold so it is not used until quality decides."""
    store.maybe_fail("quarantine_batch")
    a = store.asset(asset_id)
    if a is None:
        return _unknown(asset_id)
    a["status"] = "on hold"
    a["held_parts"] = parts
    return {"quarantined": True, "asset_id": asset_id.upper(), "parts": parts, "reason": reason}


@server.tool()
def shutdown_line(line: str, reason: str) -> dict[str, Any]:
    """Shut down a whole production line. High impact: requires a second approver."""
    store.maybe_fail("shutdown_line")
    for a in store.assets.values():
        if a["line"].lower() == line.lower():
            a["status"] = "line shut down"
    return {"shutdown": True, "line": line, "reason": reason}


@server.tool()
def request_purchase(part: str, quantity: int, unit_cost_inr: int, reason: str = "") -> dict[str, Any]:
    """Raise a purchase request for parts that are not in stock."""
    store.maybe_fail("request_purchase")
    pr = {"id": store.next_id("PR"), "part": part, "quantity": quantity, "unit_cost_inr": unit_cost_inr,
          "total_inr": quantity * unit_cost_inr, "reason": reason, "status": "raised", "at": _now()}
    store.purchases.append(pr)
    return {"raised": True, **pr}


@server.tool()
def notify_people(people: list[str], message: str, urgency: str = "normal") -> dict[str, Any]:
    """Send a message to people by name (each is briefed in their own language by EarShot)."""
    store.maybe_fail("notify_people")
    sent = []
    for person in people:
        n = {"id": store.next_id("NT"), "person": person, "message": message, "urgency": urgency,
             "status": "sent", "reply": None, "at": _now()}
        store.notifications.append(n)
        sent.append(n)
    return {"sent": True, "notifications": sent}


@server.tool()
def record_reply(notification_id: str, reply: str) -> dict[str, Any]:
    """Record a recipient's reply to a notification (e.g. 'approved', 'declined', 'no stock')."""
    for n in store.notifications:
        if n["id"] == notification_id:
            n["reply"] = reply
            n["status"] = "replied"
            return {"recorded": True, **n}
    return {"recorded": False, "message": f"No notification {notification_id}"}


@server.tool()
def announce_on_floor(message: str, at: str = "now") -> dict[str, Any]:
    """Make a public-address announcement on the shop floor (EarShot voices it)."""
    store.maybe_fail("announce_on_floor")
    a = {"id": store.next_id("PA"), "message": message, "at": at, "logged": _now()}
    store.announcements.append(a)
    return {"announced": True, **a}


@server.tool()
def generate_report(summary: str) -> dict[str, Any]:
    """File the shift report (EarShot also reads it out for the next shift)."""
    store.maybe_fail("generate_report")
    r = {"id": store.next_id("SR"), "summary": summary, "at": _now(),
         "open_work_orders": [w["id"] for w in store.work_orders if w["status"] not in ("done", "cancelled", "closed")]}
    store.reports.append(r)
    return {"filed": True, **r}


@server.tool()
def log_inspection(asset_id: str, result: str, notes: str = "") -> dict[str, Any]:
    """Record a sound check or tap test result against an asset."""
    store.maybe_fail("log_inspection")
    if store.asset(asset_id) is None:
        return _unknown(asset_id)
    entry = {"id": store.next_id("IN"), "asset_id": asset_id.upper(), "result": result, "notes": notes, "at": _now()}
    named = part_number(notes)
    if named is not None:
        entry["part"] = named
    store.inspections.append(entry)
    return {"logged": True, **entry}


@server.tool()
def register_asset(name: str, asset_type: str, line: str = "") -> dict[str, Any]:
    """Add a new machine to the asset register (used when a worker adds a machine by voice)."""
    store.maybe_fail("register_asset")
    prefix = re.sub(r"[^A-Z]", "", asset_type.upper())[:2] or "AS"
    asset_id = f"{prefix}-{next(store._ids) + 100}"
    store.assets[asset_id] = {"name": name, "type": asset_type.lower(), "line": line, "status": "running",
                              "last_serviced": "new"}
    return {"registered": True, "asset_id": asset_id, **store.assets[asset_id]}


@server.tool()
def list_open_work_orders() -> dict[str, Any]:
    """Work orders that are not finished (the worker's open jobs)."""
    return {"work_orders": [w for w in store.work_orders if w["status"] not in ("done", "cancelled", "closed")]}


@server.tool()
def admin_histories() -> dict[str, Any]:
    """Backend only: past issues and inspections for every asset, for the dashboard."""
    return {"assets": build_histories(store.assets, store.work_orders, store.inspections)}


@server.tool()
def admin_load_pack(pack: str) -> dict[str, Any]:
    """Backend only: reset mock data to the seed for an industry pack."""
    store.load(pack)
    return {"loaded": pack, "assets": list(store.assets)}


@server.tool()
def admin_integrations() -> dict[str, Any]:
    """Backend only: which optional integrations are configured."""
    return {"jira": jira.enabled, "jira_project": jira.project if jira.enabled else None}


@server.tool()
async def admin_jira_connection() -> dict[str, Any]:
    """Backend only: check whether the configured account can create Jira issues."""
    return await jira.connection_status()


@server.tool()
def admin_inject_failure(tool: str, times: int = 1) -> dict[str, Any]:
    """Backend only: make the next `times` calls to `tool` fail, to demo error handling."""
    store.failures[tool] = times
    return {"tool": tool, "will_fail": times}


def main() -> None:
    port = int(os.environ.get("PORT", "8101"))
    host = os.environ.get("HOST", "0.0.0.0")
    server.run(
        "streamable-http",
        host=host,
        port=port,
        # Reached over a private network (localhost / Railway private networking); Host headers vary.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


if __name__ == "__main__":
    main()
