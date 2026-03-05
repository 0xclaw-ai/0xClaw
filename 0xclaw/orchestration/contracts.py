"""Contracts for inter-agent envelopes and artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

PHASES = {"research", "idea", "selection", "planning", "coding", "testing", "doc"}
ENVELOPE_TYPES = {"command", "result", "error", "progress"}
ARTIFACT_TYPES = {
    "context",
    "ideas",
    "selected_idea",
    "plan",
    "tasks",
    "test_results",
    "submission",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Envelope:
    trace_id: str
    session_id: str
    phase: str
    agent_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ValueError(f"Invalid phase: {self.phase}")
        if self.type not in ENVELOPE_TYPES:
            raise ValueError(f"Invalid envelope type: {self.type}")
        if not self.trace_id or not self.session_id or not self.agent_id:
            raise ValueError("trace_id, session_id, and agent_id are required")

    @classmethod
    def from_command(
        cls,
        *,
        session_id: str,
        phase: str,
        agent_id: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> "Envelope":
        return cls(
            trace_id=trace_id or str(uuid4()),
            session_id=session_id,
            phase=phase,
            agent_id=agent_id,
            type="command",
            payload=payload,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        required = {"trace_id", "session_id", "phase", "agent_id", "type", "payload", "ts"}
        missing = sorted(required - set(data.keys()))
        if missing:
            raise ValueError(f"Missing envelope fields: {', '.join(missing)}")
        payload = data["payload"] if isinstance(data["payload"], dict) else {"raw": data["payload"]}
        return cls(
            trace_id=str(data["trace_id"]),
            session_id=str(data["session_id"]),
            phase=str(data["phase"]),
            agent_id=str(data["agent_id"]),
            type=str(data["type"]),
            payload=payload,
            ts=str(data["ts"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "agent_id": self.agent_id,
            "type": self.type,
            "payload": self.payload,
            "ts": self.ts,
        }


@dataclass(slots=True)
class ArtifactMeta:
    artifact: str
    version: str
    producer: str
    schema_version: str
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.artifact not in ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact type: {self.artifact}")
        if not self.version or not self.producer or not self.schema_version:
            raise ValueError("version, producer, and schema_version are required")

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact": self.artifact,
            "version": self.version,
            "producer": self.producer,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }


def wrap_artifact(*, meta: ArtifactMeta, data: Any) -> dict[str, Any]:
    """Wrap arbitrary artifact data with standard metadata."""
    return {"meta": meta.to_dict(), "data": data}
