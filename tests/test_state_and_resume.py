from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.session_control import SessionControl
from orchestration.state import OrchestratorStateMachine, PipelineStateStore


class StateAndResumeTests(unittest.TestCase):
    def test_validate_phase_entry_blocks_missing_dependencies(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = PipelineStateStore(workspace / "hackathon")
            machine = OrchestratorStateMachine(workspace, store)
            result = machine.validate_phase_entry("planning")
            self.assertFalse(result.ok)
            self.assertTrue(any("Dependency not complete: selection" in e for e in result.errors))

    def test_validate_phase_entry_auto_completes_dependency_when_output_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon = workspace / "hackathon"
            hackathon.mkdir(parents=True)
            (hackathon / "selected_idea.json").write_text(
                '{"name":"demo-idea","summary":"enough-content"}',
                encoding="utf-8",
            )

            store = PipelineStateStore(hackathon)
            machine = OrchestratorStateMachine(workspace, store)
            result = machine.validate_phase_entry("planning")
            self.assertTrue(result.ok, result.errors)

            state = store.load()
            row = {r["name"]: r["status"] for r in state["phases"]}
            self.assertEqual(row["selection"], "done")

    def test_resume_priority_running_then_failed_then_cancelled(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon = Path(tmp)
            (hackathon / "context.json").write_text('{"ok": true, "padding": "xxxxxxxxxx"}', encoding="utf-8")
            (hackathon / "research_summary.md").write_text("# summary\n" * 5, encoding="utf-8")
            (hackathon / "ideas.json").write_text('[{"id":1,"padding":"xxxxxxxxxx"}]', encoding="utf-8")
            (hackathon / "selected_idea.json").write_text('{"id":1,"padding":"xxxxxxxxxx"}', encoding="utf-8")
            (hackathon / "plan.md").write_text("# plan\n" * 5, encoding="utf-8")
            (hackathon / "tasks.json").write_text('[{"id":1,"padding":"xxxxxxxxxx"}]', encoding="utf-8")
            project = hackathon / "project"
            project.mkdir()
            (project / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (hackathon / "coding.done.json").write_text('{"phase":"coding","status":"done"}', encoding="utf-8")

            store = PipelineStateStore(hackathon)
            state = store.load()

            for row in state["phases"]:
                if row["name"] == "testing":
                    row["status"] = "running"
                if row["name"] == "doc":
                    row["status"] = "failed"
            state["current_phase"] = "testing"
            store.save(state)

            decision = SessionControl(store).get_resume_decision()
            self.assertEqual(decision.phase, "testing")
            self.assertEqual(decision.command, "run tests")
            self.assertIn("current phase", decision.reason.lower())

            state = store.load()
            state["current_phase"] = None
            for row in state["phases"]:
                if row["name"] == "testing":
                    row["status"] = "failed"
                if row["name"] == "doc":
                    row["status"] = "pending"
            store.save(state)

            decision = SessionControl(store).get_resume_decision()
            self.assertEqual(decision.phase, "testing")
            self.assertEqual(decision.command, "run tests")
            self.assertIn("failed", decision.reason)

            state = store.load()
            for row in state["phases"]:
                if row["name"] == "testing":
                    row["status"] = "cancelled"
            state["last_error"] = "Cancelled by /stop"
            store.save(state)

            decision = SessionControl(store).get_resume_decision()
            self.assertEqual(decision.phase, "testing")
            self.assertEqual(decision.command, "run tests")
            self.assertIn("cancelled", decision.reason)


if __name__ == "__main__":
    unittest.main()
