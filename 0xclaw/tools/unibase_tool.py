"""Unibase (membase) tool for nanobot.

Provides on-chain persistent memory for agent decisions and interactions
using the Unibase membase SDK. Allows 0xClaw to store and retrieve agent
memory with verifiable on-chain history.
"""

from __future__ import annotations

import json
import os
from typing import Any

from nanobot.agent.tools.base import Tool


class UnibaseTool(Tool):
    """Persistent on-chain agent memory via Unibase / membase."""

    def __init__(self) -> None:
        self._memory: Any = None  # lazy-initialised MultiMemory

    @property
    def name(self) -> str:
        return "unibase_memory"

    @property
    def description(self) -> str:
        return (
            "Store and retrieve agent decisions and observations in Unibase on-chain memory. "
            "Use store to persist important decisions; retrieve to recall past context; "
            "status to check connectivity."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "retrieve", "status"],
                    "description": "store = save a message; retrieve = load recent messages; status = check connectivity",
                },
                "content": {
                    "type": "string",
                    "description": "Content to store (required for store action).",
                },
                "role": {
                    "type": "string",
                    "enum": ["agent", "user", "system"],
                    "description": "Role label for stored message. Defaults to 'agent'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of messages to retrieve. Defaults to 10.",
                },
            },
            "required": ["action"],
        }

    def _configured(self) -> bool:
        return bool(
            os.environ.get("MEMBASE_ID")
            and os.environ.get("MEMBASE_ACCOUNT")
            and os.environ.get("MEMBASE_SECRET_KEY")
        )

    def _get_memory(self) -> Any:
        if self._memory is None:
            from membase.memory.multi_memory import MultiMemory
            self._memory = MultiMemory(
                membase_id=os.environ["MEMBASE_ID"],
                auto_upload=True,
            )
        return self._memory

    async def execute(self, action: str, content: str = "", role: str = "agent", limit: int = 10) -> str:
        if not self._configured():
            return json.dumps({
                "status": "skipped",
                "reason": (
                    "Unibase not configured. Set MEMBASE_ID, MEMBASE_ACCOUNT, "
                    "and MEMBASE_SECRET_KEY. Register at https://unibase.io"
                ),
            })

        if action == "status":
            return await self._check_status()
        if action == "store":
            if not content:
                return json.dumps({"error": "content is required for store"})
            return await self._store(content, role)
        if action == "retrieve":
            return await self._retrieve(limit)

        return json.dumps({"error": f"Unknown action: {action}"})

    async def _check_status(self) -> str:
        try:
            mem = self._get_memory()
            return json.dumps({
                "status": "connected",
                "membase_id": os.environ.get("MEMBASE_ID"),
                "memory_type": type(mem).__name__,
            })
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    async def _store(self, content: str, role: str) -> str:
        try:
            from membase.memory.message import Message
            mem = self._get_memory()
            msg = Message(role=role, content=content)
            mem.add(msg)
            return json.dumps({"status": "stored", "role": role, "content_preview": content[:100]})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    async def _retrieve(self, limit: int) -> str:
        try:
            mem = self._get_memory()
            messages = mem.get(limit=limit)
            return json.dumps({
                "status": "ok",
                "count": len(messages),
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in messages
                ],
            })
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})
