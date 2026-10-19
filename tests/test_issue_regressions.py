"""Regression scenarios for issues 35, 36, 37, 40, and 41."""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from orchestration.phase_completion import write_marker
from orchestration.session_control import SessionControl
from orchestration.state import PHASE_COMPLETION_ARTIFACTS, PipelineStateStore
from runtime.agent.context import ContextBuilder
from runtime.config.schema import Config
from runtime.providers.base import LLMProvider, LLMResponse, ToolCallRequest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("legacy_workspace", [False, True])
def test_issue35_workflow_contract_reaches_new_and_existing_workspaces(tmp_path, legacy_workspace):
    if legacy_workspace:
        (tmp_path / "AGENTS.md").write_text("# Existing workspace\nKeep project notes here.\n", encoding="utf-8")
    prompt = ContextBuilder(tmp_path).build_system_prompt()
    assert "There is no `0xclaw run pipeline` command" in prompt
    assert "Pipeline completion does not end the conversation" in prompt
    if legacy_workspace:
        assert "Keep project notes here" in prompt


@pytest.mark.parametrize("provider", ["custom", "zhipu"])
def test_issue41_example_uses_coding_plan_endpoint(provider):
    config = json.loads((ROOT / "0xclaw/config/config.json").read_text(encoding="utf-8"))
    assert config["providers"][provider]["apiBase"] == "https://api.z.ai/api/coding/paas/v4"
    assert config["subagents"]["claudeCode"]["baseUrl"] == "https://api.z.ai/api/anthropic"


def completed_workspace(workspace):
    hackathon = workspace / "hackathon"
    for artifacts in PHASE_COMPLETION_ARTIFACTS.values():
        for artifact in artifacts:
            path = hackathon / artifact
            if artifact == "project":
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"sources": [], "status": "pass"}\n' if path.suffix == ".json" else "Existing project artifact.\n", encoding="utf-8")
    write_marker(hackathon, "coding")
    store = PipelineStateStore(hackathon)
    assert SessionControl(store).get_resume_decision().all_complete
    return store


class FollowupProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.parameters = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        self.calls.append([dict(message) for message in messages])
        self.parameters.append(kwargs)
        if len(self.calls) == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="followup-write", name="write_file",
                arguments={"path": "hackathon/project/followup.txt", "content": "Follow-up work completed.\n"},
            )])
        return LLMResponse(content="Follow-up processing finished.")


def run_cli(monkeypatch, workspace, provider, commands):
    import main
    import prompt_toolkit

    inputs = iter(commands)

    class ScriptedPrompt:
        app = SimpleNamespace(is_running=False)

        async def prompt_async(self, *args, **kwargs):
            await asyncio.sleep(0)
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError from None

    output = io.StringIO()
    monkeypatch.setattr(prompt_toolkit, "PromptSession", lambda **kwargs: ScriptedPrompt())
    monkeypatch.setattr(main, "console", Console(file=output, force_terminal=False, width=120))
    monkeypatch.setattr(main, "_print_banner", lambda *args: None)
    monkeypatch.setattr(main, "WORKSPACE", workspace)
    monkeypatch.setattr(main, "HACKATHON_DIR", workspace / "hackathon")
    monkeypatch.setattr(main, "ENVELOPE_LOG", workspace / "hackathon/envelopes.jsonl")
    monkeypatch.setattr(main, "PHASE_OUTPUTS", {
        phase: workspace / "hackathon" / path.relative_to(main.ROOT / "workspace/hackathon")
        for phase, path in main.PHASE_OUTPUTS.items()
    })
    monkeypatch.setattr(main, "_make_tracking_provider", lambda *args: provider)
    monkeypatch.setattr(main.signal, "signal", lambda *args: None)
    config = Config()
    config.agents.defaults.model = "test-model"
    asyncio.run(asyncio.wait_for(main.run_interactive(config), timeout=10))
    return output.getvalue()


@pytest.mark.parametrize("user_command", ["continue with option A", "continue with day 2"])
def test_issues37_40_completed_pipeline_can_perform_followup_work(monkeypatch, tmp_path, user_command):
    store = completed_workspace(tmp_path)
    before = store.load()
    provider = FollowupProvider()
    output = run_cli(monkeypatch, tmp_path, provider, [user_command, "/exit"])
    result = tmp_path / "hackathon/project/followup.txt"
    assert result.is_file(), "The completed pipeline blocked a follow-up project write"
    assert result.read_text(encoding="utf-8") == "Follow-up work completed.\n"
    assert provider.calls[0][-1]["content"] == user_command
    assert "The initial seven-phase pipeline is complete" in provider.calls[0][0]["content"]
    assert store.load() == before
    assert "All phases are complete" not in output


def test_issue36_active_conversation_survives_original_turn_timeout(monkeypatch, tmp_path):
    import main

    class StreamingProvider(FollowupProvider):
        async def chat(self, messages, **kwargs):
            async for _, response in self.chat_stream(messages, **kwargs):
                if response is not None:
                    return response

        async def chat_stream(self, messages, **kwargs):
            for _ in range(20):
                await asyncio.sleep(0.02)
                yield "Working. ", None
            yield "Long active turn completed.", None
            yield "", LLMResponse(content="Long active turn completed.")

    monkeypatch.setattr(main, "DEFAULT_PHASE_TIMEOUT_S", 0.15)
    output = run_cli(monkeypatch, tmp_path, StreamingProvider(), ["continue", "/exit"])
    assert "Long active turn completed." in output
    assert "Timed out" not in output
    assert "No activity" not in output


