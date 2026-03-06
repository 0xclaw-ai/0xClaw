"""Virtual Protocol GAME SDK tool for 0xClaw.

Registers an on-chain agent identity via the Virtuals GAME API and exposes
it as a tool so 0xClaw can mint agent identities for the generated
project.
"""

from __future__ import annotations

import json
import os
from typing import Any

from runtime.agent.tools.base import Tool


class VirtualsTool(Tool):
    """Register and query agent identities on the Virtuals Protocol GAME platform."""

    @property
    def name(self) -> str:
        return "virtuals_agent"

    @property
    def description(self) -> str:
        return (
            "Create or retrieve an on-chain agent identity on the Virtuals Protocol GAME "
            "platform. Use this to give the generated project an on-chain agent identity "
            "with provenance. Returns the agent ID and a confirmation URL."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "status"],
                    "description": "create = register a new agent identity; status = check connectivity",
                },
                "name": {
                    "type": "string",
                    "description": "Agent name (required for create). Max 64 chars.",
                },
                "goal": {
                    "type": "string",
                    "description": "Agent goal statement (required for create). One sentence.",
                },
                "description": {
                    "type": "string",
                    "description": "Agent description (required for create). What the agent does.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, name: str = "", goal: str = "", description: str = "") -> str:
        api_key = os.environ.get("VIRTUALS_API_KEY", "")
        if not api_key or api_key.startswith("your-"):
            return json.dumps({
                "status": "skipped",
                "reason": "VIRTUALS_API_KEY not configured. Get your key at https://game.virtuals.io",
            })

        if action == "status":
            return await self._check_status(api_key)

        if action == "create":
            if not all([name, goal, description]):
                return json.dumps({"error": "name, goal, and description are required for create"})
            return await self._create_agent(api_key, name, goal, description)

        return json.dumps({"error": f"Unknown action: {action}"})

    async def _check_status(self, api_key: str) -> str:
        try:
            from virtuals_sdk.game.utils import post
            # Minimal connectivity probe
            result = post(
                base_url="https://game.virtuals.io",
                endpoint="/v2/ping",
                api_key=api_key,
                data={},
            )
            return json.dumps({"status": "reachable", "response": str(result)})
        except Exception as e:
            return json.dumps({"status": "unreachable", "error": str(e)})

    async def _create_agent(self, api_key: str, name: str, goal: str, description: str) -> str:
        try:
            from virtuals_sdk.game.utils import create_agent

            agent_id = create_agent(
                base_url="https://game.virtuals.io",
                api_key=api_key,
                name=name,
                description=description,
                goal=goal,
            )
            return json.dumps({
                "status": "created",
                "agent_id": agent_id,
                "name": name,
                "platform_url": f"https://game.virtuals.io/agents/{agent_id}",
            })
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})
