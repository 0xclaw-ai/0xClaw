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
- `VENICE_API_KEY` — from venice.ai/settings/api (format: `vapi_...`)
- `VIRTUALS_API_KEY` — from game.virtuals.io (Bronze sponsor, can defer)
- `MEMBASE_ID` / `MEMBASE_ACCOUNT` / `MEMBASE_SECRET_KEY` — Unibase (can defer)

---

## Two-layer architecture

```
Layer 1 — 0xClaw (the agent we maintain)
  nanobot AgentLoop + FLock.io as primary LLM
  workspace/ holds identity, skills, memory
  spawn() creates sub-agents for each pipeline phase

    hackathon-research  →  Venice (enable_web_search="auto")
    idea                →  FLock
    planner             →  FLock
    coder × N           →  Venice (qwen3-coder-480b-a35b-instruct-turbo)
    tester              →  FLock
    doc                 →  FLock

Layer 2 — Generated project (what 0xClaw produces)
  workspace/hackathon/project/
  Uses FLock + Venice + Virtuals + Unibase
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
| `0xclaw/tools/` | Custom tools — **Virtuals + Unibase not yet written** |
| `nanobot/nanobot/providers/registry.py` | FLock + Venice provider specs (we added these) |
| `nanobot/nanobot/config/schema.py` | ProvidersConfig (we added flock + venice fields) |
| `scripts/start.sh` | Startup script (activates conda, installs nanobot if needed) |
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

**`sync_workspace_templates`** — called at startup; only creates workspace files that are
*missing*. Never overwrites our custom files.

---

## Provider details

### FLock.io (Gold sponsor — 0xClaw's primary LLM)
- Endpoint: `https://api.flock.io/v1`
- Auth: `x-litellm-api-key: $FLOCK_API_KEY` (custom header, not standard Bearer)
- Model: `qwen3-30b-a3b-instruct-2507`
- LiteLLM routes as `openai/qwen3-30b-a3b-instruct-2507` with api_base override
- **Common error**: HTTP 400 `budget_exceeded` → top up credits at platform.flock.io

### Venice.ai (Silver sponsor — specialist sub-agents)
- Endpoint: `https://api.venice.ai/api/v1`
- Auth: `Authorization: Bearer vapi_...`
- Private models (no logging): `llama-3.3-70b`, `zai-org-glm-4.7-flash`, `qwen3-coder-480b-a35b-instruct-turbo`
- Web search (no extra API key): `extra_body={"venice_parameters": {"enable_web_search": "auto"}}`
- All private models support function calling — can be used for agent tasks
- **Common error**: HTTP 401 → wrong or missing API key

---

## Current status (as of Day 1 complete)

**Done:**
- Full project scaffolding, skills, config, workspace files
- FLock + Venice registered in nanobot providers
- conda env `0xclaw` set up with all deps

**Blocked / not started:**
- Pipeline never run — `workspace/hackathon/` is empty (project + submission dirs exist but empty)
- `0xclaw/tools/` is empty — Virtuals tool and Unibase tool not written yet
- No project idea selected — needs pipeline to run, then human confirmation

**Immediate next steps:**
1. Top up FLock credits + get real Venice API key
2. Run agent → trigger `hackathon-research` → produces `context.json`
3. Run `idea` skill → produces `ideas.json` → **human selects the idea**
4. Write `0xclaw/tools/virtuals_tool.py` + `unibase_tool.py`
5. Run full pipeline from planner onward

---

## Rules and constraints

- **Never modify nanobot source** except `registry.py` and `schema.py` (FLock + Venice additions)
- **Never commit `.env`** — it's gitignored, but double-check before any push
- **Workspace hackathon outputs are gitignored** — `context.json`, `ideas.json`, `plan.md`,
  `tasks.json`, `project/`, `submission/` are all runtime artefacts
- All pipeline state lives in `workspace/hackathon/` as JSON or Markdown files
- Sub-agent task strings must be self-contained — no reliance on shared memory
