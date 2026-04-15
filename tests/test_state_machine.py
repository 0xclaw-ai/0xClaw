"""Tests for orchestration.state — PipelineStateStore and OrchestratorStateMachine."""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.state import (
    COMPLETED_PHASE_STATUSES,
    PHASES,
    OrchestratorStateMachine,
    PipelineStateStore,
    reconcile_pipeline_state,
)


class PipelineStateStoreTests(unittest.TestCase):
    def test_load_returns_default_when_no_file(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.load()
            self.assertIsNone(state["current_phase"])
            self.assertEqual(len(state["phases"]), 7)
            for row in state["phases"]:
                self.assertEqual(row["status"], "pending")

    def test_save_and_load_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.load()
            state["current_phase"] = "research"
            store.save(state)

            loaded = store.load()
            self.assertEqual(loaded["current_phase"], "research")
            self.assertIn("updated_at", loaded)

    def test_save_creates_file(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.load()
            store.save(state)
            self.assertTrue(store.path.exists())

    def test_set_phase_status_running_sets_current_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.set_phase_status("research", "running")
            self.assertEqual(state["current_phase"], "research")

    def test_set_phase_status_done_clears_current_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            store.set_phase_status("research", "running")
            state = store.set_phase_status("research", "done")
            self.assertIsNone(state["current_phase"])

    def test_set_phase_status_done_sets_last_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.set_phase_status("research", "done")
            self.assertEqual(state["last_checkpoint"], "research")

    def test_set_phase_status_failed_clears_active_task(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            store.set_phase_status("coding", "running", active_task="task-1")
            state = store.set_phase_status("coding", "failed", last_error="Timeout")
            self.assertIsNone(state["active_task"])
            self.assertEqual(state["last_error"], "Timeout")

    def test_set_phase_status_cancelled_clears_active_task(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            store.set_phase_status("coding", "running", active_task="task-2")
            state = store.set_phase_status("coding", "cancelled")
            self.assertIsNone(state["active_task"])

    def test_set_phase_status_running_preserves_active_task(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.set_phase_status("coding", "running", active_task="task-3")
            self.assertEqual(state["active_task"], "task-3")

    def test_set_phase_status_records_last_error(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.set_phase_status("idea", "failed", last_error="API 400")
            self.assertEqual(state["last_error"], "API 400")

    def test_set_phase_status_updates_phase_row(self) -> None:
        with TemporaryDirectory() as tmp:
            store = PipelineStateStore(Path(tmp))
            state = store.set_phase_status("selection", "done")
            for row in state["phases"]:
                if row["name"] == "selection":
                    self.assertEqual(row["status"], "done")
                    self.assertIsNotNone(row["updated_at"])
                    break
            else:
                self.fail("selection phase not found in state")


class OrchestratorStateMachineValidationTests(unittest.TestCase):
    def test_validate_unknown_phase_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            sm = OrchestratorStateMachine(workspace, store)

            result = sm.validate_phase_entry("bogus")
            self.assertFalse(result.ok)
            self.assertIn("Unknown phase", result.errors[0])

    def test_validate_research_always_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            sm = OrchestratorStateMachine(workspace, store)

            result = sm.validate_phase_entry("research")
            self.assertTrue(result.ok, result.errors)

    def test_validate_idea_fails_without_research(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            sm = OrchestratorStateMachine(workspace, store)

            result = sm.validate_phase_entry("idea")
            self.assertFalse(result.ok)

    def test_validate_idea_passes_with_research_done(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            store.set_phase_status("research", "done")
            (hackathon_dir / "context.json").write_text('{"valid": true}', encoding="utf-8")
            (hackathon_dir / "research_summary.md").write_text("# summary\n" * 5, encoding="utf-8")

            sm = OrchestratorStateMachine(workspace, store)
            result = sm.validate_phase_entry("idea")
            self.assertTrue(result.ok, result.errors)

    def test_validate_auto_marks_dependency_done(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            # research status is "pending" but output files exist
            (hackathon_dir / "context.json").write_text('{"auto": "mark"}' * 2, encoding="utf-8")
            (hackathon_dir / "research_summary.md").write_text("# summary\n" * 5, encoding="utf-8")

            sm = OrchestratorStateMachine(workspace, store)
            result = sm.validate_phase_entry("idea")
            self.assertTrue(result.ok, result.errors)

            # Verify research was auto-marked as done
            loaded = store.load()
            status_map = {row["name"]: row["status"] for row in loaded["phases"]}
            self.assertIn(status_map["research"], COMPLETED_PHASE_STATUSES)

    def test_validate_missing_artifact_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            hackathon_dir = workspace / "hackathon"
            hackathon_dir.mkdir()
            store = PipelineStateStore(hackathon_dir)
            store.set_phase_status("research", "done")
            # context.json intentionally missing

            sm = OrchestratorStateMachine(workspace, store)
            result = sm.validate_phase_entry("idea")
            self.assertFalse(result.ok)
            self.assertTrue(any("context.json" in e for e in result.errors))


class OrchestratorWritePermissionTests(unittest.TestCase):
    def _make_sm(self, tmp: str) -> OrchestratorStateMachine:
        workspace = Path(tmp)
        hackathon_dir = workspace / "hackathon"
        hackathon_dir.mkdir(exist_ok=True)
        store = PipelineStateStore(hackathon_dir)
        return OrchestratorStateMachine(workspace, store)

    def test_is_write_allowed_positive(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            self.assertTrue(sm.is_write_allowed("research", "hackathon/context.json"))
            self.assertTrue(sm.is_write_allowed("coding", "hackathon/project"))
            self.assertTrue(sm.is_write_allowed("doc", "hackathon/submission"))

    def test_is_write_allowed_negative(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            self.assertFalse(sm.is_write_allowed("research", "hackathon/ideas.json"))
            self.assertFalse(sm.is_write_allowed("idea", "hackathon/context.json"))
            self.assertFalse(sm.is_write_allowed("coding", "hackathon/ideas.json"))

    def test_is_write_allowed_prefix_matching(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            self.assertTrue(sm.is_write_allowed("coding", "hackathon/project/src/main.py"))
            self.assertTrue(sm.is_write_allowed("doc", "hackathon/submission/README.md"))

    def test_is_write_allowed_all_phases_can_write_state(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            for phase in PHASES:
                self.assertTrue(
                    sm.is_write_allowed(phase, "hackathon/pipeline_state.json"),
                    f"{phase} should be able to write pipeline_state.json",
                )
                self.assertTrue(
                    sm.is_write_allowed(phase, "hackathon/progress.md"),
                    f"{phase} should be able to write progress.md",
                )

    def test_is_write_allowed_normalizes_leading_slash(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            self.assertTrue(sm.is_write_allowed("research", "/hackathon/context.json"))

    def test_assert_write_allowed_raises_permission_error(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            with self.assertRaises(PermissionError) as ctx:
                sm.assert_write_allowed("research", "hackathon/ideas.json")
            self.assertIn("research", str(ctx.exception))

    def test_checkpoint_delegates_to_store(self) -> None:
        with TemporaryDirectory() as tmp:
            sm = self._make_sm(tmp)
            state = sm.checkpoint("research", "done")
            self.assertEqual(state["last_checkpoint"], "research")


class ReconcilePipelineStateTests(unittest.TestCase):
    """Tests for reconcile_pipeline_state fill-gap logic."""

    def _make_store(self, tmp: str) -> tuple[Path, "PipelineStateStore"]:
        workspace = Path(tmp)
        hackathon_dir = workspace / "hackathon"
        hackathon_dir.mkdir(parents=True)
        return hackathon_dir, PipelineStateStore(hackathon_dir)

    def _write(self, path: Path, content: str = '{"ok": true, "padding": "xxxxxxxxxx"}') -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # ── no artifacts ──────────────────────────────────────────────────────────

    def test_no_artifacts_leaves_all_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            for phase in PHASES:
                self.assertEqual(status_map[phase], "pending", f"{phase} should stay pending")

    def test_no_artifacts_does_not_write_state_file(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            reconcile_pipeline_state(store)
            # No artifacts → no changes → file not written
            self.assertFalse(store.path.exists())

    # ── single phase artifacts ─────────────────────────────────────────────────

    def test_research_artifact_marks_research_done(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            self.assertIn(status_map["research"], COMPLETED_PHASE_STATUSES)
            for phase in ("idea", "selection", "planning", "coding", "testing", "doc"):
                self.assertEqual(status_map[phase], "pending")

    def test_research_artifact_updates_last_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            state = reconcile_pipeline_state(store)
            self.assertEqual(state["last_checkpoint"], "research")

    def test_research_requires_summary_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            self.assertEqual(status_map["research"], "pending")

    def test_doc_requires_all_submission_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "submission" / "README.md", "# readme\n" * 5)
            self._write(hackathon_dir / "submission" / "SUBMISSION.md", "# submission\n" * 5)
            self._write(hackathon_dir / "submission" / "PITCH.md", "# pitch\n" * 5)
            self._write(hackathon_dir / "project" / "README.md", "# project readme\n" * 5)
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            self.assertIn(status_map["doc"], COMPLETED_PHASE_STATUSES)

    def test_doc_missing_project_readme_stays_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "submission" / "README.md", "# readme\n" * 5)
            self._write(hackathon_dir / "submission" / "SUBMISSION.md", "# submission\n" * 5)
            self._write(hackathon_dir / "submission" / "PITCH.md", "# pitch\n" * 5)
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            self.assertEqual(status_map["doc"], "pending")

    def test_no_artifacts_resets_stale_done_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            state = store.load()
            for row in state["phases"]:
                row["status"] = "done"
            state["last_checkpoint"] = "doc"
            store.save(state)
            reconciled = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in reconciled["phases"]}
            for phase in PHASES:
                self.assertEqual(status_map[phase], "pending")
            self.assertIsNone(reconciled["last_checkpoint"])

    def test_no_artifacts_clears_stale_running_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            state = store.load()
            state["current_phase"] = "coding"
            state["active_task"] = "task-123"
            for row in state["phases"]:
                if row["name"] == "coding":
                    row["status"] = "running"
            store.save(state)
            reconciled = reconcile_pipeline_state(store)
            self.assertIsNone(reconciled["current_phase"])
            self.assertIsNone(reconciled["active_task"])
            status_map = {r["name"]: r["status"] for r in reconciled["phases"]}
            self.assertEqual(status_map["coding"], "pending")

    def test_no_artifacts_clears_last_error(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            state = store.load()
            state["last_error"] = "stale error"
            store.save(state)
            reconciled = reconcile_pipeline_state(store)
            self.assertIsNone(reconciled["last_error"])

    # ── fill-gap logic ─────────────────────────────────────────────────────────

    def test_planning_artifacts_fill_gap_to_research(self) -> None:
        """All phases up to planning are marked done even if earlier artifacts are absent."""
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            # Only planning artifacts present; research/idea/selection have no files
            self._write(hackathon_dir / "plan.md")
            self._write(hackathon_dir / "tasks.json")
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            for phase in ("research", "idea", "selection", "planning"):
                self.assertIn(status_map[phase], COMPLETED_PHASE_STATUSES, f"{phase} should be done")
            for phase in ("coding", "testing", "doc"):
                self.assertEqual(status_map[phase], "pending")

    def test_planning_requires_both_artifacts(self) -> None:
        """planning is NOT considered complete with only plan.md (tasks.json missing)."""
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "plan.md")
            # tasks.json intentionally absent
            state = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in state["phases"]}
            self.assertEqual(status_map["planning"], "pending")

    # ── stale "done" status reset ──────────────────────────────────────────────

    def test_stale_done_status_reset_when_beyond_highest(self) -> None:
        """Phase marked 'done' in state but artifacts deleted → reset to pending."""
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            # Mark all phases done in state file, but only research artifacts exist
            state = store.load()
            for row in state["phases"]:
                row["status"] = "done"
            store.save(state)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)

            reconciled = reconcile_pipeline_state(store)
            status_map = {r["name"]: r["status"] for r in reconciled["phases"]}
            self.assertIn(status_map["research"], COMPLETED_PHASE_STATUSES)
            for phase in ("idea", "selection", "planning", "coding", "testing", "doc"):
                self.assertEqual(status_map[phase], "pending", f"stale 'done' for {phase} should be reset")

    # ── persist=False ──────────────────────────────────────────────────────────

    def test_persist_false_does_not_write_file(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            reconcile_pipeline_state(store, persist=False)
            # Even though research is complete, persist=False → no file written
            self.assertFalse(store.path.exists())

    def test_persist_true_writes_file(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            reconcile_pipeline_state(store, persist=True)
            self.assertTrue(store.path.exists())
            loaded = store.load()
            status_map = {r["name"]: r["status"] for r in loaded["phases"]}
            self.assertIn(status_map["research"], COMPLETED_PHASE_STATUSES)

    # ── current_phase / active_task clearing ──────────────────────────────────

    def test_stale_current_phase_cleared(self) -> None:
        """current_phase stuck as non-running phase is cleared during reconcile."""
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            state = store.load()
            state["current_phase"] = "research"
            state["active_task"] = "task-xyz"
            store.save(state)
            reconciled = reconcile_pipeline_state(store)
            self.assertIsNone(reconciled["current_phase"])
            self.assertIsNone(reconciled["active_task"])

    # ── last_error clearing ────────────────────────────────────────────────────

    def test_last_error_cleared_when_no_failed_phases(self) -> None:
        with TemporaryDirectory() as tmp:
            hackathon_dir, store = self._make_store(tmp)
            self._write(hackathon_dir / "context.json")
            self._write(hackathon_dir / "research_summary.md", "# summary\n" * 5)
            state = store.load()
            state["last_error"] = "some old error"
            store.save(state)
            reconciled = reconcile_pipeline_state(store)
            self.assertIsNone(reconciled["last_error"])


if __name__ == "__main__":
    unittest.main()
