<div align="center">

<img src="0xclaw_logo.png" alt="0xClaw" width="130" />

<br />

<img src="banner.svg" alt="0xClaw" />

<br />

**Give it a hackathon URL. It researches, codes, and submits.**

<br />

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-32%20passed-22c55e?style=flat-square)
![FLock.io](https://img.shields.io/badge/Primary%20LLM-FLock.io-7c3aed?style=flat-square)
![Z.AI](https://img.shields.io/badge/Fallback%20LLM-Z.AI-5b6cf9?style=flat-square)
![Tracing](https://img.shields.io/badge/Tracing-Anyway-0ea5e9?style=flat-square)

</div>

---

## Setup

```bash
conda create -n 0xclaw python=3.11 -y && conda activate 0xclaw
pip install -e .
cp .env.example .env          # fill in FLOCK_API_KEY at minimum
./scripts/verify_setup.sh
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
Trigger any phase with natural language — routing is automatic.

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

Primary inference via **FLock.io** · Fallback via **Z.AI**

| Phases | Model | Context |
|--------|-------|---------|
| research · idea · selection · doc | `minimax-m2.1` | 196k |
| planning · coding · testing | `minimax-m2.5` | 205k |

## Observability

Set `ANYWAY_API_KEY` to stream traces to Anyway. Token usage is shown live after every agent response.

---

## Sponsors

<div align="center">

| | |
|:--|:--|
| **Gold** | FLock.io · Z.AI · Sierra.ai · Cantor8 · BGA |
| **Silver** | Lovable · SuperCell · Animoca Brands · Anyway · The Compression Company |
| **Bronze** | Virtuals Protocol · Unibase |

</div>

---

<div align="center">
<sub>Built for <a href="https://dorahacks.io/hackathon/1985">UK AI Agent Hackathon EP4</a> in collaboration with OpenClaw · Runtime powered by <a href="https://github.com/HKUDS/nanobot">nanobot</a></sub>
</div>
