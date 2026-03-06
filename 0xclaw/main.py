"""0xClaw — Autonomous Hackathon Agent."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from dotenv import load_dotenv
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
from orchestration.contracts import Envelope
from orchestration.model_profiles import ModelProfileResolver
from orchestration.router import SkillRouter
from orchestration.session_control import SessionControl
from orchestration.state import OrchestratorStateMachine, PipelineStateStore
from orchestration.write_guard import build_phase_write_guard, install_phase_write_guards
from tools.virtuals_tool import VirtualsTool
from tools.unibase_tool import UnibaseTool
from observability.anyway import init_anyway_from_env, workflow_span

# ── globals ────────────────────────────────────────────────────────────────────
console = Console()
CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"
MODEL_PROFILES_PATH = ROOT / "0xclaw" / "config" / "model_profiles.json"
WORKSPACE = ROOT / "workspace"
HACKATHON_DIR = WORKSPACE / "hackathon"
ENVELOPE_LOG = HACKATHON_DIR / "envelopes.jsonl"

PHASE_OUTPUTS: dict[str, Path] = {
    "research": HACKATHON_DIR / "context.json",
    "idea": HACKATHON_DIR / "ideas.json",
    "selection": HACKATHON_DIR / "selected_idea.json",
    "planning": HACKATHON_DIR / "plan.md",
    "coding": HACKATHON_DIR / "project",
    "testing": HACKATHON_DIR / "test_results.json",
    "doc": HACKATHON_DIR / "submission" / "README.md",
}
DEFAULT_PHASE_TIMEOUT_S = 240
HACKATHON_RUNTIME_PATHS = (
    "context.json",
    "ideas.json",
    "selected_idea.json",
    "plan.md",
    "tasks.json",
    "test_results.json",
    "progress.md",
    "pipeline_state.json",
    "metrics.jsonl",
    "envelopes.jsonl",
    "research_summary.md",
    "research",
    "artifacts",
    "project",
    "submission",
)
WORKSPACE_RUNTIME_PATHS = (
    "research",
    "hackathon-research.md",
)

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
    "/reset":  "Alias for /new",
    "/resume": "Resume from the latest pipeline checkpoint",
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
    """Load config.json with env substitution and provider-aware key validation."""
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found:[/red] {CONFIG_PATH}")
        console.print("[dim]Run:[/dim] cp .env.example .env")
        sys.exit(1)

    raw = CONFIG_PATH.read_text()

    def _substitute(match: re.Match) -> str:
        return os.environ.get(match.group(1), "")

    raw = re.sub(r"\$\{([^}]+)\}", _substitute, raw)
    data = json.loads(raw)

    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(WORKSPACE)
    config = Config.model_validate(data)

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model) or config.agents.defaults.provider
    provider_cfg = config.get_provider(model)
    if not provider_cfg or not (provider_cfg.api_key or "").strip():
        key_hints: dict[str, tuple[str, str]] = {
            "flock": ("FLOCK_API_KEY", "https://platform.flock.io"),
            "zhipu": ("ZAI_API_KEY", "https://open.bigmodel.cn"),
            "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/keys"),
            "deepseek": ("DEEPSEEK_API_KEY", "https://platform.deepseek.com"),
            "openai": ("OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
            "anthropic": ("ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys"),
            "gemini": ("GEMINI_API_KEY", "https://aistudio.google.com/apikey"),
        }
        env_name, help_url = key_hints.get(provider_name, ("<PROVIDER_API_KEY>", ""))
        console.print(f"[red bold]✗ {env_name} is not set for provider '{provider_name}'.[/red bold]")
        if help_url:
            console.print(f"  [dim]Get your key at[/dim] [cyan link={help_url}]{help_url}[/cyan]")
        sys.exit(1)

    return config


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


def _output_exists(path: Path | None) -> bool:
    if path is None:
        return False
    if path.is_dir():
        return any(path.rglob("*"))
    return path.exists() and path.stat().st_size > 10


def _fallback_classifier(text: str) -> str | None:
    t = text.lower()
    if "plan" in t or "规划" in t:
        return "planning"
    if "test" in t or "测试" in t:
        return "testing"
    if "doc" in t or "文档" in t:
        return "doc"
    if "code" in t or "实现" in t:
        return "coding"
    return None


def _append_envelope(envelope: Envelope) -> None:
    ENVELOPE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ENVELOPE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(envelope.to_dict(), ensure_ascii=False) + "\n")


def _is_spawn_started_message(text: str) -> bool:
    t = text.strip()
    return t.startswith("Subagent [") and " started (id: " in t


def _reset_hackathon_outputs() -> list[str]:
    HACKATHON_DIR.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []
    for rel in HACKATHON_RUNTIME_PATHS:
        p = HACKATHON_DIR / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(rel + "/")
        elif p.exists():
            p.unlink()
            removed.append(rel)
    return removed


def _reset_workspace_runtime_outputs() -> list[str]:
    removed: list[str] = []
    for rel in WORKSPACE_RUNTIME_PATHS:
        p = WORKSPACE / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(f"workspace/{rel}/")
        elif p.exists():
            p.unlink()
            removed.append(f"workspace/{rel}")
    return removed


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

    active_phase: str | None = None
    active_trace_id: str | None = None
    init_anyway_from_env()

    # ── agent setup ────────────────────────────────────────────────────────────
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(WORKSPACE)
    state_store = PipelineStateStore(HACKATHON_DIR)
    state_machine = OrchestratorStateMachine(WORKSPACE, state_store)
    session_control = SessionControl(state_store)
    router = SkillRouter(fallback_classifier=_fallback_classifier)
    profile_resolver = ModelProfileResolver(MODEL_PROFILES_PATH)

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
    write_guard = build_phase_write_guard(
        workspace=WORKSPACE,
        state_machine=state_machine,
        get_phase=lambda: active_phase,
    )
    install_phase_write_guards(agent.tools, write_guard)
    agent.subagents.set_write_guard(write_guard)

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

    def _on_sigint(sig, frame):
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
                    if active_phase:
                        output = PHASE_OUTPUTS.get(active_phase)
                        if _output_exists(output):
                            turn_done.set()
                        elif msg.content and _is_spawn_started_message(msg.content):
                            console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif output is None:
                            turn_done.set()
                    else:
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

    async def _send_and_wait(text: str, *, timeout_s: int = DEFAULT_PHASE_TIMEOUT_S) -> str:
        turn_done.clear()
        turn_response.clear()
        await bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="user", chat_id="direct", content=text,
        ))
        try:
            with console.status("[dim]0xClaw is thinking…[/dim]", spinner="dots"):
                await asyncio.wait_for(turn_done.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            turn_done.set()
            console.print(f"[yellow]Timed out after {timeout_s}s.[/yellow]")
        return turn_response[0] if turn_response else ""

    async def _send_and_wait_traced(
        text: str,
        *,
        timeout_s: int = DEFAULT_PHASE_TIMEOUT_S,
        command: str,
        phase: str | None,
        route_source: str | None = None,
    ) -> str:
        if command in {"/new", "/stop"}:
            return await _send_and_wait(text, timeout_s=timeout_s)

        # Only trace turns that actually produced a model response.
        response = await _send_and_wait(text, timeout_s=timeout_s)
        if not response:
            return response

        attrs = {
            "request.command": command[:200],
            "request.is_slash": command.startswith("/"),
            "request.phase": phase,
            "request.route_source": route_source,
            "request.timeout_s": timeout_s,
            "response.received": True,
            "response.length": len(response),
        }
        with workflow_span("0xclaw.cli.turn", attrs):
            pass
        return response

    try:
        while True:
            user_input = await session.prompt_async(HTML("<b fg='#5bc2e7'>❯</b> "))
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
                    response = await _send_and_wait_traced(
                        "/stop",
                        timeout_s=30,
                        command=cmd,
                        phase=active_phase,
                        route_source="slash",
                    )
                    if active_phase:
                        state_machine.checkpoint(active_phase, "cancelled", last_error="Cancelled by /stop")
                        active_phase = None
                        active_trace_id = None
                    if response:
                        console.print(f"[yellow]{response.strip()}[/yellow]")
                    else:
                        console.print("[yellow]⏹  Stop signal sent.[/yellow]")
                    continue

                if lower in {"/new", "/reset"}:
                    console.print("[dim]Resetting session…[/dim]")
                    response = await _send_and_wait_traced(
                        "/new",
                        timeout_s=30,
                        command=cmd,
                        phase=active_phase,
                        route_source="slash",
                    )
                    removed = _reset_hackathon_outputs() + _reset_workspace_runtime_outputs()
                    active_phase = None
                    active_trace_id = None
                    if response:
                        console.print(f"[green]✓[/green]  {response.strip()}")
                    else:
                        console.print("[green]✓  Fresh session ready.[/green]")
                    if removed:
                        console.print(f"[dim]Cleared hackathon outputs:[/dim] {len(removed)} item(s)")
                    console.print()
                    continue

                if lower == "/resume":
                    decision = session_control.get_resume_decision()
                    if not decision.command:
                        console.print(f"[green]✓[/green] {decision.reason}")
                        continue
                    console.print(f"[dim]{decision.reason}[/dim]")
                    cmd = decision.command
                    route = router.route(cmd)
                    if not route.phase:
                        console.print(f"[red]Resume route failed:[/red] {route.reason}")
                        continue
                    check = state_machine.validate_phase_entry(route.phase)
                    if not check.ok:
                        console.print("[red]Cannot resume phase:[/red]")
                        for err in check.errors:
                            console.print(f"  - {err}")
                        continue
                    profile = profile_resolver.resolve(route.phase)
                    if profile:
                        console.print(
                            f"[dim]Profile[/dim] {profile.provider}/{profile.model} "
                            f"[dim](timeout {profile.timeout_s}s)[/dim]"
                        )
                    active_phase = route.phase
                    active_trace_id = f"cli-{int(time.time())}-{route.phase}"
                    state_machine.checkpoint(route.phase, "running", active_task=active_trace_id)
                    envelope = Envelope.from_command(
                        session_id="cli:direct",
                        phase=route.phase,
                        agent_id="orchestrator",
                        trace_id=active_trace_id,
                        payload={"user_command": cmd, "phase": route.phase},
                    )
                    _append_envelope(envelope)
                    message = (
                        "You are executing a single pipeline phase. "
                        "Consume the envelope below and complete only that phase.\n"
                        "IMPORTANT: call spawn at most once for this phase. "
                        "If a spawned task is running, wait for its system result and do not spawn duplicates.\n\n"
                        + json.dumps(envelope.to_dict(), ensure_ascii=False)
                    )
                    timeout_s = profile.timeout_s if profile else DEFAULT_PHASE_TIMEOUT_S
                    response = await _send_and_wait_traced(
                        message,
                        timeout_s=timeout_s,
                        command=cmd,
                        phase=route.phase,
                        route_source=route.source,
                    )
                    output = PHASE_OUTPUTS.get(route.phase)
                    if _output_exists(output):
                        state_machine.checkpoint(route.phase, "done")
                        active_phase = None
                        active_trace_id = None
                    elif active_phase:
                        state_machine.checkpoint(route.phase, "failed", last_error="No expected output detected")
                        active_phase = None
                        active_trace_id = None
                    if response:
                        console.print()
                        console.print("[bold cyan]🦀  0xClaw[/bold cyan]")
                        console.print(Markdown(response))
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

            # ── route + state gate for normal inputs ───────────────────────────
            route = router.route(user_input)
            if route.phase:
                check = state_machine.validate_phase_entry(route.phase)
                if not check.ok:
                    console.print("[red]Phase blocked by state gate:[/red]")
                    for err in check.errors:
                        console.print(f"  - {err}")
                    continue

                profile = profile_resolver.resolve(route.phase)
                if profile:
                    console.print(
                        f"[dim]Phase[/dim] {route.phase} [dim]via {route.source} "
                        f"(confidence {route.confidence:.2f})[/dim]"
                    )
                    console.print(
                        f"[dim]Profile[/dim] {profile.provider}/{profile.model} "
                        f"[dim](timeout {profile.timeout_s}s)[/dim]"
                    )

                active_phase = route.phase
                active_trace_id = f"cli-{int(time.time())}-{route.phase}"
                state_machine.checkpoint(route.phase, "running", active_task=active_trace_id)

                envelope = Envelope.from_command(
                    session_id="cli:direct",
                    phase=route.phase,
                    agent_id="orchestrator",
                    trace_id=active_trace_id,
                    payload={"user_command": user_input, "phase": route.phase},
                )
                _append_envelope(envelope)
                routed_input = (
                    "You are executing a single pipeline phase. "
                    "Consume the envelope below and complete only that phase.\n"
                    "IMPORTANT: call spawn at most once for this phase. "
                    "If a spawned task is running, wait for its system result and do not spawn duplicates.\n\n"
                    + json.dumps(envelope.to_dict(), ensure_ascii=False)
                )
                timeout_s = profile.timeout_s if profile else DEFAULT_PHASE_TIMEOUT_S
                response = await _send_and_wait_traced(
                    routed_input,
                    timeout_s=timeout_s,
                    command=cmd,
                    phase=route.phase,
                    route_source=route.source,
                )
                output = PHASE_OUTPUTS.get(route.phase)
                if _output_exists(output):
                    state_machine.checkpoint(route.phase, "done")
                else:
                    state_machine.checkpoint(route.phase, "failed", last_error="No expected output detected")
                active_phase = None
                active_trace_id = None
            else:
                response = await _send_and_wait_traced(
                    user_input,
                    command=cmd,
                    phase=None,
                    route_source="none",
                )

            if response:
                console.print()
                console.print("[bold cyan]🦀  0xClaw[/bold cyan]")
                console.print(Markdown(response))
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

    load_dotenv(ROOT / ".env")
    config = _load_config()

    from nanobot.utils.helpers import sync_workspace_templates
    sync_workspace_templates(WORKSPACE)

    asyncio.run(run_interactive(config))


if __name__ == "__main__":
    main()
