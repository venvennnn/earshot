"""Murf Falcon client: voice lookup and direct synthesis, with latency measured on every call.

Used directly (not through Agora) for multilingual alert briefings, floor announcements, the spoken
shift report, and for speaking results when no voice call is active.

API facts (Murf's official SDK v2.3.0 and Murf's Falcon example): auth header `api-key`;
`POST {region}/v1/speech/stream` with `voice_id`, `text`, `locale`, `model` (e.g. "falcon-2.1"), `format`,
`sampleRate`, `channelType` streams audio bytes; `GET https://api.murf.ai/v1/speech/voices` lists voices
(`voiceId`, `locale`, `displayName`, `gender`, `supportedLocales`). Voice IDs may be a full ID or an actor name.
"""

from __future__ import annotations

import logging
import statistics
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import httpx

from config import Settings
from speech_text import pick_voice, voice_locales

log = logging.getLogger("earshot.murf")

MURF_API_BASE = "https://api.murf.ai"  # SDK default host for account-level calls such as the voice list
LOCALES = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN"}
FALLBACK_LOCALES = {"en-IN": ["en-US", "en-UK"]}


class MurfError(RuntimeError):
    pass


class LatencyMetrics:
    """Measured latencies: Murf time-to-first-audio (every direct call) and LLM time-to-reply."""

    def __init__(self) -> None:
        self.murf: deque[dict[str, Any]] = deque(maxlen=50)
        self.llm: deque[float] = deque(maxlen=50)

    def add_murf(self, kind: str, locale: str, ttfa: float, total: float, chars: int) -> None:
        self.murf.append({"kind": kind, "locale": locale, "ttfa_s": round(ttfa, 3), "total_s": round(total, 3),
                          "chars": chars, "at": time.time()})

    def add_llm(self, seconds: float) -> None:
        self.llm.append(round(seconds, 3))

    def summary(self) -> dict[str, Any]:
        ttfa = [m["ttfa_s"] for m in self.murf]
        murf_med = statistics.median(ttfa) if ttfa else None
        llm_med = statistics.median(self.llm) if self.llm else None
        voice_reply = round(murf_med + llm_med, 2) if murf_med is not None and llm_med is not None else None
        return {
            "murf_ttfa_median_s": murf_med,
            "llm_reply_median_s": llm_med,
            "voice_reply_s": voice_reply,  # LLM reply time + Murf first audio, both measured
            "murf_calls": len(ttfa),
            "llm_calls": len(self.llm),
            "recent": list(self.murf)[-10:],
        }


class MurfClient:
    def __init__(self, settings: Settings, media_dir: Path, metrics: LatencyMetrics) -> None:
        self._settings = settings
        self._media = media_dir / "tts"
        self._media.mkdir(parents=True, exist_ok=True)
        self.metrics = metrics
        self._http = httpx.AsyncClient(
            headers={"api-key": settings.murf_api_key.get_secret_value()},
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self._voices: list[dict[str, Any]] | None = None
        self._chosen: dict[tuple[Any, ...], str] = {}

    async def close(self) -> None:
        await self._http.aclose()

    # --- voices ----------------------------------------------------------------------------
    async def _get_voices(self, params: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.get(f"{MURF_API_BASE}/v1/speech/voices", params=params)
        except httpx.HTTPError as exc:
            raise MurfError(f"Could not reach Murf: {exc}") from exc

    async def voices(self) -> list[dict[str, Any]]:
        if self._voices is None:
            res = await self._get_voices({"model": self._settings.murf_model})
            if res.status_code == 400:  # the voice list may not accept this model filter; list all voices instead
                log.warning("Murf rejected the voice filter (%s); listing all voices", res.text[:200])
                res = await self._get_voices({})
            if res.is_error:
                raise MurfError(f"Could not list Murf voices ({res.status_code}): {res.text[:300]}")
            self._voices = list(res.json())
            log.info("Loaded %d Murf voices", len(self._voices))
        return self._voices

    async def voice_for(self, locale: str, index: int = 0) -> tuple[str, str]:
        """(voice_id, locale) for `locale`; `index` gives distinct voices for different roles."""
        key = (locale, index)
        if key in self._chosen:
            return self._chosen[key], locale
        voices = await self.voices()
        for loc in [locale, *FALLBACK_LOCALES.get(locale, [])]:
            picked = pick_voice(voices, [loc], index)
            if picked:
                voice, _chosen_locale = picked
                self._chosen[key] = voice
                log.info("Murf voice for %s (role %d): %s", loc, index, voice)
                return voice, loc
        raise MurfError(f"Murf has no voice for {locale}.")

    async def voice_for_locales(self, locales: list[str], prefer: str, index: int = 0) -> tuple[str, str]:
        """One voice that can speak every locale. `prefer` is the locale used for this utterance."""
        key = ("+".join(locales), prefer, index)
        if key in self._chosen:
            voice = self._chosen[key]
            return voice, self._locale_for(voice, prefer, locales[0] if locales else prefer)
        voices = await self.voices()
        picked = pick_voice(voices, locales, index)
        if not picked:
            return await self.voice_for(prefer, index)
        voice, fallback = picked
        self._chosen[key] = voice
        locale = self._locale_for(voice, prefer, fallback)
        log.info("Murf voice for %s (role %d): %s (%s)", "+".join(locales), index, voice, locale)
        return voice, locale

    def _locale_for(self, voice_id: str, prefer: str, fallback: str) -> str:
        for voice in self._voices or []:
            vid = str(voice.get("voiceId") or voice.get("voice_id") or "")
            if vid == voice_id:
                codes = voice_locales(voice)
                if not codes or prefer in codes:
                    return prefer
                return fallback if fallback in codes else sorted(codes)[0]
        return prefer

    # --- synthesis -------------------------------------------------------------------------
    async def synthesize(self, text: str, language: str = "en", kind: str = "speech", role: int = 1) -> dict[str, Any]:
        """Stream Falcon audio for `text` into an MP3 file. Returns its URL and measured latency."""
        locale = LOCALES.get(language, language)
        voice, locale = await self.voice_for(locale, role)
        body = {
            "voice_id": voice,
            "text": text,
            "locale": locale,
            "model": self._settings.murf_model,
            "format": "MP3",
            "sampleRate": 24000,
            "channelType": "MONO",
        }
        url = f"{self._settings.murf_region_url.rstrip('/')}/v1/speech/stream"
        name = f"{kind}-{uuid.uuid4().hex[:10]}.mp3"
        started = time.perf_counter()
        ttfa: float | None = None
        try:
            async with self._http.stream("POST", url, json=body) as res:
                if res.is_error:
                    detail = (await res.aread()).decode(errors="replace")[:300]
                    raise MurfError(f"Murf synthesis failed ({res.status_code}): {detail}")
                with open(self._media / name, "wb") as f:
                    async for chunk in res.aiter_bytes():
                        if chunk and ttfa is None:
                            ttfa = time.perf_counter() - started
                        f.write(chunk)
        except httpx.HTTPError as exc:
            raise MurfError(f"Could not reach Murf: {exc}") from exc
        total = time.perf_counter() - started
        self.metrics.add_murf(kind, locale, ttfa or total, total, len(text))
        log.info("Murf %s %s: first audio %.2fs, total %.2fs", kind, locale, ttfa or total, total)
        return {"url": f"/media/tts/{name}", "voice": voice, "locale": locale,
                "ttfa_s": round(ttfa or total, 3), "total_s": round(total, 3)}