@pytest.mark.parametrize("phase, activity, expected", [
    (None, True, None),
    (None, False, "idle"),
    ("coding", True, "phase"),
])
def test_issue36_idle_detection_preserves_phase_time_budgets(monkeypatch, phase, activity, expected):
    from orchestration import turn_wait

    async def scenario():
        now = [0.0]
        last = [0.0]
        done = asyncio.Event()
        original_wait = asyncio.wait_for
        original_clock = turn_wait.time.monotonic

        async def advance(awaitable, timeout):
            awaitable.close()
            now[0] += timeout
            if activity:
                last[0] = now[0]
            if now[0] >= 20:
                done.set()
            raise asyncio.TimeoutError

        monkeypatch.setattr(turn_wait.time, "monotonic", lambda: now[0])
        monkeypatch.setattr(turn_wait.asyncio, "wait_for", advance)
        try:
            return await turn_wait.wait_for_turn(
                done, started_at=0.0, last_activity=lambda: last[0], timeout_s=10, phase=phase,
            )
        finally:
            monkeypatch.setattr(turn_wait.asyncio, "wait_for", original_wait)
            monkeypatch.setattr(turn_wait.time, "monotonic", original_clock)

    assert asyncio.run(scenario()) == expected


@pytest.mark.parametrize("path, permitted", [
    ("hackathon/project/next_day.py", True),
    ("hackathon/progress.md", True),
    ("hackathon/tasks.json", False),
    ("hackathon/test_results.json", False),
    ("hackathon/submission/README.md", False),
    ("../outside.py", False),
])
def test_followup_write_permissions_remain_scoped(tmp_path, path, permitted):
    from orchestration.state import OrchestratorStateMachine
    from orchestration.write_guard import build_phase_write_guard

    store = completed_workspace(tmp_path)
    active = [True]
    guard = build_phase_write_guard(
        workspace=tmp_path, state_machine=OrchestratorStateMachine(tmp_path, store),
        get_phase=lambda: None, allow_followup=lambda: active[0],
    )
    assert (guard(path) is None) == permitted
    active[0] = False
    assert guard("hackathon/project/next_day.py") is not None


def test_incomplete_pipeline_cannot_bypass_phase_write_guard(monkeypatch, tmp_path):
    provider = FollowupProvider()
    run_cli(monkeypatch, tmp_path, provider, ["continue with day 2", "/exit"])
    assert not (tmp_path / "hackathon/project/followup.txt").exists()
    assert "The initial seven-phase pipeline is complete" not in provider.calls[0][0]["content"]


def test_completed_resume_keeps_conversation_open(monkeypatch, tmp_path):
    completed_workspace(tmp_path)
    provider = FollowupProvider()
    output = run_cli(monkeypatch, tmp_path, provider, ["/resume", "continue with day 2", "/exit"])
    assert "This does not end the session" in output
    assert (tmp_path / "hackathon/project/followup.txt").is_file()


@pytest.mark.parametrize("endpoint", [
    "https://api.z.ai/api/coding/paas/v4",
    "https://api.z.ai/api/paas/v4",
])
def test_issue41_explicit_account_endpoint_reaches_provider(monkeypatch, tmp_path, endpoint):
    import main
    import runtime.providers.litellm_provider as provider_module

    data = json.loads((ROOT / "0xclaw/config/config.json").read_text(encoding="utf-8"))
    data["providers"]["zhipu"]["apiBase"] = endpoint
    data["providers"]["zhipu"]["apiKey"] = "test-placeholder"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(main, "CONFIG_PATH", config_path)
    monkeypatch.setattr(main, "WORKSPACE", tmp_path)
    config = main._load_config()
    provider = main._make_provider(config)
    captured = []

    async def completion(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None), finish_reason="stop")],
            usage=None,
        )

    monkeypatch.setattr(provider_module, "acompletion", completion)
    response = asyncio.run(provider.chat([{"role": "user", "content": "hello"}]))
    assert response.content == "ok"
    assert captured[0]["api_base"] == endpoint


@pytest.mark.parametrize("retryable, failures, expected_calls", [(True, 1, 2), (True, 9, 4), (False, 1, 1)])
def test_stream_retries_are_bounded_and_skip_permanent_errors(monkeypatch, tmp_path, retryable, failures, expected_calls):
    from runtime.agent import loop
    from runtime.bus.queue import MessageBus

    class RetryProvider(FollowupProvider):
        async def chat(self, messages, **kwargs):
            self.calls.append(messages)
            if len(self.calls) <= failures:
                return LLMResponse(content="Simulated transport failure", finish_reason="error", retryable=retryable)
            return LLMResponse(content="Recovered response")

    monkeypatch.setattr(loop, "STREAM_RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(loop, "STREAM_MAX_RETRIES", 3)
    provider = RetryProvider()
    agent = loop.AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    response, _, _ = asyncio.run(agent._run_agent_loop([{"role": "user", "content": "continue"}]))
    assert len(provider.calls) == expected_calls
    assert (response == "Recovered response") == (retryable and failures == 1)
