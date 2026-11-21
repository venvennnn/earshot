"""Industry packs: machines, words, people, policy and knowledge for one industry (packs/*.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = ROOT / "packs"
KNOWLEDGE_DIR = ROOT / "knowledge"

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "ta": "Tamil"}


class Asset(BaseModel):
    id: str
    name: str
    type: str
    line: str = ""
    modes: list[str] = Field(default_factory=lambda: ["continuous"])
    parts: int = 0  # number of parts in a tap-test batch


class Person(BaseModel):
    name: str
    role: str
    language: str = "en"
    approver: bool = False


class Worker(BaseModel):
    name: str
    role: str
    language: str = "en"


class AlarmCode(BaseModel):
    meaning: str
    action: str


class Policy(BaseModel):
    tiers: dict[str, int] = Field(default_factory=dict)
    purchase_limit_inr: int = 50000


class Thresholds(BaseModel):
    slightly_unusual: float = 0.4
    very_unusual: float = 0.7


class Pack(BaseModel):
    id: str
    name: str
    plant: str
    line: str
    shift: str
    language: str = "en"
    worker: Worker
    assets: list[Asset]
    fault_vocab: dict[str, list[str]]
    fault_parts: dict[str, str] = Field(default_factory=dict)
    alarm_codes: dict[str, AlarmCode] = Field(default_factory=dict)
    vocabulary: dict[str, str] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    hours_saved_per_early_catch: float = 0.0
    policy: Policy = Field(default_factory=Policy)
    people: list[Person] = Field(default_factory=list)
    announcement_language: str = "en"
    knowledge: list[str] = Field(default_factory=list)

    def asset(self, asset_id: str) -> Asset | None:
        key = asset_id.strip().upper()
        return next((a for a in self.assets if a.id.upper() == key), None)

    def faults_for(self, asset_type: str) -> list[str]:
        return self.fault_vocab.get(asset_type) or self.fault_vocab.get("default", [])

    def person(self, name: str) -> Person | None:
        key = name.strip().lower()
        return next((p for p in self.people if p.name.lower() == key or p.role.lower() == key), None)

    def summary(self) -> dict[str, Any]:
        """Public view for the UI."""
        return self.model_dump(include={"id", "name", "plant", "line", "shift", "worker", "people", "language"})


def available_packs() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.yaml"))


def load_pack(pack_id: str) -> Pack:
    path = PACKS_DIR / f"{pack_id}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown pack '{pack_id}'. Available: {', '.join(available_packs())}")
    return Pack.model_validate(yaml.safe_load(path.read_text()))
