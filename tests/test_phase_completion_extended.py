"""Extended tests for orchestration.phase_completion — edge cases and full pattern coverage."""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.phase_completion import (
    _FAILURE_PATTERNS,
    clear_marker,
    detect_failure_reason,
    is_phase_complete,
    marker_path,
    output_exists,
    write_marker,
)


class OutputExistsTests(unittest.TestCase):
    def test_none_path_returns_false(self) -> None:
        self.assertFalse(output_exists(None))

    def test_missing_file_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertFalse(output_exists(Path(tmp) / "nonexistent.json"))

    def test_empty_dir_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            self.assertFalse(output_exists(empty_dir))

    def test_dir_with_content_returns_true(self) -> None:
        with TemporaryDirectory() as tmp:
            content_dir = Path(tmp) / "project"
            content_dir.mkdir()
            (content_dir / "main.py").write_text("print('hello')", encoding="utf-8")
            self.assertTrue(output_exists(content_dir))

    def test_small_file_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            small = Path(tmp) / "tiny.json"
            small.write_text("12345", encoding="utf-8")  # 5 bytes
            self.assertFalse(output_exists(small))

    def test_large_file_returns_true(self) -> None:
        with TemporaryDirectory() as tmp:
            large = Path(tmp) / "valid.json"
            large.write_text('{"valid": "data!!"}', encoding="utf-8")  # > 10 bytes
            self.assertTrue(output_exists(large))

    def test_exactly_10_bytes_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            exact = Path(tmp) / "exact.txt"
            exact.write_text("1234567890", encoding="utf-8")  # exactly 10 bytes
            self.assertFalse(output_exists(exact))

    def test_11_bytes_returns_true(self) -> None:
        with TemporaryDirectory() as tmp:
            over = Path(tmp) / "over.txt"
            over.write_text("12345678901", encoding="utf-8")  # 11 bytes
            self.assertTrue(output_exists(over))


class MarkerPathTests(unittest.TestCase):
    def test_marker_path_coding_returns_path(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            path = marker_path(hackathon_dir, "coding")
            self.assertIsNotNone(path)
            self.assertEqual(path.name, "coding.done.json")

    def test_marker_path_non_coding_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            for phase in ("research", "idea", "selection", "planning", "testing", "doc"):
                self.assertIsNone(
                    marker_path(hackathon_dir, phase),
                    f"marker_path for {phase} should be None",
                )


class WriteAndClearMarkerTests(unittest.TestCase):
    def test_write_and_clear_marker_lifecycle(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            path = write_marker(hackathon_dir, "coding")
            self.assertIsNotNone(path)
            self.assertTrue(path.exists())

            clear_marker(hackathon_dir, "coding")
            self.assertFalse(path.exists())

    def test_write_marker_non_coding_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            result = write_marker(hackathon_dir, "research")
            self.assertIsNone(result)

    def test_clear_marker_nonexistent_is_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            # Should not raise
            clear_marker(hackathon_dir, "coding")
            clear_marker(hackathon_dir, "research")


class IsPhaseCompleteTests(unittest.TestCase):
    def test_coding_requires_marker_and_output(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            project_dir = hackathon_dir / "project"
            project_dir.mkdir()
            (project_dir / "main.py").write_text("print('hello')", encoding="utf-8")

            # Output exists but no marker
            self.assertFalse(
                is_phase_complete("coding", hackathon_dir=hackathon_dir, phase_output=project_dir)
            )

            # Both marker and output
            write_marker(hackathon_dir, "coding")
            self.assertTrue(
                is_phase_complete("coding", hackathon_dir=hackathon_dir, phase_output=project_dir)
            )

    def test_non_coding_only_requires_output(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            output = hackathon_dir / "context.json"
            output.write_text('{"research": "done!!"}', encoding="utf-8")
            self.assertTrue(
                is_phase_complete("research", hackathon_dir=hackathon_dir, phase_output=output)
            )

    def test_missing_output_is_incomplete(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            missing = hackathon_dir / "nonexistent.json"
            self.assertFalse(
                is_phase_complete("research", hackathon_dir=hackathon_dir, phase_output=missing)
            )


class DetectFailureReasonTests(unittest.TestCase):
    def test_timed_out_returns_timeout_reason(self) -> None:
        result = detect_failure_reason("anything", timed_out=True)
        self.assertEqual(result, "Timed out waiting for phase completion")

    def test_all_six_failure_patterns(self) -> None:
        for needle, expected_reason in _FAILURE_PATTERNS:
            result = detect_failure_reason(f"Some text with {needle} in it.", timed_out=False)
            self.assertEqual(
                result, expected_reason,
                f"Pattern '{needle}' should produce reason '{expected_reason}'",
            )

    def test_empty_response_returns_none(self) -> None:
        self.assertIsNone(detect_failure_reason("", timed_out=False))

    def test_none_response_returns_none(self) -> None:
        self.assertIsNone(detect_failure_reason(None, timed_out=False))

    def test_clean_response_returns_none(self) -> None:
        self.assertIsNone(detect_failure_reason("Task completed successfully!", timed_out=False))


if __name__ == "__main__":
    unittest.main()
