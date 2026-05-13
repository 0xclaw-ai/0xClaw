"""0xClaw — Autonomous Hackathon Agent."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from rich import box as rich_box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, ConsoleOptions, Group
from rich.markdown import Markdown
from rich.markup import escape as rich_escape_markup
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.styled import Styled
from rich.table import Table
from rich.text import Text

# ── Live / in-progress UI palette (cool slate + indigo) — distinct from final reply (gold + default) ─
_LIVE_SPINNER = "bold #818cf8"
_LIVE_BRAND_MUTED = "#7c86a2"
_LIVE_VERB = "italic #64748b"
_LIVE_RULE = "dim #4338ca"
_LIVE_STREAM_MD = "italic #9ca3af not bold"
_LIVE_LBL = "dim #64748b"
_LIVE_SEP = "dim #4f46e5"
_LIVE_TIME = "bold #a5b4fc"
_LIVE_STREAM_TOK = "italic #c4b5fd"
_LIVE_SIGMA_LBL = "dim #818cf8"
_LIVE_SIGMA_NUM = "bold #c7d2fe"
_LIVE_INOUT = "#a5b4fc"
_LIVE_ACT_TOOL = "italic #a5b4fc"
_LIVE_ACT_PROG = "italic dim #9fb0c0"
_LIVE_ACT_BG = "italic #c4b5fd"

# ── internal deps ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))  # makes `from runtime.xxx` work when run directly

from cli_args import parse_gateway_args, parse_whatsapp_args
from orchestration.cli_session_picker import (
    cli_talk_key,
    fresh_cli_run_session_key,
    merge_cli_session_rows,
    resolve_session_pick,
)
from orchestration.contracts import Envelope
from orchestration.doc_explorer import expand_doc_urls
from orchestration.model_profiles import ModelProfile, ModelProfileResolver
from orchestration.phase_completion import (
    clear_marker,
    detect_failure_reason,
    marker_path,
    write_marker,
)
from orchestration.phase_completion import (
    output_exists as phase_output_exists,
)
from orchestration.router import SkillRouter, keyword_matches
from orchestration.session_control import SessionControl
from orchestration.state import (
    COMPLETED_PHASE_STATUSES,
    PHASE_COMPLETION_ARTIFACTS,
    OrchestratorStateMachine,
    PipelineStateStore,
    reconcile_pipeline_state,
)
from orchestration.write_guard import build_phase_write_guard, install_phase_write_guards
from runtime.agent.loop import AgentLoop
from runtime.bus.events import InboundMessage
from runtime.bus.queue import MessageBus
from runtime.config.schema import Config
from runtime.cron.service import CronService
from runtime.providers.custom_provider import CustomProvider
from runtime.providers.litellm_provider import LiteLLMProvider
from runtime.session.manager import SessionManager

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
    "/resume":        "Pick CLI conversation (cancel/q at Row# prompt), then resume pipeline",
    "/sessions":      "List CLI conversations (newest activity first)",
    "/session rename": "Set display name: /session rename <#|current|key> <title>",
    "/session delete": "Remove a CLI thread: /session delete <#|current|key>",
    "/session <name>": "Switch CLI conversation context (slug or cli:name)",
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

# Rich markup: printed under the CLI conversations table (see _print_cli_conversations_table).
_CLI_SESSION_TABLE_HELP_MARKUP = (
    "[bold dim]Sessions[/bold dim]\n"
    "  [bold]*[/bold] active row · [bold]#[/bold] row index · new chats use [bold]cli:run-…[/bold] until "
    "[bold]/sessions[/bold] or [bold]/session[/bold].\n"
    "\n"
    "[bold dim]Commands[/bold dim]\n"
    "  [bold]/sessions[/bold] N  [dim]attach row N[/dim]   ·   [bold]/resume[/bold] N  [dim]attach + continue pipeline[/dim]\n"
    "  [bold]/session rename[/bold] TARGET TITLE   ·   [bold]/session delete[/bold] TARGET  "
    "[dim](jsonl under workspace/sessions/)[/dim]\n"
    "  [dim]TARGET:[/dim] row number · [bold]current[/bold] · [bold].[/bold] · [bold]*[/bold] · full [bold]cli:…[/bold] key\n"
    "\n"
    "[bold dim]While[/bold dim] [bold]/resume[/bold] [bold dim]is asking for a row[/bold dim][dim]:[/dim]  "
    "[dim]same[/dim] [bold]/session …[/bold][dim];[/dim] [bold]cancel[/bold] [dim]·[/dim] [bold]q[/bold] [dim]·[/dim] [bold]Ctrl+C[/bold] "
    "[dim]to abort without running.[/dim]"
)


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

    def fmt_rich_live(
        self,
        *,
        stream_chars: int = 0,
        turn_start_mono: list[float | None] | None = None,
    ) -> Text:
        """Status strip: elapsed clock, stream estimate, session token totals."""
        t = Text()
        elapsed: float | None = None
        if turn_start_mono and turn_start_mono[0] is not None:
            elapsed = max(0.0, time.monotonic() - turn_start_mono[0])

        def _sep() -> None:
            t.append(" ", style="")
            t.append("·", style=_LIVE_SEP)
            t.append(" ", style="")

        first = True

        if elapsed is not None:
            t.append("⏱", style=_LIVE_LBL)
            t.append(" ", style="")
            t.append(_format_elapsed(elapsed), style=_LIVE_TIME)
            first = False

        if stream_chars > 0:
            approx = max(1, stream_chars // 4)
            if not first:
                _sep()
            t.append("out", style=_LIVE_LBL)
            t.append(" ~", style=_LIVE_LBL)
            t.append(self._k(approx), style=_LIVE_STREAM_TOK)
            t.append(" tok", style=_LIVE_LBL)
            first = False

        if self.total_tokens > 0:
            if not first:
                _sep()
            t.append("Σ", style=_LIVE_SIGMA_LBL)
            t.append(" ", style="")
            t.append(self._k(self.total_tokens), style=_LIVE_SIGMA_NUM)
            t.append(" ", style=_LIVE_SEP)
            t.append("(", style=_LIVE_SEP)
            t.append("↑", style=_LIVE_LBL)
            t.append(self._k(self.prompt_tokens), style=_LIVE_INOUT)
            t.append(" ", style=_LIVE_SEP)
            t.append("↓", style=_LIVE_LBL)
            t.append(self._k(self.completion_tokens), style=_LIVE_INOUT)
            t.append(")", style=_LIVE_SEP)
        return t


def _format_elapsed(seconds: float) -> str:
    """Human-readable duration for the live status strip."""
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    h = int(seconds // 3600)
    rem = int(seconds % 3600)
    m = rem // 60
    s = rem % 60
    return f"{h}h {m:02d}m {s:02d}s"


def _oxclaw_header_text() -> Text:
    """Branded header: crab + hair space + wordmark (tighter than two ASCII spaces)."""
    line = Text()
    line.append("🦀", style="bold #fbbf24")
    line.append("\u200a", style="bold #fbbf24")  # hair space
    line.append("0xClaw", style="bold #fbbf24")
    return line


class _OxClawWaitLine:
    """One-line waiting UI: Braille spinner (circular) + static crab + brand + verb."""

    __slots__ = ("_verbs", "_idx", "_counter", "_stream_buf", "_turn_start_mono")

    _braille = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(
        self,
        verbs: tuple[str, ...],
        idx_cell: list[int],
        counter: TokenCounter,
        stream_buf: list[str],
        turn_start_mono: list[float | None],
    ) -> None:
        self._verbs = verbs
        self._idx = idx_cell
        self._counter = counter
        self._stream_buf = stream_buf
        self._turn_start_mono = turn_start_mono

    def __rich_console__(self, console: Console, options: ConsoleOptions):
        tick = int(console.get_time() / 0.07) % len(self._braille)
        spin = self._braille[tick]
        verb = self._verbs[self._idx[0] % len(self._verbs)]
        left = Text()
        left.append(spin, style=_LIVE_SPINNER)
        left.append(" ", style="dim")
        left.append("🦀", style=_LIVE_BRAND_MUTED)
        left.append("\u200a", style=_LIVE_BRAND_MUTED)
        left.append("0xClaw", style=f"bold {_LIVE_BRAND_MUTED}")
        left.append(" · ", style="dim #475569")
        left.append(f"{verb}…", style=_LIVE_VERB)
        stream_chars = sum(len(x) for x in self._stream_buf)
        right = self._counter.fmt_rich_live(
            stream_chars=stream_chars,
            turn_start_mono=self._turn_start_mono,
        )
        if right.plain == "":
            yield left
        else:
            yield Columns([left, Align.right(right, vertical="middle")], expand=True)


# ── banner ─────────────────────────────────────────────────────────────────────
def _print_banner(provider: str, model: str) -> None:
    """Render the startup banner using Rich Panel (border always aligned)."""
    logo = Text("\n".join(LOGO_LINES), style="bold #fbbf24")

    meta = Text()
    meta.append("\n\n  Autonomous Hackathon Agent", style="white")
    meta.append("  ·  ", style="dim")
    meta.append("v0.1.1", style="dim white")
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
    _provider_display = {
        "flock": "FLock.io", "zhipu": "Z.ai", "openrouter": "OpenRouter",
        "anthropic": "Anthropic", "openai": "OpenAI", "deepseek": "DeepSeek",
        "gemini": "Gemini", "groq": "Groq",
    }
    display_provider = _provider_display.get(provider, provider.title())
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
    t.add_row("/resume 2", "Skip picker: attach to row #2 then resume pipeline")
    t.add_row("", "")
    t.add_row("?",       "Alias for /help")
    t.add_row("!<cmd>",  "Run a shell command  (e.g. !ls  !git log  !pwd)")
    t.add_row("Esc",     "During a run: shows a hint (Esc does not stop the model; use ⌃C / Ctrl+C)")
    t.add_row("⌃C / Ctrl+C", "During a run: interrupt the wait; then /stop to cancel the agent")
    console.print(
        Panel(t, title="[#fbbf24]Commands[/#fbbf24]", border_style="#7c3aed", padding=(0, 1))
    )


def _format_session_ts(iso: str | None) -> str:
    if not iso:
        return "—"
    s = str(iso).replace("T", " ")
    for sep in ("+", "Z"):
        if sep in s:
            s = s.split(sep, 1)[0]
    return s[:19] if len(s) >= 19 else s


def _truncate_display(s: str, max_len: int = 40) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t or "—"
    return t[: max_len - 1] + "…"


def _print_cli_conversations_table(rows: list[dict[str, Any]], active_key: str, *, title: str) -> None:
    t = Table(box=rich_box.SIMPLE, show_header=True, padding=(0, 1))
    t.add_column("#", style="dim", width=4, justify="right")
    t.add_column("name", style="white")
    t.add_column("key", style="#7c3aed")
    t.add_column("last activity", style="dim", width=20, no_wrap=True)
    for i, row in enumerate(rows, 1):
        key = str(row["key"])
        raw_name = str(row.get("display_name") or "").strip()
        name_cell = _truncate_display(raw_name if raw_name else "—")
        key_cell = f"* {key}" if key == active_key else key
        ts = row.get("updated_at") or row.get("created_at") or row.get("sort_ts")
        t.add_row(
            str(i),
            name_cell,
            key_cell,
            _format_session_ts(ts if isinstance(ts, str) else None),
        )
    console.print(
        Panel(
            t,
            title=f"[#fbbf24]{title}[/#fbbf24]",
            border_style="#7c3aed",
            padding=(0, 1),
        )
    )
    console.print(
        Panel(
            Text.from_markup(_CLI_SESSION_TABLE_HELP_MARKUP),
            title="[#fbbf24]Session reference[/#fbbf24]",
            border_style="#7c3aed",
            box=rich_box.ROUNDED,
            padding=(0, 1),
        )
    )


def _show_pipeline_status(state_store: PipelineStateStore) -> None:
    status_style = {
        "done":      ("[green]✓[/green]",        "done",      "green"),
        "complete":  ("[green]✓[/green]",        "done",      "green"),
        "running":   ("[#7c3aed]●[/#7c3aed]", "running",   "#7c3aed"),
        "failed":    ("[red]✗[/red]",          "failed",    "red"),
        "cancelled": ("[yellow]–[/yellow]",    "cancelled", "yellow"),
        "pending":   ("[dim]○[/dim]",          "pending",   "dim"),
    }
    try:
        state = reconcile_pipeline_state(state_store, persist=False)
    except (FileNotFoundError, json.JSONDecodeError):
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
        icon, label, _ = status_style.get(status, status_style["pending"])
        t.add_row(str(i), phase, icon, f"[{_}]{label}[/{_}]")

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
    if keyword_matches("plan", t) or keyword_matches("规划", t):
        return "planning"
    if keyword_matches("test", t) or keyword_matches("测试", t):
        return "testing"
    if keyword_matches("doc", t) or keyword_matches("文档", t):
        return "doc"
    if keyword_matches("code", t) or keyword_matches("实现", t):
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
    return _is_spawn_started_message(t)


_DOCS_PARAM_RE = re.compile(r"\bdocs=(\S+)")


def _parse_docs_param(user_input: str) -> list[str]:
    """Extract `docs=<u1>,<u2>` from a research command. Returns [] if absent."""
    m = _DOCS_PARAM_RE.search(user_input)
    if not m:
        return []
    return [u.strip() for u in m.group(1).split(",") if u.strip()]


async def _build_research_payload(user_input: str, phase: str) -> dict:
    """Build the envelope payload for a research-phase command.

    For `research <hackathon> docs=<u1>,<u2>` we pre-expand each doc root
    via sitemap.xml (with link-harvest fallback) so the spawned agent
    receives a concrete list of URLs to firecrawl_scrape rather than being
    asked to run a multi-step shell pipeline itself.
    """
    payload: dict = {"user_command": user_input, "phase": phase}
    if phase != "research":
        return payload
    doc_roots = _parse_docs_param(user_input)
    if not doc_roots:
        return payload
    # Run blocking HTTP fetches off the event loop to avoid freezing the REPL.
    expansion = await asyncio.to_thread(expand_doc_urls, doc_roots)
    flat: list[str] = []
    for urls in expansion.values():
        flat.extend(urls)
    deduped = list(dict.fromkeys(flat))
    payload["doc_roots"] = doc_roots
    payload["scrape_urls"] = deduped
    payload["doc_expansion"] = expansion  # per-root breakdown for audit
    return payload


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
    interrupted: bool = False


def _turn_request_id(sequence: int) -> str:
    return f"cli-turn-{sequence}"


def _matches_active_request(request_id: str | None, active_request_id: str | None) -> bool:
    """Return True when an outbound message belongs to the currently awaited turn."""
    return active_request_id is not None and request_id == active_request_id


def _classify_outbound_request(
    request_id: str | None,
    active_request_id: str | None,
    background_request_id: str | None,
    *,
    is_notification: bool = False,
) -> str | None:
    """Classify an outbound message as active-turn, background, notification, or unscoped."""
    if _matches_active_request(request_id, active_request_id):
        return "active"
    if background_request_id is not None and request_id == background_request_id:
        return "background"
    if is_notification:
        return "notification"
    if active_request_id is None and background_request_id is None and request_id is None:
        return "unscoped"
    return None


def _background_request_id_for_turn(
    request_id: str | None,
    *,
    background_handoff: bool,
) -> str | None:
    """Keep request routing alive for a handed-off background turn."""
    return request_id if background_handoff else None


def _interpret_stop_response(response_text: str) -> tuple[bool, bool]:
    """Return (confirmed, stopped_work) for a /stop reply."""
    normalized = response_text.strip()
    stopped_work = (
        "Stopped " in response_text
        and " task(s)." in response_text
        and "Stopped 0 task(s)." not in response_text
    )
    confirmed = stopped_work or normalized in {
        "⏹ Stopped 0 task(s).",
        "Stopped 0 task(s).",
        "No active task to stop.",
    }
    return confirmed, stopped_work


def _apply_phase_profile(agent: Any, profile: ModelProfile | None) -> dict[str, Any]:
    """Temporarily override agent model params from a phase profile.

    Returns a snapshot of the original values so callers can restore them
    after the phase completes.  Pass ``None`` profile to skip (returns
    current values unchanged).
    """
    snapshot = {
        "model": agent.model,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
    }
    if profile is not None:
        agent.model = profile.model
        agent.temperature = profile.temperature
        agent.max_tokens = profile.max_tokens
        agent.subagents.model = profile.model
        agent.subagents.temperature = profile.temperature
        agent.subagents.max_tokens = profile.max_tokens
    return snapshot


def _restore_agent_params(agent: Any, snapshot: dict[str, Any]) -> None:
    """Restore agent params from a snapshot taken by ``_apply_phase_profile``."""
    agent.model = snapshot["model"]
    agent.temperature = snapshot["temperature"]
    agent.max_tokens = snapshot["max_tokens"]
    agent.subagents.model = snapshot["model"]
    agent.subagents.temperature = snapshot["temperature"]
    agent.subagents.max_tokens = snapshot["max_tokens"]


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

    if result.interrupted:
        if primary_output_ready:
            _mark_phase_complete(phase, trace_id)
        if state_machine.phase_is_complete(phase):
            state_machine.checkpoint(phase, "done")
            return None, False
        state_machine.checkpoint(
            phase,
            "cancelled",
            last_error="Interrupted (Ctrl+C); use /stop to halt the agent.",
        )
        return None, False

    if primary_output_ready:
        _mark_phase_complete(phase, trace_id)

    if state_machine.phase_is_complete(phase):
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
    from runtime.providers.base import LLMProvider

    inner = _make_provider(config)

    class _Wrapper(LLMProvider):
        def __init__(self):
            super().__init__(getattr(inner, "api_key", None), getattr(inner, "api_base", None))

        async def chat(self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7, reasoning_effort=None):
            resp = await inner.chat(messages, tools=tools, model=model, max_tokens=max_tokens, temperature=temperature, reasoning_effort=reasoning_effort)
            if resp.usage:
                counter.add(resp.usage)
            return resp

        async def chat_stream(
            self,
            messages,
            tools=None,
            model=None,
            max_tokens=4096,
            temperature=0.7,
            reasoning_effort=None,
        ):
            async for delta_text, resp in inner.chat_stream(
                messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            ):
                if resp is not None and resp.usage:
                    counter.add(resp.usage)
                yield delta_text, resp

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
    """Reset phase and all downstream phases to pending. Returns list of affected phase names.

    Deletes artifact files for each reset phase so that reconcile_pipeline_state cannot
    re-mark phases as done from stale outputs on the next /status or phase-entry call.
    """
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
        for rel in PHASE_COMPLETION_ARTIFACTS.get(name, ()):
            p = HACKATHON_DIR / rel
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink(missing_ok=True)
    # Compute the last completed checkpoint after deletion so /resume picks the right phase.
    last_checkpoint = PHASES_LIST[idx - 1] if idx > 0 else None
    state["current_phase"] = None
    state["last_error"] = None
    state["last_checkpoint"] = last_checkpoint
    state["active_task"] = None
    state_store.save(state)
    return reset


def _reset_hackathon_outputs() -> list[str]:
    HACKATHON_DIR.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []
    for rel in HACKATHON_RUNTIME_PATHS:
        p = HACKATHON_DIR / rel
        if p.is_dir():
            shutil.rmtree(p)
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
            shutil.rmtree(p)
            removed.append(f"workspace/{rel}/")
        elif p.exists():
            p.unlink()
            removed.append(f"workspace/{rel}")
    from runtime.agent.memory import MemoryStore as _MemoryStore

    _MemoryStore(WORKSPACE).reset()
    return removed


# ── main interactive loop ──────────────────────────────────────────────────────
async def run_interactive(config: Config) -> None:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import get_app
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.styles import Style

    active_phase: str | None = None
    active_trace_id: str | None = None
    bg_phase: str | None = None
    bg_start_mono: list[float | None] = [None]
    bg_status_line: list[str | None] = [None]
    token_counter = TokenCounter()
    _processing = [False]

    def _set_bg_phase(phase: str | None) -> None:
        nonlocal bg_phase
        bg_phase = phase
        bg_start_mono[0] = time.monotonic() if phase else None
        if phase is None:
            bg_status_line[0] = None

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

    # ── agent setup ────────────────────────────────────────────────────────────
    bus = MessageBus()
    provider = _make_tracking_provider(config, token_counter)
    session_manager = SessionManager(WORKSPACE)
    active_cli_session_key: list[str] = [fresh_cli_run_session_key()]
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

    prompt_style = Style.from_dict({
        "slash":  "#fbbf24 bold",
        "shell":  "#22c55e bold",
        "help":   "#a78bfa bold",
        "completion-menu.completion":              "bg:#1a0a2e #a78bfa",
        "completion-menu.completion.current":      "bg:#7c3aed bold #fbbf24",
        "completion-menu.meta.completion":         "bg:#1a0a2e #6b7280",
        "completion-menu.meta.completion.current": "bg:#7c3aed #e5e7eb",
        "scrollbar.background":                    "bg:#1a0a2e",
        "scrollbar.button":                        "bg:#7c3aed",
        "bottom-toolbar":                          "bg:#0f172a #4b5563",
    })

    def _toolbar() -> HTML:
        import html as _h

        try:
            text = get_app().current_buffer.text
        except Exception:
            text = ""

        def _bg_rail() -> str:
            if not bg_phase:
                return (
                    '<span fg="#6b7280">Esc</span><span fg="#475569"> → </span>'
                    '<span fg="#9ca3af">not cancel</span>'
                    '<span fg="#475569"> · </span>'
                    '<span fg="#6b7280">⌃C</span>'
                    '<span fg="#475569"> / </span>'
                    '<span fg="#9ca3af">Ctrl+C</span>'
                    '<span fg="#475569"> mid-run</span>'
                )
            t0 = bg_start_mono[0]
            elapsed = _format_elapsed(time.monotonic() - t0) if t0 is not None else "—"
            phase_h = _h.escape(bg_phase)
            tok = token_counter.fmt()
            tok_seg = f'<span fg="#a5b4fc"> {_h.escape(tok)}</span>' if tok else ""
            hint = bg_status_line[0]
            hint_seg = ""
            if hint:
                one = hint.replace("\n", " ").strip()
                short = one[:72] + ("…" if len(one) > 72 else "")
                hint_seg = f'<span fg="#64748b"> · </span><span fg="#94a3b8">{_h.escape(short)}</span>'
            core = (
                f'<b bg="#312e81" fg="#e0e7ff"> bg:{phase_h} </b>'
                f'<span fg="#94a3b8"> ⏱ {_h.escape(elapsed)}</span>{tok_seg}{hint_seg}'
            )
            tail = (
                '<span fg="#475569">  ·  </span>'
                '<span fg="#6b7280">Esc</span><span fg="#475569"> → </span>'
                '<span fg="#9ca3af">not cancel</span>'
                '<span fg="#475569"> · </span>'
                '<span fg="#6b7280">⌃C</span>'
                '<span fg="#475569"> / </span>'
                '<span fg="#9ca3af">Ctrl+C</span>'
            )
            return core + tail

        rail = _bg_rail()
        if text.startswith("!"):
            preview = _h.escape(text[1:45]) or "type a command…"
            return HTML(
                f'<b bg="#14532d" fg="#86efac"> $ SHELL </b>'
                f'  <ansi fg="ansibrightgreen">{preview}</ansi>'
                f'  <span fg="#4b5563">  Enter to run · ⌃C / Ctrl+C to cancel</span>'
                f'  <span fg="#475569"> · </span>{rail}'
            )
        if text == "?":
            return HTML(
                '<b bg="#1e1b4b" fg="#a78bfa"> ? HELP </b>'
                '  <span fg="#6b7280">Show all commands and shortcuts</span>'
                f'  <span fg="#475569"> · </span>{rail}'
            )
        if text.startswith("/"):
            return HTML(
                '<b bg="#1a0a2e" fg="#fbbf24"> / CMD </b>'
                '  <span fg="#6b7280">Agent command · Tab to autocomplete</span>'
                f'  <span fg="#475569"> · </span>{rail}'
            )
        return HTML(
            '<span fg="#374151">  ? help  ·  !cmd shell  ·  /command or chat</span>'
            f'  <span fg="#475569">·</span> {rail}'
        )

    esc_kb = KeyBindings()
    _esc_hint_last = [0.0]

    @esc_kb.add(Keys.Escape, eager=True)
    def _esc_notice(_event) -> None:
        if not _processing[0]:
            return
        now = time.monotonic()
        if now - _esc_hint_last[0] < 2.0:
            return
        _esc_hint_last[0] = now
        console.print(
            "\n[dim]Esc does not stop the model or end the wait. "
            "Press [bold]Ctrl+C[/bold] ([bold]⌃C[/bold] on Mac — the [bold]⌃[/bold] Control key, "
            "not [bold]⌘[/bold] Command). Then [bold]/stop[/bold] to cancel work or [bold]/exit[/bold] to quit.[/dim]"
        )

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
        key_bindings=esc_kb,
    )

    async def _prompt_cli_session_pick(rows: list[dict[str, Any]]) -> tuple[str | None, bool]:
        """Return (session_key, cancelled). cancelled=True means user aborted (no error)."""
        _pick_cancel = frozenset(
            {"q", "quit", "cancel", "abort", "n", "no", "back", "exit", "esc"}
        )
        while True:
            try:
                raw = (
                    await session.prompt_async(
                        HTML(
                            "<span fg='#94a3b8'>Row #</span> "
                            "<span fg='#64748b'>(1 · cancel · </span>"
                            "<b>/session</b> <span fg='#64748b'>delete|rename …)</span> "
                            "<b fg='#fbbf24'>›</b> "
                        )
                    )
                ).strip()
            except KeyboardInterrupt:
                return None, True
            if raw.lower() in _pick_cancel:
                return None, True
            if not raw:
                return resolve_session_pick("1", rows), False

            if raw.startswith("/"):
                rlow = raw.lower()
                if rlow.startswith("/session"):
                    se_tail = raw[8:].strip()
                    st_low = se_tail.lower()
                    if st_low.startswith("delete"):
                        target_blob = se_tail[6:].strip()
                        if not target_blob:
                            console.print(
                                "[yellow]Usage:[/yellow] [bold]/session delete[/bold] "
                                "[dim]<row# | current | cli:…>[/dim]"
                            )
                            continue
                        rows_now = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        tlow = target_blob.lower()
                        if tlow in ("current", ".", "*"):
                            dkey = active_cli_session_key[0]
                        elif target_blob.isdigit():
                            pick = resolve_session_pick(target_blob, rows_now)
                            if pick is None:
                                console.print("[red]Invalid row number.[/red]")
                                continue
                            dkey = pick
                        else:
                            pick = resolve_session_pick(target_blob, rows_now)
                            dkey = pick if pick is not None else cli_talk_key(target_blob)
                        removed_file = session_manager.delete_session(dkey)
                        if active_cli_session_key[0] == dkey:
                            active_cli_session_key[0] = fresh_cli_run_session_key()
                            console.print(
                                "[dim]Active thread was deleted — new CLI thread[/dim] "
                                f"[bold #7c3aed]{rich_escape_markup(active_cli_session_key[0])}[/bold #7c3aed]"
                            )
                        detail = (
                            "session file removed."
                            if removed_file
                            else "no saved file for that key (cache cleared if it was loaded)."
                        )
                        console.print(
                            f"[green]✓[/green]  Deleted [bold #7c3aed]{rich_escape_markup(dkey)}[/bold #7c3aed] — {detail}"
                        )
                        rows[:] = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        _print_cli_conversations_table(
                            rows, active_cli_session_key[0], title="CLI conversations (updated)"
                        )
                        console.print("[dim]Pick a row # below (or cancel).[/dim]")
                        continue
                    if st_low.startswith("rename"):
                        rbody = se_tail[6:].strip()
                        pair = rbody.split(maxsplit=1)
                        if len(pair) < 2:
                            console.print(
                                "[yellow]Usage:[/yellow] [bold]/session rename[/bold] "
                                "[dim]<row# | current | cli:…> <new title>[/dim]\n"
                                "  [dim]Example:[/dim] [bold #fbbf24]/session rename 2 My hackathon notes[/bold #fbbf24]"
                            )
                            continue
                        target_tok, new_title = pair[0], pair[1]
                        rows_now = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        tlow_r = target_tok.lower()
                        if tlow_r in ("current", ".", "*"):
                            dkey_r = active_cli_session_key[0]
                        elif target_tok.isdigit():
                            pick_r = resolve_session_pick(target_tok, rows_now)
                            if pick_r is None:
                                console.print("[red]Invalid row number.[/red]")
                                continue
                            dkey_r = pick_r
                        else:
                            pick_r = resolve_session_pick(target_tok, rows_now)
                            dkey_r = pick_r if pick_r is not None else cli_talk_key(target_tok)
                        session_manager.set_session_display_name(dkey_r, new_title)
                        session_manager.invalidate(dkey_r)
                        console.print(
                            f"[dim]Renamed[/dim] [bold #7c3aed]{rich_escape_markup(dkey_r)}[/bold #7c3aed]"
                            f" [dim]→[/dim] [bold]{rich_escape_markup(new_title.strip()[:200])}[/bold]"
                        )
                        rows[:] = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        _print_cli_conversations_table(
                            rows, active_cli_session_key[0], title="CLI conversations (updated)"
                        )
                        console.print("[dim]Pick a row # below (or cancel).[/dim]")
                        continue
                console.print(
                    "[yellow]This prompt only accepts a row number or a full cli:… key.[/yellow]\n"
                    "[dim]Here you can use[/dim] [bold]/session delete …[/bold] [dim]or[/dim] [bold]/session rename …[/bold][dim]; "
                    "other slash commands: main[/dim] [bold]❯[/bold] [dim]prompt.[/dim]"
                )
                continue

            key = resolve_session_pick(raw, rows)
            if key is None:
                console.print(
                    "[red]Invalid pick:[/red] use a row number 1…n, a full key (e.g. cli:direct), "
                    "or [bold]/session delete[/bold] / [bold]/session rename[/bold][dim].[/dim]"
                )
                continue
            return key, False

    async def _pick_cli_session_for_resume(resume_arg: str) -> bool:
        rows = merge_cli_session_rows(
            session_manager.list_sessions(), active_key=active_cli_session_key[0]
        )
        arg = resume_arg.strip()
        if arg:
            key = resolve_session_pick(arg, rows)
            if key is None:
                console.print(
                    "[red]Invalid pick: use a row number 1…n from the table, or a full key (e.g. cli:direct).[/red]"
                )
                return False
        else:
            console.print(
                "[dim]CLI conversations (most recently touched first). "
                "Hackathon pipeline artifacts stay shared under[/dim] [bold]workspace/hackathon/[/bold][dim].[/dim]"
            )
            console.print(
                "[dim]Row 1 is usually this run’s [bold]new thread[/bold] until you pick an older key; "
                "plain chat uses that new thread automatically (Claude Code–style).[/dim]"
            )
            _print_cli_conversations_table(
                rows, active_cli_session_key[0], title="CLI conversations"
            )
            key, cancelled = await _prompt_cli_session_pick(rows)
            if cancelled:
                console.print(
                    "[dim]Cancelled — conversation unchanged; pipeline resume not started.[/dim]\n"
                )
                return False
            if key is None:
                console.print("[red]Invalid row number.[/red]")
                return False
        active_cli_session_key[0] = key
        session_manager.invalidate(key)
        console.print(f"[dim]Conversation context →[/dim] [bold #7c3aed]{key}[/bold #7c3aed]\n")
        return True

    _print_banner(config.agents.defaults.provider, config.agents.defaults.model)

    from rich.live import Live

    bus_task = asyncio.create_task(agent.run())
    turn_done = asyncio.Event()
    turn_done.set()
    turn_interrupted = [False]
    turn_response: list[str] = []
    turn_saw_background_handoff = [False]
    turn_was_streamed = [False]  # whether any streaming token arrived this turn
    turn_streamed_text: list[str] = []  # accumulated streaming text for result
    turn_activity: list[dict[str, Any]] = []  # tools / MCP / progress lines for Live strip
    turn_live: list[Live | None] = [None]  # reference to active Live context
    turn_start_mono: list[float | None] = [None]  # monotonic start of current _send_and_wait turn
    last_turn_elapsed_s = [0.0]  # wall duration of last completed turn (for footer)

    def _print_turn_footer() -> None:
        """Dim line: turn duration (if known) and cumulative session tokens."""
        bits: list[str] = []
        if last_turn_elapsed_s[0] > 0:
            bits.append(f"⏱ {_format_elapsed(last_turn_elapsed_s[0])}")
            last_turn_elapsed_s[0] = 0.0
        tok = token_counter.fmt()
        if tok:
            bits.append(tok)
        if bits:
            console.print(f"  [dim]{'  ·  '.join(bits)}[/dim]")

    request_counter = count(1)
    active_request_id: str | None = None
    background_request_id: str | None = None
    background_deadline: float | None = None

    # ── Live status: Braille spinner + crab + verbs + token hint (Claude Code–ish) ─
    _spinner_verbs = (
        "Accomplishing", "Architecting", "Baking", "Bootstrapping", "Brewing",
        "Calculating", "Cerebrating", "Cogitating", "Combobulating", "Computing",
        "Concocting", "Contemplating", "Cooking", "Crafting", "Crunching",
        "Deciphering", "Deliberating", "Elucidating", "Envisioning", "Forging",
        "Generating", "Gitifying", "Hatching", "Ideating", "Imagining",
        "Incubating", "Inferring", "Marinating", "Mulling", "Musing",
        "Orchestrating", "Percolating", "Philosophising", "Pondering", "Processing",
        "Ruminating", "Simmering", "Synthesizing", "Tinkering", "Thinking",
        "Wrangling",
    )
    _spinner_idx = [0]

    def _advance_spinner():
        _spinner_idx[0] += 1

    _activity_cap = 14

    def _append_turn_activity(metadata: dict[str, Any], content: str | None) -> None:
        raw = (content or "").strip().replace("\n", " ")
        if not raw:
            return
        if len(raw) > 140:
            raw = raw[:137] + "…"
        turn_activity.append(
            {
                "tool_hint": bool(metadata.get("_tool_hint")),
                "background": bool(metadata.get("_background_handoff")),
                "text": raw,
            }
        )
        while len(turn_activity) > _activity_cap:
            turn_activity.pop(0)

    def _live_activity_block() -> Any | None:
        if not turn_activity:
            return None
        rows: list[Text] = []
        for item in turn_activity:
            line = Text()
            if item.get("background"):
                line.append("⎆ ", style=_LIVE_SEP)
                line.append(item["text"], style=_LIVE_ACT_BG)
            elif item.get("tool_hint"):
                line.append("⚙ ", style=_LIVE_SIGMA_LBL)
                line.append(item["text"], style=_LIVE_ACT_TOOL)
            else:
                line.append("↳ ", style=_LIVE_LBL)
                line.append(item["text"], style=_LIVE_ACT_PROG)
            rows.append(line)
        return Group(*rows)

    def _build_live_renderable() -> Any:
        if turn_streamed_text:
            body = "".join(turn_streamed_text)
            nchars = len(body)
            foot = token_counter.fmt_rich_live(
                stream_chars=nchars,
                turn_start_mono=turn_start_mono,
            )
            body_r = Styled(Markdown(body), style=_LIVE_STREAM_MD)
            act = _live_activity_block()
            parts: list[Any] = []
            if act is not None:
                parts.append(Padding(act, (0, 0, 1, 0)))
            parts.append(body_r)
            if foot.plain != "":
                parts.append(Rule(characters="·", style=_LIVE_RULE))
                parts.append(Align.right(foot))
            if len(parts) == 1:
                return parts[0]
            return Group(*parts)
        wait = _OxClawWaitLine(
            _spinner_verbs, _spinner_idx, token_counter, turn_streamed_text, turn_start_mono
        )
        act = _live_activity_block()
        if act is None:
            return wait
        return Group(Padding(act, (0, 0, 1, 0)), wait)

    # ── Ctrl+C handling — never exits, only interrupts the current task ────────
    _loop = asyncio.get_running_loop()

    def _signal_interrupt():
        turn_interrupted[0] = True
        turn_done.set()

    def _on_sigint(sig, frame):
        if _processing[0]:
            # A task is in flight — unblock _send_and_wait and let user continue.
            # Do NOT set turn_saw_background_handoff here: Ctrl-C should not silently
            # promote the running phase to a background handoff. Use /stop to cancel.
            _loop.call_soon_threadsafe(_signal_interrupt)
            console.print(
                "\n[yellow]⏹  Interrupted[/yellow]"
                "  [dim]([/dim][bold #fbbf24]Ctrl+C[/bold #fbbf24][dim] / Mac [/dim]"
                "[bold #fbbf24]⌃C[/bold #fbbf24][dim] — not [/dim][bold #fbbf24]Esc[/bold #fbbf24]"
                "[dim], which does not stop the run).[/dim]\n"
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
        nonlocal active_request_id, background_request_id, background_deadline
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                metadata = msg.metadata or {}
                request_id = metadata.get("request_id")
                scope = _classify_outbound_request(
                    request_id,
                    active_request_id,
                    background_request_id,
                    is_notification=bool(metadata.get("_notification")),
                )
                if scope is None:
                    if metadata.get("_streaming"):
                        turn_was_streamed[0] = True
                        turn_streamed_text.append(msg.content or "")
                    preview = (msg.content or "").strip().replace("\n", " ")
                    if len(preview) > 120:
                        preview = preview[:117] + "..."
                    logger.warning(
                        "Dropping outbound message with unmatched request scope "
                        "request_id={} active_request_id={} background_request_id={} "
                        "notification={} progress={} preview={}",
                        request_id,
                        active_request_id,
                        background_request_id,
                        bool(metadata.get("_notification")),
                        bool(metadata.get("_progress")),
                        preview,
                    )
                    continue
                if scope in {"background", "notification"}:
                    if metadata.get("_progress") and msg.content:
                        if scope == "background":
                            bg_status_line[0] = (msg.content or "").strip().replace("\n", " ")[:200]
                            try:
                                get_app().invalidate()
                            except Exception:
                                pass
                        else:
                            console.print(f"  [dim]↳ {msg.content}[/dim]")
                    elif msg.content:
                        subagent_phase = metadata.get("_phase")
                        subagent_status = metadata.get("_subagent_status")
                        if scope == "background" and subagent_phase == bg_phase and subagent_status == "ok":
                            state_machine.checkpoint(subagent_phase, "done")
                            _set_bg_phase(None)
                            background_request_id = None
                            background_deadline = None
                        elif scope == "background" and subagent_phase == bg_phase and subagent_status == "error":
                            state_machine.checkpoint(
                                subagent_phase,
                                "failed",
                                last_error=metadata.get("_subagent_error") or "Background task reported failure",
                            )
                            _set_bg_phase(None)
                            background_request_id = None
                            background_deadline = None
                        console.print()
                        console.print(_oxclaw_header_text())
                        console.print(Markdown(msg.content))
                        console.print()
                        if scope == "background" and not bg_phase:
                            background_request_id = None
                    continue

                # ── Active-scope messages: ONLY update Live, NEVER print directly ──
                if metadata.get("_progress"):
                    if metadata.get("_background_handoff") or _is_background_handoff_progress(msg.content or ""):
                        turn_saw_background_handoff[0] = True
                    if metadata.get("_streaming"):
                        turn_was_streamed[0] = True
                        turn_streamed_text.append(msg.content)
                    else:
                        _append_turn_activity(metadata, msg.content or "")
                    if turn_live[0] is not None:
                        turn_live[0].update(_build_live_renderable())
                elif not turn_done.is_set():
                    if _is_spawn_started_message(msg.content or ""):
                        turn_saw_background_handoff[0] = True
                    elif msg.content:
                        if turn_was_streamed[0]:
                            turn_response.append("".join(turn_streamed_text))
                        else:
                            turn_response.append(msg.content)
                        turn_done.set()
                    elif active_phase is None:
                        turn_done.set()
                # Late messages after turn_done — silently ignore to prevent duplicates
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _monitor_background() -> None:
        """Poll for background phase output every 4 s; notify user on completion."""
        nonlocal background_request_id, background_deadline
        while True:
            await asyncio.sleep(4)
            if not bg_phase:
                continue
            if state_machine.phase_is_complete(bg_phase):
                state_machine.checkpoint(bg_phase, "done")
                finished = bg_phase
                _set_bg_phase(None)
                background_request_id = None
                background_deadline = None
                console.print(
                    f"\n[bold green]✓[/bold green]  Phase [#7c3aed]{finished}[/#7c3aed] complete"
                    " — type [bold #fbbf24]/resume[/bold #fbbf24] to continue.\n"
                )
                continue
            if background_deadline is not None and time.time() > background_deadline:
                state_machine.checkpoint(
                    bg_phase,
                    "failed",
                    last_error="Timed out waiting for background phase completion",
                )
                failed_phase = bg_phase
                _set_bg_phase(None)
                background_request_id = None
                background_deadline = None
                console.print(
                    f"\n[red]Phase [#7c3aed]{failed_phase}[/#7c3aed] timed out while running in the background.[/red]\n"
                )

    consume_task = asyncio.create_task(_consume())
    monitor_task = asyncio.create_task(_monitor_background())

    async def _toolbar_refresh_loop() -> None:
        while True:
            await asyncio.sleep(0.35)
            if bg_phase:
                try:
                    get_app().invalidate()
                except Exception:
                    pass

    toolbar_refresh_task = asyncio.create_task(_toolbar_refresh_loop())

    async def _send_and_wait(
        text: str,
        *,
        timeout_s: int = DEFAULT_PHASE_TIMEOUT_S,
        phase: str | None = None,
    ) -> SendWaitResult:
        nonlocal active_request_id, background_request_id
        _processing[0] = True
        turn_interrupted[0] = False
        turn_done.clear()
        turn_response.clear()
        turn_saw_background_handoff[0] = False
        turn_was_streamed[0] = False
        turn_streamed_text.clear()
        turn_activity.clear()
        turn_start_mono[0] = time.monotonic()
        active_request_id = _turn_request_id(next(request_counter))
        await bus.publish_inbound(InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=text,
            session_key_override=active_cli_session_key[0],
            metadata={
                **({"phase": phase} if phase else {}),
                "request_id": active_request_id,
            },
        ))

        # Refresh Live on a timer so elapsed clock and Braille stay smooth between bus events.
        async def _live_refresh_loop():
            verb_accum = 0.0
            while not turn_done.is_set():
                await asyncio.sleep(0.25)
                live = turn_live[0]
                if live is not None:
                    live.update(_build_live_renderable())
                verb_accum += 0.25
                if verb_accum >= 2.0 and not turn_was_streamed[0]:
                    verb_accum = 0.0
                    _advance_spinner()

        spin_task = asyncio.create_task(_live_refresh_loop())

        try:
            with Live(
                _build_live_renderable(),
                console=console,
                vertical_overflow="visible",
                refresh_per_second=16,
                transient=True,
            ) as live:
                turn_live[0] = live
                try:
                    await asyncio.wait_for(turn_done.wait(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    turn_done.set()
                    background_request_id = _background_request_id_for_turn(
                        active_request_id,
                        background_handoff=turn_saw_background_handoff[0],
                    )
                    active_request_id = None
                    console.print(f"[yellow]Timed out after {timeout_s}s waiting for agent confirmation.[/yellow]")
                    return SendWaitResult("", timed_out=True, background_handoff=turn_saw_background_handoff[0])
        finally:
            turn_live[0] = None
            spin_task.cancel()
            _processing[0] = False
            if turn_start_mono[0] is not None:
                last_turn_elapsed_s[0] = max(0.0, time.monotonic() - turn_start_mono[0])
            turn_start_mono[0] = None

        # Live was transient — nothing left on screen. Callers render the assistant
        # reply (header + Markdown + token footer) once after return.

        result = SendWaitResult(
            turn_response[0] if turn_response else "",
            background_handoff=turn_saw_background_handoff[0],
            interrupted=turn_interrupted[0],
        )
        background_request_id = _background_request_id_for_turn(
            active_request_id,
            background_handoff=result.background_handoff,
        )
        active_request_id = None
        return result

    async def _confirm_stop_running_phase() -> bool:
        nonlocal active_phase, active_trace_id, background_request_id, background_deadline
        target_phase = active_phase or bg_phase
        if not target_phase:
            return True
        response = await _send_and_wait(
            "/stop",
            timeout_s=30,
            phase=target_phase,
        )
        if response.timed_out:
            console.print(
                f"[red]Could not confirm stop for phase [#7c3aed]{target_phase}[/#7c3aed]. "
                "It may still be running.[/red]"
            )
            return False
        confirmed, stopped_work = _interpret_stop_response(response.response)
        if not confirmed and state_machine.phase_is_complete(target_phase):
            state_machine.checkpoint(target_phase, "done")
            active_phase = None
            active_trace_id = None
            _set_bg_phase(None)
            background_request_id = None
            background_deadline = None
            console.print(
                f"[dim]Phase [#7c3aed]{target_phase}[/#7c3aed] had already completed; continuing.[/dim]"
            )
            return True
        if not confirmed:
            console.print(
                f"[red]Stop was not confirmed for phase [#7c3aed]{target_phase}[/#7c3aed]. "
                "Refusing to reset while local state still shows active work.[/red]"
            )
            return False
        if state_machine.phase_is_complete(target_phase):
            state_machine.checkpoint(target_phase, "done")
        else:
            reason = "Cancelled by /stop" if stopped_work else "Cancelled by /stop; no active agent task found"
            state_machine.checkpoint(target_phase, "cancelled", last_error=reason)
        active_phase = None
        active_trace_id = None
        _set_bg_phase(None)
        background_request_id = None
        background_deadline = None
        if response.response:
            console.print(f"[yellow]{response.response.strip()}[/yellow]")
        else:
            console.print("[yellow]⏹  Stop confirmed.[/yellow]")
        return True

    try:
        while True:
            try:
                user_input = await session.prompt_async(HTML("<b fg='#fbbf24'>❯</b> "))
            except KeyboardInterrupt:
                # Ctrl+C at idle prompt — never exit, just show hint
                console.print(
                    "[dim]Use[/dim] [bold #fbbf24]/exit[/bold #fbbf24] [dim]to quit."
                    "  During a run use[/dim] [bold #fbbf24]⌃C[/bold #fbbf24][dim]/[/dim][bold #fbbf24]Ctrl+C[/bold #fbbf24]"
                    " [dim]then[/dim] [bold #fbbf24]/stop[/bold #fbbf24][dim].[/dim]"
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
                    try:
                        result = subprocess.run(
                            shell_cmd, shell=True, capture_output=True, text=True,
                            cwd=str(ROOT), timeout=60,
                        )
                        if result.stdout:
                            console.print(result.stdout.rstrip())
                        if result.stderr:
                            console.print(f"[red]{result.stderr.rstrip()}[/red]")
                        if result.returncode != 0 and not result.stdout and not result.stderr:
                            console.print(f"[dim]Exit code {result.returncode}[/dim]")
                    except subprocess.TimeoutExpired:
                        console.print("[red]Command timed out after 60 seconds.[/red]")
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
                    console.print(
                        f"  [dim]Active CLI conversation[/dim] [bold #7c3aed]{active_cli_session_key[0]}[/bold #7c3aed]"
                    )
                    tok = token_counter.fmt()
                    if tok:
                        console.print(f"  [dim]Tokens this session  {tok}[/dim]\n")
                    else:
                        console.print()
                    continue

                if lower == "/stop":
                    if not (active_phase or bg_phase):
                        console.print("[yellow]No active task to stop.[/yellow]")
                        continue
                    await _confirm_stop_running_phase()
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
                    if active_phase or bg_phase:
                        console.print("[dim]Stopping current work before redo…[/dim]")
                        if not await _confirm_stop_running_phase():
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
                    param_snapshot = _apply_phase_profile(agent, redo_profile)
                    active_phase = redo_route.phase
                    active_trace_id = f"cli-{int(time.time())}-{redo_route.phase}"
                    state_machine.checkpoint(redo_route.phase, "running", active_task=active_trace_id)
                    redo_envelope = Envelope.from_command(
                        session_id=active_cli_session_key[0],
                        phase=redo_route.phase,
                        agent_id="orchestrator",
                        trace_id=active_trace_id,
                        payload=await _build_research_payload(redo_cmd, redo_route.phase),
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
                    response = await _send_and_wait(
                        redo_message,
                        timeout_s=redo_timeout,
                        phase=redo_route.phase,
                    )
                    _, handed_off = _finalize_phase_run(
                        phase=redo_route.phase,
                        trace_id=active_trace_id,
                        result=response,
                        state_machine=state_machine,
                    )
                    _restore_agent_params(agent, param_snapshot)
                    _set_bg_phase(active_phase if handed_off else None)
                    background_deadline = time.time() + redo_timeout if handed_off else None
                    active_phase = None
                    active_trace_id = None
                    if response.response:
                        console.print()
                        console.print(_oxclaw_header_text())
                        console.print(Markdown(response.response))
                        _print_turn_footer()
                        console.print()
                    continue

                if lower == "/new":
                    if active_phase or bg_phase:
                        console.print("[dim]Stopping current work before reset…[/dim]")
                        if not await _confirm_stop_running_phase():
                            console.print("[red]/new aborted because the running phase could not be stopped safely.[/red]")
                            continue
                    console.print("[dim]Resetting session…[/dim]")
                    response = await _send_and_wait(
                        "/new",
                        timeout_s=30,
                        phase=active_phase,
                    )
                    if response.timed_out or response.response.strip() != "New session started.":
                        detail = response.response.strip()
                        if detail:
                            console.print(f"[red]/new aborted because reset was not confirmed: {detail}[/red]")
                        else:
                            console.print("[red]/new aborted because reset was not confirmed.[/red]")
                        continue
                    removed = _reset_hackathon_outputs() + _reset_workspace_runtime_outputs()
                    active_phase = None
                    active_trace_id = None
                    _set_bg_phase(None)
                    background_request_id = None
                    background_deadline = None
                    active_cli_session_key[0] = fresh_cli_run_session_key()
                    console.print(f"[green]✓[/green]  {response.response.strip()}")
                    console.print(
                        f"[dim]New CLI conversation thread[/dim] [bold #7c3aed]{active_cli_session_key[0]}[/bold #7c3aed]"
                    )
                    if removed:
                        console.print(f"[dim]Cleared hackathon outputs:[/dim] {len(removed)} item(s)")
                    console.print()
                    continue

                if lower == "/sessions":
                    parts_ls = cmd.split(maxsplit=1)
                    arg_ls = parts_ls[1].strip() if len(parts_ls) > 1 else ""
                    rows_ls = merge_cli_session_rows(
                        session_manager.list_sessions(), active_key=active_cli_session_key[0]
                    )
                    if arg_ls:
                        key_ls = resolve_session_pick(arg_ls, rows_ls)
                        if key_ls is None:
                            console.print("[red]Invalid row number.[/red]")
                            continue
                        active_cli_session_key[0] = key_ls
                        session_manager.invalidate(key_ls)
                        console.print(
                            f"[dim]Active conversation[/dim] [bold #7c3aed]{key_ls}[/bold #7c3aed]\n"
                        )
                    else:
                        _print_cli_conversations_table(
                            rows_ls, active_cli_session_key[0], title="CLI conversations"
                        )
                    continue

                if lower == "/session":
                    raw_cmd = cmd.strip()
                    rest_se = raw_cmd[8:].strip() if raw_cmd.lower().startswith("/session") else ""
                    rows_se = merge_cli_session_rows(
                        session_manager.list_sessions(), active_key=active_cli_session_key[0]
                    )
                    if rest_se.lower().startswith("rename"):
                        rbody = rest_se[6:].strip()
                        pair = rbody.split(maxsplit=1)
                        if len(pair) < 2:
                            console.print(
                                "[dim]Usage:[/dim] /session rename <row# | current | cli:…> <new title>\n"
                                "  [dim]Examples:[/dim]  [bold #fbbf24]/session rename 2 UKFinnovator notes[/bold #fbbf24]\n"
                                "            [bold #fbbf24]/session rename current Post-mortem[/bold #fbbf24]"
                            )
                            continue
                        target_tok, new_title = pair[0], pair[1]
                        tlow = target_tok.lower()
                        if tlow in ("current", ".", "*"):
                            dkey = active_cli_session_key[0]
                        elif target_tok.isdigit():
                            pick = resolve_session_pick(target_tok, rows_se)
                            if pick is None:
                                console.print("[red]Invalid row number.[/red]")
                                continue
                            dkey = pick
                        else:
                            pick = resolve_session_pick(target_tok, rows_se)
                            dkey = pick if pick is not None else cli_talk_key(target_tok)
                        session_manager.set_session_display_name(dkey, new_title)
                        session_manager.invalidate(dkey)
                        console.print(
                            f"[dim]Renamed[/dim] [bold #7c3aed]{rich_escape_markup(dkey)}[/bold #7c3aed]"
                            f" [dim]→[/dim] [bold]{rich_escape_markup(new_title.strip()[:200])}[/bold]"
                        )
                        rows_fresh = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        _print_cli_conversations_table(
                            rows_fresh, active_cli_session_key[0], title="CLI conversations (updated)"
                        )
                        console.print()
                        continue
                    del_parts = rest_se.split(None, 1)
                    if del_parts and del_parts[0].lower() == "delete":
                        dbody = del_parts[1].strip() if len(del_parts) > 1 else ""
                        if not dbody:
                            console.print(
                                "[dim]Usage:[/dim] /session delete <row# | current | cli:…>\n"
                                "  [dim]Removes that conversation’s JSONL under[/dim] [bold]workspace/sessions/[/bold]"
                                " [dim](does not clear hackathon pipeline outputs).[/dim]\n"
                                "  [dim]Examples:[/dim]  [bold #fbbf24]/session delete 2[/bold #fbbf24]\n"
                                "            [bold #fbbf24]/session delete current[/bold #fbbf24]"
                            )
                            continue
                        target_del = dbody.split(maxsplit=1)[0]
                        tlow_del = target_del.lower()
                        if tlow_del in ("current", ".", "*"):
                            dkey_del = active_cli_session_key[0]
                        elif target_del.isdigit():
                            pick_del = resolve_session_pick(target_del, rows_se)
                            if pick_del is None:
                                console.print("[red]Invalid row number.[/red]")
                                continue
                            dkey_del = pick_del
                        else:
                            pick_del = resolve_session_pick(target_del, rows_se)
                            dkey_del = pick_del if pick_del is not None else cli_talk_key(target_del)
                        removed_file = session_manager.delete_session(dkey_del)
                        if active_cli_session_key[0] == dkey_del:
                            active_cli_session_key[0] = fresh_cli_run_session_key()
                            console.print(
                                "[dim]Active thread was deleted — new CLI thread[/dim] "
                                f"[bold #7c3aed]{rich_escape_markup(active_cli_session_key[0])}[/bold #7c3aed]"
                            )
                        detail = (
                            "session file removed."
                            if removed_file
                            else "no saved file for that key (cache cleared if it was loaded)."
                        )
                        console.print(
                            f"[green]✓[/green]  Deleted [bold #7c3aed]{rich_escape_markup(dkey_del)}[/bold #7c3aed] — {detail}"
                        )
                        rows_fresh_del = merge_cli_session_rows(
                            session_manager.list_sessions(), active_key=active_cli_session_key[0]
                        )
                        _print_cli_conversations_table(
                            rows_fresh_del,
                            active_cli_session_key[0],
                            title="CLI conversations (updated)",
                        )
                        console.print()
                        continue
                    slug_se = rest_se
                    if not slug_se:
                        _print_cli_conversations_table(
                            rows_se, active_cli_session_key[0], title="CLI conversations"
                        )
                        key_se, cancelled = await _prompt_cli_session_pick(rows_se)
                        if cancelled:
                            console.print(
                                "[dim]Cancelled — active conversation unchanged.[/dim]\n"
                            )
                            continue
                        if key_se is None:
                            console.print("[red]Invalid row number.[/red]")
                            continue
                    else:
                        key_se = cli_talk_key(slug_se)
                        # Seed a default display name from the user's slug (not the normalized key).
                        sess0 = session_manager.get_or_create(key_se)
                        if slug_se and not str(sess0.metadata.get("display_name") or "").strip():
                            session_manager.set_session_display_name(key_se, slug_se.strip()[:200])
                    active_cli_session_key[0] = key_se
                    session_manager.invalidate(key_se)
                    console.print(f"[dim]Conversation context →[/dim] [bold #7c3aed]{key_se}[/bold #7c3aed]\n")
                    continue

                if lower == "/resume":
                    parts_re = cmd.split(maxsplit=1)
                    resume_arg = parts_re[1].strip() if len(parts_re) > 1 else ""
                    decision = session_control.get_resume_decision()
                    if not decision.command:
                        if resume_arg:
                            rows = merge_cli_session_rows(
                                session_manager.list_sessions(),
                                active_key=active_cli_session_key[0],
                            )
                            key = resolve_session_pick(resume_arg, rows)
                            if key is None:
                                console.print("[red]Invalid row number or session key.[/red]")
                            else:
                                active_cli_session_key[0] = key
                                session_manager.invalidate(key)
                                console.print(
                                    f"[dim]{decision.reason}[/dim]  "
                                    f"[dim]Switched conversation context →[/dim] [bold #7c3aed]{key}[/bold #7c3aed]\n"
                                )
                        else:
                            console.print(f"[green]✓[/green] {decision.reason}")
                        continue
                    if bg_phase and decision.phase == bg_phase:
                        console.print(
                            f"[dim]Phase [#7c3aed]{bg_phase}[/#7c3aed] is already running in the background.[/dim]"
                        )
                        continue
                    if not await _pick_cli_session_for_resume(resume_arg):
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
                    param_snapshot = _apply_phase_profile(agent, profile)
                    active_phase = route.phase
                    active_trace_id = f"cli-{int(time.time())}-{route.phase}"
                    state_machine.checkpoint(route.phase, "running", active_task=active_trace_id)
                    envelope = Envelope.from_command(
                        session_id=active_cli_session_key[0],
                        phase=route.phase,
                        agent_id="orchestrator",
                        trace_id=active_trace_id,
                        payload=await _build_research_payload(cmd, route.phase),
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
                    response = await _send_and_wait(
                        message,
                        timeout_s=timeout_s,
                        phase=route.phase,
                    )
                    _, handed_off = _finalize_phase_run(
                        phase=route.phase,
                        trace_id=active_trace_id,
                        result=response,
                        state_machine=state_machine,
                    )
                    _restore_agent_params(agent, param_snapshot)
                    _set_bg_phase(active_phase if handed_off else None)
                    background_deadline = time.time() + timeout_s if handed_off else None
                    active_phase = None
                    active_trace_id = None
                    if response.response:
                        console.print()
                        console.print(_oxclaw_header_text())
                        console.print(Markdown(response.response))
                        _print_turn_footer()
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
                console.print(
                    f"[dim]Phase[/dim] {route.phase} [dim]via {route.source} "
                    f"(confidence {route.confidence:.2f})[/dim]"
                )
                if profile:
                    console.print(
                        f"[dim]Profile[/dim] {profile.provider}/{profile.model} "
                        f"[dim](timeout {profile.timeout_s}s)[/dim]"
                    )
                else:
                    console.print(
                        f"[dim]Profile[/dim] default [dim](timeout {DEFAULT_PHASE_TIMEOUT_S}s)[/dim]"
                    )

                _prepare_phase_run(route.phase)
                param_snapshot = _apply_phase_profile(agent, profile)
                active_phase = route.phase
                active_trace_id = f"cli-{int(time.time())}-{route.phase}"
                state_machine.checkpoint(route.phase, "running", active_task=active_trace_id)

                envelope = Envelope.from_command(
                    session_id=active_cli_session_key[0],
                    phase=route.phase,
                    agent_id="orchestrator",
                    trace_id=active_trace_id,
                    payload=await _build_research_payload(user_input, route.phase),
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
                response = await _send_and_wait(
                    routed_input,
                    timeout_s=timeout_s,
                    phase=route.phase,
                )
                _, handed_off = _finalize_phase_run(
                    phase=route.phase,
                    trace_id=active_trace_id,
                    result=response,
                    state_machine=state_machine,
                )
                _restore_agent_params(agent, param_snapshot)
                _set_bg_phase(active_phase if handed_off else None)
                background_deadline = time.time() + timeout_s if handed_off else None
                active_phase = None
                active_trace_id = None
            else:
                response = await _send_and_wait(user_input)

            if response.response:
                console.print()
                console.print(_oxclaw_header_text())
                console.print(Markdown(response.response))
                _print_turn_footer()
                console.print()

    finally:
        agent.stop()
        consume_task.cancel()
        monitor_task.cancel()
        toolbar_refresh_task.cancel()
        await asyncio.gather(
            bus_task,
            consume_task,
            monitor_task,
            toolbar_refresh_task,
            return_exceptions=True,
        )
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
            metadata={"_notification": True},
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
                    metadata={"_notification": True},
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
            metadata={"_notification": True},
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Send heartbeat output back to the active external channel."""
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            console.print("[yellow]Warning: heartbeat notification has no external channel target; dropping response.[/yellow]")
            return
        await bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=response,
                metadata={"_notification": True},
            )
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
