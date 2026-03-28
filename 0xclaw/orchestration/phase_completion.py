"""Helpers for phase completion markers and failure classification."""

from __future__ import annotations

import json
from pathlib import Path


PHASE_COMPLETION_MARKERS: dict[str, str] = {
    "coding": "coding.done.json",
}

_FAILURE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("maximum number of tool call iterations", "Tool-call iteration limit reached"),
    ("number of tool calls has exceeded the limit", "Tool-call limit reached"),
    ("tool call limit", "Tool-call limit reached"),
    ("without completing the task", "Agent stopped before completing the task"),
    ("encountered an error", "Agent encountered an error"),
    ("sorry, i encountered an error", "Agent encountered an error"),
)


def output_exists(path: Path | None) -> bool:
    if path is None:
        return False
    if path.is_dir():
        return any(path.rglob("*"))
    return path.exists() and path.stat().st_size > 10


def marker_path(hackathon_dir: Path, phase: str) -> Path | None:
    name = PHASE_COMPLETION_MARKERS.get(phase)
    return hackathon_dir / name if name else None


def clear_marker(hackathon_dir: Path, phase: str) -> None:
    path = marker_path(hackathon_dir, phase)
    if path and path.exists():
        path.unlink()


def write_marker(hackathon_dir: Path, phase: str, payload: dict | None = None) -> Path | None:
    path = marker_path(hackathon_dir, phase)
    if not path:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    body = payload or {"phase": phase, "status": "done"}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def is_phase_complete(phase: str, *, hackathon_dir: Path, phase_output: Path | None) -> bool:
    path = marker_path(hackathon_dir, phase)
    if path is not None:
        return path.exists() and output_exists(phase_output)
    return output_exists(phase_output)


def detect_failure_reason(response: str | None, *, timed_out: bool) -> str | None:
    if timed_out:
        return "Timed out waiting for phase completion"
    text = (response or "").strip().lower()
    if not text:
        return None
    for needle, reason in _FAILURE_PATTERNS:
        if needle in text:
            return reason
    return None
