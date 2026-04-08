"""Pipeline runner for 0xClaw hackathon agent with orchestration contracts."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "0xclaw"))
from runtime.agent.loop import AgentLoop
from runtime.bus.events import InboundMessage
from runtime.bus.queue import MessageBus
from runtime.session.manager import SessionManager
from runtime.utils.helpers import sync_workspace_templates
from orchestration.contracts import ArtifactMeta, Envelope, wrap_artifact
from orchestration.model_profiles import MetricsLogger, ModelProfileResolver
from orchestration.router import SkillRouter
from orchestration.session_control import SessionControl
from orchestration.state import OrchestratorStateMachine, PipelineStateStore
from orchestration.write_guard import build_phase_write_guard, install_phase_write_guards
import main as cli_main
CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"
MODEL_PROFILES_PATH = ROOT / "0xclaw" / "config" / "model_profiles.json"
WORKSPACE = ROOT / "workspace"
HACKATHON_DIR = WORKSPACE / "hackathon"
ENVELOPE_LOG = HACKATHON_DIR / "envelopes.jsonl"
ARTIFACT_DIR = HACKATHON_DIR / "artifacts"
METRICS_PATH = HACKATHON_DIR / "metrics.jsonl"
PHASE_OUTPUTS = {
    "research": HACKATHON_DIR / "context.json",
    "idea": HACKATHON_DIR / "ideas.json",
    "selection": HACKATHON_DIR / "selected_idea.json",
    "planning": HACKATHON_DIR / "plan.md",
    "coding": HACKATHON_DIR / "project",
    "testing": HACKATHON_DIR / "test_results.json",
    "doc": HACKATHON_DIR / "submission" / "README.md",
}
PHASE_ARTIFACTS = {
    "research": "context",
    "idea": "ideas",
    "selection": "selected_idea",
    "planning": "plan",
    "coding": "tasks",
    "testing": "test_results",
    "doc": "submission",
}
CONTINUATION_PROMPT = (
    "Please proceed with ONLY the current phase. Do not ask clarifying questions. "
    "Complete only the task that was requested — do not start any other phases. "
    "Write the output file now."
)
MAX_TURNS = 200
IDLE_NUDGE_TIMEOUT_S = 30


def _fmt_wrap(text: str, width: int = 56, indent: str = "      ") -> str:
    return textwrap.fill(text, width=width, subsequent_indent=indent)


def _select_idea_interactive() -> bool:
    ideas_file = HACKATHON_DIR / "ideas.json"
    if not ideas_file.exists():
        print("[!] ideas.json not found. Run 'generate ideas' first.")
        return False
    raw = json.loads(ideas_file.read_text(encoding="utf-8"))
    idea_list: list = raw if isinstance(raw, list) else raw.get("ideas", [])
    if not idea_list:
        print("[!] ideas.json is empty.")
        return False
    print()
    print("╔" + "═" * 58 + "╗")
    print("║  🎯  SELECT YOUR PROJECT IDEA" + " " * 28 + "║")
    print("╠" + "═" * 58 + "╣")
    for i, idea in enumerate(idea_list, 1):
        title = idea.get("name") or idea.get("title", f"Idea {i}")
        tagline = idea.get("tagline") or idea.get("description", "")
        problem = idea.get("problem", "")
        scores = idea.get("scores", {})
        composite = scores.get("composite")
        sponsors = idea.get("sponsors") or list((idea.get("sponsor_integrations") or {}).keys())
        print("║                                                          ║")
        score_str = f"  [score: {composite:.2f}]" if composite else ""
        print(f"║  [{'{}] {}'.format(i, title) + score_str:<56}║")
        if tagline:
            for line in _fmt_wrap(tagline, width=54, indent="       ").splitlines():
                print(f"║      {line:<52}║")
        if problem and problem != tagline:
            for line in _fmt_wrap(f"Problem: {problem}", width=54, indent="               ").splitlines():
                print(f"║      {line:<52}║")
        if sponsors:
            print(f"║      Sponsors: {', '.join(str(s) for s in sponsors[:4]):<42}║")
    print("║                                                          ║")
    print("║  [0] Enter a custom idea instead                         ║")
    print("╚" + "═" * 58 + "╝")
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
            try:
                name = input("  Project name        : ").strip()
                tagline = input("  One-line tagline    : ").strip()
                problem = input("  Problem it solves   : ").strip()
                stack = input("  Tech stack (brief)  : ").strip()
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
                },
                "source": "human_provided",
                "selected_at": datetime.now(timezone.utc).isoformat(),
            }
        elif 1 <= num <= len(idea_list):
            idea = idea_list[num - 1]
            selected = {**idea, "selected_by": "human", "selected_at": datetime.now(timezone.utc).isoformat()}
        else:
            print(f"  Please enter a number between 0 and {len(idea_list)}.")
    out_file = HACKATHON_DIR / "selected_idea.json"
    out_file.write_text(json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n[✓] selected_idea.json written")
    return True


INTERACTIVE_HANDLERS = {
    "select": _select_idea_interactive,
    "pick": _select_idea_interactive,
    "choose": _select_idea_interactive,
}


def _detect_interactive(command: str):
    cmd_lower = command.lower()
    for keyword, handler in INTERACTIVE_HANDLERS.items():
        if keyword in cmd_lower:
            return handler
    return None


def _is_intent_only_response(response: str) -> bool:
    text = response.lower()
    intent_markers = ("state intent", "i will now execute", "i will begin")
    # Only treat concrete runtime signals as "action happened".
    # Avoid broad phrases like "written to" because "will be written to" is still intent-only.
    action_markers = (
        "has been spawned",
        "started (id:",
        "[subagent",
        "completed successfully",
        "phase 1 — research complete",
        "phase 2 — ideation is complete",
        "phase 4 — planning is complete",
    )
    return any(marker in text for marker in intent_markers) and not any(marker in text for marker in action_markers)


def _response_to_envelope(
    response: str,
    *,
    trace_id: str,
    session_id: str,
    phase: str,
    agent_id: str,
    output_ready: bool = False,
) -> Envelope:
    try:
        payload = json.loads(response)
        if isinstance(payload, dict):
            data = {"raw_response": payload}
        else:
            data = {"raw_response": response}
        kind = "result"
    except Exception:
        if output_ready:
            data = {"raw_response": response, "format": "text"}
            kind = "result"
        else:
            data = {"raw_response": response, "error": "non_json_response"}
            kind = "error"
    return Envelope(
        trace_id=trace_id,
        session_id=session_id,
        phase=phase,
        agent_id=agent_id,
        type=kind,
        payload=data,
    )


def _write_artifact_bundle(phase: str, output_path: Path) -> None:
    artifact_type = PHASE_ARTIFACTS[phase]
    meta = ArtifactMeta(
        artifact=artifact_type,
        version="v1",
        producer="orchestrator",
        schema_version="1.0.0",
    )
    if output_path.exists() and output_path.is_file() and output_path.suffix == ".json":
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"raw": output_path.read_text(encoding="utf-8")}
    else:
        data = {"path": str(output_path), "exists": output_path.exists()}
    payload = wrap_artifact(meta=meta, data=data)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / f"{artifact_type}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def run(command: str, timeout_per_turn: int = 240, max_turns: int = MAX_TURNS, resume: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    # web_search requires BRAVE_API_KEY; we don't have one, so clear it so
    # WebSearchTool.api_key returns "" (checked at call time) and the tool
    # immediately returns a "not configured" string instead of making failed
    # HTTP calls that waste sub-agent turns.
    os.environ.pop("BRAVE_API_KEY", None)

    sync_workspace_templates(WORKSPACE)
    config = cli_main._load_config(validate_provider_key=False)
    state_store = PipelineStateStore(HACKATHON_DIR)
    state_machine = OrchestratorStateMachine(WORKSPACE, state_store)
    session_control = SessionControl(state_store)
    router = SkillRouter(fallback_classifier=cli_main._fallback_classifier)
    profiles = ModelProfileResolver(MODEL_PROFILES_PATH)
    metrics = MetricsLogger(METRICS_PATH)
    if resume:
        decision = session_control.get_resume_decision()
        if not decision.command:
            print(f"[resume] {decision.reason}")
            return 0
        print(f"[resume] {decision.reason}")
        command = decision.command
    route = router.route(command)
    if not route.phase:
        print(f"[router] Unable to route command: {route.reason}")
        return 1
    phase = route.phase
    check = state_machine.validate_phase_entry(phase)
    if not check.ok:
        print("[state] Cannot start phase due to:")
        for err in check.errors:
            print(f"  - {err}")
        return 1
    profile = profiles.resolve(phase)
    if profile is not None:
        config.agents.defaults.model = profile.model
        config.agents.defaults.provider = profile.provider
        config.agents.defaults.max_tokens = profile.max_tokens
        config.agents.defaults.temperature = profile.temperature
        timeout_per_turn = profile.timeout_s
    output_file = PHASE_OUTPUTS.get(phase)
    trace_id = f"phase-{int(time.time())}-{phase}"
    state_machine.checkpoint(phase, "running", active_task=trace_id)

    # Each pipeline phase must start with a clean conversation history.
    # SessionManager persists JSONL files in workspace/sessions/; without
    # clearing them, each phase inherits the full message history of all
    # prior phases (100-200 messages).  The agent then mimics the most
    # recent tool-call patterns from validation/debug loops
    # phase bleed into the docs phase).  Deleting the files here gives
    # every phase a clean slate while leaving MEMORY.md intact.
    sessions_dir = WORKSPACE / "sessions"
    if sessions_dir.exists():
        for f in sessions_dir.glob("*.jsonl"):
            f.unlink()

    bus = MessageBus()
    provider = cli_main._make_provider(config)
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
        subagents_config=config.subagents,
    )
    write_guard = build_phase_write_guard(
        workspace=WORKSPACE,
        state_machine=state_machine,
        get_phase=lambda: phase,
    )
    install_phase_write_guards(agent.tools, write_guard)
    agent.subagents.set_write_guard(write_guard)
    envelope = Envelope.from_command(
        session_id="cli:direct",
        phase=phase,
        agent_id="orchestrator",
        trace_id=trace_id,
        payload={"user_command": command, "phase": phase},
    )
    cli_main._append_envelope(envelope)
    llm_message = (
        "You are executing a single pipeline phase. "
        "Consume the envelope below and complete only that phase.\n\n"
        f"{json.dumps(envelope.to_dict(), ensure_ascii=False)}"
    )
    print(f"\n{'='*70}")
    print(f"Command  : {command}")
    print(f"Phase    : {phase} ({route.source}, confidence={route.confidence:.2f})")
    print(f"Provider : {config.agents.defaults.provider} | {config.agents.defaults.model}")
    if phase == "coding":
        print(
            "Backend  : "
            f"{config.subagents.coding.backend} "
            f"(fallback: {config.subagents.coding.fallback_backend})"
        )
    print(f"Watching : {output_file or 'n/a'}")
    print(f"Trace ID : {trace_id}")
    print(f"{'='*70}\n")
    bus_task = asyncio.create_task(agent.run())

    async def next_response(timeout: int) -> str | None:
        # Treat timeout as inactivity timeout, not total turn duration.
        # Any outbound activity (progress or content) resets the timer.
        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                return None
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=min(1.0, remaining))
                deadline = time.monotonic() + timeout
                if msg.metadata.get("_progress"):
                    print(msg.content)
                elif msg.content:
                    return msg.content
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return None

    async def send(text: str) -> None:
        await bus.publish_inbound(
            InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="direct",
                content=text,
                metadata={"phase": phase},
            )
        )

    success = False
    nudge_count = 0
    auto_nudge_pending = False
    started_at = time.time()
    phase_status = "failed"
    llm_turns = 0
    try:
        await send(llm_message)
        for turn in range(1, max_turns + 1):
            print(f"[turn {turn}/{max_turns}] waiting for agent response...")
            turn_timeout = IDLE_NUDGE_TIMEOUT_S if auto_nudge_pending else timeout_per_turn
            response = await next_response(timeout=turn_timeout)
            if response is None:
                if auto_nudge_pending and nudge_count < 1:
                    print(f"[idle] No activity in {IDLE_NUDGE_TIMEOUT_S}s — sending continuation prompt")
                    await send(CONTINUATION_PROMPT)
                    nudge_count += 1
                    auto_nudge_pending = False
                    continue
                print(f"[timeout] No response in {turn_timeout}s")
                break
            llm_turns += 1
            auto_nudge_pending = False
            print(f"\n{'─'*60}\n[agent turn {turn}]\n{response}\n{'─'*60}\n")
            output_ready = cli_main._output_exists(output_file)
            resp_envelope = _response_to_envelope(
                response,
                trace_id=trace_id,
                session_id="cli:direct",
                phase=phase,
                agent_id="orchestrator",
                output_ready=output_ready,
            )
            cli_main._append_envelope(resp_envelope)
            await asyncio.sleep(1)
            if output_ready or cli_main._output_exists(output_file):
                print(f"[✓] Output file created: {output_file}")
                success = True
                break
            if turn == 1 and _is_intent_only_response(response):
                auto_nudge_pending = True
                print(f"[idle] Intent-only response detected — waiting {IDLE_NUDGE_TIMEOUT_S}s for activity")
            nudge_triggers = ["would you like", "shall i", "do you want", "should i", "clarif", "which option", "please confirm"]
            if nudge_count < 1 and any(t in response.lower() for t in nudge_triggers):
                print("[nudge] Agent asked a question — sending continuation prompt")
                await send(CONTINUATION_PROMPT)
                nudge_count += 1
    except KeyboardInterrupt:
        phase_status = "cancelled"
        state_machine.checkpoint(phase, "cancelled", last_error="Cancelled by Ctrl+C")
        metrics.log({
            "phase": phase,
            "model": config.agents.defaults.model,
            "duration_s": round(time.time() - started_at, 2),
            "fallback": False,
            "status": "cancelled",
        })
        print("\n[cancelled] Task cancelled by Ctrl+C. Session is preserved.")
        return 130
    finally:
        agent.stop()
        await asyncio.gather(bus_task, return_exceptions=True)
        await agent.close_mcp()

    # Final check: the output file may have been written by a subagent after
    # the last LLM turn but before the loop exhausted — check one more time.
    if not success and cli_main._output_exists(output_file):
        print(f"[✓] Output detected after loop: {output_file}")
        success = True

    phase_status = "done" if success else "failed"
    elapsed = round(time.time() - started_at, 2)
    if success:
        state_machine.checkpoint(phase, "done")
        if output_file is not None:
            _write_artifact_bundle(phase, output_file)
    else:
        state_machine.checkpoint(phase, "failed", last_error=f"No output after {max_turns} turns")
    metrics.log(
        {
            "phase": phase,
            "model": config.agents.defaults.model,
            "duration_s": elapsed,
            "fallback": False,
            "status": "done" if success else "failed",
        }
    )
    print(f"\n{'='*60}")
    if success:
        print(f"[✓] SUCCESS — phase {phase} completed")
    else:
        print(f"[✗] INCOMPLETE — phase {phase} did not produce expected output")
    print(f"{'='*60}\n")
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one 0xClaw pipeline phase")
    parser.add_argument("command", nargs="*", help="Natural language phase command")
    parser.add_argument("--resume", action="store_true", help="Resume from pipeline_state checkpoint")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ.pop("BRAVE_API_KEY", None)
    state_store = PipelineStateStore(HACKATHON_DIR)
    if not args.command and not args.resume:
        print("Usage: python scripts/run_phase.py '<command>' [--resume]")
        return 1
    command = " ".join(args.command).strip() if args.command else ""
    handler = _detect_interactive(command) if command else None
    if handler is not None:
        ok = handler()
        if ok:
            state_store.set_phase_status("selection", "done")
        else:
            state_store.set_phase_status("selection", "cancelled", last_error="Interactive selection cancelled")
        return 0 if ok else 1
    return asyncio.run(run(command, resume=args.resume))


if __name__ == "__main__":
    raise SystemExit(main())
