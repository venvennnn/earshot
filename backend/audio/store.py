"""On-disk baselines, clips and the labeled case library.

Layout under STORE_DIR:
  baselines/<ASSET>.npz      enrollment statistics (+ JSON metadata inside)
  media/clips/<id>.wav       recorded clips (served at /media/clips/<id>.wav)
  cases/cases.json + .npy    labeled cases: confirmed cause + clip embedding
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


class AudioStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.baselines = root / "baselines"
        self.clips = root / "media" / "clips"
        self.cases_dir = root / "cases"
        for d in (self.baselines, self.clips, self.cases_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- clips -----------------------------------------------------------------------------
    def save_clip(self, y: np.ndarray, sr: int) -> str:
        clip_id = uuid.uuid4().hex[:12]
        sf.write(self.clips / f"{clip_id}.wav", y, sr, subtype="PCM_16")
        return f"/media/clips/{clip_id}.wav"

    def clip_path(self, url: str) -> Path:
        return self.root / url.removeprefix("/")

    # --- baselines -------------------------------------------------------------------------
    def save_baseline(self, asset_id: str, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> None:
        np.savez(self.baselines / f"{asset_id}.npz", meta=np.array(json.dumps(meta)), **arrays)

    def load_baseline(self, asset_id: str) -> tuple[dict[str, np.ndarray], dict[str, Any]] | None:
        path = self.baselines / f"{asset_id}.npz"
        if not path.exists():
            return None
        with np.load(path) as data:
            arrays = {k: data[k] for k in data.files if k != "meta"}
            meta = json.loads(str(data["meta"]))
        return arrays, meta

    def enrolled(self) -> set[str]:
        return {p.stem for p in self.baselines.glob("*.npz")}

    # --- case library ----------------------------------------------------------------------
    def _cases_paths(self) -> tuple[Path, Path]:
        return self.cases_dir / "cases.json", self.cases_dir / "embeddings.npy"

    def cases(self) -> tuple[list[dict[str, Any]], np.ndarray | None]:
        meta_path, emb_path = self._cases_paths()
        if not meta_path.exists():
            return [], None
        return json.loads(meta_path.read_text()), np.load(emb_path)

    def add_case(self, case: dict[str, Any], embedding: np.ndarray) -> None:
        cases, embs = self.cases()
        cases.append({**case, "at": time.strftime("%Y-%m-%d %H:%M")})
        embs = embedding[None, :] if embs is None else np.vstack([embs, embedding[None, :]])
        meta_path, emb_path = self._cases_paths()
        meta_path.write_text(json.dumps(cases, indent=1))
        np.save(emb_path, embs)
