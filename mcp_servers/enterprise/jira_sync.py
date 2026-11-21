"""Optional Jira Cloud sync for work orders (REST API v3).

Enabled only when JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN and JIRA_PROJECT are all set. Otherwise every call is
a no-op and the mock CMMS stays the only record. Jira errors never fail a tool: they come back as `jira_error`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("earshot.jira")

REQUIRED = ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT")
PRIORITY = {"emergency": "Highest", "urgent": "Highest", "high": "High", "medium": "Medium", "normal": "Medium",
            "routine": "Low", "planned": "Low", "low": "Low"}
# EarShot job status -> Jira status category key (works with any workflow's status names)
CATEGORY = {"scheduled": "new", "open": "new", "in_progress": "indeterminate", "done": "done", "cancelled": "done"}


def _adf(paragraphs: list[str]) -> dict[str, Any]:
    """Plain paragraphs as an Atlassian Document Format document."""
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs if p.strip()
    ]}


class Jira:
    def __init__(self) -> None:
        values = {k: os.environ.get(k, "").strip() for k in REQUIRED}
        missing = [k for k, v in values.items() if not v]
        self.enabled = not missing
        if missing and len(missing) < len(REQUIRED):
            log.warning("Jira sync is off: missing %s", ", ".join(missing))
        if not self.enabled:
            return
        self.site = values["JIRA_SITE"].rstrip("/")
        if not self.site.startswith("http"):
            self.site = f"https://{self.site}"
        self.project = values["JIRA_PROJECT"]
        self.issue_type = os.environ.get("JIRA_ISSUE_TYPE", "Task")
        self._auth = (values["JIRA_EMAIL"], values["JIRA_API_TOKEN"])
        log.info("Jira sync on: project %s at %s", self.project, self.site)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"{self.site}/rest/api/3", auth=self._auth, timeout=8.0,
                                 headers={"Accept": "application/json"})

    def url(self, key: str) -> str:
        return f"{self.site}/browse/{key}"

    async def create(self, wo: dict[str, Any], details: list[str]) -> dict[str, Any]:
        if not self.enabled:
            return {}
        fields: dict[str, Any] = {
            "project": {"key": self.project},
            "issuetype": {"name": self.issue_type},
            "summary": f"{wo['asset_id']}: {wo['title']}"[:250],
            "labels": ["earshot", wo["asset_id"].replace(" ", "-")],
            "description": _adf([f"Raised by EarShot as {wo['id']}.", *details]),
        }
        priority = PRIORITY.get(str(wo.get("priority", "")).lower())
        try:
            async with self._client() as c:
                res = await c.post("/issue", json={"fields": {**fields, "priority": {"name": priority}}} if priority
                                   else {"fields": fields})
                if res.status_code == 400 and priority:  # priority not on this project's create screen
                    res = await c.post("/issue", json={"fields": fields})
                res.raise_for_status()
                key = res.json()["key"]
            return {"jira_key": key, "jira_url": self.url(key)}
        except Exception as exc:
            log.warning("Jira create failed: %s", exc)
            return {"jira_error": "Jira did not accept the ticket; it is saved in the maintenance system."}

    async def update(self, key: str, status: str, note: str) -> dict[str, Any]:
        if not self.enabled or not key:
            return {}
        try:
            async with self._client() as c:
                if note:
                    (await c.post(f"/issue/{key}/comment", json={"body": _adf([note])})).raise_for_status()
                target = CATEGORY.get(status)
                if target:
                    res = await c.get(f"/issue/{key}/transitions")
                    res.raise_for_status()
                    for t in res.json().get("transitions", []):
                        if t.get("to", {}).get("statusCategory", {}).get("key") == target:
                            (await c.post(f"/issue/{key}/transitions", json={"transition": {"id": t["id"]}})).raise_for_status()
                            break
            return {"jira_key": key, "jira_url": self.url(key)}
        except Exception as exc:
            log.warning("Jira update of %s failed: %s", key, exc)
            return {"jira_key": key, "jira_error": "Jira did not update; the maintenance system has the change."}
