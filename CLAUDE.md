# 0xClaw — Claude Code Development Guide

## What this project is

0xClaw is an autonomous hackathon agent competing in the **UK AI Agent Hackathon EP4 x OpenClaw**
(DoraHacks #1985, deadline **7 March 2026 23:59**). The meta-story is the submission: an AI agent
that independently researched, planned, coded, and submitted a project to the very hackathon it
was entered in.

The agent receives a hackathon URL, then autonomously runs a 7-phase pipeline:
**Research → Ideation → Selection → Planning → Implementation → Testing → Documentation**

---

## Environment — always do this first

```bash
conda activate 0xclaw          # Python 3.11, all deps installed
cp .env.example .env           # first time only; fill in real API keys
./scripts/verify_setup.sh      # confirms nanobot import + workspace + API keys
./scripts/start.sh             # launch the agent
```

Required `.env` keys:
- `FLOCK_API_KEY` — from platform.flock.io (needs budget; 400 = budget exhausted)
- `VIRTUALS_API_KEY` — from game.virtuals.io (Bronze sponsor, can defer)
- `MEMBASE_ID` / `MEMBASE_ACCOUNT` / `MEMBASE_SECRET_KEY` — Unibase (can defer)

---

## Sponsors (from Luma — authoritative)

| Tier | Sponsors |
|------|---------|
| Gold | FLock.io, Sierra.ai, Z.ai, Cantor8 |
| Silver | The Compression Company, Animoca Brands, Lovable, Anyway, SuperCell, AfterQuery |
| Bronze | Virtual Protocol, Unibase |
| Partner | ManusAI (co-host, not sponsor — autonomous agent platform) |

---

## Two-layer architecture

```
Layer 1 — 0xClaw (the agent we maintain)
  nanobot AgentLoop + FLock.io as primary LLM
  workspace/ holds identity, skills, memory
  spawn() creates sub-agents for each pipeline phase

    hackathon-research  →  FLock
    idea                →  FLock
    planner             →  FLock
    coder × N           →  FLock
    tester              →  FLock
    doc                 →  FLock

Layer 2 — Generated project (what 0xClaw produces)
  workspace/hackathon/project/
  Uses FLock + Virtual Protocol + Unibase + other sponsors as relevant
  Submitted to DoraHacks as the hackathon entry
```

---

## Key files

| File | Purpose |
|------|---------|
| `0xclaw/main.py` | Entry point. Loads config, creates AgentLoop, runs CLI |
| `0xclaw/config/config.json` | Provider config (env vars substituted at load time) |
| `workspace/SOUL.md` | Agent identity and mission |
| `workspace/AGENTS.md` | 7-phase pipeline protocol + sponsor integration details |
| `workspace/HEARTBEAT.md` | Scheduled tasks (countdown, API health) |
| `workspace/memory/MEMORY.md` | Persistent agent facts (read every turn) |
| `workspace/skills/*/SKILL.md` | Spawn task templates for each pipeline phase |
| `0xclaw/tools/virtuals_tool.py` | Virtual Protocol GAME SDK — registers on-chain agent identity |
| `0xclaw/tools/unibase_tool.py` | Unibase membase — persistent on-chain agent memory |
| `0xclaw/framework/nanobot/providers/registry.py` | FLock provider spec (we added this) |
| `0xclaw/framework/nanobot/config/schema.py` | ProvidersConfig (we added flock field) |
| `scripts/start.sh` | Startup script (activates conda, validates integrated framework path) |
| `scripts/verify_setup.sh` | Pre-flight check for deps, workspace, API keys |

---

## Nanobot concepts

**Skills** — `SKILL.md` files in `workspace/skills/{name}/`. The agent reads these when asked to
perform a phase. Each skill contains a spawn task template string.

**spawn()** — creates a background asyncio sub-agent. Sub-agents have their own tool registry
(no spawn/message tools). Results are published back as `channel="system"` messages.
Sub-agents have no shared memory — the full task context must be in the task string.

**Workspace bootstrap files** — `SOUL.md`, `AGENTS.md`, `HEARTBEAT.md` are loaded into the
system prompt every turn by `ContextBuilder`. `MEMORY.md` is loaded separately.

**`sync_workspace_templates`** — called at startup; only creates missing workspace files.
Never overwrites our custom files.

---

## Provider details

### FLock.io (Gold sponsor — 0xClaw's primary LLM)
- Endpoint: `https://api.flock.io/v1`
- Auth: `x-litellm-api-key: $FLOCK_API_KEY` (custom header, not standard Bearer)
- Model: `qwen3-30b-a3b-instruct-2507`
- LiteLLM routes as `openai/qwen3-30b-a3b-instruct-2507` with api_base override
- **Common error**: HTTP 400 `budget_exceeded` → top up credits at platform.flock.io

---

## Current status (as of Day 2)

**Done:**
- Full project scaffolding, skills, config, workspace files
- FLock registered in nanobot providers
- conda env `0xclaw` set up with all deps
- Sponsor list confirmed from Luma (authoritative source)

**Blocked / not started:**
- Pipeline never run — `workspace/hackathon/` is empty (project + submission dirs exist but empty)
- No project idea selected — needs pipeline to run, then human confirmation

**Immediate next steps:**
1. Resolve FLock budget (currently HTTP 400 `budget_exceeded` despite credited account — check per-key limit at platform.flock.io)
2. Run agent → trigger `hackathon-research` → produces `context.json`
3. Run `idea` skill → produces `ideas.json` → **human selects the idea**
4. Run full pipeline from planner onward

---

## Rules and constraints

- **Never modify nanobot source** except `registry.py` and `schema.py` (FLock addition)
- **Never commit `.env`** — it's gitignored, but double-check before any push
- **Workspace hackathon outputs are gitignored** — `context.json`, `ideas.json`, `plan.md`,
  `tasks.json`, `project/`, `submission/` are all runtime artefacts
- All pipeline state lives in `workspace/hackathon/` as JSON or Markdown files
- Sub-agent task strings must be self-contained — no reliance on shared memory
