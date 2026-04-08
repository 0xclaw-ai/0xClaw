"""ACP provider backed by a local CLI agent via acpx."""

from __future__ import annotations

import atexit
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from runtime.config.schema import Config
from runtime.providers.base import LLMProvider, LLMResponse

_DONE_RE = re.compile(r"^\[done\]")
_CLIENT_RE = re.compile(r"^\[client\]")
_ACPX_RE = re.compile(r"^\[acpx\]")
_TOOL_RE = re.compile(r"^\[tool\]")


@dataclass
class ACPConfig:
    """Runtime config for a local ACP agent session."""

    agent: str = "claude"
    model_id: str = "qwen3.5-plus"
    cwd: str = "./workspace"
    session_name: str = "0xclaw"
    timeout_sec: int = 1800
    acpx_command: str = ""
    approve_all: bool = True


def _find_acpx() -> str | None:
    found = shutil.which("acpx")
    if found:
        return found
    bundled = os.path.expanduser("~/.openclaw/extensions/acpx/node_modules/.bin/acpx")
    if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    return None


class ACPProvider(LLMProvider):
    """Local ACP bridge that reuses a named agent session through acpx."""

    _live_instances: list[weakref.ref["ACPProvider"]] = []
    _atexit_registered = False
    _MAX_CLI_PROMPT_BYTES = 20_000 if sys.platform == "win32" else 100_000
    _MAX_CMD_WRAPPER_PROMPT_BYTES = 6_000 if sys.platform == "win32" else 100_000
    _CMD_TOO_LONG_HINTS = ("too long", "trop long", "zu lang", "demasiado larg", "e2big")
    _RECONNECT_ERRORS = ("agent needs reconnect", "session not found", "Query closed")
    _MAX_RECONNECT_ATTEMPTS = 2

    def __init__(self, config: ACPConfig, default_model: str = "acp/claude"):
        super().__init__(api_key=None, api_base=None)
        self.config = config
        self.default_model = default_model
        self._acpx: str | None = config.acpx_command or None
        self._session_ready = False

        ACPProvider._live_instances = [r for r in ACPProvider._live_instances if r() is not None]
        ACPProvider._live_instances.append(weakref.ref(self))
        if not ACPProvider._atexit_registered:
            atexit.register(ACPProvider._atexit_cleanup)
            ACPProvider._atexit_registered = True

    @classmethod
    def from_config(cls, config: Config, *, default_model: str | None = None) -> "ACPProvider":
        acp = config.providers.acp
        return cls(
            ACPConfig(
                agent=acp.agent,
                model_id=acp.model_id,
                cwd=acp.cwd,
                session_name=acp.session_name,
                timeout_sec=acp.timeout_sec,
                acpx_command=acp.acpx_command,
                approve_all=acp.approve_all,
            ),
            default_model=default_model or config.agents.defaults.model,
        )

    def get_default_model(self) -> str:
        return self.default_model

    def preflight(self) -> tuple[bool, str]:
        acpx = self._resolve_acpx()
        if not acpx:
            return False, "acpx not found. Install it or set providers.acp.acpx_command."
        if not shutil.which(self.config.agent):
            return False, f"ACP agent CLI not found: {self.config.agent!r} (not on PATH)"
        try:
            self._ensure_session_sync()
            return True, f"OK - ACP session ready ({self.config.agent} via acpx)"
        except Exception as exc:  # noqa: BLE001
            return False, f"ACP session init failed: {exc}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        del max_tokens, temperature, reasoning_effort
        prompt_text = self._messages_to_prompt(messages, tools=tools)
        try:
            content = await self._send_prompt(prompt_text)
            return LLMResponse(
                content=content,
                finish_reason="stop",
            )
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(
                content=f"Error calling ACP agent: {exc}",
                finish_reason="error",
            )

    async def run_prompt(self, prompt: str) -> str:
        """Run a raw ACP prompt and return the cleaned text response."""
        return await self._send_prompt(prompt)

    async def run_prompt_streaming(
        self,
        prompt: str,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Run a raw ACP prompt and stream process output lines to a callback."""
        return await self._send_prompt(prompt, on_output=on_output)

    async def close(self) -> None:
        if not self._session_ready:
            return
        acpx = self._resolve_acpx()
        if not acpx:
            return
        await asyncio.to_thread(
            subprocess.run,
            [acpx, "--ttl", "0", "--cwd", self._abs_cwd(), self.config.agent, "sessions", "close", self.config.session_name],
            capture_output=True,
            timeout=15,
        )
        self._session_ready = False

    @staticmethod
    def _trim_output(text: str | None, *, limit: int = 8000) -> str:
        """Trim captured process output while keeping the most useful tail."""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit // 2]}\n...\n{text[-(limit // 2):]}"

    @classmethod
    def _format_process_failure(cls, result: subprocess.CompletedProcess[str], *, context: str) -> RuntimeError:
        """Build a rich runtime error that includes both stdout and stderr."""
        stdout = cls._trim_output(result.stdout)
        stderr = cls._trim_output(result.stderr)
        parts = [f"{context} (exit {result.returncode})"]
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        return RuntimeError("\n\n".join(parts))

    def _resolve_acpx(self) -> str | None:
        if self._acpx:
            return self._acpx
        self._acpx = _find_acpx()
        return self._acpx

    def _abs_cwd(self) -> str:
        return str(Path(self.config.cwd).expanduser().resolve())

    def _acpx_preamble(self, acpx: str) -> list[str]:
        cmd = [acpx]
        if self.config.model_id:
            cmd.extend(["--model", self.config.model_id])
        return cmd

    def _set_session_model_sync(self, acpx: str) -> None:
        if not self.config.model_id:
            return
        result = subprocess.run(
            [acpx, "--ttl", "0", "--cwd", self._abs_cwd(), self.config.agent, "set", "-s", self.config.session_name, "model", self.config.model_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            raise self._format_process_failure(result, context="Failed to set ACP session model")

    @classmethod
    def _atexit_cleanup(cls) -> None:
        for ref in cls._live_instances:
            inst = ref()
            if inst is not None:
                try:
                    asyncio.run(inst.close())
                except Exception:
                    pass
        cls._live_instances.clear()

    def _ensure_session_sync(self) -> None:
        if self._session_ready:
            return
        acpx = self._resolve_acpx()
        if not acpx:
            raise RuntimeError("acpx not found")

        result = subprocess.run(
            self._acpx_preamble(acpx)
            + ["--ttl", "0", "--cwd", self._abs_cwd(), self.config.agent, "sessions", "ensure", "--name", self.config.session_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            result = subprocess.run(
                self._acpx_preamble(acpx)
                + ["--ttl", "0", "--cwd", self._abs_cwd(), self.config.agent, "sessions", "new", "--name", self.config.session_name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                raise self._format_process_failure(result, context="Failed to create ACP session")
        self._set_session_model_sync(acpx)
        self._session_ready = True

    async def _ensure_session(self) -> None:
        await asyncio.to_thread(self._ensure_session_sync)

    @classmethod
    def _cli_prompt_limit(cls, acpx: str | None) -> int:
        limit = cls._MAX_CLI_PROMPT_BYTES
        if sys.platform == "win32" and acpx and acpx.lower().endswith((".cmd", ".bat")):
            return min(limit, cls._MAX_CMD_WRAPPER_PROMPT_BYTES)
        return limit

    async def _send_prompt(
        self,
        prompt: str,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        prompt = prompt.replace("\x00", "")
        acpx = self._resolve_acpx()
        if not acpx:
            raise RuntimeError("acpx not found")

        prompt_bytes = len(prompt.encode("utf-8"))
        use_file = prompt_bytes > self._cli_prompt_limit(acpx)
        last_exc: RuntimeError | None = None

        for attempt in range(1 + self._MAX_RECONNECT_ATTEMPTS):
            await self._ensure_session()
            try:
                if use_file:
                    return await self._send_prompt_via_file(acpx, prompt, on_output=on_output)
                return await self._send_prompt_cli(acpx, prompt, on_output=on_output)
            except OSError as os_exc:
                if not use_file:
                    use_file = True
                    return await self._send_prompt_via_file(acpx, prompt, on_output=on_output)
                raise RuntimeError(f"ACP prompt failed: {os_exc}") from os_exc
            except RuntimeError as exc:
                exc_lower = str(exc).lower()
                if not use_file and any(hint in exc_lower for hint in self._CMD_TOO_LONG_HINTS):
                    use_file = True
                    return await self._send_prompt_via_file(acpx, prompt, on_output=on_output)
                if not any(pat in str(exc) for pat in self._RECONNECT_ERRORS):
                    raise
                last_exc = exc
                if attempt < self._MAX_RECONNECT_ATTEMPTS:
                    await self._force_reconnect()

        raise last_exc or RuntimeError("ACP prompt failed")

    async def _force_reconnect(self) -> None:
        try:
            await self.close()
        except Exception:
            pass
        self._session_ready = False

    def _base_command(self, acpx: str) -> list[str]:
        cmd = self._acpx_preamble(acpx)
        if self.config.approve_all:
            cmd.append("--approve-all")
        cmd.extend(["--ttl", "0", "--cwd", self._abs_cwd(), self.config.agent, "-s", self.config.session_name])
        return cmd

    @staticmethod
    async def _emit_process_output(
        text: str,
        *,
        source: str,
        on_output: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        if on_output is None:
            return
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if _DONE_RE.match(line) or _CLIENT_RE.match(line):
                continue
            if source == "stderr" and not line.startswith("["):
                line = f"[stderr] {line}"
            await on_output(line)

    async def _run_streaming_process(
        self,
        cmd: list[str],
        *,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _pump(
            stream: asyncio.StreamReader | None,
            collector: list[str],
            *,
            source: str,
        ) -> None:
            if stream is None:
                return
            while True:
                chunk = await stream.readline()
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                collector.append(text)
                await self._emit_process_output(text, source=source, on_output=on_output)

        stdout_task = asyncio.create_task(_pump(process.stdout, stdout_chunks, source="stdout"))
        stderr_task = asyncio.create_task(_pump(process.stderr, stderr_chunks, source="stderr"))

        try:
            await asyncio.wait_for(
                asyncio.gather(process.wait(), stdout_task, stderr_task),
                timeout=self.config.timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            await process.wait()
            raise RuntimeError(f"ACP prompt timed out after {self.config.timeout_sec}s") from exc

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=process.returncode,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
        )

    async def _send_prompt_cli(
        self,
        acpx: str,
        prompt: str,
        *,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        try:
            result = await self._run_streaming_process(
                self._base_command(acpx) + [prompt],
                on_output=on_output,
            )
        except RuntimeError:
            raise

        if result.returncode != 0:
            raise self._format_process_failure(result, context="ACP prompt failed")
        return self._extract_response(result.stdout)

    async def _send_prompt_via_file(
        self,
        acpx: str,
        prompt: str,
        *,
        on_output: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        fd, prompt_path = tempfile.mkstemp(suffix=".md", prefix="0xclaw_acp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(prompt)

            short_prompt = (
                f"Read the file at {prompt_path} in full. "
                "Follow all instructions in that file exactly. "
                "Do not summarize the file; produce the requested response directly."
            )
            try:
                result = await self._run_streaming_process(
                    self._base_command(acpx) + [short_prompt],
                    on_output=on_output,
                )
            except RuntimeError:
                raise

            if result.returncode != 0:
                raise self._format_process_failure(result, context="ACP prompt failed")
            return self._extract_response(result.stdout)
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    @staticmethod
    def _extract_response(raw_output: str | None) -> str:
        if not raw_output:
            return ""

        lines: list[str] = []
        in_tool_block = False
        for line in raw_output.splitlines():
            if _DONE_RE.match(line) or _CLIENT_RE.match(line) or _ACPX_RE.match(line):
                in_tool_block = False
                continue
            if _TOOL_RE.match(line):
                in_tool_block = True
                continue
            if in_tool_block:
                if line.startswith("  ") or not line.strip():
                    continue
                in_tool_block = False
            if not lines and not line.strip():
                continue
            lines.append(line)

        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str:
        parts: list[str] = []
        system_parts = [str(msg.get("content", "")) for msg in messages if msg.get("role") == "system" and msg.get("content")]
        if system_parts:
            parts.append("System instructions:\n" + "\n\n".join(system_parts))

        if tools:
            tool_names = []
            for tool in tools:
                fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
                if fn.get("name"):
                    tool_names.append(str(fn["name"]))
            if tool_names:
                parts.append(
                    "Available runtime tools are provided by 0xClaw, but this ACP bridge currently "
                    "returns text-only responses. If a tool is needed, describe the intended tool use in text.\n"
                    + ", ".join(tool_names)
                )

        for msg in messages:
            role = str(msg.get("role", "user")).upper()
            if role == "SYSTEM":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                rendered = content
            else:
                rendered = str(content)
            parts.append(f"{role}:\n{rendered}")

        parts.append("Respond as the assistant. Return plain text only.")
        return "\n\n".join(part for part in parts if part).strip()
