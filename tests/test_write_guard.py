from __future__ import annotations

from pathlib import Path


def test_phase_write_guard_blocks_workspace_workspace_path(tmp_path, state_mod):
    import importlib

    write_guard_mod = importlib.import_module("0xclaw.orchestration.write_guard")

    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    store = state_mod.PipelineStateStore(hackathon)
    sm = state_mod.OrchestratorStateMachine(workspace, store)

    guard = write_guard_mod.build_phase_write_guard(
        workspace=workspace,
        state_machine=sm,
        get_phase=lambda: "idea",
    )

    # idea phase should only write hackathon/ideas.json, not workspace/workspace/ideas.md
    err = guard("workspace/ideas.md")
    assert err is not None
    assert "cannot write" in err


def test_phase_write_guard_allows_expected_output(tmp_path, state_mod):
    import importlib

    write_guard_mod = importlib.import_module("0xclaw.orchestration.write_guard")

    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    store = state_mod.PipelineStateStore(hackathon)
    sm = state_mod.OrchestratorStateMachine(workspace, store)

    guard = write_guard_mod.build_phase_write_guard(
        workspace=workspace,
        state_machine=sm,
        get_phase=lambda: "idea",
    )

    assert guard("hackathon/ideas.json") is None


def test_main_and_runner_install_write_guard():
    main_content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    runner_content = Path("scripts/run_phase.py").read_text(encoding="utf-8")

    assert "install_phase_write_guards(agent.tools, write_guard)" in main_content
    assert "agent.subagents.set_write_guard(write_guard)" in main_content

    assert "install_phase_write_guards(agent.tools, write_guard)" in runner_content
    assert "agent.subagents.set_write_guard(write_guard)" in runner_content
