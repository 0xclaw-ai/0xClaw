from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

import main


class InterpretStopResponseTests(unittest.TestCase):
    def test_stopped_one_task_with_glyph(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("⏹ Stopped 1 task(s).", None)
        self.assertTrue(confirmed)
        self.assertTrue(stopped_work)

    def test_stopped_multiple_tasks_plain(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("Stopped 3 task(s).", None)
        self.assertTrue(confirmed)
        self.assertTrue(stopped_work)

    def test_stopped_zero_tasks_with_glyph(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("⏹ Stopped 0 task(s).", None)
        self.assertTrue(confirmed)
        self.assertFalse(stopped_work)

    def test_stopped_zero_tasks_plain(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("Stopped 0 task(s).", None)
        self.assertTrue(confirmed)
        self.assertFalse(stopped_work)

    def test_no_active_task_message(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("No active task to stop.", None)
        self.assertTrue(confirmed)
        self.assertFalse(stopped_work)

    def test_no_active_task_message_with_whitespace(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response(
            "  No active task to stop.\n", None
        )
        self.assertTrue(confirmed)
        self.assertFalse(stopped_work)

    def test_unrelated_response_is_not_confirmed(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("Acknowledged.", None)
        self.assertFalse(confirmed)
        self.assertFalse(stopped_work)

    def test_empty_response_is_not_confirmed(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("", None)
        self.assertFalse(confirmed)
        self.assertFalse(stopped_work)

    def test_stopped_phrase_without_task_suffix_is_not_confirmed(self) -> None:
        confirmed, stopped_work = main._interpret_stop_response("Stopped 5 widgets.", None)
        self.assertFalse(confirmed)
        self.assertFalse(stopped_work)


if __name__ == "__main__":
    unittest.main()
