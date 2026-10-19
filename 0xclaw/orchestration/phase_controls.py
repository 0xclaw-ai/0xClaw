"""Opt-in entry points for separately installed phase-control components."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any


@dataclass
class PhaseControlRun:
    phase: str
    profile: Any
    plugins: tuple[Any, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    def frame(self, message: str) -> str:
        for plugin in self.plugins:
            message = plugin.frame(self.phase, message, self.context)
        return message


class PhaseControls:
    def __init__(self, plugins: tuple[Any, ...] = ()):
        self.plugins = plugins

    def prepare(self, phase: str, command: str, profile: Any) -> PhaseControlRun:
        run = PhaseControlRun(phase, profile, self.plugins)
        for plugin in self.plugins:
            run.profile = plugin.prepare(phase, command, run.profile, run.context)
        return run


def load_phase_controls(*, root: Path, workspace: Path) -> PhaseControls:
    """Load only explicitly enabled components; the default is a no-op."""
    selection = os.environ.get("OXCLAW_PHASE_CONTROLS", "").strip()
    if not selection and os.environ.get("OXCLAW_ENABLE_BUDGET_DEADLINE", "").lower() in {
        "1", "true", "yes", "on",
    }:
        selection = "budget-router,deadline-framer"
    names = list(dict.fromkeys(name.strip() for name in selection.split(",") if name.strip()))
    if not names:
        return PhaseControls()

    available: dict[str, list[Any]] = {}
    for entry in entry_points(group="oxclaw.phase_controls"):
        available.setdefault(entry.name, []).append(entry)
    plugins = []
    for name in names:
        entries = available.get(name, [])
        if len(entries) != 1:
            raise RuntimeError(
                f"Phase control {name!r} requires exactly one installed plugin; found {len(entries)}. "
                "See the optional components in the 0xClaw README for installation instructions."
            )
        plugins.append(entries[0].load()(root=root, workspace=workspace))
    return PhaseControls(tuple(plugins))
