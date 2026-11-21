"""Signal processing for the three listening modes (no model needed): clip quality, spectrum bands,
tap ring-decay, and alarm beep patterns."""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

SR = 48_000  # CLAP's sample rate; every clip is resampled to this
N_BANDS = 24


@dataclass(frozen=True)
class Quality:
    ok: bool
    issue: str = ""  # "too_short" | "too_quiet" | "clipped"
    tip: str = ""
    level_db: float = 0.0


def check_quality(y: np.ndarray, min_seconds: float = 3.0) -> Quality:
    seconds = len(y) / SR
    rms = float(np.sqrt(np.mean(y**2)) + 1e-12)
    level_db = 20 * np.log10(rms)
    if seconds < min_seconds:
        return Quality(False, "too_short", "Keep the phone still near the machine for the full ten seconds.", level_db)
    if level_db < -55:
        return Quality(False, "too_quiet", "Move the phone closer, about a hand's width from where it sounds loudest.",
                       level_db)
    if float(np.mean(np.abs(y) > 0.99)) > 0.01:
        return Quality(False, "clipped", "Hold the phone a little further away; the sound is too loud for the mic.",
                       level_db)
    return Quality(True, level_db=level_db)


def band_energies(y: np.ndarray) -> np.ndarray:
    """Mean power (dB) in 24 log-spaced bands, 50 Hz to 16 kHz."""
    spec = np.abs(librosa.stft(y, n_fft=4096, hop_length=2048)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=4096)
    edges = np.geomspace(50, 16_000, N_BANDS + 1)
    power = spec.mean(axis=1)
    bands = [power[(freqs >= lo) & (freqs < hi)].mean() for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    return 10 * np.log10(np.asarray(bands, dtype=np.float64) + 1e-12)


def windows(y: np.ndarray, seconds: float = 1.0, overlap: float = 0.5) -> list[np.ndarray]:
    size = int(SR * seconds)
    hop = int(size * (1 - overlap))
    if len(y) <= size:
        return [np.pad(y, (0, size - len(y)))]
    return [y[i : i + size] for i in range(0, len(y) - size + 1, hop)]


def _envelope_db(y: np.ndarray, hop: int) -> np.ndarray:
    rms = librosa.feature.rms(y=y, frame_length=hop * 4, hop_length=hop)[0]
    return 20 * np.log10(rms + 1e-9)


@dataclass(frozen=True)
class Tap:
    start: float  # seconds into the clip
    decay_ms: float  # time for the ring to fall 20 dB below its peak
    segment: np.ndarray
    envelope: list[float]  # 24 points, 0..1, for the "good vs this" ring picture


def detect_taps(y: np.ndarray, max_ring: float = 1.0) -> list[Tap]:
    onsets = librosa.onset.onset_detect(y=y, sr=SR, units="samples", backtrack=True, hop_length=256, delta=0.2)
    onsets = [int(o) for o in onsets]
    # Ignore re-triggers within 250 ms of a tap.
    kept: list[int] = []
    for o in onsets:
        if not kept or o - kept[-1] > 0.25 * SR:
            kept.append(o)
    peak_level = float(np.max(np.abs(y)) + 1e-9)
    taps: list[Tap] = []
    for i, start in enumerate(kept):
        end = min(kept[i + 1] if i + 1 < len(kept) else len(y), start + int(max_ring * SR))
        seg = y[start:end]
        if len(seg) < SR * 0.05 or np.max(np.abs(seg)) < 0.1 * peak_level:
            continue  # too short or too faint to be a deliberate tap
        hop = 120  # 2.5 ms
        env = _envelope_db(seg, hop)
        p = int(np.argmax(env))
        below = np.nonzero(env[p:] < env[p] - 20)[0]
        decay_frames = below[0] if len(below) else len(env) - p
        lin = 10 ** ((env - env[p]) / 20)
        pts = np.interp(np.linspace(p, len(env) - 1, N_BANDS), np.arange(len(env)), lin)
        taps.append(Tap(start / SR, decay_frames * hop / SR * 1000, seg, [round(float(v), 3) for v in pts]))
    return taps


def beep_pattern(y: np.ndarray, long_seconds: float = 0.35) -> tuple[str, list[float]]:
    """Encode beeps as 'L'/'S' by duration, e.g. 'L L S'. Returns the pattern and beep durations."""
    hop = 480  # 10 ms
    env = _envelope_db(y, hop)
    floor = float(np.percentile(env, 20))
    peak = float(np.max(env))
    if peak - floor < 12:
        return "", []
    on = env > max(floor + 12, peak - 18)
    # close gaps shorter than 60 ms
    gap = 6
    idx = np.nonzero(on)[0]
    durations: list[float] = []
    if len(idx):
        start = prev = idx[0]
        for i in idx[1:]:
            if i - prev > gap:
                durations.append((prev - start + 1) * hop / SR)
                start = i
            prev = i
        durations.append((prev - start + 1) * hop / SR)
    durations = [d for d in durations if d >= 0.06]
    return " ".join("L" if d >= long_seconds else "S" for d in durations), [round(d, 2) for d in durations]
