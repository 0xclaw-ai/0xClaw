"""E2B sandbox executor for Phase 6 (testing).

Creates a cloud sandbox via the E2B API, uploads the hackathon project,
runs Claude Code inside the sandbox to validate the project, and writes
the test results back to the local filesystem.

The sandbox provides full isolation (separate Linux VM) with internet
access, so CC can freely pip/npm install, run servers, and iterate on
fixes without affecting the host system.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger
from runtime.agent.claude_code_executor import PHASE_PROMPTS, CodingExecutionResult
from runtime.config.schema import ClaudeCodeSubagentConfig, E2BConfig

# Remote directory inside the E2B sandbox where we upload the project.
_REMOTE_PROJECT_DIR = "/home/user/project"
_REMOTE_RESULTS_PATH = f"{_REMOTE_PROJECT_DIR}/../test_results.json"

# Directories to skip when uploading the project to E2B.
_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".next", ".nuxt", "dist", "build", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "target",
})


def _e2b_preflight(e2b_config: E2BConfig) -> tuple[bool, str]:
    """Check that the E2B API key is available."""
    key = os.environ.get(e2b_config.api_key_env, "").strip()
    if not key:
        return False, (
            f"E2B API key not found. Set the {e2b_config.api_key_env} environment variable."
        )
    return True, ""


def _build_prompt(messages: list[dict[str, Any]]) -> str:
    """Build the testing prompt from phase instructions + user messages."""
    parts: list[str] = list(PHASE_PROMPTS.get("testing", PHASE_PROMPTS["coding"]))
    parts.insert(1, f"Repository workspace root: {_REMOTE_PROJECT_DIR}")

    user_context = "\n\n".join(
        str(msg.get("content", ""))
        for msg in messages
        if msg.get("role") != "system" and msg.get("content")
    ).strip()[:12000]
    if user_context:
        parts.append("Phase request:\n" + user_context)

    parts.append(
        "When finished, return a brief plain-text summary covering the main files changed, "
        "validation performed, and any remaining risks."
    )
    return "\n\n".join(p for p in parts if p).strip()


class E2BTestingExecutor:
    """Execute Phase 6 inside an E2B cloud sandbox with Claude Code."""

    def __init__(
        self,
        cc_config: ClaudeCodeSubagentConfig,
        e2b_config: E2BConfig,
        *,
        workspace: Path,
        default_model: str,
    ):
        self._cc_config = cc_config
        self._e2b_config = e2b_config
        self._workspace = workspace
        self._project_dir = workspace / "hackathon" / "project"
        self._default_model = default_model

    @staticmethod
    def preflight(e2b_config: E2BConfig) -> tuple[bool, str]:
        return _e2b_preflight(e2b_config)

    async def execute_streaming(
        self,
        messages: list[dict[str, Any]],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> CodingExecutionResult:
        from e2b import Sandbox

        prompt = _build_prompt(messages)

        if on_progress:
            await on_progress("[e2b] creating sandbox...")

        sandbox = await asyncio.to_thread(
            Sandbox.create,
            template=self._e2b_config.template,
            timeout=self._e2b_config.timeout_sec,
        )

        try:
            if on_progress:
                await on_progress("[e2b] sandbox ready, uploading project...")

            file_count = await asyncio.to_thread(self._upload_project, sandbox)
            await asyncio.to_thread(self._inject_env, sandbox)

            if on_progress:
                await on_progress(f"[e2b] uploaded {file_count} files, running Claude Code...")

            result_content = await self._run_claude(sandbox, prompt, on_progress)
            await asyncio.to_thread(self._download_results, sandbox)
        finally:
            try:
                await asyncio.to_thread(sandbox.kill)
            except Exception:  # noqa: BLE001
                pass

        return CodingExecutionResult(content=result_content, backend="e2b_claude_code")

    async def close(self) -> None:
        return None

    def _inject_env(self, sandbox: Any) -> None:
        """Write API credentials into the sandbox so claude CLI can use them.

        E2B strips sensitive env var names like ANTHROPIC_API_KEY from
        Sandbox.create(envs=...), so we write the key to a file and export
        it in the shell command instead.
        """
        base_url = (self._cc_config.base_url or "").strip()
        token_env = (self._cc_config.auth_token_env or "").strip()
        token = os.environ.get(token_env, "").strip() if token_env else ""

        if token:
            sandbox.files.write("/tmp/.cc_api_key", token)
        if base_url:
            sandbox.files.write("/tmp/.cc_base_url", base_url)

    def _upload_project(self, sandbox: Any) -> int:
        """Upload the hackathon project directory to the sandbox. Returns file count."""
        if not self._project_dir.exists():
            logger.warning("e2b_testing_executor: project dir does not exist: {}", self._project_dir)
            return 0

        count = 0

        # Also upload sibling hackathon files (plan.md, tasks.json, etc.) for context.
        hackathon_dir = self._project_dir.parent
        for path in hackathon_dir.iterdir():
            if path.is_file():
                try:
                    sandbox.files.write(
                        f"/home/user/{path.name}",
                        path.read_text(encoding="utf-8", errors="replace"),
                    )
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("e2b: failed to upload {}: {}", path.name, exc)

        # Upload project directory recursively, truly pruning heavy/generated dirs.
        count += self._upload_dir(sandbox, self._project_dir, _REMOTE_PROJECT_DIR)
        return count

    def _upload_dir(
        self, sandbox: Any, local_dir: Path, remote_dir: str
    ) -> int:
        """Walk local_dir and upload files, skipping _SKIP_DIRS entirely. Returns file count."""
        count = 0
        self._ensure_remote_dir(sandbox, remote_dir)
        for entry in local_dir.iterdir():
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                count += self._upload_dir(sandbox, entry, f"{remote_dir}/{entry.name}")
            elif entry.is_file() and entry.stat().st_size < 5 * 1024 * 1024:
                try:
                    content = entry.read_bytes()
                    sandbox.files.write(f"{remote_dir}/{entry.name}", content)
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("e2b: failed to upload {}: {}", entry.name, exc)
        return count

    @staticmethod
    def _ensure_remote_dir(sandbox: Any, remote_dir: str) -> None:
        sandbox.commands.run(f"mkdir -p {shlex.quote(remote_dir)}", timeout=30)

    async def _run_claude(
        self,
        sandbox: Any,
        prompt: str,
        on_progress: Callable[..., Awaitable[None]] | None,
    ) -> str:
        """Run Claude Code inside the sandbox and return the text output."""
        # Write prompt to a file to avoid shell escaping issues.
        prompt_path = "/tmp/0xclaw_prompt.txt"
        await asyncio.to_thread(sandbox.files.write, prompt_path, prompt)

        # Quick diagnostics before running claude.
        diag = await asyncio.to_thread(
            sandbox.commands.run,
            "which claude && claude --version 2>&1; "
            "echo KEY_LEN=$(cat /tmp/.cc_api_key 2>/dev/null | wc -c); "
            "echo URL=$(cat /tmp/.cc_base_url 2>/dev/null); "
            f"test -d {_REMOTE_PROJECT_DIR} && echo PROJECT_DIR=ok || echo PROJECT_DIR=missing",
            timeout=30,
        )
        logger.info("e2b diagnostics: {}", diag.stdout.strip()[:500])

        # Build shell prefix to inject ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL
        # from files we wrote in _inject_env (E2B strips these from envs).
        env_prefix = ""
        env_prefix += "export ANTHROPIC_API_KEY=$(cat /tmp/.cc_api_key) 2>/dev/null; "
        env_prefix += "export ANTHROPIC_BASE_URL=$(cat /tmp/.cc_base_url) 2>/dev/null; "

        cmd = (
            f"{env_prefix}"
            f"cd {_REMOTE_PROJECT_DIR} && "
            f"claude --dangerously-skip-permissions "
            f"--output-format json "
            f"--verbose "
            f"-p \"$(cat {prompt_path})\" 2>&1"
        )

        if on_progress:
            await on_progress("[e2b] claude code running in sandbox...")

        # Run the blocking commands.run in a thread.
        # CC may exit with code 1 on test failures — that's expected.
        # Capture whatever output was produced regardless of exit code.
        raw_output = ""
        try:
            result = await asyncio.to_thread(
                sandbox.commands.run,
                cmd,
                timeout=self._e2b_config.timeout_sec,
            )
            raw_output = (result.stdout or "").strip()
        except Exception as run_exc:  # noqa: BLE001
            logger.warning("e2b: claude command exited: {}", run_exc)
            if on_progress:
                await on_progress(f"[e2b] claude exited: {run_exc}")
            raw_output = str(run_exc)

        # Parse the JSON result from CC (--output-format json returns a single object).
        output = self._extract_cc_result(raw_output)

        # Truncate very long output but keep the beginning and end.
        if len(output) > 8000:
            output = output[:4000] + "\n\n... [truncated] ...\n\n" + output[-3000:]

        return output

    @staticmethod
    def _extract_cc_result(raw: str) -> str:
        """Extract the final text from CC's JSON output.

        ``--output-format json`` returns a JSON array of events:
        [{"type":"system",...}, {"type":"assistant","message":{...}}, ...]

        We extract text from the last assistant message that has text content.
        """
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data = E2BTestingExecutor._load_embedded_json(raw)
            if data is None:
                return raw[:6000]

        # Handle dict with "result" key (single-object format).
        if isinstance(data, dict):
            result = data.get("result", "")
            if isinstance(result, str) and result.strip():
                return result.strip()

        # Handle array of events (the actual --output-format json format).
        events = data if isinstance(data, list) else data.get("messages", [])

        # Collect all assistant text blocks, then return the last substantial one.
        assistant_texts: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            # Array format: {"type": "assistant", "message": {"content": [...]}}
            if event.get("type") == "assistant":
                msg = event.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                assistant_texts.append(text)
            # Dict format: {"role": "assistant", "content": [...]}
            elif event.get("role") == "assistant":
                content = event.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                assistant_texts.append(text)

        # Return the last substantial assistant text (likely the summary).
        for text in reversed(assistant_texts):
            if len(text) > 50:  # skip short tool-use descriptions
                return text

        # Fallback: return whatever text we have.
        if assistant_texts:
            return assistant_texts[-1]

        return raw[:6000]

    @staticmethod
    def _load_embedded_json(raw: str) -> Any | None:
        """Parse CC JSON when diagnostics or shell output precede the payload."""
        starts = [idx for idx in (raw.find("{"), raw.find("[")) if idx >= 0]
        for start in sorted(starts):
            try:
                return json.loads(raw[start:])
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    def _download_results(self, sandbox: Any) -> None:
        """Download test_results.json from the sandbox to local workspace."""
        local_path = self._workspace / "hackathon" / "test_results.json"
        try:
            content = sandbox.files.read(_REMOTE_RESULTS_PATH)
            if content:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")
                local_path.write_text(content, encoding="utf-8")
                logger.info("e2b: downloaded test_results.json")
        except Exception as exc:  # noqa: BLE001
            logger.warning("e2b: failed to download test_results.json: {}", exc)
