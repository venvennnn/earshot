import json
import unittest
from unittest.mock import patch

import httpx

from jira_sync import Jira


class JiraSyncTest(unittest.IsolatedAsyncioTestCase):
    def configure(self, handler):
        with patch.dict("os.environ", {
            "JIRA_SITE": "example.atlassian.net", "JIRA_EMAIL": "demo@example.com",
            "JIRA_API_TOKEN": "test-token", "JIRA_PROJECT": "EAR", "JIRA_ISSUE_TYPE": "Task",
        }, clear=True):
            jira = Jira()
        jira._client = lambda: httpx.AsyncClient(
            base_url=f"{jira.site}/rest/api/3", transport=httpx.MockTransport(handler)
        )
        return jira

    async def test_check_is_read_only_and_verifies_project_permission(self):
        def handle(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/rest/api/3/mypermissions")
            self.assertEqual(request.url.params["projectKey"], "EAR")
            return httpx.Response(200, json={"permissions": {"CREATE_ISSUES": {"havePermission": True}}})

        self.assertEqual(await self.configure(handle).connection_status(), {"status": "connected", "project": "EAR"})

    async def test_check_reports_denied_permission(self):
        jira = self.configure(lambda request: httpx.Response(
            200, json={"permissions": {"CREATE_ISSUES": {"havePermission": False}}}
        ))
        self.assertEqual((await jira.connection_status())["status"], "error")

    async def test_work_order_creates_project_ticket(self):
        def handle(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/rest/api/3/issue")
            fields = json.loads(request.content)["fields"]
            self.assertEqual(fields["project"], {"key": "EAR"})
            self.assertEqual(fields["summary"], "P-14: Check bearing")
            return httpx.Response(201, json={"key": "EAR-42"})

        result = await self.configure(handle).create(
            {"id": "WO-2401", "asset_id": "P-14", "title": "Check bearing"}, ["Replace if worn."]
        )
        self.assertEqual(result, {"jira_key": "EAR-42", "jira_url": "https://example.atlassian.net/browse/EAR-42"})

    async def test_unconfigured_connection_lists_settings(self):
        with patch.dict("os.environ", {}, clear=True):
            jira = Jira()
        result = await jira.connection_status()
        self.assertEqual(result["status"], "not_configured")
        self.assertIn("JIRA_API_TOKEN", result["missing"])
