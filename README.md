# 0xClaw

Autonomous hackathon agent. Given a hackathon URL, it researches requirements, generates ideas,
writes and tests code, and produces submission materials — entirely on its own.

Built on [nanobot](https://github.com/HKUDS/nanobot) for the
[UK AI Agent Hackathon EP4 × OpenClaw](https://dorahacks.io/hackathon/1985) (March 2026).

---

## Setup

```bash
conda create -n 0xclaw python=3.11 -y
conda activate 0xclaw
pip install -e .

cp .env.example .env
# Fill in at minimum: FLOCK_API_KEY
```

Verify:

```bash
./scripts/verify_setup.sh
```

## Start

```bash
conda activate 0xclaw
./scripts/start.sh          # normal mode
./scripts/start.sh --logs   # with debug output
```

---

## Usage

0xClaw runs as an interactive CLI. Describe what you want in natural language and the agent
routes it to the correct pipeline phase automatically.

### Pipeline

The agent runs a 7-phase pipeline to produce a complete hackathon submission:

| # | Phase | Output |
|---|-------|--------|
| 1 | **research** | `hackathon/context.json` — hackathon requirements and sponsor analysis |
| 2 | **idea** | `hackathon/ideas.json` — ranked project proposals |
| 3 | **selection** | `hackathon/selected_idea.json` — chosen project (human-confirmed) |
| 4 | **planning** | `hackathon/plan.md` + `tasks.json` — architecture and task breakdown |
| 5 | **coding** | `hackathon/project/` — full implementation |
| 6 | **testing** | `hackathon/test_results.json` — test run summary |
| 7 | **doc** | `hackathon/submission/` — README, pitch, submission materials |

Phases run in order. Each phase depends on the previous one's output.

### Natural language commands

Describe what you want — 0xClaw routes to the right phase automatically:

```
research the hackathon requirements
generate project ideas
plan the architecture
implement the project
run tests
write the documentation
```

Chinese is supported:

```
研究黑客松要求
生成创意
实现项目
```

### Slash commands

| Command | What it does |
|---------|--------------|
| `/status` | Show pipeline progress and session token usage |
| `/resume` | Resume from the last completed checkpoint |
| `/redo <phase>` | Reset a phase (and all downstream) and re-run it |
| `/new` | Clear all outputs and start a fresh run |
| `/stop` | Cancel the currently running task |
| `/help` | Show all commands |
| `/exit` | Quit |

**`/redo` accepts phase name or number:**

```
/redo planning        reset planning + coding + testing + doc, then re-plan
/redo 5               same as /redo coding
/redo doc             regenerate submission materials only
```

### Background phases

Long-running phases (coding, planning) hand off to the background automatically after the agent
sends its first reply. You can keep chatting while the work continues. When the phase completes:

```
✓  Phase coding complete — type /resume to continue.
```

---

## Development

```bash
# Run tests
conda run -n 0xclaw python -m pytest tests/ -q

# Run a single phase headlessly (for testing/scripting)
conda run -n 0xclaw python scripts/run_phase.py "run research phase"
conda run -n 0xclaw python scripts/run_phase.py --resume
```

## Project structure

```
0xclaw/               Entry point, config, orchestration, tools, observability
  config/             model_profiles.json — per-phase LLM settings
  framework/          Vendored nanobot runtime (do not modify except registry.py)
  orchestration/      Router, state machine, write guards, session control
workspace/            Agent identity, skills, pipeline state (gitignored outputs)
  skills/             research, idea, planner, coder, tester, doc
  hackathon/          Runtime pipeline outputs (gitignored)
scripts/              start.sh, verify_setup.sh, run_phase.py
tests/                Test suite (32 tests)
```

## LLM models

| Phase | Model | Max tokens |
|-------|-------|------------|
| research, idea, selection, doc | `minimax-m2.1` (196k ctx, fast) | 4k – 16k |
| planning, coding, testing | `minimax-m2.5` (205k ctx, reasoning) | 16k – 64k |

All inference via FLock.io. Fallback configured per phase in `0xclaw/config/model_profiles.json`.

## Observability

Tracing is sent to [Anyway](https://anyway.mintlify.app) when `ANYWAY_API_KEY` is set.
Token usage is displayed live in the CLI after every agent response.

## Sponsors

Gold: FLock.io · Sierra.ai · Z.ai · Cantor8
Silver: The Compression Company · Animoca Brands · Lovable · Anyway · SuperCell · AfterQuery
Bronze: [Virtual Protocol](https://virtuals.io) · [Unibase](https://unibase.io)
