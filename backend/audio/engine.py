"""EarShot's ear: compare a machine's sound with its enrolled healthy sound. No training required.

Model: LAION CLAP (laion/clap-htsat-unfused), loaded once at startup, 48 kHz mono input.
- enroll:  10 s of healthy sound -> 1 s windows (50% overlap) -> L2-normalised CLAP embeddings ->
           mean vector + distribution of each window's cosine distance to the mean.
- score:   median window distance to the baseline mean, z-scored against enrollment, logistic -> 0..1.
- label:   zero-shot CLAP against "the sound of a <type> with <fault>" prompts from the pack, blended with
           nearest-neighbour votes from the labeled case library. Always presented as a suggestion.
- tap:     per-tap ring decay (to -20 dB) and embedding distance vs an enrolled good tap.
- alarm:   beep durations -> pattern string -> pack alarm codes.
"""

from __future__ import annotations

import io
import logging
import math
import time
import uuid
from typing import Any, Protocol

import librosa
import numpy as np
import soundfile as sf

from audio.modes import SR, band_energies, beep_pattern, check_quality, detect_taps, windows
from audio.store import AudioStore
from packs import Pack

log = logging.getLogger("earshot.audio")

CLAP_MODEL = "laion/clap-htsat-unfused"
Z_MIDPOINT = 3.0  # z-score that maps to anomaly 0.5
Z_SPREAD = 1.2
# Floor for the enrollment distance spread. A steady machine gives very similar windows, so the raw spread
# can be tiny and any small change (room noise, phone position) would look alarming. The spread is at least
# half the mean distance, and never below MIN_STD.
MIN_STD = 0.01
REL_STD = 0.5


class Embedder(Protocol):
    def audio(self, clips: list[np.ndarray]) -> np.ndarray: ...
    def text(self, prompts: list[str]) -> np.ndarray: ...


class ClapEmbedder:
    """CLAP audio/text embeddings (L2-normalised)."""

    def __init__(self) -> None:
        import torch  # heavy imports kept here so the rest of the app starts without them
        from transformers import ClapModel, ClapProcessor

        self._torch = torch
        started = time.time()
        self._processor = ClapProcessor.from_pretrained(CLAP_MODEL)
        self._model = ClapModel.from_pretrained(CLAP_MODEL).eval()
        log.info("Loaded %s in %.1fs", CLAP_MODEL, time.time() - started)

    @staticmethod
    def _features(out: Any) -> Any:
        # transformers 5 returns an output object with normalised pooler_output; 4.x returns a tensor.
        return getattr(out, "pooler_output", out)

    def audio(self, clips: list[np.ndarray]) -> np.ndarray:
        vectors = []
        with self._torch.no_grad():
            for i in range(0, len(clips), 16):
                inputs = self._processor.feature_extractor(
                    [c.astype(np.float32) for c in clips[i : i + 16]], sampling_rate=SR, return_tensors="pt"
                )
                vectors.append(self._features(self._model.get_audio_features(**inputs)).cpu().numpy())
        return _normalise(np.vstack(vectors))

    def text(self, prompts: list[str]) -> np.ndarray:
        with self._torch.no_grad():
            inputs = self._processor.tokenizer(prompts, padding=True, return_tensors="pt")
            out = self._features(self._model.get_text_features(**inputs)).cpu().numpy()
        return _normalise(out)


