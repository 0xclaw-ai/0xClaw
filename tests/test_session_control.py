from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.session_control import SessionControl
from orchestration.state import PipelineStateStore


class SessionControlTests(unittest.TestCase):
    def test_resume_prefers_failed_phase_over_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            store.set_phase_status("research", "done")
            store.set_phase_status("idea", "done")
            store.set_phase_status("selection", "done")
            store.set_phase_status("planning", "done")
            store.set_phase_status("coding", "failed", last_error="Timed out")

            decision = SessionControl(store).get_resume_decision()

            self.assertEqual(decision.phase, "coding")
            self.assertEqual(decision.command, "start coding")

    def test_done_phase_clears_current_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            store.set_phase_status("coding", "running", active_task="trace-1")
            state = store.set_phase_status("coding", "done")

            self.assertIsNone(state["current_phase"])
            self.assertIsNone(state["active_task"])
            self.assertEqual(state["last_checkpoint"], "coding")


if __name__ == "__main__":
    unittest.main()
