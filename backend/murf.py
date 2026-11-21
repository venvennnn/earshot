"""Murf Falcon client.

Phase 2 scope: pick voices from Murf's own voice list (never hard-coded guesses) and cache
the choice per locale. Direct synthesis (alerts, announcements, shift report) is added later.

API facts (from Murf's official SDK, v2.3.0): auth header `api-key`; `GET /v1/speech/voices?model=FALCON`
on the default API host returns objects with `voiceId`, `locale`, `displayName`, `gender`, `supportedLocales`.
The regional host (MURF_REGION_URL, e.g. global.api.murf.ai) is used for low-latency synthesis.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import Settings

log = logging.getLogger("earshot.murf")

FALCON = "FALCON"
MURF_API_BASE = "https://api.murf.ai"  # SDK default host for account-level calls such as the voice list


class MurfError(RuntimeError):
    pass


class MurfClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(
            headers={"api-key": settings.murf_api_key.get_secret_value()},
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        self._voices: list[dict[str, Any]] | None = None
        self._chosen: dict[str, str] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def _get_voices(self, params: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.get(f"{MURF_API_BASE}/v1/speech/voices", params=params)
        except httpx.HTTPError as exc:
            raise MurfError(f"Could not reach Murf: {exc}") from exc

    async def voices(self) -> list[dict[str, Any]]:
        if self._voices is None:
            res = await self._get_voices({"model": FALCON})
            if res.status_code == 400:  # some accounts reject the model filter; list all voices instead
                log.warning("Murf rejected the Falcon voice filter (%s); listing all voices", res.text[:200])
                res = await self._get_voices({})
            if res.is_error:
                raise MurfError(f"Could not list Murf voices ({res.status_code}): {res.text[:300]}")
            self._voices = list(res.json())
            log.info("Loaded %d Murf voices", len(self._voices))
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
