"""Plain helpers for what EarShot hears and what it says when the model does not answer.

Speech recognition listens in English, Hindi and Tamil together. A voice is usable for the
live call only when it can speak all three. If the model returns nothing, the worker still
gets a short answer about the machines on this line instead of an apology.
"""

from __future__ import annotations

import re
from typing import Any

SPEECH_LOCALES = ("en-IN", "hi-IN", "ta-IN")

# Words that name a machine even when the worker says them in Hindi or Tamil.
_KIND = {
    "pump": ("pump", "पंप", "पंंप", "பம்பு"),
    "coach": ("coach", "कोच", "रेल", "கோச்", "ரயில்"),
    "casting": ("casting", "batch", "कास्टिंग", "காஸ்டிங்"),
    "conveyor": ("conveyor", "कन्वेयर", "கன்வேயர்"),
    "compressor": ("compressor", "कंप्रेसर", "கம்ப்ரசர்"),
    "motor": ("motor", "मोटर", "மோட்டார்"),
    "generator": ("generator", "जनरेटर", "ஜெனரேட்டர்"),
    "wheel": ("wheel", "पहिया", "சக்கரம்"),
}
_ALIAS = {word: kind for kind, words in _KIND.items() for word in words}

_SKIP = {
    "the", "a", "an", "of", "to", "for", "and", "we", "are", "is", "it", "this", "that",
    "checking", "check", "machine", "please", "what", "huh", "sorry", "again", "hello", "hi",
    "on", "in", "my", "our", "i", "am", "ok", "okay",
}

_HERE = {
    "en": "I'm here, {worker}. Which machine are we checking?",
    "hi": "मैं हूँ, {worker}. कौन सी मशीन चेक करनी है?",
    "ta": "நான் இருக்கிறேன், {worker}. எந்த இயந்திரத்தை பார்க்கலாம்?",
}
_MISSING = {
    "en": "I don't have that on this line. I can check {names}.",
    "hi": "यह मशीन इस लाइन पर नहीं है। मैं {names} चेक कर सकता हूँ।",
    "ta": "இந்த இயந்திரம் இந்த லைனில் இல்லை. நான் {names} பார்க்கலாம்.",
}
_WHICH = {
    "en": "Which one, {names}?",
    "hi": "कौन सी, {names}?",
    "ta": "எது, {names}?",
}
_LISTEN = {
    "en": "That's {name}. Hold the phone near it and I'll listen.",
    "hi": "यह {name} है। फोन को पास रखो, मैं सुनता हूँ।",
    "ta": "இது {name}. போனை அருகில் வையுங்கள், நான் கேட்கிறேன்.",
}
_TAP = {
    "en": "That's {name}. Tap each part near the phone, then say finish.",
    "hi": "यह {name} है। हर हिस्से को फोन के पास टैप करो, फिर finish कहो।",
    "ta": "இது {name}. ஒவ்வொரு பாகத்தையும் போன் அருகில் தட்டுங்கள், பிறகு finish சொல்லுங்கள்.",
}


def asr_languages(primary: str) -> list[str]:
    """Primary language first, then the other two. A list makes Agora use voice-activity end of speech."""
    first = primary if primary in SPEECH_LOCALES else "en-IN"
    return [first, *[loc for loc in SPEECH_LOCALES if loc != first]]


def language_update(text: str) -> str | None:
    """Language to keep for the rest of the call. A bare 'what?' does not switch it back to English."""
    heard = detect_language(text)
    if heard is None or (heard == "en" and _is_bare(text)):
        return None
    return heard


