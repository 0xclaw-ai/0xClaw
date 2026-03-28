import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.phase_completion import (
    clear_marker,
    detect_failure_reason,
    is_phase_complete,
    write_marker,
)


class PhaseCompletionTests(unittest.TestCase):
    def test_coding_requires_marker_and_output(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            project_dir = hackathon_dir / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("partial output\n", encoding="utf-8")

            self.assertFalse(
                is_phase_complete("coding", hackathon_dir=hackathon_dir, phase_output=project_dir)
            )

            write_marker(hackathon_dir, "coding", {"phase": "coding", "status": "done"})
            self.assertTrue(
                is_phase_complete("coding", hackathon_dir=hackathon_dir, phase_output=project_dir)
            )

            clear_marker(hackathon_dir, "coding")
            self.assertFalse(
                is_phase_complete("coding", hackathon_dir=hackathon_dir, phase_output=project_dir)
            )

    def test_non_marker_phases_still_use_artifact_presence(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            plan_path = hackathon_dir / "plan.md"
            plan_path.write_text("valid plan output\n", encoding="utf-8")
            self.assertTrue(
                is_phase_complete("planning", hackathon_dir=hackathon_dir, phase_output=plan_path)
            )

    def test_failure_reason_detects_timeout_and_tool_limit(self) -> None:
        self.assertEqual(
            detect_failure_reason("", timed_out=True),
            "Timed out waiting for phase completion",
        )
        self.assertEqual(
            detect_failure_reason(
                "I reached the maximum number of tool call iterations (40) without completing the task.",
                timed_out=False,
            ),
            "Tool-call iteration limit reached",
        )


if __name__ == "__main__":
    unittest.main()
