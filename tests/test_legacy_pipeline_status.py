from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.session_control import SessionControl
from orchestration.state import OrchestratorStateMachine, PipelineStateStore


class LegacyPipelineStatusTests(unittest.TestCase):
    def test_complete_status_satisfies_dependencies(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir(parents=True)
            (hackathon_dir / "selected_idea.json").write_text("{}", encoding="utf-8")

            store = PipelineStateStore(hackathon_dir)
            state = store.load()
            for row in state["phases"]:
                if row["name"] in {"research", "idea", "selection"}:
                    row["status"] = "complete"
            state["last_checkpoint"] = "selection"
            store.save(state)

            result = OrchestratorStateMachine(workspace, store).validate_phase_entry("planning")
            self.assertTrue(result.ok, result.errors)

    def test_resume_treats_complete_as_finished(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir = Path(tmp)
            store = PipelineStateStore(hackathon_dir)
            state = store.load()
            for row in state["phases"]:
                if row["name"] in {"research", "idea", "selection"}:
                    row["status"] = "complete"
            state["last_checkpoint"] = "selection"
            store.save(state)

            decision = SessionControl(store).get_resume_decision()
            self.assertEqual(decision.phase, "planning")


if __name__ == "__main__":
    unittest.main()
