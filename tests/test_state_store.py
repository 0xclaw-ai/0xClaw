from __future__ import annotations


def test_planning_blocked_without_selected_idea(tmp_path, state_mod):
    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    store = state_mod.PipelineStateStore(hackathon)
    sm = state_mod.OrchestratorStateMachine(workspace, store)

    store.set_phase_status("research", "done")
    store.set_phase_status("idea", "done")

    result = sm.validate_phase_entry("planning")
    assert not result.ok
    assert any("selected_idea.json" in e for e in result.errors)


def test_write_whitelist_enforced(tmp_path, state_mod):
    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    sm = state_mod.OrchestratorStateMachine(workspace, state_mod.PipelineStateStore(hackathon))

    assert sm.is_write_allowed("planning", "hackathon/plan.md")
    assert not sm.is_write_allowed("planning", "hackathon/project/api/main.py")


def test_dependencies_pass_when_ready(tmp_path, state_mod):
    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    (hackathon / "context.json").write_text("{}", encoding="utf-8")
    (hackathon / "ideas.json").write_text("{}", encoding="utf-8")
    (hackathon / "selected_idea.json").write_text("{}", encoding="utf-8")

    store = state_mod.PipelineStateStore(hackathon)
    sm = state_mod.OrchestratorStateMachine(workspace, store)

    store.set_phase_status("research", "done")
    store.set_phase_status("idea", "done")
    store.set_phase_status("selection", "done")

    result = sm.validate_phase_entry("planning")
    assert result.ok
