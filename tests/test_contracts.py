from __future__ import annotations

import pytest


def test_envelope_roundtrip(contracts_mod):
    env = contracts_mod.Envelope.from_command(
        session_id="cli:direct",
        phase="research",
        agent_id="orchestrator",
        payload={"user_command": "run research"},
    )
    restored = contracts_mod.Envelope.from_dict(env.to_dict())
    assert restored.phase == "research"
    assert restored.type == "command"


def test_envelope_missing_fields(contracts_mod):
    with pytest.raises(ValueError):
        contracts_mod.Envelope.from_dict({"phase": "research"})


def test_artifact_validation_and_wrap(contracts_mod):
    meta = contracts_mod.ArtifactMeta(
        artifact="context",
        version="v1",
        producer="tester",
        schema_version="1.0.0",
    )
    payload = contracts_mod.wrap_artifact(meta=meta, data={"ok": True})
    assert payload["meta"]["artifact"] == "context"
    assert payload["data"]["ok"] is True


def test_artifact_invalid_type(contracts_mod):
    with pytest.raises(ValueError):
        contracts_mod.ArtifactMeta(
            artifact="bad",
            version="v1",
            producer="tester",
            schema_version="1.0.0",
        )
