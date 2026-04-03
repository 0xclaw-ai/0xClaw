"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from runtime.agent.subagent_backends import (
    SubagentBackendDecision,
    SubagentTaskContext,
    resolve_subagent_backend,
)
from runtime.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from runtime.agent.tools.registry import ToolRegistry
from runtime.agent.tools.shell import ExecTool
from runtime.agent.tools.web import WebFetchTool, WebSearchTool
from runtime.bus.events import InboundMessage, OutboundMessage
from runtime.config.schema import SubagentsConfig
from runtime.bus.queue import MessageBus
from runtime.config.schema import ExecToolConfig
from runtime.providers.base import LLMProvider


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        write_guard: Callable[[str], str | None] | None = None,
        subagents_config: "SubagentsConfig | None" = None,
    ):
        from runtime.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._write_guard = write_guard
        self._subagents_config = subagents_config or SubagentsConfig()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    def set_write_guard(self, guard: Callable[[str], str | None] | None) -> None:
        """Set a path guard applied to write/edit operations in subagents."""
        self._write_guard = guard

    def _apply_write_guards(self, tools: ToolRegistry) -> None:
        if self._write_guard is None:
            return

        for tool_name in ("write_file", "edit_file"):
            tool = tools.get(tool_name)
            if tool is None:
                continue
            original = tool.execute

            async def guarded_execute(*args, __original=original, **kwargs):  # type: ignore[no-untyped-def]
                path = kwargs.get("path")
                if isinstance(path, str):
                    err = self._write_guard(path)
                    if err:
                        return f"Error: {err}"
                return await __original(*args, **kwargs)

            tool.execute = guarded_execute  # type: ignore[method-assign]

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        phase: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}
        backend_decision = self._resolve_backend(phase=phase, label=display_label, task=task)

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, phase, backend_decision)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        backend_note = f"backend={backend_decision.actual_backend}"
        if backend_decision.fallback_reason:
            backend_note += f" (fallback: {backend_decision.fallback_reason})"
        return f"Subagent [{display_label}] started (id: {task_id}, {backend_note}). I'll notify you when it completes."

    def _resolve_backend(
        self,
        *,
        phase: str | None,
        label: str | None,
        task: str,
    ) -> SubagentBackendDecision:
        return resolve_subagent_backend(
            context=SubagentTaskContext(phase=phase, label=label, task=task),
            default_provider=self.provider,
            default_model=self.model,
            config=self._subagents_config,
        )

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        phase: str | None,
        backend_decision: SubagentBackendDecision,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info(
            "Subagent [{}] starting task: {} (phase={}, requested_backend={}, actual_backend={})",
            task_id, label, phase, backend_decision.requested_backend, backend_decision.actual_backend,
        )
        if backend_decision.fallback_reason:
            await self._publish_progress(
                origin,
                f"[coder backend] requested={backend_decision.requested_backend} actual={backend_decision.actual_backend} fallback={backend_decision.fallback_reason}",
            )
        else:
            await self._publish_progress(
                origin,
                f"[coder backend] requested={backend_decision.requested_backend} actual={backend_decision.actual_backend}",
            )

        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
            tools.register(WebFetchTool(proxy=self.web_proxy))
            self._apply_write_guards(tools)
            
            system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            initial_messages = list(messages)
            backend_provider = backend_decision.provider
            current_backend = backend_decision.actual_backend

            # Run agent loop (limited iterations)
            max_iterations = 200
            iteration = 0
            final_result: str | None = None

            while iteration < max_iterations:
                iteration += 1

                response = await backend_provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )

                if current_backend != "default_llm" and (
                    response.finish_reason == "error" or not response.has_tool_calls
                ):
                    fallback_reason = "unsupported tool-driving behavior / no executable tool calls"
                    if response.finish_reason == "error":
                        fallback_reason = response.content or "backend returned an error response"
                    logger.warning(
                        "Subagent [{}] backend fallback during execution: {} -> default_llm ({})",
                        task_id, current_backend, fallback_reason,
                    )
                    await self._publish_progress(
                        origin,
                        f"[coder backend] fallback during execution: {current_backend} -> default_llm ({fallback_reason})",
                    )
                    current_backend = "default_llm"
                    backend_provider = self.provider
                    messages = list(initial_messages)
                    iteration = 0
                    continue

                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })

                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break

            if final_result is None:
                final_result = "Task completed but no final response was generated."

            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
        finally:
            if backend_decision.provider is not self.provider and hasattr(backend_decision.provider, "close"):
                try:
                    await backend_decision.provider.close()  # type: ignore[attr-defined]
                except Exception:
                    logger.debug("Subagent [{}] backend close skipped after error", task_id)

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    async def _publish_progress(self, origin: dict[str, str], content: str) -> None:
        """Publish a progress update visible to the caller."""
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=origin["channel"],
                chat_id=origin["chat_id"],
                content=content,
                metadata={"_progress": True},
            )
        )
    
    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from runtime.agent.context import ContextBuilder
        from runtime.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}")

        return "\n\n".join(parts)
    
    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
