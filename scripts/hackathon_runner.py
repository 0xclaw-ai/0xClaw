#!/usr/bin/env python3
"""
0xClaw Hackathon Runner (Deprecated)

Fully automated pipeline that implements every project idea in
workspace/raw_ideas.md one by one.

For each idea:
  Phase 0 — Set up isolated workspace
  Phase 2 — Ideation   (generate 3 implementation variants)
  Phase 3 — Selection  (user picks a variant, or presses Enter to auto-select)
  Phase 4 — Planning   (architecture + task breakdown)
  Phase 5 — Coding     (full implementation)
  Phase 6 — Testing    (run & validate)
  Phase 7 — Docs       (README + submission package)
  Deploy   — Auto-start the project locally (best-effort)
  Confirm  — Ask whether to continue with the next project

Outputs live in:  workspace/hackathon/projects/{slug}/

Usage:
  python scripts/hackathon_runner.py              # implement all ideas
  python scripts/hackathon_runner.py --list       # show idea list and exit
  python scripts/hackathon_runner.py --idea 3     # implement only idea #3
  python scripts/hackathon_runner.py --start-from 4  # skip first 3 ideas

NOTE:
  This script is deprecated and kept only for backwards compatibility.
  It has a separate orchestration path from the main `0xclaw` CLI and
  may diverge in state semantics. Prefer `0xclaw` + `/resume` + `/redo`
  for regular workflow runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "0xclaw"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# web_search requires BRAVE_API_KEY; we don't have one, so clear it so
# The agent runtime's WebSearchTool returns an error string instead of making
# failed HTTP calls that waste sub-agent turns.
os.environ.pop("BRAVE_API_KEY", None)

WORKSPACE    = ROOT / "workspace"
HACKATHON_DIR = WORKSPACE / "hackathon"
PROJECTS_DIR  = HACKATHON_DIR / "projects"
RAW_IDEAS_FILE = WORKSPACE / "raw_ideas.md"
MODEL_PROFILES_PATH = ROOT / "0xclaw" / "config" / "model_profiles.json"

# State management — imported lazily to keep startup fast
from orchestration.state import PipelineStateStore  # noqa: E402


def _seed_state(phases_done: list[str]) -> None:
    """Mark one or more phases as 'done' in pipeline_state.json.

    The runner handles research/idea/selection phases itself (writing the
    artefacts directly rather than through rp.run), so we must tell the
    state machine about them so it allows downstream phases to proceed.
    """
    store = PipelineStateStore(HACKATHON_DIR)
    for phase in phases_done:
        store.set_phase_status(phase, "done")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _wrap(text: str, width: int = 60, indent: str = "  ") -> list[str]:
    return textwrap.wrap(text, width, subsequent_indent=indent)


def _phase_idle_timeout(phase: str, default: int) -> int:
    """Read per-phase idle timeout from model_profiles.json."""
    try:
        raw = json.loads(MODEL_PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default

    for row in raw.get("profiles", []):
        if row.get("phase") == phase:
            try:
                return int(row.get("timeout_s", default))
            except (TypeError, ValueError):
                return default
    return default


# ── Idea parsing ───────────────────────────────────────────────────────────────

def parse_ideas(path: Path) -> list[dict]:
    """Parse workspace/raw_ideas.md into a list of structured idea dicts."""
    text = path.read_text()
    ideas: list[dict] = []

    # Each idea has YAML frontmatter:  ---\ntitle: "..." \n...\n---
    fm_pattern = re.compile(
        r"---\s*\ntitle:\s*['\"]?(.+?)['\"]?\s*\n(.*?)---",
        re.DOTALL,
    )
    for m in fm_pattern.finditer(text):
        title = m.group(1).strip()
        body  = m.group(2)
        idea: dict = {"title": title, "slug": _slug(title)}

        # summary (folded scalar >)
        sm = re.search(r"summary:\s*>\s*\n((?:[ \t]+.+\n?)+)", body)
        if sm:
            idea["summary"] = re.sub(r"\s+", " ", sm.group(1)).strip()

        # category list
        cm = re.search(r"category:\s*\n((?:[ \t]+-[ \t]+.+\n?)+)", body)
        if cm:
            idea["categories"] = re.findall(r"-[ \t]+(.+)", cm.group(1))

        # integrations list
        im = re.search(r"integrations:\s*\n((?:[ \t]+-[ \t]+.+\n?)+)", body)
        if im:
            idea["integrations"] = re.findall(r"-[ \t]+(.+)", im.group(1))

        # keywords
        km = re.search(r"keywords:\s*\n((?:[ \t]+-[ \t]+.+\n?)+)", body)
        if km:
            idea["keywords"] = re.findall(r"-[ \t]+(.+)", km.group(1))

        # source
        src = re.search(r'source:\s*["\']?([^"\'\n]+)["\']?', body)
        if src:
            idea["source"] = src.group(1).strip()

        ideas.append(idea)

    # Attach ## Description sections (appear after frontmatter, in order)
    desc_blocks = re.findall(r"## Description\s*\n((?:[^\n#].*\n?)+)", text)
    for i, desc in enumerate(desc_blocks):
        if i < len(ideas):
            ideas[i]["description"] = desc.strip()

    # Attach ## Possible Implementation Components
    comp_blocks = re.findall(
        r"## Possible Implementation Components\s*\n((?:[^\n#].*\n?)+)", text
    )
    for i, comps in enumerate(comp_blocks):
        if i < len(ideas):
            ideas[i]["components"] = [
                c.strip("- ").strip()
                for c in comps.strip().splitlines()
                if c.strip().startswith("-")
            ]

    return ideas


# ── Workspace management ───────────────────────────────────────────────────────

def setup_project_workspace(idea: dict) -> None:
    """
    Clear workspace/hackathon/ (preserving projects/) and write a
    seed context.json that anchors the idea agent to this project domain.
    """
    HACKATHON_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    # Clear working files from previous project
    for item in HACKATHON_DIR.iterdir():
        if item.name == "projects":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Seed context.json — idea agent reads this in Phase 2
    context = {
        "hackathon": {
            "name": "UK AI Agent Hackathon EP4 x OpenClaw",
            "url": "https://dorahacks.io/hackathon/1985",
            "submission_deadline": "2026-03-07T23:59:00",
            "format": "hybrid",
            "judging_criteria": [
                {"criterion": "Technical Innovation", "weight": "high",
                 "notes": "Novel use of AI/agent tech"},
                {"criterion": "Sponsor Integration", "weight": "high",
                 "notes": "Depth of sponsor API usage"},
                {"criterion": "Demo Impact", "weight": "high",
                 "notes": "Live demo wow factor"},
                {"criterion": "Market Fit", "weight": "medium",
                 "notes": "Real problem, real users"},
                {"criterion": "Code Quality", "weight": "medium",
                 "notes": "Production-ready, not a prototype"},
            ],
            "submission_requirements": [
                "Working demo (video or live)",
                "Public GitHub repo",
                "DoraHacks BUIDL submission with description",
                "README with setup instructions",
            ],
        },
        "sponsors": [
            {
                "name": "FLock.io", "tier": "gold",
                "api_base_url": "https://api.flock.io/v1",
                "auth_method": "custom_header",
                "auth_header": "x-litellm-api-key",
                "available_models": ["qwen3-30b-a3b-instruct-2507"],
                "key_capability": "Decentralised AI model hub — primary LLM for all inference",
                "bounty_available": True,
                "bounty_notes": "Gold sponsor — integrate as primary LLM for maximum score",
            },
        ],
        "seed_concept": {
            "title":        idea["title"],
            "summary":      idea.get("summary", ""),
            "categories":   idea.get("categories", []),
            "integrations": idea.get("integrations", []),
            "description":  idea.get("description", ""),
            "keywords":     idea.get("keywords", []),
        },
        "strategic_notes": (
            f"Target concept: '{idea['title']}'. "
            "Generate 3 concrete, distinct implementation variants of this concept. "
            "Each variant must deeply integrate ≥2 sponsor technologies as core mechanics "
            "(not add-ons). All variants must be buildable in 5–7 days. "
            "Stay within the domain defined by seed_concept."
        ),
        "recommended_sponsor_priority": ["FLock.io", "Virtual Protocol", "Unibase"],
    }

    (HACKATHON_DIR / "context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False)
    )
    print(f"  ✓ Workspace ready — context.json written for '{idea['title']}'")


def archive_project(slug: str) -> Path:
    """
    Copy completed workspace/hackathon/ outputs to
    workspace/hackathon/projects/{slug}/  (preserves projects/ dir itself).
    """
    dest = PROJECTS_DIR / slug
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for item in HACKATHON_DIR.iterdir():
        if item.name == "projects":
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    print(f"  ✓ Project archived → workspace/hackathon/projects/{slug}/")
    return dest


# ── Variant selection UI ───────────────────────────────────────────────────────

def show_and_select_idea(ideas_file: Path) -> bool:
    """
    Display the 3 generated variants from ideas.json.
    User enters 1–N to pick, or presses Enter to let 0xClaw auto-select (★ best).
    Writes hackathon/selected_idea.json.  Returns True on success.
    """
    if not ideas_file.exists():
        print("  [select] ideas.json not found — will use raw idea as fallback.")
        return False

    raw = json.loads(ideas_file.read_text())
    idea_list: list = raw if isinstance(raw, list) else raw.get("ideas", [])
    if not idea_list:
        print("  [select] ideas.json is empty — will use raw idea as fallback.")
        return False

    recommendation: str | None = (
        raw.get("recommendation") if isinstance(raw, dict) else None
    )

    # Determine auto-select index (recommendation > highest composite > 0)
    rec_idx = 0
    for i, item in enumerate(idea_list):
        if item.get("id") == recommendation:
            rec_idx = i
            break
    else:
        rec_idx = max(
            range(len(idea_list)),
            key=lambda i: idea_list[i].get("scores", {}).get("composite", 0),
        )

    auto_name = (
        idea_list[rec_idx].get("name")
        or idea_list[rec_idx].get("title", "Best option")
    )

    W = 66
    print()
    print("╔" + "═" * W + "╗")
    print(f"║  🎯  SELECT IMPLEMENTATION VARIANT{' ' * (W - 35)}║")
    print(f"║  Press Enter to auto-select (★ recommended by agent){' ' * (W - 53)}║")
    print("╠" + "═" * W + "╣")

    for i, item in enumerate(idea_list, 1):
        title     = item.get("name") or item.get("title", f"Variant {i}")
        tagline   = item.get("tagline") or item.get("description", "")
        scores    = item.get("scores", {})
        composite = scores.get("composite")
        is_rec    = (i - 1 == rec_idx)
        rec_mark  = "  ★" if is_rec else ""
        score_str = f" [score: {composite:.2f}]" if composite else ""
        header    = f"[{i}] {title}{score_str}{rec_mark}"

        print(f"║{' ' * W}║")
        print(f"║  {header:<{W-2}}║")
        for line in textwrap.wrap(tagline[:160], W - 6):
            print(f"║      {line:<{W-6}}║")

        sponsors = item.get("sponsor_integrations", {})
        if sponsors:
            sp_str = ", ".join(
                f"{k}: {str(v)[:30]}"
                for k, v in list(sponsors.items())[:2]
                if v
            )
            print(f"║      Sponsors → {sp_str:<{W-17}}║")

    print(f"║{' ' * W}║")
    print(f"║  [0] Enter a custom idea instead{' ' * (W - 33)}║")
    print("╚" + "═" * W + "╝")

    selected: dict | None = None
    auto_selected = False

    while selected is None:
        try:
            raw_input = input(
                f"\n  Your choice [1–{len(idea_list)}]"
                f" (Enter = auto '{auto_name}'): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [cancelled]")
            return False

        if not raw_input:
            selected = idea_list[rec_idx]
            auto_selected = True
            continue

        try:
            num = int(raw_input)
        except ValueError:
            print(f"  Please enter a number between 0 and {len(idea_list)}.")
            continue

        if num == 0:
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
                },
                "source": "human_provided",
            }
        elif 1 <= num <= len(idea_list):
            selected = idea_list[num - 1]
        else:
            print(f"  Please enter a number between 0 and {len(idea_list)}.")
            continue

    out = {
        **selected,
        "selected_by": "auto" if auto_selected else "human",
        "selected_at": datetime.now(timezone.utc).isoformat(),
    }
    (HACKATHON_DIR / "selected_idea.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )
    how  = "Auto-selected" if auto_selected else "Selected"
    name = out.get("name") or out.get("title", "?")
    print(f"\n  ✓ {how}: {name}")
    print(f"  ✓ Written → workspace/hackathon/selected_idea.json\n")
    return True


# ── Auto-deploy ────────────────────────────────────────────────────────────────

def try_auto_deploy(project_dir: Path) -> "subprocess.Popen | None":
    """
    Install deps and start the completed project locally.
    Best-effort, non-blocking.  Returns the Popen handle or None.
    """
    code_dir = project_dir / "project"
    if not code_dir.exists():
        print("  [deploy] No project/ directory — skipping auto-deploy.")
        return None

    print("\n  🚀 Attempting local deployment...")

    # Install Python dependencies
    req_file = code_dir / "requirements.txt"
    if req_file.exists():
        print("  [deploy] pip install -r requirements.txt ...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                print("  [deploy] ✓ Dependencies installed")
            else:
                print(f"  [deploy] ✗ pip failed:\n{result.stderr[:300]}")
        except subprocess.TimeoutExpired:
            print("  [deploy] ✗ pip install timed out")

    pyproject = code_dir / "pyproject.toml"
    if pyproject.exists() and not req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-e", str(code_dir)],
            capture_output=True, timeout=120,
        )

    # Priority: docker-compose > Makefile > shell scripts
    ordered_cmds = [
        ("docker-compose.yml",  ["docker-compose", "up", "-d"]),
        ("docker-compose.yaml", ["docker-compose", "up", "-d"]),
        ("Makefile",            ["make", "start"]),
        ("start.sh",            ["bash", "start.sh"]),
        ("run.sh",              ["bash", "run.sh"]),
    ]
    for filename, cmd in ordered_cmds:
        if (code_dir / filename).exists():
            print(f"  [deploy] {' '.join(cmd)}")
            try:
                proc = subprocess.Popen(cmd, cwd=str(code_dir))
                print(f"  [deploy] ✓ Started (PID {proc.pid})")
                print("  [deploy] → http://localhost:8000")
                return proc
            except Exception as exc:
                print(f"  [deploy] ✗ {exc}")

    # Fallback: Python entry-point detection
    for py_entry in ["main.py", "app.py", "server.py", "api.py"]:
        entry = code_dir / py_entry
        if not entry.exists():
            continue
        content = entry.read_text(errors="replace")

        if "uvicorn" in content or "fastapi" in content.lower():
            module  = py_entry.replace(".py", "")
            app_var = "app"
            mv = re.search(r"(\w+)\s*=\s*FastAPI\(", content)
            if mv:
                app_var = mv.group(1)
            cmd = [sys.executable, "-m", "uvicorn",
                   f"{module}:{app_var}", "--host", "0.0.0.0", "--port", "8000"]
        elif "streamlit" in content:
            cmd = [sys.executable, "-m", "streamlit", "run", str(entry),
                   "--server.address", "0.0.0.0"]
        elif "gradio" in content or "gr.Interface" in content:
            cmd = [sys.executable, str(entry)]
        else:
            cmd = [sys.executable, str(entry)]

        print(f"  [deploy] {' '.join(cmd[:4])} ...")
        try:
            proc = subprocess.Popen(cmd, cwd=str(code_dir))
            print(f"  [deploy] ✓ Started (PID {proc.pid})")
            print("  [deploy] → http://localhost:8000")
            return proc
        except Exception as exc:
            print(f"  [deploy] ✗ {exc}")
        break

    print(f"  [deploy] Could not determine entry point.")
    print(f"  [deploy] Run manually from: {code_dir}")
    return None


# ── Pipeline runner ────────────────────────────────────────────────────────────

async def run_phase_cmd(
    command: str,
    output_file: "Path | None" = None,
    timeout: int = 300,
    max_turns: int = 20,
) -> bool:
    """
    Run one pipeline phase via run_phase.run().
    Returns True if output_file was produced (or always True when output_file is None).
    """
    import run_phase as rp

    print(f"\n  ▶ {command[:100]}")
    await rp.run(command, timeout_per_turn=timeout, max_turns=max_turns)

    if output_file is not None:
        if output_file.is_dir():
            ok = output_file.exists() and any(output_file.rglob("*"))
        else:
            ok = output_file.exists() and output_file.stat().st_size > 10
        rel = output_file.relative_to(ROOT) if output_file.is_relative_to(ROOT) else output_file
        if ok:
            print(f"  ✓ Output: {rel}")
        else:
            print(f"  ✗ Expected output not found: {rel}")
        return ok

    return True


# ── Display helpers ────────────────────────────────────────────────────────────

def _print_banner(total: int) -> None:
    print("\n" + "═" * 68)
    print(f"  0xClaw Hackathon Runner")
    print(f"  {total} project ideas found in workspace/raw_ideas.md")
    print(f"  Full pipeline: Ideation → Selection → Plan → Code → Test → Docs")
    print("═" * 68)


def _print_project_header(idx: int, total: int, idea: dict) -> None:
    cats = ", ".join(idea.get("categories", [])[:2])
    print(f"\n{'═' * 68}")
    print(f"  Project {idx}/{total}: {idea['title']}")
    if cats:
        print(f"  [{cats}]")
    summary = idea.get("summary", "")
    if summary:
        for line in _wrap(summary, 60, "  "):
            print(f"  {line}")
    print("═" * 68)


# ── Main orchestrator ──────────────────────────────────────────────────────────

async def run_hackathon(
    start_from: int = 0,
    only_idea: int | None = None,
    list_only: bool = False,
) -> None:
    """
    Main entry point.  Parses raw_ideas.md and runs the full pipeline
    for each selected idea.
    """
    load_dotenv(ROOT / ".env")

    if not RAW_IDEAS_FILE.exists():
        print(f"[!] {RAW_IDEAS_FILE} not found.")
        print("    Place your collected hackathon ideas in workspace/raw_ideas.md")
        return

    ideas = parse_ideas(RAW_IDEAS_FILE)
    if not ideas:
        print("[!] No ideas parsed from workspace/raw_ideas.md")
        return

    _print_banner(len(ideas))
    print()

    # ── List all ideas ────────────────────────────────────────────────────────
    for i, idea in enumerate(ideas, 1):
        cats      = ", ".join(idea.get("categories", [])[:2])
        done_mark = " ✓ done" if (PROJECTS_DIR / idea["slug"]).exists() else ""
        print(f"  [{i:2d}] {idea['title']:<46} [{cats}]{done_mark}")
    print()

    if list_only:
        return

    # ── Build target list ─────────────────────────────────────────────────────
    if only_idea is not None:
        if not (1 <= only_idea <= len(ideas)):
            print(f"[!] --idea must be between 1 and {len(ideas)}")
            return
        targets = [(only_idea, ideas[only_idea - 1])]
    else:
        targets = [(i + 1, idea) for i, idea in enumerate(ideas[start_from:])]

    # ── Process each project ──────────────────────────────────────────────────
    deploy_proc: "subprocess.Popen | None" = None

    for rel_idx, (abs_idx, idea) in enumerate(targets):
        slug = idea["slug"]
        _print_project_header(abs_idx, len(ideas), idea)

        # Skip already-done projects unless forced
        if only_idea is None and (PROJECTS_DIR / slug).exists():
            if (PROJECTS_DIR / slug / "selected_idea.json").exists():
                try:
                    ans = input(
                        f"  '{idea['title']}' already implemented. Re-run? [y/N]: "
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\n  Stopping.")
                    break
                if ans != "y":
                    continue

        # Stop any running server from the previous project
        if deploy_proc and deploy_proc.poll() is None:
            print(f"\n  [deploy] Stopping previous server (PID {deploy_proc.pid})...")
            deploy_proc.terminate()
            deploy_proc = None

        # ── Phase 0: workspace setup ──────────────────────────────────────────
        print(f"\n  ── Phase 0/7: Setting up project workspace ──")
        setup_project_workspace(idea)
        # context.json was written directly (bypassing run_phase), so tell
        # the state machine that research is complete.
        _seed_state(["research"])

        # ── Phase 2: ideation — generate 3 variants ───────────────────────────
        print(f"\n  ── Phase 2/7: Generating implementation variants ──")
        ideas_file  = HACKATHON_DIR / "ideas.json"
        ideation_ok = await run_phase_cmd(
            (
                f"generate ideas — create 3 scored variants for "
                f"'{idea['title']}'. Read context.json (seed_concept field). "
                f"Write hackathon/ideas.json with 3 variants. "
                f"DO NOT use spawn() — execute every step yourself directly."
            ),
            output_file=ideas_file,
            timeout=240,
            max_turns=15,
        )
        # If ideation failed (router conflict, LLM error, etc.), mark the idea
        # phase done anyway so planning is not blocked by a stale dependency.
        if not ideation_ok:
            _seed_state(["idea"])

        # ── Phase 3: selection ────────────────────────────────────────────────
        print(f"\n  ── Phase 3/7: Variant selection ──")
        if ideation_ok:
            sel_ok = show_and_select_idea(ideas_file)
        else:
            sel_ok = False

        if not sel_ok:
            # Fallback: write raw idea directly as selected_idea.json
            print("  [fallback] Using raw idea directly as selected project...")
            fallback: dict = {
                "id": slug,
                "name": idea["title"],
                "tagline": idea.get("summary", "")[:120],
                "problem": idea.get("description", ""),
                "tech_stack": {
                    "backend": "Python 3.11 + FastAPI",
                    "ai_primary": "FLock API (qwen3-30b-a3b-instruct-2507)",
                    "storage": "SQLite",
                    "frontend": "Gradio",
                },
                "sponsor_integrations": {
                    "flock": "primary LLM inference engine",
                },
                "selected_by": "fallback",
                "selected_at": datetime.now(timezone.utc).isoformat(),
            }
            (HACKATHON_DIR / "selected_idea.json").write_text(
                json.dumps(fallback, indent=2, ensure_ascii=False)
            )

        # Selection was handled by the runner (either interactively or via
        # fallback), not through rp.run, so mark it done in the state store.
        _seed_state(["selection"])

        # ── Phase 4: planning ─────────────────────────────────────────────────
        print(f"\n  ── Phase 4/7: Planning architecture & task breakdown ──")
        await run_phase_cmd(
            "plan the architecture — read selected_idea.json and context.json, "
            "then write hackathon/plan.md and hackathon/tasks.json",
            output_file=HACKATHON_DIR / "plan.md",
            timeout=300,
            max_turns=15,
        )
        # Ensure coding is not blocked if planning failed or produced no output.
        _seed_state(["planning"])
        # Required artifacts for coding: plan.md and tasks.json must exist.
        if not (HACKATHON_DIR / "plan.md").exists():
            (HACKATHON_DIR / "plan.md").write_text(
                f"# {idea['title']}\n\nImplement as described in selected_idea.json.\n"
            )
        if not (HACKATHON_DIR / "tasks.json").exists():
            (HACKATHON_DIR / "tasks.json").write_text(
                json.dumps({"tasks": ["implement core features", "verify core flows", "write docs"]}, indent=2)
            )

        # ── Phase 5: implementation ───────────────────────────────────────────
        print(f"\n  ── Phase 5/7: Implementing the project (coding) ──")
        await run_phase_cmd(
            "start coding — implement the hackathon project. "
            "Read plan.md and tasks.json. Write all code to hackathon/project/. "
            "STRICT RULES to prevent loops: "
            "(1) Write each file path EXACTLY ONCE — never call write_file on the same path twice. "
            "(2) Before writing any file, call list_dir to check if it already exists; if it does, skip it. "
            "(3) Keep a mental checklist; once a file is written, cross it off and never revisit it. "
            "(4) When requirements.txt and main.py are both written, STOP immediately — do not continue. "
            "DO NOT use spawn() — execute every task yourself directly. "
            "DO NOT call message() when done — just stop.",
            output_file=HACKATHON_DIR / "project",
            timeout=_phase_idle_timeout("coding", 420),
            max_turns=30,
        )
        # Ensure testing is not blocked if coding failed.
        _seed_state(["coding"])
        # Required artifact for testing: project/ directory must exist.
        (HACKATHON_DIR / "project").mkdir(exist_ok=True)

        # ── Phase 6: testing ──────────────────────────────────────────────────
        print(f"\n  ── Phase 6/7: Running tests ──")
        await run_phase_cmd(
            "run tests — validate the build, run any existing test files, "
            "write hackathon/test_results.json. "
            "DO NOT write new test files. DO NOT use spawn(). DO NOT call message().",
            output_file=HACKATHON_DIR / "test_results.json",
            timeout=240,
            max_turns=15,
        )
        # Ensure docs phase is not blocked if testing failed.
        _seed_state(["testing"])
        # Required artifact for docs: test_results.json must exist.
        if not (HACKATHON_DIR / "test_results.json").exists():
            (HACKATHON_DIR / "test_results.json").write_text(
                json.dumps({"status": "skipped", "reason": "testing phase produced no results"}, indent=2)
            )

        # ── Phase 7: documentation ────────────────────────────────────────────
        print(f"\n  ── Phase 7/7: Generating documentation ──")
        await run_phase_cmd(
            "prepare docs — write submission README and SUBMISSION.md to "
            "hackathon/submission/",
            output_file=HACKATHON_DIR / "submission" / "README.md",
            timeout=240,
            max_turns=15,
        )

        # ── Archive ───────────────────────────────────────────────────────────
        print(f"\n  ── Archiving project ──")
        project_dir = archive_project(slug)

        # Progress log
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        prog_file = HACKATHON_DIR / "progress.md"
        with open(prog_file, "a") as f:
            f.write(f"[{ts}] Complete: {idea['title']} → projects/{slug}/\n")

        # ── Auto-deploy ───────────────────────────────────────────────────────
        deploy_proc = try_auto_deploy(project_dir)

        # ── Per-project summary ───────────────────────────────────────────────
        print(f"\n  {'─' * 64}")
        print(f"  ✅  Project complete: {idea['title']}")
        print(f"      Code    → workspace/hackathon/projects/{slug}/project/")
        print(f"      Docs    → workspace/hackathon/projects/{slug}/submission/")
        if deploy_proc and deploy_proc.poll() is None:
            print(f"      Server  → http://localhost:8000  (PID {deploy_proc.pid})")
        print(f"  {'─' * 64}")

        # ── Continue? ─────────────────────────────────────────────────────────
        remaining = targets[rel_idx + 1:]
        if not remaining:
            break

        next_abs, next_idea = remaining[0]
        print()
        try:
            ans = input(
                f"  ▶ Continue with project [{next_abs}/{len(ideas)}]"
                f" '{next_idea['title']}'? [Y/n/q]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Stopping.")
            break

        if ans in {"n", "no", "q", "quit", "exit"}:
            print("  Hackathon runner stopped by user.")
            break

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"\n{'═' * 68}")
    print(f"  0xClaw Hackathon Runner — Session complete")
    done_projects = sorted(PROJECTS_DIR.iterdir()) if PROJECTS_DIR.exists() else []
    print(f"  {len(done_projects)} project(s) implemented:")
    for p in done_projects:
        print(f"    • {p.name}")
    print(f"{'═' * 68}\n")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    print(
        "[deprecated] scripts/hackathon_runner.py is deprecated. "
        "Use the `0xclaw` CLI pipeline commands for regular runs."
    )

    parser = argparse.ArgumentParser(
        description="0xClaw Hackathon Runner — implements all collected ideas one by one",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/hackathon_runner.py               # implement all ideas
  python scripts/hackathon_runner.py --list        # show idea list
  python scripts/hackathon_runner.py --idea 3      # implement only idea #3
  python scripts/hackathon_runner.py --start-from 4  # skip first 3 ideas
        """,
    )
    parser.add_argument("--list",       action="store_true",
                        help="Print all ideas and exit")
    parser.add_argument("--idea",       type=int, default=None, metavar="N",
                        help="Implement only idea #N")
    parser.add_argument("--start-from", type=int, default=0,   metavar="N",
                        help="Skip first N-1 ideas (default: 0)")
    args = parser.parse_args()

    asyncio.run(run_hackathon(
        start_from=args.start_from,
        only_idea=args.idea,
        list_only=args.list,
    ))
