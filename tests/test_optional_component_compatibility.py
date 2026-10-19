"""Exercise installed optional components through the real interactive CLI."""

import json

import pytest

from test_issue_regressions import FollowupProvider, completed_workspace, run_cli

pytest.importorskip("budget_router")
pytest.importorskip("deadline_framer")

from budget_router import BudgetRouterRuntime
from orchestration.model_profiles import ModelProfile
from runtime.config.schema import Config
from runtime.session.manager import SessionManager


@pytest.mark.parametrize("components", ["", "budget-router", "deadline-framer", "budget-router,deadline-framer"])
@pytest.mark.parametrize("entry", ["normal", "resume", "redo"])
def test_components_keep_profiles_frames_and_phase_budgets(monkeypatch, tmp_path, components, entry):
    import main

    store = completed_workspace(tmp_path)
    monkeypatch.setenv("OXCLAW_PHASE_CONTROLS", components)
    monkeypatch.delenv("OXCLAW_ENABLE_BUDGET_DEADLINE", raising=False)
    monkeypatch.setenv("OXCLAW_BUDGET_ROUTER_MODEL_PATH", "./models/base")
    monkeypatch.setenv("OXCLAW_BUDGET_ROUTER_ADAPTER_PATH", "./models/adapter")
    monkeypatch.setenv("OXCLAW_BUDGET_ROUTER_MODE", "enforce")
    monkeypatch.setenv("OXCLAW_DEADLINE_CONTROL_TEMPLATE", "<PHASE_{phase}><TOKEN_0.75X><TIME_HIGH><THINK_LOW><REPAIR_1>")
    monkeypatch.setattr(BudgetRouterRuntime, "_generate", lambda *args: "<PHASE_CODING><TOKEN_0.75X><TIME_HIGH><THINK_LOW><REPAIR_1>")
    monkeypatch.setattr(main.ModelProfileResolver, "resolve", lambda self, phase: ModelProfile(phase, "test", "phase-model", 4000, 0.2, 400))
    waits = []
    original_wait = main.wait_for_turn

    async def capture_wait(*args, **kwargs):
        waits.append((kwargs["phase"], kwargs["timeout_s"]))
        return await original_wait(*args, **kwargs)

    monkeypatch.setattr(main, "wait_for_turn", capture_wait)
    command = "start coding"
    if entry == "resume":
        store.set_phase_status("coding", "failed")
        sessions = SessionManager(tmp_path)
        session = sessions.get_or_create("cli:issue-regression")
        session.add_message("user", "Continue the project")
        sessions.save(session)
        command = "/resume cli:issue-regression"
    elif entry == "redo":
        command = "/redo coding"
    provider = FollowupProvider()
    run_cli(monkeypatch, tmp_path, provider, [command, "hello", "/exit"])
    assert (tmp_path / "hackathon/project/followup.txt").is_file()
    assert provider.parameters[0]["max_tokens"] == (3000 if "budget-router" in components else 4000)
    assert ("Deadline Guidance" in provider.calls[0][-1]["content"]) == ("deadline-framer" in components)
    assert waits[0] == ("coding", 500 if "budget-router" in components else 400)
    assert provider.parameters[-1]["model"] == "test-model"
    assert provider.parameters[-1]["max_tokens"] == Config().agents.defaults.max_tokens
    assert "Deadline Guidance" not in provider.calls[-1][-1]["content"]
    if "budget-router" in components:
        record = json.loads((tmp_path / "hackathon/budget_router.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert record["effective_profile"]["timeout_s"] == 500


@pytest.mark.parametrize("components", ["budget-router", "deadline-framer", "budget-router,deadline-framer"])
@pytest.mark.parametrize("command", ["continue with option A", "continue with day 2"])
def test_completed_followups_work_with_components_enabled(monkeypatch, tmp_path, components, command):
    completed_workspace(tmp_path)
    monkeypatch.setenv("OXCLAW_PHASE_CONTROLS", components)
    monkeypatch.setenv("OXCLAW_BUDGET_ROUTER_MODEL_PATH", "./models/base")
    monkeypatch.setenv("OXCLAW_BUDGET_ROUTER_ADAPTER_PATH", "./models/adapter")
    monkeypatch.setattr(BudgetRouterRuntime, "_generate", lambda *args: pytest.fail("Follow-up chat invoked the phase router"))
    provider = FollowupProvider()
    run_cli(monkeypatch, tmp_path, provider, [command, "/exit"])
    assert (tmp_path / "hackathon/project/followup.txt").is_file()
    assert provider.calls[0][-1]["content"] == command
    assert "Deadline Guidance" not in provider.calls[0][-1]["content"]
    assert not (tmp_path / "hackathon/budget_router.jsonl").exists()
    assert not (tmp_path / "hackathon/deadline_framer.jsonl").exists()
