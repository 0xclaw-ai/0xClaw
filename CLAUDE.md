# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

0xClaw is a general-purpose **autonomous hackathon agent** platform. Given a hackathon URL,
it autonomously runs a 7-phase pipeline on behalf of a human participant:

**Research → Ideation → Selection → Planning → Implementation → Testing → Documentation**

A single user can run 0xClaw against multiple hackathons in sequence. Each run produces
an independent set of gitignored artefacts under `workspace/hackathon/`.

The generated project (Layer 2) is created fresh per hackathon and lives at
`workspace/hackathon/project/` (gitignored at runtime).

---

## Environment — always do this first

```bash
conda activate 0xclaw          # Python 3.11, all deps installed
cp .env.example .env           # first time only; fill in real API keys
./scripts/verify_setup.sh      # confirms runtime import + workspace + API keys
0xclaw                         # canonical runtime entrypoint
0xclaw --logs                  # launch with loguru output visible
```

`./scripts/start.sh` is an optional wrapper that activates conda and loads `.env` before running `0xclaw`.
`./scripts/verify_setup.sh` is a preflight checker, not the runtime entrypoint.

### Required `.env` keys

| Key | Purpose | Notes |
|-----|---------|-------|
| `ZAI_API_KEY` | Primary LLM via Z.ai (international) | `zhipu` provider in config; model `glm-4.5` |
| `FLOCK_API_KEY` | Secondary LLM via FLock.io | HTTP 400 = budget exhausted |
| `BRAVE_API_KEY` | Web search | Optional |

---

## Two-layer architecture

```
Layer 1 — 0xClaw (the agent we maintain)
  0xclaw/main.py            CLI entry point, interactive REPL, slash commands
  0xclaw/orchestration/     Phase routing, state machine, write guards, model profiles
  0xclaw/config/            config.json (providers), model_profiles.json (per-phase settings)
  0xclaw/runtime/           Integrated agent runtime engine (DO NOT modify except providers/registry.py + config/schema.py)
  launcher/                 CLI entry point wrapper (resolves 0x hex-literal import issue)
  workspace/                Agent identity, skills, pipeline state

Layer 2 — Generated project (per-hackathon, gitignored)
  workspace/hackathon/project/    The built project (gitignored)
  workspace/hackathon/submission/ README, pitch, and submission docs (gitignored)
```

---

## Key files

| File | Purpose |
|------|---------|
| `0xclaw/main.py` | Entry point: CLI loop, AgentLoop wiring, slash commands, reset/resume/stop |
| `0xclaw/config/config.json` | Provider config (edit to set your LLM provider + API key). Env vars substituted at load time |
| `0xclaw/config/model_profiles.json` | Per-phase model + timeout overrides |
| `0xclaw/orchestration/state.py` | `PipelineStateStore`, `OrchestratorStateMachine` — phase deps and artifact requirements |
| `0xclaw/orchestration/router.py` | `SkillRouter` — keyword + LLM fallback routing. Supports English and Chinese triggers |
| `0xclaw/orchestration/contracts.py` | `Envelope`, `ArtifactMeta` dataclasses for CLI → AgentLoop messages |
| `0xclaw/orchestration/model_profiles.py` | `ModelProfileResolver`, `MetricsLogger` |
| `0xclaw/orchestration/session_control.py` | `SessionControl` — `/resume` logic, `PHASE_TO_COMMAND` map |
| `0xclaw/orchestration/write_guard.py` | `install_phase_write_guards()` — phase-scoped filesystem write protection |
| `0xclaw/runtime/providers/registry.py` | Provider spec registry (safe to modify — add new providers here) |
| `0xclaw/runtime/config/schema.py` | `ProvidersConfig` Pydantic schema (safe to modify — add provider fields here) |
| `workspace/SOUL.md` | Agent identity and mission (loaded every turn) |
| `workspace/AGENTS.md` | 7-phase pipeline protocol (loaded every turn) |
| `workspace/skills/*/SKILL.md` | Spawn task templates — one per pipeline phase |

---

## Orchestration layer

The `0xclaw/orchestration/` package sits between `main.py` and the agent runtime.

**`SkillRouter`** maps free-form user input to a pipeline phase via keyword rules, with an
LLM classifier as fallback. `KEYWORD_MAP` in `router.py` covers English and Chinese triggers.
Important: Chinese keywords use plain substring matching (not `\b` word boundaries, which
break for CJK characters).

