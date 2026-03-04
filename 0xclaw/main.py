"""0xClaw — Autonomous Hackathon Agent."""
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
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box as rich_box

# ── internal deps ──────────────────────────────────────────────────────────────
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

sys.path.insert(0, str(Path(__file__).parent))
from tools.virtuals_tool import VirtualsTool
from tools.unibase_tool import UnibaseTool

# ── globals ────────────────────────────────────────────────────────────────────
console = Console()
CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"
WORKSPACE = ROOT / "workspace"

# ── ASCII art (each line measured to 53 display columns) ──────────────────────
LOGO_LINES = [
    "  ██████╗  ██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗",
    " ██╔═████╗ ╚██╗██╔╝██╔════╝██║     ██╔══██╗██║    ██║",
    " ██║██╔██║  ╚███╔╝ ██║     ██║     ███████║██║ █╗ ██║",
    " ████╔╝██║  ██╔██╗ ██║     ██║     ██╔══██║██║███╗██║",
    " ╚██████╔╝ ██╔╝ ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝",
    "  ╚═════╝  ╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝",
]

# ── slash commands ─────────────────────────────────────────────────────────────
SLASH_COMMANDS: dict[str, str] = {
    "/help":   "Show all available commands",
    "/new":    "Start a fresh conversation",
    "/stop":   "Cancel the current running task",
    "/status": "Show provider and model information",
    "/exit":   "Exit 0xClaw",
    "/quit":   "Exit 0xClaw",
}


# ── banner ─────────────────────────────────────────────────────────────────────
def _print_banner(provider: str, model: str) -> None:
    """Render the startup banner using Rich Panel (border always aligned)."""
    logo = Text("\n".join(LOGO_LINES), style="bold cyan")

    meta = Text()
    meta.append("\n\n  Autonomous Hackathon Agent", style="white")
    meta.append("  ·  ", style="dim")
    meta.append("v0.1.0", style="dim white")
    meta.append("\n  UK AI Agent Hackathon EP4 × OpenClaw", style="dim white")
    meta.append("  ·  ", style="dim")
    meta.append("DoraHacks #1985", style="dim white")
    meta.append("\n")

    content = Text()
    content.append_text(logo)
    content.append_text(meta)

    console.print(
        Panel(
            content,
            border_style="cyan",
            box=rich_box.DOUBLE,
            padding=(0, 2),
            expand=False,
        )
    )
    console.print(
        f"  [dim]Provider[/dim] [cyan]{provider}[/cyan]"
        f"  [dim]·  Model[/dim] [cyan]{model}[/cyan]"
    )
    console.print(
        "  [dim]Type[/dim] [bold cyan]/help[/bold cyan]"
        " [dim]for commands  ·  [/dim][bold cyan]Tab[/bold cyan]"
        "[dim] to autocomplete[/dim]\n"
    )


# ── config ─────────────────────────────────────────────────────────────────────
def _load_config() -> Config:
    """Load config.json, substituting env vars silently. Fails fast for FLOCK_API_KEY."""
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found:[/red] {CONFIG_PATH}")
        console.print("[dim]Run:[/dim] cp .env.example .env")
        sys.exit(1)

    raw = CONFIG_PATH.read_text()

    def _substitute(match: re.Match) -> str:
        return os.environ.get(match.group(1), "")

    raw = re.sub(r"\$\{([^}]+)\}", _substitute, raw)
    data = json.loads(raw)

    # Fail fast: FLOCK_API_KEY is the only required key
    if not data.get("providers", {}).get("flock", {}).get("apiKey", "").strip():
        console.print("[red bold]✗ FLOCK_API_KEY is not set.[/red bold]")
        console.print(
            "  [dim]Get your key at[/dim] "
            "[cyan link=https://platform.flock.io]https://platform.flock.io[/cyan]"
        )
        sys.exit(1)

    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(WORKSPACE)
    return Config.model_validate(data)


def _make_provider(config: Config):
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


