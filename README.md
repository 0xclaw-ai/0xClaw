<div align="center">
  <img src="0xclaw_logo.png" alt="0xClaw" width="160" />
</div>

```
  ██████╗  ██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗
 ██╔═████╗ ╚██╗██╔╝██╔════╝██║     ██╔══██╗██║    ██║
 ██║██╔██║  ╚███╔╝ ██║     ██║     ███████║██║ █╗ ██║
 ████╔╝██║  ██╔██╗ ██║     ██║     ██╔══██║██║███╗██║
 ╚██████╔╝ ██╔╝ ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝
  ╚═════╝  ╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
```

<div align="center">

Autonomous hackathon agent — researches, plans, codes, tests, and submits. Entirely on its own.

Built on [nanobot](https://github.com/HKUDS/nanobot) · [UK AI Agent Hackathon EP4 × OpenClaw](https://dorahacks.io/hackathon/1985)

</div>

---

## Setup

```bash
conda create -n 0xclaw python=3.11 -y && conda activate 0xclaw
pip install -e .
cp .env.example .env   # fill in FLOCK_API_KEY at minimum
```

## Start

```bash
conda activate 0xclaw
0xclaw
```

---

## Pipeline

| # | Phase | Output |
|---|-------|--------|
| 1 | research | `hackathon/context.json` |
| 2 | idea | `hackathon/ideas.json` |
| 3 | selection | `hackathon/selected_idea.json` |
| 4 | planning | `hackathon/plan.md` + `tasks.json` |
| 5 | coding | `hackathon/project/` |
| 6 | testing | `hackathon/test_results.json` |
| 7 | doc | `hackathon/submission/` |

Trigger any phase with natural language: `research the hackathon`, `generate ideas`, `start coding`, etc.

## Commands

| Command | |
|---------|--|
| `/status` | Pipeline progress + session token usage |
| `/resume` | Resume from last checkpoint |
| `/redo <phase>` | Reset phase and all downstream, then re-run |
| `/new` | Clear all outputs, fresh start |
| `/stop` | Cancel running task |
| `/help` | Show all commands |

---

## LLM

All inference via [FLock.io](https://platform.flock.io).

| Phase | Model |
|-------|-------|
| research · idea · selection · doc | `minimax-m2.1` |
| planning · coding · testing | `minimax-m2.5` |

## Observability

Set `ANYWAY_API_KEY` to stream traces to [Anyway](https://anyway.mintlify.app).
Token usage is shown live in the CLI after every response.

---

## Sponsors

**Gold** — FLock.io · Sierra.ai · Z.ai · Cantor8
**Silver** — The Compression Company · Animoca Brands · Lovable · Anyway · SuperCell · AfterQuery
**Bronze** — [Virtuals Protocol](https://virtuals.io) · [Unibase](https://unibase.io)