**`OrchestratorStateMachine`** validates phase entry — checks that all dependency phases are
`done` and required artifact files exist — then enforces per-phase write permissions via
`PHASE_ALLOWED_WRITE_DIRS`.

**`PipelineStateStore`** is a file-backed store at `workspace/hackathon/pipeline_state.json`.
Phase lifecycle: `pending → running → done | failed | cancelled`.

**Write guards** — `install_phase_write_guards()` monkey-patches the runtime's `write_file` /
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

## Runtime internals

> The agent runtime lives in `0xclaw/runtime/`. It is the execution engine for all agent
> behaviour — do not modify it except `runtime/providers/registry.py` and `runtime/config/schema.py`
> (our FLock additions). All imports use `from runtime.xxx import yyy`.

**Skills** — `SKILL.md` files in `workspace/skills/{name}/`. Frontmatter key is `openclaw`.
Auto-loaded when `always: true` is set; loaded on-demand via `read_file` otherwise.

**`spawn()`** — creates a background asyncio sub-agent with its own isolated tool registry
(no `spawn` or `message` tools). Results arrive as `channel="system"` messages on the main
agent's bus. Sub-agents have no shared memory — all context must be embedded in the task string.

**Workspace bootstrap** — `SOUL.md`, `AGENTS.md`, and `HEARTBEAT.md` are loaded every turn.
`MEMORY.md` is loaded separately for long-term state.

**`sync_workspace_templates`** — called at startup. Creates missing workspace files from
templates in `runtime/templates/`; never overwrites files that already exist.

**File paths in tasks** — the runtime resolves relative paths as `workspace_dir / path`.
Always write `hackathon/context.json` (not `workspace/hackathon/context.json`). Same rule
applies to `exec()` working directory.

---

## Provider / model details

### Z.ai (primary LLM — `provider: "zhipu"`)
- Endpoint: `https://api.z.ai/api/paas/v4` (international; NOT bigmodel.cn)
- Auth: `ZAI_API_KEY` via standard Bearer token
- Default model: `glm-4.5` (`config.json`); all 7 phases use `glm-4.5` (`model_profiles.json`)
- OpenAI-compatible API; LiteLLM routes as `zai/<model>` automatically
- Configured under both `zhipu` and `custom` keys in `config.json` (identical settings)

### FLock.io (secondary LLM — `provider: "flock"`)
- Endpoint: `https://api.flock.io/v1`
- Auth: custom header `x-litellm-api-key: $FLOCK_API_KEY` (not standard Bearer)
- Routed through LiteLLM as `openai/<model>` with `api_base` override
- HTTP 400 = budget exhausted

### Anyway (observability — optional)
  it silently disables itself — no errors, no crash.
- Use `workflow_span(name, attrs)` context manager to wrap phase runs with traces.

### Adding a new provider
Edit `config.json` (add under `providers`). Update `runtime/config/schema.py` only if adding
a new typed field to `ProvidersConfig`. The `agents.defaults.provider` key picks the default
provider when no model-level override is active.

---

## Slash commands (CLI)

| Command | Effect |
|---------|--------|
| `/status` | Show pipeline phase progress (which phases are done/running/failed) |
| `/resume` | Resume from last pipeline checkpoint (reads `pipeline_state.json`) |
| `/redo <phase>` | Reset one phase (and downstream phases) and run it again |
| `/new` | Reset session — clears all hackathon runtime outputs |
| `/stop` | Cancel the currently running sub-agent task |
| `/exit` | Exit the CLI |
| `/help` | Show this list |
| `?` | Alias for `/help` |
| `!<cmd>` | Run shell command passthrough in CLI |

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

## Rules and constraints

- **Only modify `runtime/providers/registry.py` and `runtime/config/schema.py`** — all other files in `0xclaw/runtime/` are the engine; leave them alone
- **Never commit `.env`** — gitignored, but double-check before any push
- **All workspace/hackathon/ outputs are gitignored** — they are runtime artefacts, not source
- **Sub-agent task strings must be self-contained** — sub-agents have no shared memory
- **Write guard violations surface as tool errors**, not Python exceptions — sub-agent continues
- **litellm requires openai>=1.66** — do not downgrade openai below 1.66 (breaks `openai.types.responses`)
- **`launcher/` is the CLI entry point wrapper** — `pyproject.toml` points `0xclaw` command here; do not rename it
