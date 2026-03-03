"""Pipeline runner for 0xClaw hackathon agent.

Runs a command in the 0xClaw agent and waits until an expected output file
is produced. Decision phases (idea selection, etc.) are handled interactively
— the user picks from numbered options in the terminal.

Usage:
    python scripts/run_phase.py "run hackathon research"
    python scripts/run_phase.py "generate ideas"
    python scripts/run_phase.py "select idea"          # interactive menu
    python scripts/run_phase.py "plan the architecture"
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "nanobot"))
sys.path.insert(0, str(ROOT / "0xclaw"))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.custom_provider import CustomProvider
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import sync_workspace_templates

from tools.virtuals_tool import VirtualsTool
from tools.unibase_tool import UnibaseTool

CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"
WORKSPACE = ROOT / "workspace"
HACKATHON_DIR = WORKSPACE / "hackathon"

# Map command keywords to the output file we wait for
OUTPUT_FILE_MAP = {
    "research": HACKATHON_DIR / "context.json",
    "idea":     HACKATHON_DIR / "ideas.json",
    "plan":     HACKATHON_DIR / "plan.md",
    "coder":    None,   # poll project/ dir instead
    "test":     HACKATHON_DIR / "test_results.json",
    "doc":      HACKATHON_DIR / "submission" / "README.md",
}

# Keywords that trigger interactive (human-in-the-loop) phases instead of agent runs
INTERACTIVE_KEYWORDS = {"select", "pick", "choose"}

CONTINUATION_PROMPT = (
    "Please proceed with ONLY the current phase. Do not ask clarifying questions. "
    "Complete only the task that was requested — do not start any other phases. "
    "Write the output file now."
)

MAX_TURNS = 20

# ─────────────────────────────────────────────────────────────
# Interactive selection handlers
# ─────────────────────────────────────────────────────────────

def _fmt_wrap(text: str, width: int = 56, indent: str = "      ") -> str:
    """Wrap long text for terminal display."""
    return textwrap.fill(text, width=width, subsequent_indent=indent)


def _select_idea_interactive() -> bool:
    """Present ideas.json as a numbered menu and write selected_idea.json."""
    ideas_file = HACKATHON_DIR / "ideas.json"
    if not ideas_file.exists():
        print("[!] ideas.json not found. Run 'generate ideas' first.")
        return False

    raw = json.loads(ideas_file.read_text())
    # Support both list schema and {"ideas": [...]} schema
    idea_list: list = raw if isinstance(raw, list) else raw.get("ideas", [])

    if not idea_list:
        print("[!] ideas.json is empty.")
        return False

    # ── Display ──────────────────────────────────────────────
    print()
    print("╔" + "═" * 58 + "╗")
    print("║  🎯  SELECT YOUR PROJECT IDEA" + " " * 28 + "║")
    print("╠" + "═" * 58 + "╣")

    for i, idea in enumerate(idea_list, 1):
        title    = idea.get("name") or idea.get("title", f"Idea {i}")
        tagline  = idea.get("tagline") or idea.get("description", "")
        problem  = idea.get("problem", "")
        scores   = idea.get("scores", {})
        composite = scores.get("composite")
        sponsors = idea.get("sponsors") or list(
            (idea.get("sponsor_integrations") or {}).keys()
        )

        print(f"║                                                          ║")
        score_str = f"  [score: {composite:.2f}]" if composite else ""
        header = f"  [{i}] {title}{score_str}"
        print(f"║  {header:<56}║")

        if tagline:
            wrapped = _fmt_wrap(tagline, width=54, indent="       ")
            for line in wrapped.splitlines():
                print(f"║      {line:<52}║")

        if problem and problem != tagline:
            wrapped = _fmt_wrap(f"Problem: {problem}", width=54, indent="               ")
            for line in wrapped.splitlines():
                print(f"║      {line:<52}║")

        if sponsors:
            sp_str = ", ".join(str(s) for s in sponsors[:4])
            print(f"║      Sponsors: {sp_str:<42}║")

    print(f"║                                                          ║")
    print(f"║  [0] Enter a custom idea instead                         ║")
    print("╚" + "═" * 58 + "╝")

    # ── Get choice ───────────────────────────────────────────
    selected: dict | None = None
    while selected is None:
        try:
            raw_input = input("\n  Your choice → ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [cancelled]")
            return False

        if not raw_input:
            continue

        try:
            num = int(raw_input)
        except ValueError:
            print(f"  Please enter a number (0–{len(idea_list)}).")
            continue

        if num == 0:
            # Custom idea path
            print()
            try:
                name    = input("  Project name        : ").strip()
                tagline = input("  One-line tagline    : ").strip()
                problem = input("  Problem it solves   : ").strip()
                stack   = input("  Tech stack (brief)  : ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  [cancelled]")
                return False

            selected = {
                "id": "custom",
                "name": name,
                "tagline": tagline,
                "problem": problem,
                "tech_stack": {"summary": stack},
                "sponsor_integrations": {
                    "flock": "primary LLM inference",
                    "virtuals": "on-chain agent identity",
                    "unibase": "persistent memory",
                },
                "source": "human_provided",
                "selected_at": datetime.now(timezone.utc).isoformat(),
            }

        elif 1 <= num <= len(idea_list):
            idea = idea_list[num - 1]
            selected = {**idea, "selected_by": "human",
                        "selected_at": datetime.now(timezone.utc).isoformat()}
        else:
            print(f"  Please enter a number between 0 and {len(idea_list)}.")
            continue

    # ── Write output ─────────────────────────────────────────
    out_file = HACKATHON_DIR / "selected_idea.json"
    out_file.write_text(json.dumps(selected, indent=2, ensure_ascii=False))

    name = selected.get("name") or selected.get("title", "?")
    print()
    print("╔" + "═" * 58 + "╗")
    print(f"║  ✓  Selected: {name:<43}║")
    print(f"║     Written → hackathon/selected_idea.json               ║")
    print(f"║     Next    → python scripts/run_phase.py 'plan arch'    ║")
    print("╚" + "═" * 58 + "╝")
    print()
    return True


# Map interactive keywords to their handler
INTERACTIVE_HANDLERS = {
    "select": _select_idea_interactive,
    "pick":   _select_idea_interactive,
    "choose": _select_idea_interactive,
}


def _detect_interactive(command: str):
    """Return interactive handler if command matches, else None."""
    cmd_lower = command.lower()
    for keyword, handler in INTERACTIVE_HANDLERS.items():
        if keyword in cmd_lower:
            return handler
    return None


# ─────────────────────────────────────────────────────────────
# Agent runner (LLM phases)
# ─────────────────────────────────────────────────────────────

def _load_config() -> Config:
    raw = CONFIG_PATH.read_text()

    def _sub(m: re.Match) -> str:
        return os.environ.get(m.group(1), "")

    raw = re.sub(r"\$\{([^}]+)\}", _sub, raw)
    data = json.loads(raw)
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


def _detect_output_file(command: str) -> Path | None:
    cmd_lower = command.lower()
    for keyword, path in OUTPUT_FILE_MAP.items():
        if keyword in cmd_lower:
            return path
    return None


def _output_exists(path: Path | None) -> bool:
    if path is None:
        return False
    return path.exists() and path.stat().st_size > 10


async def run(command: str, timeout_per_turn: int = 240, max_turns: int = MAX_TURNS) -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    config = _load_config()
    sync_workspace_templates(WORKSPACE)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(WORKSPACE)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=WORKSPACE,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        exec_config=config.tools.exec,
        session_manager=session_manager,
    )
    agent.tools.register(VirtualsTool())
    agent.tools.register(UnibaseTool())

    output_file = _detect_output_file(command)

    print(f"\n{'='*60}")
    print(f"Command  : {command}")
    print(f"Provider : {config.agents.defaults.provider} | {config.agents.defaults.model}")
    print(f"Watching : {output_file or 'n/a'}")
    print(f"{'='*60}\n")

    bus_task = asyncio.create_task(agent.run())

    async def next_response(timeout: int) -> str | None:
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    print(f"  ... {msg.content}")
                elif msg.content:
                    return msg.content
            except asyncio.TimeoutError:
                timeout -= 1
                if timeout <= 0:
                    return None
            except asyncio.CancelledError:
                return None

    async def send(text: str) -> None:
        await bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="user", chat_id="direct", content=text,
        ))

    success = False
    nudge_count = 0
    try:
        await send(command)

        for turn in range(1, max_turns + 1):
            print(f"[turn {turn}/{max_turns}] waiting for agent response...")
            response = await next_response(timeout=timeout_per_turn)

            if response is None:
                print(f"[timeout] No response in {timeout_per_turn}s")
                break

            print(f"\n{'─'*60}")
            print(f"[agent turn {turn}]\n{response}")
            print(f"{'─'*60}\n")

            await asyncio.sleep(1)
            if _output_exists(output_file):
                print(f"[✓] Output file created: {output_file}")
                success = True
                break

            nudge_triggers = ["would you like", "shall i", "do you want", "should i",
                              "clarif", "which option", "please confirm"]
            if nudge_count < 1 and any(t in response.lower() for t in nudge_triggers):
                print("[nudge] Agent asked a question — sending continuation prompt")
                await send(CONTINUATION_PROMPT)
                nudge_count += 1

    finally:
        agent.stop()
        await asyncio.gather(bus_task, return_exceptions=True)
        await agent.close_mcp()

    print(f"\n{'='*60}")
    if success and output_file:
        size = output_file.stat().st_size
        print(f"[✓] SUCCESS — {output_file.name} ({size} bytes)")
        if output_file.suffix == ".json":
            try:
                data = json.loads(output_file.read_text())
                if isinstance(data, dict):
                    print(f"[preview] keys: {list(data.keys())}")
            except Exception:
                pass
    elif output_file and not _output_exists(output_file):
        print(f"[✗] INCOMPLETE — {output_file} not created after {max_turns} turns")
    else:
        print("[done] Run complete.")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_phase.py '<command>'")
        print()
        print("LLM phases:")
        print("  python scripts/run_phase.py 'run hackathon research'")
        print("  python scripts/run_phase.py 'generate ideas'")
        print("  python scripts/run_phase.py 'plan architecture'")
        print("  python scripts/run_phase.py 'start coding'")
        print("  python scripts/run_phase.py 'run tests'")
        print("  python scripts/run_phase.py 'prepare docs'")
        print()
        print("Interactive phases (human picks from menu):")
        print("  python scripts/run_phase.py 'select idea'")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    command = " ".join(sys.argv[1:])

    # Check for interactive phases first — no LLM needed
    handler = _detect_interactive(command)
    if handler is not None:
        ok = handler()
        sys.exit(0 if ok else 1)

    asyncio.run(run(command))
