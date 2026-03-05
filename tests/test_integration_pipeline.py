from __future__ import annotations


def test_pipeline_flow_with_resume(tmp_path, state_mod, session_mod, router_mod, model_mod):
    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    store = state_mod.PipelineStateStore(hackathon)
    sm = state_mod.OrchestratorStateMachine(workspace, store)
    ctl = session_mod.SessionControl(store)
    router = router_mod.SkillRouter()

    assert router.route("run hackathon research").phase == "research"
    sm.checkpoint("research", "done")
    (hackathon / "context.json").write_text("{}", encoding="utf-8")

    assert sm.validate_phase_entry("idea").ok
    sm.checkpoint("idea", "done")
    (hackathon / "ideas.json").write_text("{}", encoding="utf-8")

    sm.checkpoint("selection", "done")
    (hackathon / "selected_idea.json").write_text("{}", encoding="utf-8")

    assert sm.validate_phase_entry("planning").ok
    sm.checkpoint("planning", "cancelled", last_error="ctrl+c")

    decision = ctl.get_resume_decision()
    assert decision.phase == "planning"
    assert decision.command == "plan architecture"

    resolver = model_mod.ModelProfileResolver(__import__("pathlib").Path("0xclaw/config/model_profiles.json"))
    fallback = resolver.resolve_with_fallback("planning", failed=True)
    assert fallback is not None
    assert fallback.phase in {"planning", "research", "doc"}
