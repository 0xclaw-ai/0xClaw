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
from dataclasses import dataclass, field
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
sys.path.insert(0, str(Path(__file__).parent))  # makes `from runtime.xxx` work when run directly

from runtime.agent.loop import AgentLoop
from runtime.bus.events import InboundMessage
from runtime.bus.queue import MessageBus
from runtime.config.schema import Config
from runtime.cron.service import CronService
from runtime.providers.litellm_provider import LiteLLMProvider
from runtime.providers.custom_provider import CustomProvider
from runtime.session.manager import SessionManager

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
    "/status":        "Show pipeline progress and session token usage",
    "/resume":        "Resume from the latest checkpoint",
    "/redo <phase>":  "Reset phase (and downstream) and re-run it",
    "/new":           "Reset session and clear all pipeline outputs",
    "/stop":          "Cancel the current running task",
    "/exit":          "Exit 0xClaw",
    "/help":          "Show this help",
}

PHASES_LIST = list(PHASE_OUTPUTS.keys())  # ordered pipeline phase names


# ── token tracking ─────────────────────────────────────────────────────────────
@dataclass
class TokenCounter:
    """Accumulates token usage across all LLM calls in a session."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: dict) -> None:
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)

    @staticmethod
    def _k(n: int) -> str:
        return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

    def fmt(self) -> str:
        if self.total_tokens == 0:
            return ""
        return (
            f"↑{self._k(self.prompt_tokens)} ↓{self._k(self.completion_tokens)}"
            f"  total {self._k(self.total_tokens)}"
        )


# ── banner ─────────────────────────────────────────────────────────────────────
def _print_banner(provider: str, model: str) -> None:
    """Render the startup banner using Rich Panel (border always aligned)."""
    logo = Text("\n".join(LOGO_LINES), style="bold #fbbf24")

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
            border_style="#7c3aed",
            box=rich_box.DOUBLE,
            padding=(0, 2),
            expand=False,
        )
    )
    _PROVIDER_DISPLAY = {
        "flock": "FLock.io", "zhipu": "Z.ai", "openrouter": "OpenRouter",
        "anthropic": "Anthropic", "openai": "OpenAI", "deepseek": "DeepSeek",
        "gemini": "Gemini", "groq": "Groq",
    }
    display_provider = _PROVIDER_DISPLAY.get(provider, provider.title())
    console.print(
        f"  [dim]Provider:[/dim] [#fbbf24]{display_provider}[/#fbbf24]"
        f"  [dim]  Model:[/dim] [#fbbf24]{model}[/#fbbf24]"
    )
    console.print(
        "  [dim]Type[/dim] [bold #fbbf24]/help[/bold #fbbf24]"
        " [dim]for commands  ·  [/dim][bold #fbbf24]Tab[/bold #fbbf24]"
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
    t.add_column("cmd", style="bold #fbbf24", no_wrap=True)
    t.add_column("desc", style="dim")
    for cmd, desc in SLASH_COMMANDS.items():
        t.add_row(cmd, desc)
    console.print(
        Panel(t, title="[#fbbf24]Commands[/#fbbf24]", border_style="#7c3aed", padding=(0, 1))
    )



def _show_pipeline_status(state_store: PipelineStateStore) -> None:
    STATUS_STYLE = {
        "done":      ("[green]✓[/green]",        "done",      "green"),
        "running":   ("[#7c3aed]●[/#7c3aed]", "running",   "#7c3aed"),
        "failed":    ("[red]✗[/red]",          "failed",    "red"),
        "cancelled": ("[yellow]–[/yellow]",    "cancelled", "yellow"),
        "pending":   ("[dim]○[/dim]",          "pending",   "dim"),
    }
    try:
        state = state_store.load()
    except Exception:
        console.print("[dim]No pipeline state found. Run a phase to begin.[/dim]")
        return

    rows = {row["name"]: row for row in state["phases"]}
    done_count = sum(1 for r in rows.values() if r["status"] == "done")
    total = len(PHASE_OUTPUTS)

    t = Table(box=rich_box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("n",      style="dim",  no_wrap=True, width=2)
    t.add_column("phase",  no_wrap=True, width=10)
    t.add_column("icon",   no_wrap=True, width=3)
    t.add_column("status", no_wrap=True, width=10)

    for i, phase in enumerate(PHASE_OUTPUTS, 1):
        row = rows.get(phase, {"status": "pending"})
        status = row.get("status", "pending")
        icon, label, _ = STATUS_STYLE.get(status, STATUS_STYLE["pending"])
        t.add_row(str(i), phase, icon, f"[{_[2]}]{label}[/{_[2]}]")

    console.print(
        Panel(
            t,
            title=f"[#fbbf24]Pipeline[/#fbbf24]  [dim]{done_count}/{total} phases done[/dim]",
            border_style="#7c3aed",
            padding=(0, 1),
        )
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


def _make_tracking_provider(config: Config, counter: TokenCounter):
    """Return a provider that intercepts every LLM response to count tokens."""
    from runtime.providers.base import LLMProvider, LLMResponse

    inner = _make_provider(config)

    class _Wrapper(LLMProvider):
        def __init__(self):
            super().__init__(getattr(inner, "api_key", None), getattr(inner, "api_base", None))

        async def chat(self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7, reasoning_effort=None):
            resp = await inner.chat(messages, tools=tools, model=model, max_tokens=max_tokens, temperature=temperature, reasoning_effort=reasoning_effort)
            if resp.usage:
                counter.add(resp.usage)
            return resp

        def get_default_model(self) -> str:
            return inner.get_default_model()

    return _Wrapper()


def _reset_phase_and_downstream(phase: str, state_store: PipelineStateStore) -> list[str]:
    """Reset phase and all downstream phases to pending. Returns list of affected phase names."""
    idx = PHASES_LIST.index(phase)
    state = state_store.load()
    reset: list[str] = []
    for row in state["phases"]:
        if row["name"] in PHASES_LIST[idx:]:
            if row["status"] != "pending":
                row["status"] = "pending"
                row["updated_at"] = None
                reset.append(row["name"])
    state["last_error"] = None
    state["active_task"] = None
    state_store.save(state)
    return reset


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
        # Slash command input highlight — gold
        "slash": "#fbbf24 bold",
        # Completion dropdown — dark purple theme
        "completion-menu.completion":              "bg:#1a0a2e #a78bfa",
        "completion-menu.completion.current":      "bg:#7c3aed bold #fbbf24",
        "completion-menu.meta.completion":         "bg:#1a0a2e #6b7280",
        "completion-menu.meta.completion.current": "bg:#7c3aed #e5e7eb",
        "scrollbar.background":                    "bg:#1a0a2e",
        "scrollbar.button":                        "bg:#7c3aed",
    })

    active_phase: str | None = None
    active_trace_id: str | None = None
    bg_phase: str | None = None      # phase handed off to background monitor
    bg_trace_id: str | None = None
    token_counter = TokenCounter()
    init_anyway_from_env()

    # ── agent setup ────────────────────────────────────────────────────────────
    bus = MessageBus()
    provider = _make_tracking_provider(config, token_counter)
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
        get_phase=lambda: active_phase or bg_phase,
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
        """Drain the outbound bus. Releases prompt as soon as agent replies."""
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    console.print(f"  [dim]↳ {msg.content}[/dim]")
                elif not turn_done.is_set():
                    if _is_spawn_started_message(msg.content or ""):
                        console.print(f"  [dim]↳ {msg.content}[/dim]")
                    elif msg.content:
                        # Agent sent a substantive reply — release the prompt immediately.
                        # Background phase (if any) is monitored by _monitor_background.
                        turn_response.append(msg.content)
                        turn_done.set()
                    elif active_phase is None:
                        turn_done.set()
                elif msg.content:
                    console.print()
                    console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                    console.print(Markdown(msg.content))
                    console.print()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _monitor_background() -> None:
        """Poll for background phase output every 4 s; notify user on completion."""
        nonlocal bg_phase, bg_trace_id
        while True:
            await asyncio.sleep(4)
            if not bg_phase:
                continue
            output = PHASE_OUTPUTS.get(bg_phase)
            if _output_exists(output):
                state_machine.checkpoint(bg_phase, "done")
                finished = bg_phase
                bg_phase = None
                bg_trace_id = None
                console.print(
                    f"\n[bold green]✓[/bold green]  Phase [#7c3aed]{finished}[/#7c3aed] complete"
                    " — type [bold #fbbf24]/resume[/bold #fbbf24] to continue.\n"
                )

    consume_task = asyncio.create_task(_consume())
    monitor_task = asyncio.create_task(_monitor_background())

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
            user_input = await session.prompt_async(HTML("<b fg='#fbbf24'>❯</b> "))
            cmd = user_input.strip()
            if not cmd:
                continue

            # ── slash commands ─────────────────────────────────────────────────
            if cmd.startswith("/"):
                lower = cmd.lower().split()[0]

                if lower == "/exit":
                    console.print("[yellow]Goodbye! 🦀[/yellow]")
                    break

                if lower == "/help":
                    _show_help()
                    continue

                if lower == "/status":
                    _show_pipeline_status(state_store)
                    tok = token_counter.fmt()
                    if tok:
                        console.print(f"  [dim]Tokens this session  {tok}[/dim]\n")
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

                if lower.startswith("/redo"):
                    parts = cmd.split(maxsplit=1)
                    arg = parts[1].strip().lower() if len(parts) > 1 else ""
                    target_phase: str | None = None
                    if arg.isdigit():
                        idx = int(arg) - 1
                        if 0 <= idx < len(PHASES_LIST):
                            target_phase = PHASES_LIST[idx]
                    elif arg in PHASES_LIST:
                        target_phase = arg
                    if not target_phase:
                        console.print("[yellow]Usage:[/yellow] /redo <phase-name-or-number>")
                        console.print(
                            "  Phases: "
                            + "  ".join(f"[dim]{i + 1}.[/dim][#7c3aed]{p}[/#7c3aed]" for i, p in enumerate(PHASES_LIST))
                        )
                        continue
                    reset = _reset_phase_and_downstream(target_phase, state_store)
                    console.print(f"[dim]Reset:[/dim] {', '.join(reset)}")
                    _redo_commands = {
                        "research": "run research phase",
                        "idea": "generate ideas",
                        "selection": "select best idea for DevAgent",
                        "planning": "plan the architecture",
                        "coding": "implement the project",
                        "testing": "run tests",
                        "doc": "generate documentation and submission",
                    }
                    redo_cmd = _redo_commands[target_phase]
                    redo_route = router.route(redo_cmd)
                    if not redo_route.phase:
                        console.print(f"[red]Route failed:[/red] {redo_route.reason}")
                        continue
                    redo_check = state_machine.validate_phase_entry(redo_route.phase)
                    if not redo_check.ok:
                        console.print("[red]Phase blocked after reset:[/red]")
                        for err in redo_check.errors:
                            console.print(f"  - {err}")
                        continue
                    redo_profile = profile_resolver.resolve(redo_route.phase)
                    if redo_profile:
                        console.print(
                            f"[dim]Profile[/dim] {redo_profile.provider}/{redo_profile.model} "
                            f"[dim](timeout {redo_profile.timeout_s}s)[/dim]"
                        )
                    active_phase = redo_route.phase
                    active_trace_id = f"cli-{int(time.time())}-{redo_route.phase}"
                    state_machine.checkpoint(redo_route.phase, "running", active_task=active_trace_id)
                    redo_envelope = Envelope.from_command(
                        session_id="cli:direct",
                        phase=redo_route.phase,
                        agent_id="orchestrator",
                        trace_id=active_trace_id,
                        payload={"user_command": redo_cmd, "phase": redo_route.phase},
                    )
                    _append_envelope(redo_envelope)
                    redo_message = (
                        "You are executing a single pipeline phase. "
                        "Consume the envelope below and complete only that phase.\n"
                        "IMPORTANT: call spawn at most once for this phase. "
                        "If a spawned task is running, wait for its system result and do not spawn duplicates.\n\n"
                        + json.dumps(redo_envelope.to_dict(), ensure_ascii=False)
                    )
                    redo_timeout = redo_profile.timeout_s if redo_profile else DEFAULT_PHASE_TIMEOUT_S
                    response = await _send_and_wait_traced(
                        redo_message,
                        timeout_s=redo_timeout,
                        command=redo_cmd,
                        phase=redo_route.phase,
                        route_source=redo_route.source,
                    )
                    output = PHASE_OUTPUTS.get(redo_route.phase)
                    if _output_exists(output):
                        state_machine.checkpoint(redo_route.phase, "done")
                        active_phase = None
                        active_trace_id = None
                    else:
                        bg_phase = active_phase
                        bg_trace_id = active_trace_id
                        active_phase = None
                        active_trace_id = None
                    if response:
                        console.print()
                        console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                        console.print(Markdown(response))
                        tok = token_counter.fmt()
                        if tok:
                            console.print(f"  [dim]{tok}[/dim]")
                        console.print()
                    continue

                if lower == "/new":
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
                    else:
                        bg_phase = active_phase
                        bg_trace_id = active_trace_id
                        active_phase = None
                        active_trace_id = None
                    if response:
                        console.print()
                        console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                        console.print(Markdown(response))
                        tok = token_counter.fmt()
                        if tok:
                            console.print(f"  [dim]{tok}[/dim]")
                        console.print()
                    continue

                # unknown slash command — show hint
                console.print(
                    f"[yellow]Unknown command[/yellow] [#7c3aed]{cmd}[/#7c3aed]  "
                    "[dim]— type[/dim] [bold #fbbf24]/help[/bold #fbbf24] [dim]to see all commands[/dim]"
                )
                continue

            # ── route + state gate for normal inputs ───────────────────────────
            route = router.route(user_input)
            if route.phase:
                if bg_phase == route.phase:
                    console.print(f"[dim]Phase [#7c3aed]{bg_phase}[/#7c3aed] is already running in the background.[/dim]")
                    continue
                check = state_machine.validate_phase_entry(route.phase)
                if not check.ok:
                    if bg_phase:
                        console.print(
                            f"[yellow]Phase [#7c3aed]{bg_phase}[/#7c3aed] is running — "
                            f"you'll be notified when it's done.[/yellow]"
                        )
                    else:
                        console.print("[red]Phase blocked:[/red]")
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
                    active_phase = None
                    active_trace_id = None
                else:
                    # Sub-agent still running — hand off to background monitor.
                    bg_phase = active_phase
                    bg_trace_id = active_trace_id
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
                console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                console.print(Markdown(response))
                tok = token_counter.fmt()
                if tok:
                    console.print(f"  [dim]{tok}[/dim]")
                console.print()

    finally:
        agent.stop()
        consume_task.cancel()
        monitor_task.cancel()
        await asyncio.gather(bus_task, consume_task, monitor_task, return_exceptions=True)
        await agent.close_mcp()


# ── entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    # Suppress all loguru output unless --logs flag is passed
    if "--logs" not in sys.argv:
        logger.remove()

    load_dotenv(ROOT / ".env")
    config = _load_config()

    from runtime.utils.helpers import sync_workspace_templates
    sync_workspace_templates(WORKSPACE)

    asyncio.run(run_interactive(config))


if __name__ == "__main__":
    main()