# ── slash command UI helpers ───────────────────────────────────────────────────
def _show_help() -> None:
    t = Table(box=rich_box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("cmd", style="bold cyan", no_wrap=True)
    t.add_column("desc", style="dim")
    for cmd, desc in SLASH_COMMANDS.items():
        t.add_row(cmd, desc)
    console.print(
        Panel(t, title="[cyan]Commands[/cyan]", border_style="dim cyan", padding=(0, 1))
    )


def _show_status(config: Config) -> None:
    t = Table(box=None, show_header=False, padding=(0, 2))
    t.add_column("key", style="dim", no_wrap=True)
    t.add_column("val", style="cyan")
    t.add_row("Provider",    config.agents.defaults.provider)
    t.add_row("Model",       config.agents.defaults.model)
    t.add_row("Max tokens",  str(config.agents.defaults.max_tokens))
    t.add_row("Temperature", str(config.agents.defaults.temperature))
    t.add_row("Workspace",   str(WORKSPACE))
    console.print(
        Panel(t, title="[cyan]Status[/cyan]", border_style="dim cyan", padding=(0, 1))
    )


# ── main interactive loop ──────────────────────────────────────────────────────
async def run_interactive(config: Config) -> None:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.styles import Style

    # ── slash command completer ────────────────────────────────────────────────
    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.lstrip()
            if not text.startswith("/"):
                return
            for cmd, desc in SLASH_COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=desc,
                    )

    # ── syntax highlighter: cyan for /commands ─────────────────────────────────
    class _SlashLexer(Lexer):
        def lex_document(self, document):
            def get_line(lineno):
                line = document.text
                if line.startswith("/"):
                    return [("class:slash", line)]
                return [("", line)]
            return get_line

    prompt_style = Style.from_dict({
        # Slash command input highlight
        "slash": "#5bc2e7 bold",
        # Completion dropdown
        "completion-menu.completion":              "bg:#111827 #7ec8e3",
        "completion-menu.completion.current":      "bg:#1e3a5f bold #ffffff",
        "completion-menu.meta.completion":         "bg:#111827 #4b5563",
        "completion-menu.meta.completion.current": "bg:#1e3a5f #9ca3af",
        "scrollbar.background":                    "bg:#111827",
        "scrollbar.button":                        "bg:#1e3a5f",
    })

    # ── agent setup ────────────────────────────────────────────────────────────
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
    agent.tools.register(VirtualsTool())
    agent.tools.register(UnibaseTool())

    history_path = WORKSPACE / ".history" / "cli_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=_SlashCompleter(),
        lexer=_SlashLexer(),
        complete_while_typing=True,
        style=prompt_style,
        multiline=False,
    )

    _print_banner(config.agents.defaults.provider, config.agents.defaults.model)

    # ── Signal Handling with Context Awareness ────────────────────────────────
    is_task_running = False

    def _on_sigint(sig, frame):
        if is_task_running:
            # Interrupt the agent but stay in the CLI
            agent.stop()
            turn_done.set()
            console.print("\n[yellow]⏹  Task interrupted (Ctrl+C). Returning to prompt.[/yellow]")
        else:
            # Normal exit if no task is active
            console.print("\n[yellow]Goodbye! 🦀[/yellow]")
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
                    console.print("[bold cyan]🦀  0xClaw[/bold cyan]")
                    console.print(Markdown(msg.content))
                    console.print()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    consume_task = asyncio.create_task(_consume())

    try:
        while True:
            try:
                user_input = await session.prompt_async(HTML("<b fg='#5bc2e7'>❯</b> "))
            except (KeyboardInterrupt, EOFError):
                # This handles Ctrl+C when prompt_toolkit is active (idle state)
                _on_sigint(None, None)
                continue

            cmd = user_input.strip()
            if not cmd:
                continue

            # ── slash commands ─────────────────────────────────────────────────
            if cmd.startswith("/"):
                lower = cmd.lower().split()[0]

                if lower in {"/exit", "/quit"}:
                    console.print("[yellow]Goodbye! 🦀[/yellow]")
                    break

                if lower == "/help":
                    _show_help()
                    continue

                if lower == "/status":
                    _show_status(config)
                    continue

                if lower == "/stop":
                    agent.stop()
                    turn_done.set()
                    console.print("[yellow]⏹  Task cancelled.[/yellow]")
                    continue

                if lower == "/new":
                    console.print("[dim]Resetting session…[/dim]")
                    turn_done.clear()
                    turn_response.clear()
                    is_task_running = True
                    await bus.publish_inbound(InboundMessage(
                        channel="cli", sender_id="user", chat_id="direct",
                        content=(
                            "[SYSTEM] Start a completely fresh conversation. "
                            "Clear all previous context. "
                            "Acknowledge with a single short line."
                        ),
                    ))
                    with console.status("[dim]Resetting…[/dim]", spinner="dots"):
                        await turn_done.wait()
                    is_task_running = False
                    if turn_response:
                        console.print(f"[green]✓[/green]  {turn_response[0].strip()}")
                    else:
                        console.print("[green]✓  Fresh session ready.[/green]")
                    console.print()
                    continue

                # unknown slash command — show hint
                console.print(
                    f"[yellow]Unknown command[/yellow] [cyan]{cmd}[/cyan]  "
                    "[dim]— type[/dim] [bold cyan]/help[/bold cyan] [dim]to see all commands[/dim]"
                )
                continue

            # ── plain text exit ────────────────────────────────────────────────
            if cmd.lower() in {"exit", "quit"}:
                console.print("[yellow]Goodbye! 🦀[/yellow]")
                break

            # ── send message to agent ──────────────────────────────────────────
            turn_done.clear()
            turn_response.clear()
            is_task_running = True

            await bus.publish_inbound(InboundMessage(
                channel="cli", sender_id="user", chat_id="direct", content=user_input,
            ))

            with console.status("[dim]0xClaw is thinking…[/dim]", spinner="dots"):
                await turn_done.wait()

            is_task_running = False

            if turn_response:
                console.print()
                console.print("[bold cyan]🦀  0xClaw[/bold cyan]")
                console.print(Markdown(turn_response[0]))
                console.print()

    finally:
        agent.stop()
        consume_task.cancel()
        await asyncio.gather(bus_task, consume_task, return_exceptions=True)
        await agent.close_mcp()


# ── entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    # Suppress all loguru output unless --logs flag is passed
    if "--logs" not in sys.argv:
        logger.remove()

    config = _load_config()

    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(WORKSPACE)

    asyncio.run(run_interactive(config))


if __name__ == "__main__":
    main()
