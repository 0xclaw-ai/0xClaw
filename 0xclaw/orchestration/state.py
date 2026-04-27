"""Pipeline state store and orchestration state-machine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .phase_completion import is_phase_complete as phase_output_is_complete
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

# Cleanup list for /redo and reset flows. This no longer defines phase completion.
PHASE_COMPLETION_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "research": ("context.json", "research_summary.md"),
    "idea": ("ideas.json",),
    "selection": ("selected_idea.json",),
    "planning": ("plan.md", "tasks.json"),
    "coding": ("project",),
    "testing": ("test_results.json",),
    "doc": (
        "submission/README.md",
        "submission/SUBMISSION.md",
        "submission/PITCH.md",
        "project/README.md",
    ),
}

PHASE_ALLOWED_WRITE_DIRS: dict[str, tuple[str, ...]] = {
    "research": ("hackathon/context.json", "hackathon/research_summary.md", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "idea": ("hackathon/ideas.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "selection": ("hackathon/selected_idea.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "planning": ("hackathon/plan.md", "hackathon/tasks.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "coding": ("hackathon/project", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "testing": ("hackathon/test_results.json", "hackathon/pipeline_state.json", "hackathon/progress.md"),
    "doc": ("hackathon/submission", "hackathon/project/README.md", "hackathon/pipeline_state.json", "hackathon/progress.md"),
}

PROTECTED_PIPELINE_PATHS = tuple(
    dict.fromkeys(path for paths in PHASE_ALLOWED_WRITE_DIRS.values() for path in paths)
)

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


def _normalize_state(data: dict | None) -> dict:
    """Hydrate a possibly stale or partial state file into the current schema."""
    base = _default_state()
    if not isinstance(data, dict):
        return base

    state = dict(base)
    state.update({k: v for k, v in data.items() if k != "phases"})

    existing_rows = {}
    for row in data.get("phases", []) if isinstance(data.get("phases"), list) else []:
        if isinstance(row, dict) and row.get("name") in PHASES:
            existing_rows[row["name"]] = row

    normalized_rows = []
    for default_row in base["phases"]:
        row = dict(default_row)
        row.update(existing_rows.get(default_row["name"], {}))
        normalized_rows.append(row)

    state["phases"] = normalized_rows
    return state


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
        return _normalize_state(data)

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


def phase_completion_ready(hackathon_dir: Path, phase: str) -> bool:
    """Return True when the phase's primary output exists."""
    rel = PHASE_PRIMARY_OUTPUTS.get(phase)
    if rel is None:
        return False
    output = hackathon_dir / rel
    if phase == "coding":
        return phase_output_is_complete("coding", hackathon_dir=hackathon_dir, phase_output=output)
    return output_exists(output)


def reconcile_pipeline_state(store: PipelineStateStore, *, persist: bool = True) -> dict:
    """Reconcile pipeline_state.json against actual hackathon artifacts.

    The highest phase with a primary output becomes the effective checkpoint,
    and all earlier phases are treated as complete to avoid impossible gaps like
    planning=done with selection=pending.

    If no primary outputs exist at all, stale completed/running state is
    reset back to the empty-session baseline.
    """
    state = store.load()
    rows = {row["name"]: row for row in state["phases"]}
    highest_complete_idx = -1

    for idx, phase in enumerate(PHASES):
        if phase_completion_ready(store.hackathon_dir, phase):
            highest_complete_idx = idx

    changed = False
    for idx, phase in enumerate(PHASES):
        row = rows[phase]
        status = row.get("status", "pending")
        if highest_complete_idx >= 0:
            if idx <= highest_complete_idx:
                desired = "done"
            elif status in COMPLETED_PHASE_STATUSES:
                desired = "pending"
            else:
                desired = status
        else:
            desired = "pending" if status in COMPLETED_PHASE_STATUSES or status == "running" else status

        if desired != status:
            row["status"] = desired
            row["updated_at"] = _utc_now()
            changed = True

    current_phase = state.get("current_phase")
    if current_phase not in PHASES or rows.get(current_phase, {}).get("status") != "running":
        if state.get("current_phase") is not None:
            changed = True
        state["current_phase"] = None
        if state.get("active_task") is not None:
            changed = True
        state["active_task"] = None

    desired_checkpoint = PHASES[highest_complete_idx] if highest_complete_idx >= 0 else None
    if state.get("last_checkpoint") != desired_checkpoint:
        state["last_checkpoint"] = desired_checkpoint
        changed = True

    if not any(row.get("status") == "failed" for row in rows.values()) and state.get("last_error") is not None:
        state["last_error"] = None
        changed = True

    state["phases"] = [rows[phase] for phase in PHASES]
    if changed and persist:
        store.save(state)
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

        state = reconcile_pipeline_state(self.store)
        status_map = {row["name"]: row["status"] for row in state["phases"]}

        for dep in PHASE_DEPENDENCIES[phase]:
            if status_map.get(dep) not in COMPLETED_PHASE_STATUSES:
                errors.append(f"Dependency not complete: {dep}")

        for req in REQUIRED_ARTIFACTS[phase]:
            p = self.hackathon_dir / req
            if not p.exists():
                errors.append(f"Missing required artifact: hackathon/{req}")

        return ValidationResult(not errors, errors)

    def phase_is_complete(self, phase: str) -> bool:
        return phase_completion_ready(self.hackathon_dir, phase)

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
