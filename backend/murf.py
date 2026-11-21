"""Murf Falcon client.

Phase 2 scope: pick voices from Murf's own voice list (never hard-coded guesses) and cache
the choice per locale. Direct synthesis (alerts, announcements, shift report) is added later.

API facts (from Murf's official SDK, v2.3.0): auth header `api-key`; `GET /v1/speech/voices?model=FALCON`
returns objects with `voiceId`, `locale`, `displayName`, `gender`, `supportedLocales`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import Settings

log = logging.getLogger("earshot.murf")

FALCON = "FALCON"


class MurfError(RuntimeError):
    pass


class MurfClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.murf_region_url.rstrip("/"),
            headers={"api-key": settings.murf_api_key.get_secret_value()},
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        self._voices: list[dict[str, Any]] | None = None
        self._chosen: dict[str, str] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def voices(self) -> list[dict[str, Any]]:
        if self._voices is None:
            try:
                res = await self._http.get("/v1/speech/voices", params={"model": FALCON})
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise MurfError(f"Could not list Murf voices: {exc}") from exc
            self._voices = list(res.json())
            log.info("Loaded %d Murf Falcon voices", len(self._voices))
        return self._voices

    async def voice_for(self, locale: str) -> str:
        """A Falcon voice ID for `locale`: native voices first, then voices that support it."""
        if locale in self._chosen:
            return self._chosen[locale]
        voices = await self.voices()
        native = sorted(v["voiceId"] for v in voices if v.get("locale") == locale and v.get("voiceId"))
        multi = sorted(
            v["voiceId"] for v in voices if locale in (v.get("supportedLocales") or {}) and v.get("voiceId")
        )
        candidates = native or multi
        if not candidates:
            raise MurfError(f"Murf has no Falcon voice for {locale}.")
        self._chosen[locale] = candidates[0]
        log.info("Murf voice for %s: %s", locale, candidates[0])
        return candidates[0]
