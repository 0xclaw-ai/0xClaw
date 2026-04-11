"""Tests for orchestration.write_guard — phase-aware filesystem write guards."""

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.state import (
    PHASES,
    OrchestratorStateMachine,
    PipelineStateStore,
)
from orchestration.write_guard import build_phase_write_guard, install_phase_write_guards


class BuildPhaseWriteGuardTests(unittest.TestCase):
    def _make_guard(self, tmp: str, phase_holder: list):
        workspace = Path(tmp)
        hackathon_dir = workspace / "hackathon"
        hackathon_dir.mkdir(exist_ok=True)
        store = PipelineStateStore(hackathon_dir)
        sm = OrchestratorStateMachine(workspace, store)
        guard = build_phase_write_guard(
            workspace=workspace,
            state_machine=sm,
            get_phase=lambda: phase_holder[0],
        )
        return guard

    def test_guard_allows_valid_write_for_research(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["research"])
            result = guard(str(Path(tmp) / "hackathon" / "context.json"))
            self.assertIsNone(result)

    def test_guard_blocks_cross_phase_write(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["research"])
            result = guard(str(Path(tmp) / "hackathon" / "ideas.json"))
            self.assertIsNotNone(result)
            self.assertIn("research", result)

    def test_guard_allows_pipeline_state_for_all_phases(self) -> None:
        with TemporaryDirectory() as tmp:
            for phase in PHASES:
                guard = self._make_guard(tmp, [phase])
                result = guard(str(Path(tmp) / "hackathon" / "pipeline_state.json"))
                self.assertIsNone(result, f"{phase} should be able to write pipeline_state.json")

    def test_guard_allows_progress_for_all_phases(self) -> None:
        with TemporaryDirectory() as tmp:
            for phase in PHASES:
                guard = self._make_guard(tmp, [phase])
                result = guard(str(Path(tmp) / "hackathon" / "progress.md"))
                self.assertIsNone(result, f"{phase} should be able to write progress.md")

    def test_guard_allows_nested_path_for_coding(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["coding"])
            result = guard(str(Path(tmp) / "hackathon" / "project" / "src" / "main.py"))
            self.assertIsNone(result)

    def test_guard_allows_nested_path_for_doc(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["doc"])
            result = guard(str(Path(tmp) / "hackathon" / "submission" / "README.md"))
            self.assertIsNone(result)

    def test_guard_blocks_outside_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["research"])
            result = guard("/tmp/outside/evil.txt")
            self.assertIsNotNone(result)
            self.assertIn("outside workspace", result)

    def test_guard_returns_none_when_no_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, [None])
            result = guard(str(Path(tmp) / "hackathon" / "anything.txt"))
            self.assertIsNone(result)

    def test_guard_handles_relative_path(self) -> None:
        with TemporaryDirectory() as tmp:
            guard = self._make_guard(tmp, ["research"])
            result = guard("hackathon/context.json")
            self.assertIsNone(result)


class InstallPhaseWriteGuardsTests(unittest.TestCase):
    """Test that install_phase_write_guards wraps tool execute methods."""

    def _make_mock_tool(self):
        class MockTool:
            def __init__(self):
                self.called = False

            async def execute(self, **kwargs):
                self.called = True
                return "original result"

        return MockTool()

    def _make_mock_registry(self, tools: dict):
        class MockRegistry:
            def __init__(self, _tools):
                self._tools = _tools

            def get(self, name):
                return self._tools.get(name)

        return MockRegistry(tools)

    def test_install_wraps_write_file_tool(self) -> None:
        tool = self._make_mock_tool()
        original_execute = tool.execute
        registry = self._make_mock_registry({"write_file": tool})
        guard = lambda path: None  # noqa: E731
        install_phase_write_guards(registry, guard)
        self.assertIsNot(tool.execute, original_execute)

    def test_install_wraps_edit_file_tool(self) -> None:
        tool = self._make_mock_tool()
        original_execute = tool.execute
        registry = self._make_mock_registry({"edit_file": tool})
        guard = lambda path: None  # noqa: E731
        install_phase_write_guards(registry, guard)
        self.assertIsNot(tool.execute, original_execute)

    def test_install_skips_missing_tool(self) -> None:
        registry = self._make_mock_registry({})
        guard = lambda path: None  # noqa: E731
        # Should not raise
        install_phase_write_guards(registry, guard)

    def test_guarded_execute_returns_error_on_violation(self) -> None:
        tool = self._make_mock_tool()
        registry = self._make_mock_registry({"write_file": tool})
        guard = lambda path: "Permission denied: test"  # noqa: E731
        install_phase_write_guards(registry, guard)

        result = asyncio.run(tool.execute(path="hackathon/forbidden.txt"))
        self.assertIn("Error:", result)
        self.assertIn("Permission denied", result)
        self.assertFalse(tool.called)

    def test_guarded_execute_passes_through_on_allowed(self) -> None:
        tool = self._make_mock_tool()
        registry = self._make_mock_registry({"write_file": tool})
        guard = lambda path: None  # noqa: E731
        install_phase_write_guards(registry, guard)

        result = asyncio.run(tool.execute(path="hackathon/context.json"))
        self.assertEqual(result, "original result")
        self.assertTrue(tool.called)


if __name__ == "__main__":
    unittest.main()
