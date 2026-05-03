"""Claude Code executor and provider via the official `claude-agent-sdk`.

Two public types are exposed:

- ``ClaudeCodeExecutor``  — phase-level streaming executor used by the
  ``loop._run_external_phase`` codepath for top-level phase runs (coding,
  testing, …).  Picks up ``<cwd>/.claude/agents/*.md`` so seeded hackathon
  subagents are available inside Claude Code.

- ``ClaudeCodeProvider`` — thin ``LLMProvider`` adapter so the subagent
  backend resolver in ``subagent_backends`` can hand a Claude Code session
  back to callers that expect a chat() interface.  Treats Claude Code as a
  black box: each chat() call runs one full SDK session and returns the
  final assistant text with no tool_calls.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    UserMessage,
)
from loguru import logger
from runtime.config.schema import ClaudeCodeSubagentConfig
from runtime.providers.base import LLMProvider, LLMResponse


@dataclass(slots=True)
class CodingExecutionResult:
    """Result from a Claude Code phase execution."""

    content: str
    backend: str


_PHASE_PROMPTS: dict[str, list[str]] = {
    "coding": [
        "You are Claude Code acting as the autonomous coding executor for 0xClaw.",
        "You are executing Phase 5 only: Coding / implementation. Assume research, ideation, "
        "selection, and planning are already complete — DO NOT re-run earlier phases.",
        "Your cwd IS the project directory you should write into. The planning artifacts "
        "(plan.md, tasks.json, selected_idea.json, context.json) live in the parent "
        "directory at ../ (i.e. ../plan.md, ../tasks.json). Read them first, then "
        "create or edit code, tests, configs, and startup scripts inside cwd.",
        "If those parent files are missing, STOP and report — do not attempt to recreate "
        "research or planning artifacts. That is out of scope for this phase.",
        "Do not ask clarifying questions. Make reasonable assumptions and mention any important "
        "ones in the final summary.",
    ],
    "testing": [
        "You are Claude Code acting as the autonomous testing executor for 0xClaw.",
        "You are executing Phase 6: validate the project in your cwd so it is demo-ready.",
        "",
        "## Goal",
        "Install dependencies, run tests, fix any issues you find, and produce a test report.",
        "You have full autonomy — decide what to install, how to test, and what to fix.",
        "You are running inside an isolated sandbox — you can freely install packages, "
        "run servers, and modify files without affecting the host system.",
        "",
        "## Steps (adapt to the actual tech stack you discover)",
        "1. Inspect the project structure and detect the tech stack (Python, Node, Go, etc.).",
        "2. Install dependencies (pip install, npm install, or equivalent).",
        "3. Run whatever tests or validation the project provides (pytest, npm test, go test, etc.).",
        "4. If installation or tests fail, apply minimal fixes (requirements.txt, imports, "
        "config, missing files) and retry. Cap yourself at ~3 fix rounds.",
        "5. Optionally smoke-start the app and verify it responds.",
        "",
        "## Output — test_results.json",
        "When done, write `../test_results.json` (relative to cwd) with this shape:",
        "```json",
        "{",
        '  "status": "pass" | "partial" | "fail",',
        '  "summary": "one-line human-readable summary",',
        '  "install_ok": true,',
        '  "tests_total": 0,',
        '  "tests_passed": 0,',
        '  "tests_failed": 0,',
        '  "errors": [],',
        '  "fix_log": [{"attempt": 1, "trigger": "...", "outcome": "fixed|no-op"}],',
        '  "demo_readiness": "ready" | "partially_ready" | "not_ready"',
        "}",
        "```",
        "Set `status=pass` only when install + import succeed and all tests pass. "
        "`partial` = some tests fail but the app runs. `fail` = cannot install or run.",
        "",
        "Do not ask clarifying questions. Make reasonable assumptions and mention any important "
        "ones in the final summary.",
    ],
}


def claude_cli_preflight() -> tuple[bool, str]:
    """Check that the Claude Code CLI is installed and reachable."""
    if shutil.which("claude") is None:
        return False, (
            "Claude Code CLI not found. Install with `npm install -g @anthropic-ai/claude-code` "
            "and run `claude` once to authenticate."
        )
    return True, ""


class ClaudeCodeExecutor:
    """Execute a phase through Claude Code via the official SDK."""

    _MAX_SECTION_CHARS = 4000
    _MAX_USER_CHARS = 12000

    def __init__(
        self,
        config: ClaudeCodeSubagentConfig,
        *,
        workspace: Path,
        default_model: str,
        phase: str = "coding",
    ):
        self._config = config
        self._agent_workspace = workspace
        self._workspace = self._resolve_cwd(config, workspace)
        self._default_model = default_model
        self._phase = phase

    @staticmethod
    def _resolve_cwd(config: ClaudeCodeSubagentConfig, agent_workspace: Path) -> Path:
        """Resolve the CC working dir from config.cwd.

        - empty/missing -> fall back to agent workspace (legacy behaviour).
        - absolute path -> use as-is.
        - relative path -> resolve against the project root (agent_workspace.parent),
          since users write paths like "./workspace/hackathon/project" expecting
          them to be relative to where `0xclaw` was launched.
        """
        raw = (config.cwd or "").strip()
        if not raw:
            return agent_workspace
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (agent_workspace.parent / candidate).resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    @staticmethod
    def preflight() -> tuple[bool, str]:
        return claude_cli_preflight()

    def _build_options(self) -> ClaudeAgentOptions:
        model = (self._config.model or "").strip() or None
        return ClaudeAgentOptions(
            cwd=str(self._workspace),
            model=model,
            permission_mode=self._config.permission_mode,
            setting_sources=["project"],
            skills="all",
            add_dirs=self._extra_read_dirs(),
            env=self._build_env(),
        )

    def _extra_read_dirs(self) -> list[str | Path]:
        """Directories outside cwd that CC should be able to read from."""
        extras: list[str | Path] = []
        hackathon_dir = self._workspace.parent
        if hackathon_dir.name == "hackathon" and hackathon_dir.is_dir():
            extras.append(str(hackathon_dir))
        return extras

    def _build_env(self) -> dict[str, str]:
        """Build env overrides for the spawned `claude` CLI subprocess.

        Returning an empty dict (the default) means the SDK passes through the
        parent process env unchanged. We only inject ANTHROPIC_BASE_URL /
        ANTHROPIC_AUTH_TOKEN when the user has opted into a custom endpoint
        (e.g. GLM's Anthropic-compatible layer).
        """
        overrides: dict[str, str] = {}
        base_url = (self._config.base_url or "").strip()
        if base_url:
            overrides["ANTHROPIC_BASE_URL"] = base_url
        token_env = (self._config.auth_token_env or "").strip()
        if token_env:
            token = os.environ.get(token_env, "").strip()
            if token:
                overrides["ANTHROPIC_AUTH_TOKEN"] = token
            else:
                logger.warning(
                    "claude_code_executor: auth_token_env={} is set but the env var is empty",
                    token_env,
                )
        return overrides

    async def execute_streaming(
        self,
        messages: list[dict[str, Any]],
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> CodingExecutionResult:
        prompt = self._messages_to_prompt(messages)
        chunks: list[str] = []

        async with ClaudeSDKClient(options=self._build_options()) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                rendered = self._render(msg)
                if rendered is None:
                    continue
                chunks.append(rendered)
                if on_progress:
                    await on_progress(f"[claude] {rendered}")

        return CodingExecutionResult(content="\n".join(chunks).strip(), backend="claude_code")

    async def execute(self, messages: list[dict[str, Any]]) -> CodingExecutionResult:
        return await self.execute_streaming(messages, on_progress=None)

    async def close(self) -> None:  # pragma: no cover — kept for legacy callers
        return None

    # --- prompt assembly --------------------------------------------------------

    def _messages_to_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = list(_PHASE_PROMPTS.get(self._phase, _PHASE_PROMPTS["coding"]))
        parts.insert(1, f"Repository workspace root: {self._workspace}")

        distilled = self._distill_system_messages(messages)
        if distilled:
            parts.append("System instructions:\n" + distilled)

        user_context = self._collect_non_system_messages(messages)
        if user_context:
            parts.append("Phase request:\n" + user_context)

        parts.append(
            "When finished, return a brief plain-text summary covering the main files changed, "
            "validation performed, and any remaining risks."
        )
        return "\n\n".join(p for p in parts if p).strip()

    def _distill_system_messages(self, messages: list[dict[str, Any]]) -> str:
        text = "\n\n".join(
            str(msg.get("content", ""))
            for msg in messages
            if msg.get("role") == "system" and msg.get("content")
        )
        if not text:
            return ""

        sections: list[str] = []
        for header in (r"## Workspace", r"### Phase 5", r"### Phase 6", r"## State Convention"):
            match = re.search(rf"{header}[\s\S]*?(?=\n## |\n### |\n---|\Z)", text)
            if match:
                sections.append(match.group(0).strip()[: self._MAX_SECTION_CHARS])
        if not sections:
            return text[: self._MAX_SECTION_CHARS]
        return "\n\n".join(sections)

    def _collect_non_system_messages(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = str(msg.get("role", "user")).upper()
            if role == "SYSTEM":
                continue
            content = msg.get("content")
            rendered = content if isinstance(content, str) else str(content)
            if rendered:
                parts.append(f"{role}:\n{rendered}")
        return "\n\n".join(parts).strip()[: self._MAX_USER_CHARS]

    # --- message rendering ------------------------------------------------------

    @staticmethod
    def _render(msg: Any) -> str | None:
        if isinstance(msg, AssistantMessage):
            chunks: list[str] = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    chunks.append(f"[tool] {block.name}")
                elif isinstance(block, ThinkingBlock):
                    continue
            text = "".join(chunks).strip()
            return text or None
        if isinstance(msg, (ResultMessage, SystemMessage, UserMessage)):
            return None
        return None


class ClaudeCodeProvider(LLMProvider):
    """``LLMProvider`` adapter that routes a chat() call through Claude Code."""

    def __init__(
        self,
        config: ClaudeCodeSubagentConfig,
        *,
        default_model: str,
        phase: str = "coding",
    ):
        super().__init__(api_key=None, api_base=None)
        self._config = config
        self._default_model = default_model
        self._phase = phase
        self._executor = ClaudeCodeExecutor(
            config,
            workspace=Path(config.cwd),
            default_model=default_model,
            phase=phase,
        )

    def preflight(self) -> tuple[bool, str]:
        return self._executor.preflight()

    def get_default_model(self) -> str:
        return self._default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        # Claude Code runs its own internal tool loop; we treat each chat() call
        # as one black-box session and return the final assistant text.
        del tools, model, max_tokens, temperature, reasoning_effort
        result = await self._executor.execute_streaming(messages)
        return LLMResponse(content=result.content or "", tool_calls=[], finish_reason="stop")

    async def close(self) -> None:
        await self._executor.close()
