"""Tests for orchestration.model_profiles — ModelProfileResolver and MetricsLogger."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.model_profiles import MetricsLogger, ModelProfileResolver

# Path to the real model_profiles.json used by the project.
REAL_CONFIG_PATH = ROOT / "0xclaw" / "config" / "model_profiles.json"


class ModelProfileResolverTests(unittest.TestCase):
    def test_resolve_all_seven_phases(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        phases = ("research", "idea", "selection", "planning", "coding", "testing", "doc")
        for phase in phases:
            profile = resolver.resolve(phase)
            self.assertIsNotNone(profile, f"Profile for {phase} should not be None")
            self.assertEqual(profile.phase, phase)

    def test_resolve_unknown_phase_returns_none(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        self.assertIsNone(resolver.resolve("bogus"))

    def test_resolve_returns_correct_coding_profile(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        profile = resolver.resolve("coding")
        self.assertEqual(profile.provider, "zhipu")
        self.assertEqual(profile.model, "glm-4.5")
        self.assertEqual(profile.max_tokens, 65536)
        self.assertAlmostEqual(profile.temperature, 0.1)
        self.assertEqual(profile.timeout_s, 600)

    def test_fallback_when_failed_true(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        profile = resolver.resolve_with_fallback("coding", failed=True)
        self.assertIsNotNone(profile)
        # coding fallback is "planning"
        self.assertEqual(profile.phase, "planning")

    def test_no_fallback_when_failed_false(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        profile = resolver.resolve_with_fallback("coding", failed=False)
        self.assertEqual(profile.phase, "coding")

    def test_fallback_chain_terminates_at_doc(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        # doc has fallback=null, so failed=True returns doc itself
        profile = resolver.resolve_with_fallback("doc", failed=True)
        self.assertEqual(profile.phase, "doc")

    def test_missing_config_file(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nonexistent.json"
            resolver = ModelProfileResolver(missing)
            self.assertIsNone(resolver.resolve("research"))

    def test_empty_profiles_array(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "empty.json"
            config_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")
            resolver = ModelProfileResolver(config_path)
            self.assertIsNone(resolver.resolve("research"))

    def test_resolve_with_fallback_unknown_phase(self) -> None:
        resolver = ModelProfileResolver(REAL_CONFIG_PATH)
        self.assertIsNone(resolver.resolve_with_fallback("bogus", failed=False))


class MetricsLoggerTests(unittest.TestCase):
    def test_log_appends_record_with_timestamp(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            logger = MetricsLogger(path)
            logger.log({"phase": "research", "tokens": 100})

            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertIn("ts", record)
            self.assertEqual(record["phase"], "research")
            self.assertEqual(record["tokens"], 100)

    def test_log_multiple_records(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            logger = MetricsLogger(path)
            for i in range(3):
                logger.log({"i": i})

            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 3)

    def test_log_creates_parent_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "metrics.jsonl"
            logger = MetricsLogger(path)
            logger.log({"test": True})
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
