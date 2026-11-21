"""Connects the orchestrator to the enterprise MCP server (streamable HTTP).

Tools are discovered with `list_tools` and offered to the LLM in OpenAI function format (admin_* tools are
kept for the backend). Each call retries once before reporting a plain-language failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp import Client

log = logging.getLogger("earshot.mcp")

ADMIN_PREFIX = "admin_"


class ToolFailed(RuntimeError):
    pass


def clean_schema(schema: Any) -> Any:
    """Strip JSON-schema details Gemini's function calling rejects (titles, $defs noise, nullable anyOf)."""
    if isinstance(schema, dict):
        if "anyOf" in schema:
            options = [o for o in schema["anyOf"] if o.get("type") != "null"]
            if len(options) == 1:
                merged = {**{k: v for k, v in schema.items() if k != "anyOf"}, **options[0]}
                return clean_schema(merged)
        return {
            k: clean_schema(v)
            for k, v in schema.items()
            if k not in ("title", "additionalProperties", "$schema", "default")
        }
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


def to_openai(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI function format. Tools without inputs get no `parameters` at all: Gemini rejects an object schema
    with empty `properties`."""
    fn: dict[str, Any] = {"name": name, "description": description}
    params = clean_schema(input_schema)
    if params.get("properties"):
        fn["parameters"] = params
    return {"type": "function", "function": fn}


class EnterpriseTools:
    def __init__(self, url: str) -> None:
        self._url = url
        self._schemas: list[dict[str, Any]] | None = None

    async def schemas(self) -> list[dict[str, Any]]:
        """OpenAI-format tool schemas for every non-admin MCP tool (cached)."""
        if self._schemas is None:
            async with Client(self._url) as client:
                listed = await client.list_tools()
            self._schemas = [to_openai(t.name, t.description or t.name, t.input_schema)
                             for t in listed.tools if not t.name.startswith(ADMIN_PREFIX)]
            log.info("Loaded %d enterprise tools from MCP", len(self._schemas))
        return self._schemas

    async def names(self) -> set[str]:
        return {s["function"]["name"] for s in await self.schemas()}

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        last_error = ""
        for attempt in (1, 2):
            try:
                async with Client(self._url, read_timeout_seconds=20) as client:
                    result = await client.call_tool(name, arguments)
                if not result.is_error:
                    if isinstance(result.structured_content, dict):
                        return result.structured_content
                    text = "".join(getattr(c, "text", "") for c in result.content)
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"result": text}
                last_error = "".join(getattr(c, "text", "") for c in result.content) or "tool error"
            except Exception as exc:  # network or protocol failure
                last_error = str(exc) or exc.__class__.__name__
            log.warning("MCP %s failed (attempt %d): %s", name, attempt, last_error)
            if attempt == 1:
                await asyncio.sleep(0.4)
        raise ToolFailed(last_error)
