"""External coding-phase executors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from runtime.config.schema import ClaudeCodeSubagentConfig
from runtime.providers.acp_provider import ACPConfig, ACPProvider


@dataclass(slots=True)
class CodingExecutionResult:
    """Result from an external coding executor."""

    content: str
    backend: str


class ClaudeCodeCodingExecutor:
    """Execute the coding phase through Claude Code via ACP."""

    _MAX_SECTION_CHARS = 4000
    _MAX_USER_CHARS = 12000

    def __init__(self, config: ClaudeCodeSubagentConfig, *, workspace: Path, default_model: str):
        self._workspace = workspace
        self._provider = ACPProvider(
            ACPConfig(
                agent=config.agent,
                model_id=config.model_id,
                cwd=config.cwd,
                session_name=config.session_name,
                timeout_sec=config.timeout_sec,
                acpx_command=config.acpx_command,
                approve_all=config.approve_all,
            ),
            default_model=default_model,
        )

    def preflight(self) -> tuple[bool, str]:
        return self._provider.preflight()

    async def execute(self, messages: list[dict[str, Any]]) -> CodingExecutionResult:
        prompt = self._messages_to_prompt(messages)
        content = await self._provider.run_prompt(prompt)
        return CodingExecutionResult(content=content, backend="claude_code")

    async def execute_streaming(
        self,
        messages: list[dict[str, Any]],
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> CodingExecutionResult:
        prompt = self._messages_to_prompt(messages)

        async def _forward(line: str) -> None:
            if on_progress is None:
                return
            formatted = self._format_progress_line(line)
            if formatted:
                await on_progress(f"[claude] {formatted}")

        content = await self._provider.run_prompt_streaming(prompt, on_output=_forward if on_progress else None)
        return CodingExecutionResult(content=content, backend="claude_code")

    async def close(self) -> None:
        await self._provider.close()

    def _messages_to_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = [
            "You are Claude Code acting as the autonomous coding executor for 0xClaw.",
            f"Repository workspace root: {self._workspace}",
            (
                "You are executing Phase 5 only: Coding / implementation. "
                "Assume research, ideation, selection, and planning are already complete."
            ),
            (
                "Work directly in the local repository using Claude Code's native file editing, "
                "search, and shell capabilities. Do not describe hypothetical tool use."
            ),
            (
                "Complete the requested coding phase end-to-end inside the repo, make the needed "
                "file changes, run validation when useful, and return a concise implementation summary."
            ),
            (
                "Do not ask clarifying questions. Make reasonable assumptions, keep scope limited "
                "to the coding phase, and mention any important assumptions or risks in the final summary."
            ),
            (
                "Prefer a fast, focused implementation pass. Do not re-run or re-audit earlier phases, "
                "do not summarize research/ideas again, and do not restate hackathon context unless it is "
                "strictly needed to implement missing code."
            ),
            (
                "Do not inspect, monitor, or wait on other agents or subagents. There is no need to look "
                "for active coding agents, background tasks, or orchestration state beyond the files needed "
                "to implement Phase 5."
            ),
            (
                "Use hackathon/tasks.json and hackathon/plan.md as the primary source of truth for what to "
                "build. Read only the minimum additional files needed, then implement the missing project "
                "parts directly."
            ),
            (
                "Stay anchored on implementation. Move quickly from reading tasks.json/plan.md to creating "
                "or editing code, tests, configs, and startup scripts required for the MVP."
            ),
        ]

        distilled_system = self._distill_system_messages(messages)
        if distilled_system:
            parts.append("System instructions:\n" + distilled_system)

        user_context = self._collect_non_system_messages(messages)
        if user_context:
            parts.append("Phase request:\n" + user_context)

        parts.append(
            "When finished, return a brief plain-text summary with the main files changed, "
            "validation performed, and any remaining risks."
        )
        return "\n\n".join(part for part in parts if part).strip()

    def _distill_system_messages(self, messages: list[dict[str, Any]]) -> str:
        text = "\n\n".join(
            str(msg.get("content", ""))
            for msg in messages
            if msg.get("role") == "system" and msg.get("content")
        )
        if not text:
            return ""

        sections: list[str] = []

        workspace_match = re.search(r"## Workspace[\s\S]*?(?=\n## |\Z)", text)
        if workspace_match:
            sections.append(workspace_match.group(0).strip()[: self._MAX_SECTION_CHARS])

        phase5_match = re.search(r"### Phase 5 [\s\S]*?(?=\n### Phase 6|\n---|\Z)", text)
        if phase5_match:
            sections.append(phase5_match.group(0).strip()[: self._MAX_SECTION_CHARS])

        state_match = re.search(r"## State Convention[\s\S]*?(?=\n## |\n---|\Z)", text)
        if state_match:
            sections.append(state_match.group(0).strip()[: self._MAX_SECTION_CHARS])

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

    @staticmethod
    def _format_progress_line(line: str) -> str | None:
        text = line.strip()
        if not text:
            return None

        if text.startswith("[acpx]"):
            return None

        for prefix in ("input:", "kind:", "files:", "output:"):
            if text.startswith(prefix):
                return None

        if text == "{}":
            return None

        if text in {"```", "```console"}:
            return None

        if re.match(r"^\d+→", text):
            return None

        if text.startswith("[thinking] "):
            return text

        if text.startswith("[plan]"):
            return "Plan update"

        if text.startswith("[tool] Read File (pending)"):
            return None

        if text.startswith("[tool] Terminal (pending)"):
            return None

        if text.startswith("[tool] Write (pending)"):
            return None

        read_completed = re.match(r"^\[tool\] Read (.+) \(completed\)$", text)
        if read_completed:
            return None

        terminal_completed = re.match(r"^\[tool\] (.+) \(completed\)$", text)
        if terminal_completed:
            action = terminal_completed.group(1)
            if action.startswith("Write "):
                return action
            if action.startswith("Edit "):
                return action
            return f"tool: {action}"

        if text.startswith("File created successfully at: "):
            return "created: " + text.removeprefix("File created successfully at: ")

        if text.startswith("File updated successfully at: "):
            return "updated: " + text.removeprefix("File updated successfully at: ")

        return text
