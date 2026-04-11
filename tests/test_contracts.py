"""Tests for orchestration.contracts — Envelope and ArtifactMeta dataclasses."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.contracts import (
    ARTIFACT_TYPES,
    ENVELOPE_TYPES,
    PHASES,
    ArtifactMeta,
    Envelope,
    wrap_artifact,
)


class EnvelopeCreationTests(unittest.TestCase):
    def _make_envelope(self, **overrides) -> Envelope:
        defaults = {
            "trace_id": "trace-1",
            "session_id": "sess-1",
            "phase": "research",
            "agent_id": "agent-1",
            "type": "command",
        }
        defaults.update(overrides)
        return Envelope(**defaults)

    def test_valid_envelope_creation(self) -> None:
        env = self._make_envelope()
        self.assertEqual(env.phase, "research")
        self.assertEqual(env.type, "command")
        self.assertIsInstance(env.ts, str)

    def test_all_valid_phases_accepted(self) -> None:
        for phase in PHASES:
            env = self._make_envelope(phase=phase)
            self.assertEqual(env.phase, phase)

    def test_all_valid_types_accepted(self) -> None:
        for t in ENVELOPE_TYPES:
            env = self._make_envelope(type=t)
            self.assertEqual(env.type, t)

    def test_invalid_phase_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._make_envelope(phase="bogus")
        self.assertIn("Invalid phase", str(ctx.exception))

    def test_invalid_type_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._make_envelope(type="bogus")
        self.assertIn("Invalid envelope type", str(ctx.exception))

    def test_empty_trace_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._make_envelope(trace_id="")

    def test_empty_session_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._make_envelope(session_id="")

    def test_empty_agent_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._make_envelope(agent_id="")

    def test_default_payload_is_empty_dict(self) -> None:
        env = self._make_envelope()
        self.assertEqual(env.payload, {})


class EnvelopeFromCommandTests(unittest.TestCase):
    def test_from_command_sets_type(self) -> None:
        env = Envelope.from_command(
            session_id="s1", phase="idea", agent_id="a1", payload={"key": "val"}
        )
        self.assertEqual(env.type, "command")

    def test_from_command_auto_generates_trace_id(self) -> None:
        env = Envelope.from_command(
            session_id="s1", phase="idea", agent_id="a1", payload={}
        )
        self.assertTrue(len(env.trace_id) > 0)

    def test_from_command_uses_provided_trace_id(self) -> None:
        env = Envelope.from_command(
            session_id="s1", phase="idea", agent_id="a1", payload={}, trace_id="custom-trace"
        )
        self.assertEqual(env.trace_id, "custom-trace")


class EnvelopeSerializationTests(unittest.TestCase):
    def test_to_dict_contains_all_fields(self) -> None:
        env = Envelope(
            trace_id="t1", session_id="s1", phase="coding",
            agent_id="a1", type="result", payload={"out": 42},
        )
        d = env.to_dict()
        self.assertEqual(d["trace_id"], "t1")
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(d["phase"], "coding")
        self.assertEqual(d["agent_id"], "a1")
        self.assertEqual(d["type"], "result")
        self.assertEqual(d["payload"], {"out": 42})
        self.assertIn("ts", d)

    def test_to_dict_from_dict_roundtrip(self) -> None:
        original = Envelope.from_command(
            session_id="s1", phase="planning", agent_id="a1",
            payload={"step": 1}, trace_id="rt-1",
        )
        restored = Envelope.from_dict(original.to_dict())
        self.assertEqual(original.to_dict(), restored.to_dict())

    def test_from_dict_missing_field_raises(self) -> None:
        incomplete = {
            "trace_id": "t1", "session_id": "s1", "phase": "research",
            "agent_id": "a1", "type": "command",
            # missing: payload, ts
        }
        with self.assertRaises(ValueError) as ctx:
            Envelope.from_dict(incomplete)
        self.assertIn("Missing envelope fields", str(ctx.exception))

    def test_from_dict_wraps_non_dict_payload(self) -> None:
        data = {
            "trace_id": "t1", "session_id": "s1", "phase": "research",
            "agent_id": "a1", "type": "command", "payload": "hello", "ts": "2026-01-01",
        }
        env = Envelope.from_dict(data)
        self.assertEqual(env.payload, {"raw": "hello"})


class ArtifactMetaTests(unittest.TestCase):
    def test_valid_creation(self) -> None:
        meta = ArtifactMeta(
            artifact="context", version="1.0", producer="research-agent",
            schema_version="1",
        )
        self.assertEqual(meta.artifact, "context")
        self.assertIsInstance(meta.created_at, str)

    def test_all_valid_artifact_types_accepted(self) -> None:
        for art in ARTIFACT_TYPES:
            meta = ArtifactMeta(
                artifact=art, version="1.0", producer="agent", schema_version="1",
            )
            self.assertEqual(meta.artifact, art)

    def test_invalid_artifact_type_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ArtifactMeta(
                artifact="bogus", version="1.0", producer="agent", schema_version="1",
            )
        self.assertIn("Invalid artifact type", str(ctx.exception))

    def test_empty_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            ArtifactMeta(artifact="context", version="", producer="a", schema_version="1")

    def test_to_dict_contains_all_fields(self) -> None:
        meta = ArtifactMeta(
            artifact="plan", version="2.0", producer="planner", schema_version="1",
        )
        d = meta.to_dict()
        self.assertEqual(set(d.keys()), {"artifact", "version", "producer", "schema_version", "created_at"})


class WrapArtifactTests(unittest.TestCase):
    def test_wrap_artifact_structure(self) -> None:
        meta = ArtifactMeta(
            artifact="ideas", version="1.0", producer="idea-agent", schema_version="1",
        )
        wrapped = wrap_artifact(meta=meta, data={"ideas": [1, 2, 3]})
        self.assertIn("meta", wrapped)
        self.assertIn("data", wrapped)
        self.assertEqual(wrapped["data"], {"ideas": [1, 2, 3]})
        self.assertEqual(wrapped["meta"]["artifact"], "ideas")


if __name__ == "__main__":
    unittest.main()
