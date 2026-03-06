# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

0xClaw is an autonomous hackathon agent competing in the **UK AI Agent Hackathon EP4 x OpenClaw**
(DoraHacks #1985, deadline **7 March 2026 23:59**). The meta-story is the submission: an AI agent
that independently researched, planned, coded, and submitted a project to the very hackathon it
was entered in.

The agent receives a hackathon URL, then autonomously runs a 7-phase pipeline:
**Research → Ideation → Selection → Planning → Implementation → Testing → Documentation**

The **generated project** (Layer 2) is **DevAgent** — an autonomous terminal coding agent —
located at `workspace/hackathon/project/`.

### Current pipeline status

All 7 phases are complete. Outputs are gitignored runtime artefacts in `workspace/hackathon/`:

| Phase | Status | Key output |
|-------|--------|------------|
| research | done | `context.json`, `research_summary.md` |
| idea | done | `ideas.json` |
| selection | done | `selected_idea.json` |
| planning | done | `plan.md`, `tasks.json` |
| coding | done | `project/` (DevAgent) |
| testing | done | `test_results.json` |
| doc | done | `submission/` (README, SUBMISSION, PITCH) |

Remaining work: demo video, GitHub repo publish, DoraHacks BUIDL page submission.

---

## Environment — always do this first

```bash
conda activate 0xclaw          # Python 3.11, all deps installed
cp .env.example .env           # first time only; fill in real API keys
./scripts/verify_setup.sh      # confirms nanobot import + workspace + API keys
./scripts/start.sh             # launch the agent
./scripts/start.sh --logs      # launch with loguru output visible
```

### Required `.env` keys

| Key | Purpose | Notes |
|-----|---------|-------|
| `FLOCK_API_KEY` | Primary LLM via FLock.io | HTTP 400 = budget exhausted |
| `ZAI_API_KEY` | Secondary LLM via Z.ai/Zhipu | `zhipu`/`custom` provider in config |
| `BRAVE_API_KEY` | Web search | Optional |
| `ANYWAY_API_KEY` | Observability tracing | Optional; leave blank to disable |
| `VIRTUALS_API_KEY` | Virtuals Protocol (Bronze sponsor) | Optional; tool registered but not critical |
| `MEMBASE_ID` / `MEMBASE_ACCOUNT` / `MEMBASE_SECRET_KEY` | Unibase (Bronze sponsor) | Optional |

---

## Sponsors (from Luma — authoritative)

| Tier | Sponsors |
|------|---------|
| Gold | FLock.io, Sierra.ai, Z.ai, Cantor8 |
| Silver | The Compression Company, Animoca Brands, Lovable, Anyway, SuperCell, AfterQuery |
| Bronze | Virtual Protocol, Unibase |
| Partner | ManusAI (co-host, not sponsor) |

**Venice.ai is NOT a sponsor — do not include it anywhere.**

---

## Two-layer architecture

```
Layer 1 — 0xClaw (the agent we maintain)
  0xclaw/main.py            CLI entry point, interactive REPL, slash commands
  0xclaw/orchestration/     Phase routing, state machine, write guards, model profiles
  0xclaw/observability/     Anyway OpenTelemetry tracing (optional)
  0xclaw/tools/             VirtualsTool, UnibaseTool (custom nanobot tools)
  0xclaw/config/            config.json (providers), model_profiles.json (per-phase settings)
  0xclaw/framework/         Vendored nanobot runtime — DO NOT modify except registry.py + schema.py
  workspace/                Agent identity, skills, pipeline state

Layer 2 — Generated project (DevAgent)
  workspace/hackathon/project/   The hackathon submission (gitignored)
  workspace/hackathon/submission/ Pitch and README documents (gitignored)
```

---

## Key files

| File | Purpose |
|------|---------|
| `0xclaw/main.py` | Entry point: CLI loop, AgentLoop wiring, slash commands, reset/resume/stop |
| `0xclaw/config/config.json` | Provider config — FLock (primary), Zhipu/Z.ai (secondary). Env vars substituted at load time |
| `0xclaw/config/model_profiles.json` | Per-phase model + timeout overrides (minimax-m2.1 for early phases, minimax-m2.5 for coding/testing) |
| `0xclaw/orchestration/state.py` | `PipelineStateStore`, `OrchestratorStateMachine` — phase deps and artifact requirements |
| `0xclaw/orchestration/router.py` | `SkillRouter` — keyword + LLM fallback routing. Supports English and Chinese triggers |
| `0xclaw/orchestration/contracts.py` | `Envelope`, `ArtifactMeta` dataclasses for CLI → AgentLoop messages |
| `0xclaw/orchestration/model_profiles.py` | `ModelProfileResolver`, `MetricsLogger` |
| `0xclaw/orchestration/session_control.py` | `SessionControl` — `/resume` logic, `PHASE_TO_COMMAND` map |
| `0xclaw/orchestration/write_guard.py` | `install_phase_write_guards()` — phase-scoped filesystem write protection |
| `0xclaw/observability/anyway.py` | `init_anyway_from_env()`, `workflow_span()` — gracefully no-ops if key absent |
| `0xclaw/tools/virtuals_tool.py` | Virtuals Protocol GAME SDK — on-chain agent identity |
| `0xclaw/tools/unibase_tool.py` | Unibase membase — persistent on-chain memory |
| `0xclaw/framework/nanobot/providers/registry.py` | FLock provider spec (our addition — safe to modify) |
| `0xclaw/framework/nanobot/config/schema.py` | `ProvidersConfig` with `flock` field (our addition — safe to modify) |
| `workspace/SOUL.md` | Agent identity and mission (loaded every turn) |
| `workspace/AGENTS.md` | 7-phase pipeline protocol (loaded every turn) |
| `workspace/skills/*/SKILL.md` | Spawn task templates — one per pipeline phase |

---

## Orchestration layer

The `0xclaw/orchestration/` package sits between `main.py` and nanobot.

**`SkillRouter`** maps free-form user input to a pipeline phase via keyword rules, with an
LLM classifier as fallback. `KEYWORD_MAP` in `router.py` covers English and Chinese triggers.
Important: Chinese keywords use plain substring matching (not `\b` word boundaries, which
break for CJK characters).

**`OrchestratorStateMachine`** validates phase entry — checks that all dependency phases are
`done` and required artifact files exist — then enforces per-phase write permissions via
`PHASE_ALLOWED_WRITE_DIRS`.

**`PipelineStateStore`** is a file-backed store at `workspace/hackathon/pipeline_state.json`.
Phase lifecycle: `pending → running → done | failed | cancelled`.

**Write guards** — `install_phase_write_guards()` monkey-patches nanobot's `write_file` /
`edit_file` tools so sub-agents can only write inside their allowed directories. A violation
returns an error string; it does not raise (sub-agent continues safely).

**`ModelProfileResolver`** loads `model_profiles.json` to resolve per-phase model, max_tokens,
temperature, and timeout overrides on top of the defaults in `config.json`.

**`Envelope`** — typed dataclass wrapping every CLI → AgentLoop phase invocation. Serialised to
`workspace/hackathon/envelopes.jsonl` for audit/replay. Contains phase name, command, timestamp,
model profile used, and run metadata.

**`SessionControl`** implements `/resume` by scanning `pipeline_state.json` for the first
non-`done` phase and returning its natural-language command (via `PHASE_TO_COMMAND`).

---

## Nanobot framework internals

> The nanobot source lives in `0xclaw/framework/nanobot/`. The top-level `nanobot/` directory
> contains orphaned framework tests from a previous layout — it is removed from git tracking
> and ignored. Do not commit anything to it.

**Skills** — `SKILL.md` files in `workspace/skills/{name}/`. Auto-loaded when `always: true` is
set in frontmatter. Loaded on-demand via `read_file` otherwise.

**`spawn()`** — creates a background asyncio sub-agent with its own isolated tool registry
(no `spawn` or `message` tools). Results arrive as `channel="system"` messages on the main
agent's bus. Sub-agents have no shared memory — all context must be embedded in the task string.

**Workspace bootstrap** — `SOUL.md`, `AGENTS.md`, and `HEARTBEAT.md` are loaded every turn.
`MEMORY.md` is loaded separately for long-term state.

**`sync_workspace_templates`** — called at startup. Creates missing workspace files from
templates; never overwrites files that already exist.

**File paths in tasks** — nanobot resolves relative paths as `workspace_dir / path`.
Always write `hackathon/context.json` (not `workspace/hackathon/context.json`). Same rule
applies to `exec()` working directory.

---

## Provider / model details

### FLock.io (primary LLM — `provider: "flock"`)
- Endpoint: `https://api.flock.io/v1`
- Auth: custom header `x-litellm-api-key: $FLOCK_API_KEY` (not standard Bearer)
- Default model: `minimax-m2.5` (`config.json`)
- Early phases (research/idea/selection/doc): `minimax-m2.1`, 180–240 s timeout
- Heavy phases (planning/coding/testing): `minimax-m2.5`, 240–300 s timeout, up to 16k tokens
- Routed through LiteLLM as `openai/<model>` with `api_base` override

### Z.ai / Zhipu (secondary — `provider: "zhipu"` or `"custom"`)
- Endpoint: `https://open.bigmodel.cn/api/paas/v4/`
- Auth: `ZAI_API_KEY` via standard Bearer
- Configured under both `zhipu` and `custom` keys in `config.json` (identical settings)

### Anyway (observability — optional)
- `init_anyway_from_env()` is called at startup. If `ANYWAY_API_KEY` is absent or blank,
  it silently disables itself — no errors, no crash.
- Use `workflow_span(name, attrs)` context manager to wrap phase runs with traces.

### Adding a new provider
Edit `config.json` (add under `providers`). Update `schema.py` only if adding a new typed
field to `ProvidersConfig`. The `agents.defaults.provider` key picks the default provider
when no model-level override is active.

---

## Slash commands (CLI)

| Command | Effect |
|---------|--------|
| `/status` | Show pipeline phase progress (which phases are done/running/failed) |
| `/resume` | Resume from last pipeline checkpoint (reads `pipeline_state.json`) |
| `/new` | Reset session — clears all hackathon runtime outputs |
| `/stop` | Cancel the currently running sub-agent task |
| `/exit` | Exit the CLI |
| `/help` | Show this list |

Phase commands are free-form natural language routed by `SkillRouter`. Each phase invocation
wraps the input in an `Envelope` and sends it to the `AgentLoop` with a per-phase timeout from
`model_profiles.json`. The `/stop` command routes directly through `_send_and_wait_traced()`.

---

## Pipeline phase artifacts

All outputs live in `workspace/hackathon/` (gitignored at runtime):

| Phase | Output | Required inputs |
|-------|--------|-----------------|
| research | `context.json`, `research_summary.md` | — |
| idea | `ideas.json` | `context.json` |
| selection | `selected_idea.json` | `ideas.json` |
| planning | `plan.md`, `tasks.json` | `selected_idea.json` |
| coding | `project/` | `tasks.json`, `plan.md` |
| testing | `test_results.json` | `project/` |
| doc | `submission/` | `test_results.json` |

Additional runtime files (also gitignored):
- `envelopes.jsonl` — append-only log of every phase invocation
- `metrics.jsonl` — per-run latency / token metrics from `MetricsLogger`
- `pipeline_state.json` — current phase status map

---

## Test suite

32 tests, all passing. Run with:

```bash
conda activate 0xclaw
python -m pytest tests/ -q
```

Key test files:

| File | Covers |
|------|--------|
| `tests/test_router.py` | `SkillRouter` — 30-sample accuracy test (≥90% required), CJK matching |
| `tests/test_state_store.py` | `PipelineStateStore` phase transitions |
| `tests/test_contracts.py` | `Envelope` serialisation |
| `tests/test_write_guard.py` | Phase-scoped write protection |
| `tests/test_model_profiles.py` | `ModelProfileResolver` |
| `tests/test_cancel_resume.py` | `/resume` logic, `/stop` wiring, `/new` reset wiring |
| `tests/test_anyway_observability.py` | Anyway tracing (no-op when key absent) |
| `tests/test_integration_pipeline.py` | Full pipeline state flow |

---

## DevAgent — the generated product

Location: `workspace/hackathon/project/` (gitignored)

```
devagent/
  cli.py              Click CLI — 5 commands: init, plan, build, status, history
  config.py           Env-based config loader (FLOCK_API_KEY, DEVAGENT_DIR)
  agents/
    planner.py        PlannerAgent — FLock LLM → structured JSON plan (Pydantic)
    coder.py          CoderAgent — generates each file with preview + y/n/e prompt
  llm/
    flock_client.py   Thin async wrapper around FLock OpenAI-compatible endpoint
  state/
    store.py          SQLite-backed StateStore — sessions, decisions, file writes
  memory/
    unibase_memory.py Unibase on-chain persistent memory (optional)
  identity/
    virtuals_identity.py Virtuals Protocol agent identity (optional)
```

Install and verify:

```bash
cd workspace/hackathon/project
pip install -e .
devagent --help
```

Dependencies: `click>=8.1`, `rich>=13.7`, `httpx>=0.27`, `openai>=1.66,<2.0`

---

## Rules and constraints

- **Never modify nanobot source** except `registry.py` and `schema.py` (our FLock additions)
- **Never commit `.env`** — gitignored, but double-check before any push
- **All workspace/hackathon/ outputs are gitignored** — they are runtime artefacts, not source
- **Sub-agent task strings must be self-contained** — sub-agents have no shared memory
- **Write guard violations surface as tool errors**, not Python exceptions — sub-agent continues
- **litellm requires openai>=1.66** — do not downgrade openai below 1.66 (breaks `openai.types.responses`)
- **Top-level `nanobot/` directory is gitignored and untracked** — do not add files there
