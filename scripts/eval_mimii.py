"""How well does EarShot's no-training method separate normal from abnormal machine sound? (MIMII)

For each machine type (pump, fan, valve, slider) and machine id, using channel 0:
- enroll a baseline from N normal clips: 10 s (1 clip), 1 min (6 clips), 5 min (30 clips);
- score held-out normal and abnormal clips with the same method the app uses (median cosine distance of
  1 s CLAP windows to the baseline mean);
- report ROC-AUC (0.5 = chance, 1.0 = perfect). Nothing is hard-coded: every number comes from this run.

Usage (from the repo root):
    backend/.venv/bin/pip install -r scripts/requirements.txt
    backend/.venv/bin/python scripts/eval_mimii.py --mimii data/mimii --max-test 50
Writes results/mimii_auc.csv and results/mimii_auc.png.
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np

from _common import ROOT, clips, load_channel0, machine_ids

MACHINES = ["pump", "fan", "valve", "slider"]
BASELINES = {"10 s": 1, "1 min": 6, "5 min": 30}  # MIMII clips are 10 s each


def auc(normal: np.ndarray, abnormal: np.ndarray) -> float:
    """ROC-AUC = probability an abnormal clip scores higher than a normal one (ties count half)."""
    scores = np.concatenate([normal, abnormal])
    order = scores.argsort()
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    for v in np.unique(scores):  # average ranks for ties
        idx = scores == v
        ranks[idx] = ranks[idx].mean()
    n_pos, n_neg = len(abnormal), len(normal)
    return float((ranks[n_neg:].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mimii", type=Path, default=ROOT / "data" / "mimii")
    ap.add_argument("--machines", nargs="*", default=MACHINES)
    ap.add_argument("--max-test", type=int, default=50, help="held-out clips per class per machine id")
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    args = ap.parse_args()

    from audio.engine import ClapEmbedder, _normalise
    from audio.modes import windows

    embedder = ClapEmbedder()
    cache: dict[Path, np.ndarray] = {}

    def window_embeddings(path: Path) -> np.ndarray:
        if path not in cache:
            cache[path] = embedder.audio(windows(load_channel0(path)))
        return cache[path]

    rows: list[dict[str, object]] = []
    biggest = max(BASELINES.values())
    for machine in args.machines:
        for mid in machine_ids(args.mimii, machine):
            normal = clips(args.mimii, machine, mid, "normal")
            abnormal = clips(args.mimii, machine, mid, "abnormal")[: args.max_test]
            if len(normal) <= biggest or not abnormal:
                print(f"skip {machine}/{mid}: not enough clips")
                continue
            enroll_pool, test_normal = normal[:biggest], normal[biggest : biggest + args.max_test]
            started = time.time()
            for label, n in BASELINES.items():
                base = np.vstack([window_embeddings(p) for p in enroll_pool[:n]])
                mean = _normalise(base.mean(axis=0))

                def score(path: Path, mean: np.ndarray = mean) -> float:
                    return float(np.median(1 - window_embeddings(path) @ mean))

                a = auc(np.array([score(p) for p in test_normal]), np.array([score(p) for p in abnormal]))
                rows.append({"machine": machine, "id": mid, "baseline": label, "auc": round(a, 4),
                             "test_normal": len(test_normal), "test_abnormal": len(abnormal)})
                print(f"{machine:6s} {mid}  baseline {label:5s}  AUC {a:.3f}")
            print(f"  ({time.time() - started:.0f}s)")

    if not rows:
        print(f"No MIMII clips found under {args.mimii}. Expected <snr>_dB_<machine>/<machine>/id_XX/<normal|abnormal>/*.wav")
        return
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "mimii_auc.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _chart(rows, args.out / "mimii_auc.png")
    print(f"Wrote {args.out / 'mimii_auc.csv'} and {args.out / 'mimii_auc.png'}")


def _chart(rows: list[dict[str, object]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    machines = [m for m in MACHINES if any(r["machine"] == m for r in rows)]
    colors = {"10 s": "#B9BEC7", "1 min": "#E58A12", "5 min": "#2B54D4"}
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    width = 0.26
    for i, label in enumerate(BASELINES):
        means = [np.mean([r["auc"] for r in rows if r["machine"] == m and r["baseline"] == label]) for m in machines]
        bars = ax.bar(np.arange(len(machines)) + (i - 1) * width, means, width, label=f"{label} baseline", color=colors[label])
        ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    ax.axhline(0.5, color="#5B6372", linewidth=0.8, linestyle="--")
    ax.text(len(machines) - 0.5, 0.51, "chance", fontsize=7, color="#5B6372", ha="right")
    ax.set_xticks(np.arange(len(machines)), [m.capitalize() for m in machines])
    ax.set_ylim(0.4, 1.0)
    ax.set_ylabel("ROC-AUC (mean over machine ids)")
    ax.set_title("EarShot on MIMII (channel 0, no training)", fontsize=10, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, ncols=3, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)


if __name__ == "__main__":
    main()
