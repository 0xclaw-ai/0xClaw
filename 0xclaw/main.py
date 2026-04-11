"""0xClaw — Autonomous Hackathon Agent."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import shutil
import sys
import time
from dataclasses import dataclass
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
from runtime.providers.acp_provider import ACPProvider
from runtime.providers.litellm_provider import LiteLLMProvider
from runtime.providers.custom_provider import CustomProvider
from runtime.session.manager import SessionManager

from cli_args import parse_gateway_args, parse_whatsapp_args
from orchestration.contracts import Envelope
from orchestration.model_profiles import ModelProfileResolver
from orchestration.phase_completion import (
    clear_marker,
    detect_failure_reason,
    is_phase_complete,
    marker_path,
    output_exists as phase_output_exists,
    write_marker,
)
from orchestration.router import SkillRouter
from orchestration.session_control import SessionControl
from orchestration.state import (
    COMPLETED_PHASE_STATUSES,
    OrchestratorStateMachine,
    PipelineStateStore,
)
from orchestration.write_guard import build_phase_write_guard, install_phase_write_guards

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
    "coding.done.json",
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
    "memory/MEMORY.md",    # agent long-term memory — stale hackathon context bleeds through after /new
    "memory/HISTORY.md",  # conversation history log
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

# ── shell passthrough suggestions (shown when user types !) ───────────────────
SHELL_SUGGESTIONS: list[tuple[str, str]] = [
    ("ls",                                         "list files in project root"),
    ("ls -la",                                     "list all files with details"),
    ("git status",                                 "git working tree status"),
    ("git log --oneline -5",                       "last 5 commits"),
    ("git diff",                                   "show unstaged changes"),
    ("cat workspace/hackathon/pipeline_state.json","pipeline phase state"),
    ("pwd",                                        "current directory"),
]

REDO_COMMANDS: dict[str, str] = {
    "research": "run research phase",
    "idea": "generate ideas",
    "selection": "select the best idea",
    "planning": "plan the architecture",
    "coding": "implement the project",
    "testing": "run tests",
    "doc": "generate documentation and submission",
}


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
        "acp": "ACP/Claude Code",
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
        "  [dim]Type[/dim] [bold #fbbf24]?[/bold #fbbf24]"
        " [dim]or[/dim] [bold #fbbf24]/help[/bold #fbbf24]"
        " [dim]for commands  ·  [/dim][bold #fbbf24]![/bold #fbbf24][dim]<cmd>[/dim]"
        " [dim]for shell  ·  [/dim][bold #fbbf24]Tab[/bold #fbbf24]"
        "[dim] to autocomplete[/dim]\n"
    )


# ── config ─────────────────────────────────────────────────────────────────────
def _load_config(*, validate_provider_key: bool = True) -> Config:
    """Load config.json with env-var substitution.

    Args:
        validate_provider_key: When True (default), abort if the active provider
            has no API key configured.  Pass False for channel/gateway mode where
            a missing LLM key is non-fatal.
    """
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found:[/red] {CONFIG_PATH}")
        console.print(
            "[dim]Copy the example and fill in your API keys:[/dim] "
            f"cp {CONFIG_PATH}.example {CONFIG_PATH}"
        )
        sys.exit(1)

    raw = CONFIG_PATH.read_text()

    missing_vars: list[str] = []

    def _substitute(match: re.Match) -> str:
        key = match.group(1)
        val = os.environ.get(key, "")
        if not val:
            missing_vars.append(key)
        return val

    raw = re.sub(r"\$\{([^}]+)\}", _substitute, raw)
    if missing_vars:
        logger.debug("Env vars not set (will be empty in config): %s", ", ".join(missing_vars))

    data = json.loads(raw)
    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(WORKSPACE)
    config = Config.model_validate(data)

    if validate_provider_key:
        model = config.agents.defaults.model
        provider_name = config.get_provider_name(model) or config.agents.defaults.provider
        provider_cfg = config.get_provider(model)
        if provider_name == "acp":
            ok, message = ACPProvider.from_config(config, default_model=model).preflight()
            if not ok:
                console.print("[red bold]✗ ACP provider is not ready.[/red bold]")
                console.print(f"  [dim]{message}[/dim]")
                console.print("  [dim]Install acpx, ensure `claude` is on PATH, and log into Claude Code first.[/dim]")
                sys.exit(1)
            return config
        if not provider_cfg or not (provider_cfg.api_key or "").strip():
            key_hints: dict[str, tuple[str, str]] = {
                "flock": ("FLOCK_API_KEY", "https://platform.flock.io"),
                "zhipu": ("ZAI_API_KEY", "https://z.ai/model-api"),
                "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/keys"),
                "deepseek": ("DEEPSEEK_API_KEY", "https://platform.deepseek.com"),
                "openai": ("OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
                "anthropic": ("ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys"),
                "gemini": ("GEMINI_API_KEY", "https://aistudio.google.com/apikey"),
            }
            env_name, help_url = key_hints.get(provider_name, ("<PROVIDER_API_KEY>", ""))
            console.print(f"[red bold]✗ {env_name} is not set for provider '{provider_name}'.[/red bold]")
            if help_url:
                console.print(f"  [dim]Get your key at[/dim] [cyan link='{help_url}']{help_url}[/cyan]")
            sys.exit(1)

    return config


def _make_provider(config: Config):
    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model) or config.agents.defaults.provider
    p = config.get_provider(model)

    if provider_name == "acp":
        return ACPProvider.from_config(config, default_model=model)
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
    t.add_row("", "")
    t.add_row("?",       "Alias for /help")
    t.add_row("!<cmd>",  "Run a shell command  (e.g. !ls  !git log  !pwd)")
    console.print(
        Panel(t, title="[#fbbf24]Commands[/#fbbf24]", border_style="#7c3aed", padding=(0, 1))
    )



def _show_pipeline_status(state_store: PipelineStateStore) -> None:
    STATUS_STYLE = {
        "done":      ("[green]✓[/green]",        "done",      "green"),
        "complete":  ("[green]✓[/green]",        "done",      "green"),
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
    done_count = sum(1 for r in rows.values() if r["status"] in COMPLETED_PHASE_STATUSES)
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
    return phase_output_exists(path)


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


def _is_background_handoff_progress(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith('spawn("') or _is_spawn_started_message(t)


def _phase_is_complete(phase: str | None) -> bool:
    if not phase:
        return False
    return is_phase_complete(
        phase,
        hackathon_dir=HACKATHON_DIR,
        phase_output=PHASE_OUTPUTS.get(phase),
    )


def _prepare_phase_run(phase: str) -> None:
    clear_marker(HACKATHON_DIR, phase)


def _mark_phase_complete(phase: str, trace_id: str | None) -> None:
    path = marker_path(HACKATHON_DIR, phase)
    if path is None:
        return
    write_marker(HACKATHON_DIR, phase, {"phase": phase, "status": "done", "trace_id": trace_id})


@dataclass(slots=True)
class SendWaitResult:
    response: str
    timed_out: bool = False
    background_handoff: bool = False


def _finalize_phase_run(
    *,
    phase: str,
    trace_id: str | None,
    result: SendWaitResult,
    state_machine: OrchestratorStateMachine,
) -> tuple[str | None, bool]:
    failure_reason = detect_failure_reason(result.response, timed_out=result.timed_out)
    primary_output_ready = _output_exists(PHASE_OUTPUTS.get(phase))

    if result.background_handoff:
        state_machine.checkpoint(phase, "running", active_task=trace_id)
        return trace_id, True

    if failure_reason:
        state_machine.checkpoint(phase, "failed", last_error=failure_reason)
        return None, False

    if primary_output_ready:
        _mark_phase_complete(phase, trace_id)

    if _phase_is_complete(phase):
        state_machine.checkpoint(phase, "done")
        return None, False

    state_machine.checkpoint(
        phase,
        "failed",
        last_error="Phase ended without producing the completion artifact",
    )
    return None, False


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


def _print_cli_usage() -> None:
    """Show top-level CLI usage."""
    console.print("Usage:")
    console.print("  0xclaw [--logs]")
    console.print("  0xclaw gateway [--port PORT] [--verbose]")
    console.print("  0xclaw whatsapp login")


def _parse_gateway_args(argv: list[str]) -> tuple[int | None, bool]:
    """Parse arguments for the gateway subcommand."""
    if any(arg in {"-h", "--help"} for arg in argv):
        _print_cli_usage()
        raise SystemExit(0)
    return parse_gateway_args(argv)


def _parse_whatsapp_args(argv: list[str]) -> str:
    """Parse arguments for the whatsapp subcommand."""
    command = parse_whatsapp_args(argv)
    if command == "help":
        console.print("Usage:")
        console.print("  0xclaw whatsapp login")
        raise SystemExit(0)
    return command


def _find_whatsapp_bridge_source() -> Path:
    """Locate the installed WhatsApp bridge source directory."""
    try:
        import nanobot  # type: ignore
    except ImportError as exc:
        console.print("[red]0xClaw WhatsApp bridge assets not found.[/red]")
        console.print("Install the dependency first in this environment: [cyan]python -m pip install nanobot-ai[/cyan]")
        raise SystemExit(1) from exc

    bridge_dir = Path(nanobot.__file__).resolve().parent / "bridge"
    if not (bridge_dir / "package.json").exists():
        console.print("[red]Installed dependency does not include 0xClaw WhatsApp bridge assets.[/red]")
        console.print("Reinstall it in this environment: [cyan]python -m pip install --force-reinstall nanobot-ai[/cyan]")
        raise SystemExit(1)
    return bridge_dir


def _rewrite_bridge_branding(bridge_dir: Path) -> None:
    """Rewrite copied bridge assets so user-facing branding uses 0xClaw."""
    replacements = {
        "nanobot WhatsApp Bridge": "0xClaw WhatsApp Bridge",
        "WhatsApp bridge for nanobot using Baileys": "WhatsApp bridge for 0xClaw using Baileys",
        "This bridge connects WhatsApp Web to nanobot's Python backend": "This bridge connects WhatsApp Web to 0xClaw's Python backend",
        "AUTH_DIR=~/.nanobot/whatsapp npm start": "AUTH_DIR=~/.0xclaw/whatsapp-auth npm start",
        "join(homedir(), '.nanobot', 'whatsapp-auth')": "join(homedir(), '.0xclaw', 'whatsapp-auth')",
        "nanobot-whatsapp-bridge": "0xclaw-whatsapp-bridge",
        "🐈 nanobot WhatsApp Bridge": "🦀 0xClaw WhatsApp Bridge",
        "🐈 0xClaw WhatsApp Bridge": "🦀 0xClaw WhatsApp Bridge",
    }
    targets = [
        bridge_dir / "package.json",
        bridge_dir / "src" / "index.ts",
    ]
    for path in targets:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        updated = content
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != content:
            path.write_text(updated, encoding="utf-8")


def _migrate_whatsapp_auth_dir() -> Path:
    """Move existing WhatsApp auth state into the 0xClaw namespace."""
    new_auth_dir = Path.home() / ".0xclaw" / "whatsapp-auth"
    old_auth_dir = Path.home() / ".nanobot" / "whatsapp-auth"

    if new_auth_dir.exists() or not old_auth_dir.exists():
        new_auth_dir.parent.mkdir(parents=True, exist_ok=True)
        return new_auth_dir

    new_auth_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(old_auth_dir, new_auth_dir)
    console.print(f"[yellow]Migrated WhatsApp login state to {new_auth_dir}[/yellow]")
    return new_auth_dir


def _get_whatsapp_bridge_dir() -> Path:
    """Prepare the WhatsApp bridge working directory if needed."""
    user_bridge = Path.home() / ".0xclaw" / "bridge"

    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 20.[/red]")
        raise SystemExit(1)

    source = _find_whatsapp_bridge_source()
    console.print("[bold #fbbf24]🦀  Setting up WhatsApp bridge...[/bold #fbbf24]")

    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))
    _rewrite_bridge_branding(user_bridge)

    npm_env = {**os.environ}
    npm_cache_dir = user_bridge / ".npm-cache"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    # Use a bridge-local npm cache to avoid failing on a broken global ~/.npm cache.
    npm_env["npm_config_cache"] = str(npm_cache_dir)

    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True, env=npm_env)
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True, env=npm_env)
        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Bridge setup failed: {exc}[/red]")
        if exc.stderr:
            console.print(f"[dim]{exc.stderr.decode()[:800]}[/dim]")
        raise SystemExit(1) from exc

    return user_bridge


def run_whatsapp_login() -> None:
    """Start the WhatsApp bridge and wait for QR login."""
    config = _load_config(validate_provider_key=False)
    bridge_dir = _get_whatsapp_bridge_dir()
    auth_dir = _migrate_whatsapp_auth_dir()

    console.print("[bold #fbbf24]🦀  Starting WhatsApp bridge...[/bold #fbbf24]")
    console.print("Scan the QR code in this terminal to link WhatsApp.\n")

    env = {**os.environ}
    env["npm_config_cache"] = str(bridge_dir / ".npm-cache")
    env["AUTH_DIR"] = str(auth_dir)
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Bridge failed: {exc}[/red]")
        raise SystemExit(1) from exc
    except FileNotFoundError as exc:
        console.print("[red]npm not found. Please install Node.js >= 20.[/red]")
        raise SystemExit(1) from exc


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
    for name in PHASES_LIST[idx:]:
        clear_marker(HACKATHON_DIR, name)
    state["current_phase"] = None
    state["last_error"] = None
    state["last_checkpoint"] = None
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
    from prompt_toolkit.application import get_app
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.styles import Style

    # ── slash command + shell completer ───────────────────────────────────────
    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.lstrip()

            # ? → help
            if text == "?":
                yield Completion("?", start_position=-1, display="?", display_meta="Show help")
                return

            # !cmd → shell suggestions
            if text.startswith("!"):
                partial = text[1:]
                for shell_cmd, desc in SHELL_SUGGESTIONS:
                    if shell_cmd.startswith(partial):
                        full = "!" + shell_cmd
                        yield Completion(
                            full,
                            start_position=-len(text),
                            display=full,
                            display_meta=desc,
                        )
                return

            # /cmd → slash commands
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

    # ── syntax highlighter: gold /cmd · green !shell · purple ? ───────────────
    class _SlashLexer(Lexer):
        def lex_document(self, document):
            def get_line(lineno):
                line = document.text
                if line.startswith("/"):
                    return [("class:slash", line)]
                if line.startswith("!"):
                    return [("class:shell", line)]
                if line == "?":
                    return [("class:help", line)]
                return [("", line)]
            return get_line

    # ── bottom toolbar — dynamically shows the current input mode ─────────────
    def _toolbar():
        try:
            text = get_app().current_buffer.text
        except Exception:
            text = ""
        if text.startswith("!"):
            import html as _h
            preview = _h.escape(text[1:45]) or "type a command…"
            return HTML(
                f'<b bg="#14532d" fg="#86efac"> $ SHELL </b>'
                f'  <ansi fg="ansibrightgreen">{preview}</ansi>'
                f'  <span fg="#4b5563">  Enter to run · Ctrl+C to cancel</span>'
            )
        if text == "?":
            return HTML(
                '<b bg="#1e1b4b" fg="#a78bfa"> ? HELP </b>'
                '  <span fg="#6b7280">Show all commands and shortcuts</span>'
            )
        if text.startswith("/"):
            return HTML(
                '<b bg="#1a0a2e" fg="#fbbf24"> / CMD </b>'
                '  <span fg="#6b7280">Agent command · Tab to autocomplete</span>'
            )
        return HTML(
            '<span fg="#374151">  ? help  ·  !cmd shell  ·  /command agent  ·  or just chat</span>'
        )

    prompt_style = Style.from_dict({
        # Input highlights
        "slash":  "#fbbf24 bold",   # /commands — gold
        "shell":  "#22c55e bold",   # !shell    — green
        "help":   "#a78bfa bold",   # ?         — purple
        # Completion dropdown — dark purple theme
        "completion-menu.completion":              "bg:#1a0a2e #a78bfa",
        "completion-menu.completion.current":      "bg:#7c3aed bold #fbbf24",
        "completion-menu.meta.completion":         "bg:#1a0a2e #6b7280",
        "completion-menu.meta.completion.current": "bg:#7c3aed #e5e7eb",
        "scrollbar.background":                    "bg:#1a0a2e",
        "scrollbar.button":                        "bg:#7c3aed",
        # Bottom toolbar
        "bottom-toolbar":                          "bg:#0f172a #4b5563",
    })

    active_phase: str | None = None
    active_trace_id: str | None = None
    bg_phase: str | None = None      # phase handed off to background monitor
    token_counter = TokenCounter()

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
        subagents_config=config.subagents,
    )
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
        bottom_toolbar=_toolbar,
        complete_while_typing=True,
        style=prompt_style,
        multiline=False,
    )

    _print_banner(config.agents.defaults.provider, config.agents.defaults.model)

    bus_task = asyncio.create_task(agent.run())
    turn_done = asyncio.Event()
    turn_done.set()
    turn_response: list[str] = []
    turn_saw_background_handoff = [False]

    # ── Ctrl+C handling — never exits, only interrupts the current task ────────
    _processing = [False]   # mutable so the signal handler closure can read it
    _loop = asyncio.get_event_loop()

    def _on_sigint(sig, frame):
        if _processing[0]:
            # If a phase is running in background, mark it so monitoring continues
            if active_phase:
                turn_saw_background_handoff[0] = True
            # A task is in flight — unblock _send_and_wait and let user continue
            _loop.call_soon_threadsafe(turn_done.set)
            console.print(
                "\n[yellow]⏹  Interrupted.[/yellow]"
                "  [dim]Type[/dim] [bold #fbbf24]/stop[/bold #fbbf24]"
                " [dim]to cancel the agent task, or[/dim]"
                " [bold #fbbf24]/exit[/bold #fbbf24] [dim]to quit.[/dim]"
            )
        else:
            console.print(
                "\n[dim]Use[/dim] [bold #fbbf24]/exit[/bold #fbbf24] [dim]to quit.[/dim]"
            )

    signal.signal(signal.SIGINT, _on_sigint)

    async def _consume():
        """Drain the outbound bus. Releases prompt as soon as agent replies."""
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    if _is_background_handoff_progress(msg.content or ""):
                        turn_saw_background_handoff[0] = True
                    console.print(f"  [dim]↳ {msg.content}[/dim]")
                elif not turn_done.is_set():
                    if _is_spawn_started_message(msg.content or ""):
                        turn_saw_background_handoff[0] = True
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
        nonlocal bg_phase
        while True:
            await asyncio.sleep(4)
            if not bg_phase:
                continue
            if _phase_is_complete(bg_phase):
                state_machine.checkpoint(bg_phase, "done")
                finished = bg_phase
                bg_phase = None
                console.print(
                    f"\n[bold green]✓[/bold green]  Phase [#7c3aed]{finished}[/#7c3aed] complete"
                    " — type [bold #fbbf24]/resume[/bold #fbbf24] to continue.\n"
                )

    consume_task = asyncio.create_task(_consume())
    monitor_task = asyncio.create_task(_monitor_background())

    async def _send_and_wait(
        text: str,
        *,
        timeout_s: int = DEFAULT_PHASE_TIMEOUT_S,
        phase: str | None = None,
    ) -> SendWaitResult:
        _processing[0] = True
        turn_done.clear()
        turn_response.clear()
        turn_saw_background_handoff[0] = False
        await bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="user", chat_id="direct", content=text, metadata={"phase": phase} if phase else {},
        ))
        try:
            with console.status("[dim]0xClaw is thinking…[/dim]", spinner="dots"):
                await asyncio.wait_for(turn_done.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            turn_done.set()
            console.print(f"[yellow]Timed out after {timeout_s}s.[/yellow]")
            return SendWaitResult("", timed_out=True, background_handoff=turn_saw_background_handoff[0])
        finally:
            _processing[0] = False
        return SendWaitResult(
            turn_response[0] if turn_response else "",
            background_handoff=turn_saw_background_handoff[0],
        )

    async def _send_and_wait_traced(
        text: str,
        *,
        timeout_s: int = DEFAULT_PHASE_TIMEOUT_S,
        command: str,
        phase: str | None,
        route_source: str | None = None,
    ) -> SendWaitResult:
        if command in {"/new", "/stop"}:
            return await _send_and_wait(text, timeout_s=timeout_s, phase=phase)

        # Only trace turns that actually produced a model response.
        response = await _send_and_wait(text, timeout_s=timeout_s, phase=phase)
        if not response.response:
            return response

        return response

    try:
        while True:
            try:
                user_input = await session.prompt_async(HTML("<b fg='#fbbf24'>❯</b> "))
            except KeyboardInterrupt:
                # Ctrl+C at idle prompt — never exit, just show hint
                console.print(
                    "[dim]Use[/dim] [bold #fbbf24]/exit[/bold #fbbf24] [dim]to quit.[/dim]"
                )
                continue
            except EOFError:
                # Ctrl+D — treat same as /exit
                console.print("[yellow]Goodbye! 🦀[/yellow]")
                break

            cmd = user_input.strip()
            if not cmd:
                continue

            # ── ? → help alias ─────────────────────────────────────────────────
            if cmd == "?":
                _show_help()
                continue

            # ── !cmd → shell passthrough ───────────────────────────────────────
            if cmd.startswith("!"):
                shell_cmd = cmd[1:].strip()
                if not shell_cmd:
                    console.print(
                        "[dim]Usage:[/dim] [bold #fbbf24]!<command>[/bold #fbbf24]"
                        "  [dim]e.g.[/dim] [dim]!ls  !git log  !pwd[/dim]"
                    )
                else:
                    result = subprocess.run(
                        shell_cmd, shell=True, capture_output=True, text=True, cwd=str(ROOT)
                    )
                    if result.stdout:
                        console.print(result.stdout.rstrip())
                    if result.stderr:
                        console.print(f"[red]{result.stderr.rstrip()}[/red]")
                    if result.returncode != 0 and not result.stdout and not result.stderr:
                        console.print(f"[dim]Exit code {result.returncode}[/dim]")
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
                    target_phase = active_phase or bg_phase
                    if not target_phase:
                        console.print("[yellow]No active task to stop.[/yellow]")
                        continue
                    response = await _send_and_wait_traced(
                        "/stop",
                        timeout_s=30,
                        command=cmd,
                        phase=target_phase,
                        route_source="slash",
                    )
                    if target_phase:
                        state_machine.checkpoint(target_phase, "cancelled", last_error="Cancelled by /stop")
                    active_phase = None
                    active_trace_id = None
                    bg_phase = None
                    if response.response:
                        console.print(f"[yellow]{response.response.strip()}[/yellow]")
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
                    redo_cmd = REDO_COMMANDS[target_phase]
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
                    _prepare_phase_run(redo_route.phase)
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
                    _, handed_off = _finalize_phase_run(
                        phase=redo_route.phase,
                        trace_id=active_trace_id,
                        result=response,
                        state_machine=state_machine,
                    )
                    bg_phase = active_phase if handed_off else None
                    active_phase = None
                    active_trace_id = None
                    if response.response:
                        console.print()
                        console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                        console.print(Markdown(response.response))
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
                    if response.response:
                        console.print(f"[green]✓[/green]  {response.response.strip()}")
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
                    if bg_phase and decision.phase == bg_phase:
                        console.print(
                            f"[dim]Phase [#7c3aed]{bg_phase}[/#7c3aed] is already running in the background.[/dim]"
                        )
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
                    _prepare_phase_run(route.phase)
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
                    _, handed_off = _finalize_phase_run(
                        phase=route.phase,
                        trace_id=active_trace_id,
                        result=response,
                        state_machine=state_machine,
                    )
                    bg_phase = active_phase if handed_off else None
                    active_phase = None
                    active_trace_id = None
                    if response.response:
                        console.print()
                        console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                        console.print(Markdown(response.response))
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

                _prepare_phase_run(route.phase)
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
                _, handed_off = _finalize_phase_run(
                    phase=route.phase,
                    trace_id=active_trace_id,
                    result=response,
                    state_machine=state_machine,
                )
                bg_phase = active_phase if handed_off else None
                active_phase = None
                active_trace_id = None
            else:
                response = await _send_and_wait_traced(
                    user_input,
                    command=cmd,
                    phase=None,
                    route_source="none",
                )

            if response.response:
                console.print()
                console.print("[bold #fbbf24]🦀  0xClaw[/bold #fbbf24]")
                console.print(Markdown(response.response))
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


async def run_gateway(config: Config, *, port: int | None = None, verbose: bool = False) -> None:
    """Start messaging channels using the repository-local config."""
    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    from runtime.agent.tools.message import MessageTool
    from runtime.bus.events import OutboundMessage
    from runtime.channels.manager import ChannelManager
    from runtime.heartbeat.service import HeartbeatService

    provider = _make_provider(config)
    bus = MessageBus()
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
        reasoning_effort=config.agents.defaults.reasoning_effort,
        brave_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        subagents_config=config.subagents,
    )
    async def on_cron_job(job) -> str | None:
        """Execute a scheduled job through the main agent loop."""
        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        response = await agent.process_direct(
            reminder_note,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response,
                )
            )
        return response

    cron.on_job = on_cron_job
    channels = ChannelManager(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick the best available external session for heartbeat delivery."""
        enabled = set(channels.enabled_channels)
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        return "cli", "direct"

    async def on_heartbeat_execute(tasks: str) -> str:
        """Run heartbeat work through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs) -> None:
            return None

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Send heartbeat output back to the active external channel."""
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=WORKSPACE,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    listen_port = port or config.gateway.port
    console.print(f"[bold #fbbf24]🦀  Starting 0xClaw gateway on port {listen_port}[/bold #fbbf24]")
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    try:
        await cron.start()
        await heartbeat.start()
        await asyncio.gather(
            agent.run(),
            channels.start_all(),
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down gateway...[/yellow]")
    finally:
        await agent.close_mcp()
        heartbeat.stop()
        cron.stop()
        agent.stop()
        await channels.stop_all()


# ── entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] in {"-h", "--help"}:
        _print_cli_usage()
        return

    wants_logs = "--logs" in argv or "--verbose" in argv

    # Suppress all loguru output unless logs were explicitly requested.
    if not wants_logs:
        logger.remove()

    load_dotenv(ROOT / ".env")
    from runtime.utils.helpers import sync_workspace_templates
    sync_workspace_templates(WORKSPACE)

    if argv and argv[0] == "gateway":
        try:
            port, verbose = _parse_gateway_args(argv[1:])
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            _print_cli_usage()
            raise SystemExit(2) from exc
        config = _load_config()
        asyncio.run(run_gateway(config, port=port, verbose=verbose))
        return

    if argv and argv[0] == "whatsapp":
        try:
            command = _parse_whatsapp_args(argv[1:])
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            _print_cli_usage()
            raise SystemExit(2) from exc
        if command == "login":
            run_whatsapp_login()
            return

    config = _load_config()
    asyncio.run(run_interactive(config))


if __name__ == "__main__":
    main()
