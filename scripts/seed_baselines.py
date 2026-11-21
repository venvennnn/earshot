"""Enroll the demo assets from MIMII normal clips and seed the labeled case library.

Usage (from the repo root, with the backend venv):
    backend/.venv/bin/python scripts/seed_baselines.py --mimii data/mimii

- P-11, P-12, P-13, P-14 <- MIMII pump ids 00, 02, 04, 06 (10 s of normal sound each, channel 0)
- CP-2                   <- MIMII fan id_00 (MIMII has no compressor; a fan is the closest rotating machine)
- Case library           <- a few MIMII abnormal pump clips labeled "a leak or blockage" (MIMII documents its pump
                            anomalies as leakage, contamination and clogging)
- data/demo/             <- normal and abnormal clips of the P-14 pump to play from a second phone in the demo

Baselines go to STORE_DIR (default backend/store). For the live demo, re-enroll through the same speaker
you will use to play the faulty clip (app: Add a machine -> Enroll from this speaker).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import soundfile as sf

from _common import ROOT, SR, clips, load_channel0

ASSETS = {"P-11": ("pump", "id_00"), "P-12": ("pump", "id_02"), "P-13": ("pump", "id_04"),
          "P-14": ("pump", "id_06"), "CP-2": ("fan", "id_00")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mimii", type=Path, default=ROOT / "data" / "mimii")
    ap.add_argument("--store", type=Path, default=Path(os.environ.get("STORE_DIR", ROOT / "backend" / "store")))
    ap.add_argument("--cases", type=int, default=4, help="abnormal pump clips to add to the case library")
    args = ap.parse_args()

    from audio.engine import AudioEngine, ClapEmbedder
    from audio.store import AudioStore

    engine = AudioEngine(AudioStore(args.store.resolve()), ClapEmbedder())
    for asset_id, (machine, mid) in ASSETS.items():
        normal = clips(args.mimii, machine, mid, "normal")
        if not normal:
            print(f"skip {asset_id}: no MIMII {machine}/{mid}/normal clips under {args.mimii}")
            continue
        result = engine.enroll(asset_id, load_channel0(normal[0]))
        print(f"{asset_id}: enrolled from {normal[0].relative_to(args.mimii)} -> {result}")

    abnormal = clips(args.mimii, "pump", "id_00", "abnormal")[: args.cases]
    for path in abnormal:
        y = load_channel0(path)
        analysis = engine.analyze("P-11", "pump", y, _pack())
        if analysis.get("ok"):
            engine.record_feedback(analysis, "pump", "a leak or blockage")
            print(f"case: {path.name} labeled 'a leak or blockage'")

    demo = ROOT / "data" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for kind in ("normal", "abnormal"):
        found = clips(args.mimii, "pump", "id_06", kind)
        if found:
            out = demo / f"P-14_{kind}.wav"
            sf.write(out, load_channel0(found[min(1, len(found) - 1)]), SR)
            print(f"demo clip: {out.relative_to(ROOT)}")


def _pack():
    from packs import load_pack

    return load_pack("manufacturing")


if __name__ == "__main__":
    main()
