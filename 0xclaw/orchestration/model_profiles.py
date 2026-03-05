"""Phase-based model profile resolver and metrics logging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ModelProfile:
    phase: str
    provider: str
    model: str
    max_tokens: int
    temperature: float
    timeout_s: int
    fallback: str | None = None


class ModelProfileResolver:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._profiles: dict[str, ModelProfile] = {}
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            self._profiles = {}
            return
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        profiles = {}
        for row in raw.get("profiles", []):
            p = ModelProfile(
                phase=row["phase"],
                provider=row["provider"],
                model=row["model"],
                max_tokens=int(row["max_tokens"]),
                temperature=float(row["temperature"]),
                timeout_s=int(row["timeout_s"]),
                fallback=row.get("fallback"),
            )
            profiles[p.phase] = p
        self._profiles = profiles

    def resolve(self, phase: str) -> ModelProfile | None:
        return self._profiles.get(phase)

    def resolve_with_fallback(self, phase: str, *, failed: bool) -> ModelProfile | None:
        prof = self.resolve(phase)
        if not prof:
            return None
        if not failed or not prof.fallback:
            return prof
        return self._profiles.get(prof.fallback, prof)


class MetricsLogger:
    def __init__(self, metrics_path: Path):
        self.metrics_path = metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict[str, Any]) -> None:
        payload = {"ts": _utc_now(), **record}
        with self.metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
