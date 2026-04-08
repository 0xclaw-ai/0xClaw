"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from runtime.agent.tools.base import Tool

if TYPE_CHECKING:
    from runtime.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
        self._phase: str | None = None
        self._spawn_allowed = True
        self._spawn_block_reason: str | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    def set_phase_context(self, phase: str | None) -> None:
        """Set the current pipeline phase for backend selection."""
        self._phase = phase

    def set_execution_policy(self, *, spawn_allowed: bool, reason: str | None = None) -> None:
        """Control whether spawn() may be used in the current execution mode."""
        self._spawn_allowed = spawn_allowed
        self._spawn_block_reason = reason

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        if not self._spawn_allowed:
            reason = self._spawn_block_reason or "spawn() is disabled in the current execution mode."
            return f"Error: {reason}"
        return await self._manager.spawn(
            task=task,
            label=label,
            phase=self._phase,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
