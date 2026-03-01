"""0xClaw entry point — Autonomous Hackathon Agent."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.markdown import Markdown

# Add nanobot to path (sibling package)
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "nanobot"))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.custom_provider import CustomProvider
from nanobot.session.manager import SessionManager

console = Console()

CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"
WORKSPACE = ROOT / "workspace"

BANNER = """
╔═══════════════════════════════════════════╗
║   ██████╗ ██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗ ║
║  ██╔═████╗╚██╗██╔╝██╔════╝██║     ██╔══██╗██║    ██║ ║
║  ██║██╔██║ ╚███╔╝ ██║     ██║     ███████║██║ █╗ ██║ ║
║  ████╔╝██║ ██╔██╗ ██║     ██║     ██╔══██║██║███╗██║ ║
║  ╚██████╔╝██╔╝ ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝ ║
║   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  ║
║                                                       ║
║   Autonomous Hackathon Agent   v0.1.0                 ║
║   UK AI Agent Hackathon EP4 × OpenClaw                ║
╚═══════════════════════════════════════════╝
"""


def _load_config() -> Config:
    """Load config from project config.json, substituting env vars."""
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        console.print("Run: cp .env.example .env && fill in your API keys")
        sys.exit(1)

    raw = CONFIG_PATH.read_text()

    # Substitute ${VAR_NAME} patterns with environment variables
    def _substitute(match: re.Match) -> str:
        var = match.group(1)
        value = os.environ.get(var, "")
        if not value:
            logger.warning("Environment variable {} not set", var)
        return value

    raw = re.sub(r"\$\{([^}]+)\}", _substitute, raw)

    data = json.loads(raw)
    # Fix workspace path to absolute
    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(WORKSPACE)
    return Config.model_validate(data)


def _make_provider(config: Config):
    """Create LLM provider from config."""
    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model) or config.agents.defaults.provider
    p = config.get_provider(model)

    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


async def run_interactive(config: Config) -> None:
    """Run 0xClaw in interactive CLI mode."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(WORKSPACE)

    cron_path = WORKSPACE / ".cron" / "jobs.json"
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    cron = CronService(cron_path)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=WORKSPACE,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        session_manager=session_manager,
    )

    history_path = WORKSPACE / ".history" / "cli_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(history=FileHistory(str(history_path)), multiline=False)

    console.print(BANNER)
    console.print("[cyan]UK AI Agent Hackathon EP4 × OpenClaw[/cyan]")
    console.print(f"[dim]Provider: {config.agents.defaults.provider} | Model: {config.agents.defaults.model}[/dim]")
    console.print("[dim]Type 'exit' to quit | /new to reset session | /stop to cancel task[/dim]\n")

    def _on_sigint(sig, frame):
        console.print("\n[yellow]Goodbye![/yellow]")
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    bus_task = asyncio.create_task(agent.run())
    turn_done = asyncio.Event()
    turn_done.set()
    turn_response: list[str] = []

    async def _consume():
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    console.print(f"  [dim]↳ {msg.content}[/dim]")
                elif not turn_done.is_set():
                    if msg.content:
                        turn_response.append(msg.content)
                    turn_done.set()
                elif msg.content:
                    console.print()
                    console.print("[cyan]🦀 0xClaw[/cyan]")
                    console.print(Markdown(msg.content))
                    console.print()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    consume_task = asyncio.create_task(_consume())

    try:
        while True:
            user_input = await session.prompt_async(HTML("<b fg='ansiblue'>You:</b> "))
            cmd = user_input.strip()
            if not cmd:
                continue
            if cmd.lower() in {"exit", "quit", "/exit", "/quit"}:
                console.print("[yellow]Goodbye![/yellow]")
                break

            turn_done.clear()
            turn_response.clear()

            await bus.publish_inbound(InboundMessage(
                channel="cli", sender_id="user", chat_id="direct", content=user_input,
            ))

            with console.status("[dim]0xClaw is thinking...[/dim]", spinner="dots"):
                await turn_done.wait()

            if turn_response:
                console.print()
                console.print("[cyan]🦀 0xClaw[/cyan]")
                console.print(Markdown(turn_response[0]))
                console.print()

    finally:
        agent.stop()
        consume_task.cancel()
        await asyncio.gather(bus_task, consume_task, return_exceptions=True)
        await agent.close_mcp()


def main() -> None:
    """Main entry point."""
    if "--logs" not in sys.argv:
        logger.disable("nanobot")

    config = _load_config()

    # Create any workspace files that are still missing (never overwrites existing).
    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(WORKSPACE)

    asyncio.run(run_interactive(config))


if __name__ == "__main__":
    main()
