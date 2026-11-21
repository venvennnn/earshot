"""Helpers shared by the MIMII scripts: find clips and load channel 0 at CLAP's 48 kHz."""

from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SR = 48_000


def clips(mimii: Path, machine: str, machine_id: str, kind: str) -> list[Path]:
    """MIMII layout: <snr>_dB_<machine>/<machine>/<id>/<normal|abnormal>/*.wav (any SNR folder)."""
    found = sorted(mimii.glob(f"**/{machine}/{machine_id}/{kind}/*.wav"))
    return found


def machine_ids(mimii: Path, machine: str) -> list[str]:
    return sorted({p.name for p in mimii.glob(f"**/{machine}/id_*") if p.is_dir()})


def load_channel0(path: Path) -> np.ndarray:
    """MIMII clips are 8-channel, 16 kHz, 10 s. Use channel 0, resampled to 48 kHz."""
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    return librosa.resample(y[:, 0], orig_sr=sr, target_sr=SR).astype(np.float32)