def _normalise(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def decode_audio(data: bytes) -> np.ndarray:
    """Any WAV/FLAC/OGG bytes -> mono float32 at 48 kHz."""
    y, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    return y.astype(np.float32)


def confidence_word(p: float) -> str:
    return "very sure" if p >= 0.6 else "fairly sure" if p >= 0.4 else "not sure"


def band_word(score: float, pack: Pack) -> str:
    t = pack.thresholds
    return "very unusual" if score > t.very_unusual else "slightly unusual" if score >= t.slightly_unusual else "normal"


class AudioEngine:
    def __init__(self, store: AudioStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    # --- enrollment ------------------------------------------------------------------------
    def enroll(self, asset_id: str, y: np.ndarray, mode: str = "continuous") -> dict[str, Any]:
        quality = check_quality(y, min_seconds=1.0 if mode == "tap" else 3.0)
        # A tap recording is mostly silence between taps, so its average level is not a useful check.
        if not quality.ok and not (mode == "tap" and quality.issue == "too_quiet"):
            return {"enrolled": False, "issue": quality.issue, "tip": quality.tip}
        if mode == "tap":
            if float(np.max(np.abs(y))) < 0.01:
                return {"enrolled": False, "issue": "too_quiet", "tip": "Move the phone closer and tap the good part firmly once."}
            taps = detect_taps(y)
            if not taps:
                return {"enrolled": False, "issue": "no_taps", "tip": "Tap the good part firmly, close to the phone."}
            if len(taps) > 1:
                # Onset detection can pick up reflections and handling noise after the real tap.
                ranked = sorted(taps, key=lambda tap: float(np.max(np.abs(tap.segment))), reverse=True)
                strongest, runner_up = (float(np.max(np.abs(tap.segment))) for tap in ranked[:2])
                if runner_up >= strongest * 0.5:
                    return {"enrolled": False, "issue": "multiple_taps",
                            "tip": "I heard more than one strong tap. Keep the phone still, then tap one good part once."}
                taps = ranked[:1]
            clip_url = self.store.save_clip(y, SR)
            embs = self.embedder.audio([windows(t.segment)[0] for t in taps])
            mean = _normalise(embs.mean(axis=0))
            dist = 1 - embs @ mean
            meta = {"mode": "tap", "asset_id": asset_id, "clip_url": clip_url, "taps": len(taps),
                    "good_tap_url": self.store.save_clip(taps[0].segment, SR),  # one ring, for "good vs this"
                    "good_decay_ms": float(np.median([t.decay_ms for t in taps])),
                    "good_envelope": taps[0].envelope, "enrolled_at": time.time()}
            self.store.save_baseline(asset_id, {"mean": mean, "dist": dist}, meta)
            return {"enrolled": True, "mode": "tap", "taps": len(taps), "clip_url": clip_url,
                    "good_tap_url": meta["good_tap_url"]}
        clip_url = self.store.save_clip(y, SR)
        embs = self.embedder.audio(windows(y))
        mean = _normalise(embs.mean(axis=0))
        dist = 1 - embs @ mean
        meta = {"mode": "continuous", "asset_id": asset_id, "clip_url": clip_url, "windows": len(embs),
                "seconds": round(len(y) / SR, 1), "dist_mean": float(dist.mean()),
                "dist_std": float(max(dist.std(), REL_STD * dist.mean(), MIN_STD)), "enrolled_at": time.time()}
        self.store.save_baseline(asset_id, {"mean": mean, "dist": dist, "bands": band_energies(y)}, meta)
        return {"enrolled": True, "mode": "continuous", "seconds": meta["seconds"], "clip_url": clip_url}

    # --- continuous scoring ----------------------------------------------------------------
    def analyze(self, asset_id: str, asset_type: str, y: np.ndarray, pack: Pack) -> dict[str, Any]:
        base = {"id": uuid.uuid4().hex[:10], "asset_id": asset_id, "mode": "continuous", "at": time.time()}
        quality = check_quality(y)
        if not quality.ok:
            return {**base, "ok": False, "issue": quality.issue, "tip": quality.tip}
        baseline = self.store.load_baseline(asset_id)
        if baseline is None or baseline[1].get("mode") != "continuous":
            return {**base, "ok": False, "issue": "not_enrolled",
                    "tip": "This machine has no healthy sound recorded yet. Record it while it runs normally."}
        arrays, meta = baseline
        clip_url = self.store.save_clip(y, SR)
        embs = self.embedder.audio(windows(y))
        dist = 1 - embs @ arrays["mean"]
        z = (float(np.median(dist)) - meta["dist_mean"]) / meta["dist_std"]
        score = round(_logistic((z - Z_MIDPOINT) / Z_SPREAD), 3)
        band = band_word(score, pack)
        clip_emb = _normalise(embs.mean(axis=0))
        label = self._label(clip_emb, asset_type, band, pack)
        now_bands = band_energies(y)
        spectrum = self._spectrum(arrays["bands"], now_bands)
        return {
            **base, "ok": True, "anomaly_score": score, "band": band, **label, "spectrum": spectrum,
            "explanation": self._explain(arrays["bands"], now_bands, band, label["label"]),
            "clip_url": clip_url, "baseline_url": meta["clip_url"], "embedding": clip_emb.tolist(),
        }

    def _label(self, clip_emb: np.ndarray, asset_type: str, band: str, pack: Pack) -> dict[str, Any]:
        faults = pack.faults_for(asset_type)
        prompts = [f"the sound of a {asset_type} running normally"] + [
            f"the sound of a {asset_type} with {f}" for f in faults
        ]
        sims = self.embedder.text(prompts) @ clip_emb
        logits = sims * 100.0
        probs = np.exp(logits - logits.max())
        probs = probs / probs.sum()
        fault_probs = {f: float(p) for f, p in zip(faults, probs[1:], strict=True)}
        # Blend in nearest-neighbour votes from confirmed cases of the same asset type: the neighbours
        # together carry as much weight as the zero-shot probabilities (which sum to at most 1).
        cases, embs = self.store.cases()
        same = [i for i, c in enumerate(cases) if c.get("asset_type") == asset_type and c.get("cause") in fault_probs]
        if same and embs is not None:
            near = sorted(same, key=lambda i: -float(embs[i] @ clip_emb))[:5]
            for i in near:
                fault_probs[cases[i]["cause"]] += 1.0 / len(near)
        total = sum(fault_probs.values()) or 1.0
        ranked = sorted(((f, p / total) for f, p in fault_probs.items()), key=lambda x: -x[1])
        if band == "normal":
            return {"label": "running normally", "confidence": confidence_word(float(probs[0]) + 0.3),
                    "alternatives": [f for f, _ in ranked[:2]], "label_probs": dict(ranked)}
        return {"label": ranked[0][0], "confidence": confidence_word(ranked[0][1]),
                "alternatives": [f for f, _ in ranked[1:3]], "label_probs": dict(ranked)}

    @staticmethod
    def _spectrum(base_db: np.ndarray, now_db: np.ndarray) -> dict[str, list[float]]:
        lo = float(min(base_db.min(), now_db.min()))
        hi = float(max(base_db.max(), now_db.max()))
        span = max(hi - lo, 1e-6)
        return {
            "baseline": [round(float(v - lo) / span, 3) for v in base_db],
            "now": [round(float(v - lo) / span, 3) for v in now_db],
        }

    @staticmethod
    def _explain(base_db: np.ndarray, now_db: np.ndarray, band: str, label: str) -> str:
        if band == "normal":
            return "The sound now matches how it sounds when it is healthy."
        diff = now_db - base_db
        groups = {"low": float(diff[:8].mean()), "middle": float(diff[8:16].mean()), "high": float(diff[16:].mean())}
        where = max(groups, key=lambda k: groups[k])
        if groups[where] <= 1.0:
            return f"The overall character of the sound has changed. It could be {label}."
        return f"There is extra noise in the {where} tones compared with when it was healthy. That could be {label}."

    # --- tap test --------------------------------------------------------------------------
    def tap_test(self, asset_id: str, y: np.ndarray) -> dict[str, Any]:
        baseline = self.store.load_baseline(asset_id)
        if baseline is None or baseline[1].get("mode") != "tap":
            return {"ok": False, "issue": "not_enrolled", "tip": "Tap a part you know is good first, to set the reference."}
        arrays, meta = baseline
        taps = detect_taps(y)
        if not taps:
            return {"ok": False, "issue": "no_taps", "tip": "No taps heard. Tap each part firmly, close to the phone."}
        embs = self.embedder.audio([windows(t.segment)[0] for t in taps])
        dist = 1 - embs @ arrays["mean"]
        d_mean = float(arrays["dist"].mean())
        d_std = max(float(arrays["dist"].std()), REL_STD * d_mean, MIN_STD)
        results = []
        for tap, d in zip(taps, dist, strict=True):
            z = (float(d) - d_mean) / d_std
            short = tap.decay_ms < 0.6 * meta["good_decay_ms"]
            dull = short or z > 4.0
            reason = "the ring dies away quickly" if short else "the tone is different" if dull else ""
            results.append({"start": round(tap.start, 2), "decay_ms": round(tap.decay_ms), "distance_z": round(z, 1),
                            "result": "dull" if dull else "good", "reason": reason, "envelope": tap.envelope,
                            "clip_url": self.store.save_clip(tap.segment, SR)})
        return {"ok": True, "asset_id": asset_id, "mode": "tap", "good_decay_ms": round(meta["good_decay_ms"]),
                "good_envelope": meta["good_envelope"], "good_url": meta.get("good_tap_url") or meta["clip_url"],
                "taps": results}

    # --- alarm -----------------------------------------------------------------------------
    @staticmethod
    def alarm(y: np.ndarray, pack: Pack) -> dict[str, Any]:
        pattern, durations = beep_pattern(y)
        if not pattern:
            return {"ok": False, "issue": "no_beeps", "tip": "Hold the phone closer to the beeping box."}
        code = pack.alarm_codes.get(pattern)
        return {"ok": True, "mode": "alarm", "pattern": pattern, "durations": durations,
                "meaning": code.meaning if code else None, "action": code.action if code else None,
                "known": code is not None}

    # --- learning --------------------------------------------------------------------------
    def record_feedback(self, analysis: dict[str, Any], asset_type: str, cause: str) -> None:
        self.store.add_case(
            {"asset_id": analysis["asset_id"], "asset_type": asset_type, "cause": cause, "clip_url": analysis["clip_url"]},
            np.asarray(analysis["embedding"], dtype=np.float32),
        )

    def similar_cases(self, analysis: dict[str, Any], asset_type: str, k: int = 3) -> list[dict[str, Any]]:
        cases, embs = self.store.cases()
        if not cases or embs is None or "embedding" not in analysis:
            return []
        q = np.asarray(analysis["embedding"], dtype=np.float32)
        idx = [i for i, c in enumerate(cases) if c.get("asset_type") == asset_type]
        ranked = sorted(idx, key=lambda i: -float(embs[i] @ q))[:k]
        return [{**cases[i], "similarity": round(float(embs[i] @ q), 2)} for i in ranked]
