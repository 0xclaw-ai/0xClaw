"""Tests for _reset_phase_and_downstream artifact cleanup.

Uses AST extraction (same technique as test_safe_resets.py) to run the
function in isolation without importing all of main.py's runtime deps.
"""
import ast
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))
MAIN_PATH = ROOT / "0xclaw" / "main.py"


def _load_reset_phase_helper() -> dict:
    """Extract _reset_phase_and_downstream from main.py via AST."""
    source = MAIN_PATH.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(MAIN_PATH))

    selected = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_reset_phase_and_downstream":
            selected.append(node)
            break

    from orchestration.state import PHASES, PHASE_COMPLETION_ARTIFACTS, PipelineStateStore
    from orchestration.phase_completion import clear_marker

    phases_list = list(PHASES)

    namespace: dict = {
        "Path": Path,
        "shutil": shutil,
        "PHASE_COMPLETION_ARTIFACTS": PHASE_COMPLETION_ARTIFACTS,
        "PHASES_LIST": phases_list,
        "PipelineStateStore": PipelineStateStore,
        "clear_marker": clear_marker,
    }
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(MAIN_PATH), "exec")
    exec(compiled, namespace)
    return namespace


class RedoCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _load_reset_phase_helper()

    def _make_state(self, tmp_root: Path) -> tuple[Path, object]:
        hackathon_dir = tmp_root / "hackathon"
        hackathon_dir.mkdir(parents=True, exist_ok=True)
        from orchestration.state import PipelineStateStore

        store = PipelineStateStore(hackathon_dir)
        state = store.load()
        for row in state["phases"]:
            row["status"] = "done"
        state["last_checkpoint"] = "doc"
        store.save(state)
        return hackathon_dir, store

    def _write_all_artifacts(self, hackathon_dir: Path) -> None:
        """Create realistic completion artifacts for all phases."""
        (hackathon_dir / "context.json").write_text('{"k":1}' * 5, encoding="utf-8")
        (hackathon_dir / "research_summary.md").write_text("# Research\n" * 5, encoding="utf-8")
        (hackathon_dir / "ideas.json").write_text('[{"id":1}]' * 5, encoding="utf-8")
        (hackathon_dir / "selected_idea.json").write_text('{"id":1}' * 5, encoding="utf-8")
        (hackathon_dir / "plan.md").write_text("# Plan\n" * 5, encoding="utf-8")
        (hackathon_dir / "tasks.json").write_text('[{"t":1}]' * 5, encoding="utf-8")

        project = hackathon_dir / "project"
        project.mkdir(exist_ok=True)
        (project / "main.py").write_text("print('ok')" * 2, encoding="utf-8")
        (project / "README.md").write_text("# Project Readme\n" * 5, encoding="utf-8")

        (hackathon_dir / "test_results.json").write_text('{"ok":1}' * 5, encoding="utf-8")

        submission = hackathon_dir / "submission"
        submission.mkdir(exist_ok=True)
        (submission / "README.md").write_text("# Readme\n" * 5, encoding="utf-8")
        (submission / "SUBMISSION.md").write_text("# Submission\n" * 5, encoding="utf-8")
        (submission / "PITCH.md").write_text("# Pitch\n" * 5, encoding="utf-8")

    def test_redo_idea_deletes_downstream_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            reset = ns["_reset_phase_and_downstream"]("idea", store)

            self.assertIn("idea", reset)
            self.assertIn("selection", reset)
            self.assertIn("planning", reset)
            self.assertIn("coding", reset)
            self.assertIn("testing", reset)
            self.assertIn("doc", reset)

            self.assertFalse((hackathon_dir / "ideas.json").exists())
            self.assertFalse((hackathon_dir / "selected_idea.json").exists())
            self.assertFalse((hackathon_dir / "plan.md").exists())
            self.assertFalse((hackathon_dir / "tasks.json").exists())
            self.assertFalse((hackathon_dir / "project").exists())
            self.assertFalse((hackathon_dir / "test_results.json").exists())
            self.assertFalse((hackathon_dir / "submission" / "README.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "SUBMISSION.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "PITCH.md").exists())

            self.assertTrue((hackathon_dir / "context.json").exists())
            self.assertTrue((hackathon_dir / "research_summary.md").exists())

    def test_redo_research_deletes_all_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            reset = ns["_reset_phase_and_downstream"]("research", store)

            self.assertIn("research", reset)
            self.assertFalse((hackathon_dir / "context.json").exists())
            self.assertFalse((hackathon_dir / "research_summary.md").exists())
            self.assertFalse((hackathon_dir / "ideas.json").exists())

    def test_redo_planning_preserves_checkpoint_at_selection(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            ns["_reset_phase_and_downstream"]("planning", store)

            state = store.load()
            self.assertEqual(state["last_checkpoint"], "selection")

    def test_redo_research_clears_checkpoint_to_none(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            ns["_reset_phase_and_downstream"]("research", store)

            state = store.load()
            self.assertIsNone(state["last_checkpoint"])

    def test_redo_testing_only_deletes_testing_and_doc(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            ns["_reset_phase_and_downstream"]("testing", store)

            self.assertTrue((hackathon_dir / "context.json").exists())
            self.assertTrue((hackathon_dir / "research_summary.md").exists())
            self.assertTrue((hackathon_dir / "ideas.json").exists())
            self.assertTrue((hackathon_dir / "selected_idea.json").exists())
            self.assertTrue((hackathon_dir / "plan.md").exists())
            self.assertTrue((hackathon_dir / "tasks.json").exists())
            self.assertTrue((hackathon_dir / "project").exists())
            self.assertTrue((hackathon_dir / "project" / "main.py").exists())

            self.assertFalse((hackathon_dir / "project" / "README.md").exists())
            self.assertFalse((hackathon_dir / "test_results.json").exists())
            self.assertFalse((hackathon_dir / "submission" / "README.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "SUBMISSION.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "PITCH.md").exists())

    def test_redo_doc_deletes_project_readme_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hackathon_dir, store = self._make_state(tmp_root)
            self._write_all_artifacts(hackathon_dir)

            ns = self.ns
            ns["HACKATHON_DIR"] = hackathon_dir

            ns["_reset_phase_and_downstream"]("doc", store)

            self.assertFalse((hackathon_dir / "submission" / "README.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "SUBMISSION.md").exists())
            self.assertFalse((hackathon_dir / "submission" / "PITCH.md").exists())
            self.assertFalse((hackathon_dir / "project" / "README.md").exists())
            self.assertTrue((hackathon_dir / "project" / "main.py").exists())


if __name__ == "__main__":
    unittest.main()
