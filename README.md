<div align="center">

<img src="0xclaw_logo.png" alt="0xClaw" width="150" />

<!-- <pre> -->
  ██████╗  ██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗
 ██╔═████╗ ╚██╗██╔╝██╔════╝██║     ██╔══██╗██║    ██║
 ██║██╔██║  ╚███╔╝ ██║     ██║     ███████║██║ █╗ ██║
 ████╔╝██║  ██╔██╗ ██║     ██║     ██╔══██║██║███╗██║
 ╚██████╔╝ ██╔╝ ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝
  ╚═════╝  ╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
<!-- </pre> -->

**An AI agent that autonomously researches, plans, codes, tests, and submits a hackathon project.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-32%20passed-22c55e?style=flat-square)
![Inference](https://img.shields.io/badge/Inference-FLock.io-7c3aed?style=flat-square)
![Tracing](https://img.shields.io/badge/Tracing-Anyway-0ea5e9?style=flat-square)

</div>

---

## Setup

```bash
conda create -n 0xclaw python=3.11 -y && conda activate 0xclaw
pip install -e .
cp .env.example .env          # fill in FLOCK_API_KEY at minimum
./scripts/verify_setup.sh     # confirm everything is working
```

## Launch

```bash
conda activate 0xclaw
0xclaw           # interactive CLI
0xclaw --logs    # with debug output
```

---

## Pipeline

The agent runs a 7-phase pipeline to produce a complete hackathon submission.
Trigger any phase in natural language — routing is automatic.

| # | Phase | Output |
|:-:|-------|--------|
| 1 | **research** | `hackathon/context.json` |
| 2 | **idea** | `hackathon/ideas.json` |
| 3 | **selection** | `hackathon/selected_idea.json` |
| 4 | **planning** | `hackathon/plan.md` · `tasks.json` |
| 5 | **coding** | `hackathon/project/` |
| 6 | **testing** | `hackathon/test_results.json` |
| 7 | **doc** | `hackathon/submission/` |

```
research the hackathon requirements
generate project ideas
plan the architecture
implement the project
run tests
write the documentation
```

## Commands

| Command | |
|---------|--|
| `/status` | Pipeline progress + session token usage |
| `/resume` | Resume from last checkpoint |
| `/redo <phase>` | Reset phase and all downstream, then re-run |
| `/new` | Clear all outputs, fresh start |
| `/stop` | Cancel running task |
| `/help` | Show all commands |

Long-running phases hand off to the background after the first reply — you can keep chatting while work continues.

---

## Models

All inference via [FLock.io](https://flock.io).

| Phases | Model | Context |
|--------|-------|---------|
| research · idea · selection · doc | `minimax-m2.1` | 196k |
| planning · coding · testing | `minimax-m2.5` | 205k |

## Observability

Set `ANYWAY_API_KEY` to stream traces to [Anyway](https://anyway.mintlify.app). Token usage is shown live after every agent response.

---

## Sponsors

<div align="center">

| | |
|:--|:--|
| **Gold** | FLock.io &nbsp;·&nbsp; Z.AI &nbsp;·&nbsp; Sierra.ai &nbsp;·&nbsp; Cantor8 &nbsp;·&nbsp; BGA |
| **Silver** | Lovable &nbsp;·&nbsp; SuperCell &nbsp;·&nbsp; Animoca Brands &nbsp;·&nbsp; Anyway &nbsp;·&nbsp; The Compression Company |
| **Bronze** | [Virtuals Protocol](https://virtuals.io) &nbsp;·&nbsp; [Unibase](https://unibase.io) |

</div>

---

<div align="center">

Built for [UK AI Agent Hackathon EP4](https://dorahacks.io/hackathon/1985) in collaboration with [OpenClaw](https://dorahacks.io/hackathon/1985). Runtime powered by [nanobot](https://github.com/HKUDS/nanobot).

</div>