def detect_language(text: str) -> str | None:
    """en, hi or ta from the script the worker used. Latin text stays English."""
    hindi = len(re.findall(r"[\u0900-\u097F]", text))
    tamil = len(re.findall(r"[\u0B80-\u0BFF]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if hindi == tamil == latin == 0:
        return None
    if hindi > tamil and hindi >= latin:
        return "hi"
    if tamil > hindi and tamil >= latin:
        return "ta"
    if latin:
        return "en"
    return "hi" if hindi >= tamil else "ta"


def message_text(content: Any) -> str:
    """Spoken text from an OpenAI message, including a list of content parts. Skips thinking parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [_part_text(part) for part in content]
        return " ".join(part for part in parts if part).strip()
    return str(content).strip()


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part.strip()
    if isinstance(part, dict):
        if part.get("type") in {"thought", "reasoning"} or part.get("thought"):
            return ""
        return str(part.get("text") or "").strip()
    if getattr(part, "type", None) in {"thought", "reasoning"} or getattr(part, "thought", None):
        return ""
    return str(getattr(part, "text", "") or "").strip()


def voice_locales(voice: dict[str, Any]) -> set[str]:
    """Locale codes a Murf voice can speak. Catalog strings look like 'hi-IN (Hindi - India)'."""
    found: set[str] = set()
    for key in ("locale", "voiceLocale"):
        value = voice.get(key)
        if isinstance(value, str) and value:
            found.add(value.split()[0])
    raw = voice.get("supportedLocales")
    if raw is None:
        raw = voice.get("supported_locales") or []
    if isinstance(raw, dict):
        raw = list(raw.keys())
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                found.add(item.split()[0])
            elif isinstance(item, dict):
                code = item.get("locale") or item.get("code") or item.get("id")
                if code:
                    found.add(str(code).split()[0])
    return found


def pick_voice(voices: list[dict[str, Any]], locales: list[str], index: int = 0) -> tuple[str, str] | None:
    """A voice that supports every locale. One locale prefers a native voice, same as before."""
    wanted = [str(loc) for loc in locales if loc]
    if not wanted:
        return None
    usable: list[dict[str, Any]] = []
    for voice in voices:
        vid = voice.get("voiceId") or voice.get("voice_id")
        if not vid:
            continue
        if all(loc in voice_locales(voice) for loc in wanted):
            usable.append(voice)
    if not usable and len(wanted) > 1:
        for name in ("Anisha", "Pooja", "Samar", "Chirag", "Jaya", "Neeta"):
            for voice in voices:
                vid = str(voice.get("voiceId") or voice.get("voice_id") or "")
                if vid.lower() == name.lower() or vid.lower().endswith("-" + name.lower()):
                    usable.append(voice)
                    break
            if usable:
                break
    if not usable:
        return None
    if len(wanted) == 1:
        native = [voice for voice in usable if str(voice.get("locale") or voice.get("voiceLocale") or "").split()[0] == wanted[0]]
        pool = native or usable
    else:
        pool = usable
    pool = sorted(pool, key=lambda voice: str(voice.get("voiceId") or voice.get("voice_id")))
    chosen = pool[index % len(pool)]
    vid = str(chosen.get("voiceId") or chosen.get("voice_id"))
    codes = voice_locales(chosen)
    locale = wanted[0] if not codes or wanted[0] in codes else sorted(codes)[0]
    return vid, locale


def offline_reply(assets: list[dict[str, Any]], text: str, *, language: str = "en", worker: str = "") -> str:
    """A short spoken answer from the machines on this line, in the worker's language."""
    heard = detect_language(text)
    if heard and not _is_bare(text):
        lang = heard
    else:
        lang = language if language in _HERE else (heard or "en")
    matches = match_assets(assets, text)
    if _is_bare(text):
        return _HERE[lang].format(worker=worker or "there")
    if not matches:
        return _MISSING[lang].format(names=_join([a.get("name") or a.get("id") for a in assets][:4], lang))
    if len(matches) > 1:
        return _WHICH[lang].format(names=_join([a.get("name") or a.get("id") for a in matches][:4], lang))
    asset = matches[0]
    name = str(asset.get("name") or asset.get("id"))
    modes = asset.get("modes") or []
    template = _TAP if "tap" in modes else _LISTEN
    return template[lang].format(name=name)


def match_assets(assets: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Assets the words could mean. An id wins; a shared type asks which one."""
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    digits = re.findall(r"\d+", text.lower())
    words = _words(text)
    if not words and not digits and not compact:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for asset in assets:
        asset_id = str(asset.get("id") or "")
        hay = f"{asset_id} {asset.get('name', '')} {asset.get('type', '')}".lower()
        hay_kinds = set(_words(hay))
        score = 0
        id_compact = re.sub(r"[^a-z0-9]", "", asset_id.lower())
        if id_compact and id_compact in compact:
            score = 5
        elif words and any(word in hay_kinds or word in hay for word in words):
            id_digits = re.findall(r"\d+", asset_id)
            if digits and id_digits and digits[-1] == id_digits[-1]:
                score = 4
            elif not digits:
                score = 2
        elif digits and not words:
            id_digits = re.findall(r"\d+", asset_id)
            if id_digits and digits[-1] == id_digits[-1]:
                score = 3
        if score:
            scored.append((score, asset))
    if not scored:
        return []
    best = max(score for score, _asset in scored)
    return [asset for score, asset in scored if score == best]


def _words(text: str) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[a-z0-9\u0900-\u097F\u0B80-\u0BFF]+", text.lower()):
        letters = re.sub(r"\d+", "", token)
        word = letters or token
        if word in _SKIP or (len(word) < 3 and word not in _ALIAS):
            continue
        kind = _ALIAS.get(word)
        found.append(kind or word)
    return found


def _is_bare(text: str) -> bool:
    kept = re.sub(r"[^a-z\u0900-\u097F\u0B80-\u0BFF]+", " ", text.lower()).split()
    useful = [word for word in kept if word not in _SKIP]
    return not useful


def _join(names: list[Any], language: str) -> str:
    clean = [str(name) for name in names if name]
    if not clean:
        return "the machines on this line" if language == "en" else "इन मशीनों" if language == "hi" else "இந்த இயந்திரங்கள்"
    if len(clean) == 1:
        return clean[0]
    if language == "en":
        return ", ".join(clean[:-1]) + ", or " + clean[-1]
    return ", ".join(clean)
