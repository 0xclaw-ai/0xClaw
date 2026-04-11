"""Session-level cancel/resume helpers built on pipeline state."""

from __future__ import annotations

from dataclasses import dataclass

from .state import COMPLETED_PHASE_STATUSES, PHASE_PRIMARY_OUTPUTS, PHASES, PipelineStateStore
from .phase_completion import output_exists


PHASE_TO_COMMAND = {
    "research": "run hackathon research",
    "idea": "generate ideas",
    "selection": "select idea",
    "planning": "plan architecture",
    "coding": "start coding",
    "testing": "run tests",
    "doc": "prepare docs",
}


@dataclass(slots=True)
class ResumeDecision:
    phase: str | None
    command: str | None
    reason: str


class SessionControl:
    def __init__(self, store: PipelineStateStore):
        self.store = store

    def mark_cancelled(self, phase: str, reason: str = "Cancelled by user") -> dict:
        return self.store.set_phase_status(phase, "cancelled", last_error=reason)

    def get_resume_decision(self) -> ResumeDecision:
        state = self.store.load()
        status_map = {row["name"]: row["status"] for row in state["phases"]}

        current = state.get("current_phase")
        if current in PHASES and status_map.get(current) == "running":
            return ResumeDecision(current, PHASE_TO_COMMAND[current], f"Resume current phase: {current}")

        for status, label in (("failed", "Retry failed phase"), ("cancelled", "Resume cancelled phase")):
            for phase in PHASES:
                if status_map.get(phase) == status:
                    return ResumeDecision(phase, PHASE_TO_COMMAND[phase], f"{label}: {phase}")

        checkpoint = state.get("last_checkpoint")
        if checkpoint in PHASES:
            idx = PHASES.index(checkpoint)
            for p in PHASES[idx + 1:]:
                if status_map.get(p) not in COMPLETED_PHASE_STATUSES:
                    return ResumeDecision(p, PHASE_TO_COMMAND[p], f"Resume from next phase after {checkpoint}")

        # Auto-heal: if state file is missing or stale, check actual output files
        healed = False
        for phase, primary_output in PHASE_PRIMARY_OUTPUTS.items():
            if status_map.get(phase) not in COMPLETED_PHASE_STATUSES:
                out_path = self.store.hackathon_dir / primary_output
                if output_exists(out_path):
                    self.store.set_phase_status(phase, "done")
                    status_map[phase] = "done"
                    healed = True

        if healed:
            # Re-evaluate after healing — skip to first genuinely incomplete phase
            for p in PHASES:
                if status_map.get(p) not in COMPLETED_PHASE_STATUSES:
                    return ResumeDecision(p, PHASE_TO_COMMAND[p], "Resume from first incomplete phase")
            return ResumeDecision(None, None, "All phases are complete")

        for p in PHASES:
            if status_map.get(p) not in COMPLETED_PHASE_STATUSES:
                return ResumeDecision(p, PHASE_TO_COMMAND[p], "Resume from first incomplete phase")

        return ResumeDecision(None, None, "All phases are complete")
