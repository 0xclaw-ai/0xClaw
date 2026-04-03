"""Pipeline state store and orchestration state-machine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .phase_completion import output_exists

PHASES = ("research", "idea", "selection", "planning", "coding", "testing", "doc")

PHASE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "research": (),
    "idea": ("research",),
    "selection": ("idea",),
    "planning": ("selection",),
    "coding": ("planning",),
    "testing": ("coding",),
    "doc": ("testing",),
}

REQUIRED_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "research": (),
    "idea": ("context.json",),
    "selection": ("ideas.json",),
    "planning": ("selected_idea.json",),
    "coding": ("tasks.json", "plan.md"),
    "testing": ("project",),
    "doc": ("test_results.json",),
}

PHASE_PRIMARY_OUTPUTS: dict[str, str] = {
    "research": "context.json",
    "idea": "ideas.json",
    "selection": "selected_idea.json",
    "planning": "plan.md",
    "coding": "project",
    "testing": "test_results.json",
    "doc": "submission/README.md",
}

PHASE_ALLOWED_WRITE_DIRS: dict[str, tuple[str, ...]] = {
    "research": ("hackathon/context.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "idea": ("hackathon/ideas.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "selection": ("hackathon/selected_idea.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "planning": ("hackathon/plan.md", "hackathon/tasks.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "coding": ("hackathon/project", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "testing": ("hackathon/test_results.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "doc": ("hackathon/submission", "hackathon/pipeline_state.json", "hackathon/progress.md"),
}

COMPLETED_PHASE_STATUSES = frozenset({"done", "complete"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "current_phase": None,
        "phases": [{"name": p, "status": "pending", "updated_at": None} for p in PHASES],
        "last_error": None,
        "last_checkpoint": None,
        "active_task": None,
        "updated_at": _utc_now(),
    }


class PipelineStateStore:
    """File-backed pipeline state store."""

    def __init__(self, hackathon_dir: Path):
        self.hackathon_dir = hackathon_dir
        self.path = hackathon_dir / "pipeline_state.json"
        self.hackathon_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return _default_state()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data

    def save(self, state: dict) -> None:
        state["updated_at"] = _utc_now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic rename — prevents partial-write corruption

    def set_phase_status(self, phase: str, status: str, *, last_error: str | None = None, active_task: str | None = None) -> dict:
        state = self.load()
        state["current_phase"] = phase if status == "running" else None
        state["active_task"] = active_task if status == "running" else None
        state["last_error"] = last_error
        for row in state["phases"]:
            if row["name"] == phase:
                row["status"] = status
                row["updated_at"] = _utc_now()
                break
        if status == "done":
            state["last_checkpoint"] = phase
        if status in {"failed", "cancelled"}:
            state["active_task"] = None
        self.save(state)
        return state


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    errors: list[str]


class OrchestratorStateMachine:
    """Dependency and permission gate before phase execution."""

    def __init__(self, workspace: Path, store: PipelineStateStore):
        self.workspace = workspace
        self.hackathon_dir = workspace / "hackathon"
        self.store = store

    def validate_phase_entry(self, phase: str) -> ValidationResult:
        errors: list[str] = []
        if phase not in PHASES:
            return ValidationResult(False, [f"Unknown phase: {phase}"])

        state = self.store.load()
        status_map = {row["name"]: row["status"] for row in state["phases"]}

        for dep in PHASE_DEPENDENCIES[phase]:
            if status_map.get(dep) not in COMPLETED_PHASE_STATUSES:
                primary_output = PHASE_PRIMARY_OUTPUTS.get(dep)
                dep_output = self.hackathon_dir / primary_output if primary_output else None
                if dep_output is not None and output_exists(dep_output):
                    self.store.set_phase_status(dep, "done")
                    status_map[dep] = "done"
                    continue
                errors.append(f"Dependency not complete: {dep}")

        for req in REQUIRED_ARTIFACTS[phase]:
            p = self.hackathon_dir / req
            if not p.exists():
                errors.append(f"Missing required artifact: hackathon/{req}")

        return ValidationResult(not errors, errors)

    def is_write_allowed(self, phase: str, target_rel: str) -> bool:
        target = target_rel.strip("/")
        allowed = PHASE_ALLOWED_WRITE_DIRS.get(phase, ())
        for prefix in allowed:
            normalized = prefix.strip("/")
            if target == normalized or target.startswith(normalized + "/"):
                return True
        return False

    def assert_write_allowed(self, phase: str, target_rel: str) -> None:
        if not self.is_write_allowed(phase, target_rel):
            raise PermissionError(f"Phase '{phase}' cannot write to '{target_rel}'")

    def checkpoint(self, phase: str, status: str, *, last_error: str | None = None, active_task: str | None = None) -> dict:
        return self.store.set_phase_status(phase, status, last_error=last_error, active_task=active_task)
