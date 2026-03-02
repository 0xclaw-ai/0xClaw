# 0xClaw

Autonomous hackathon agent. Given a hackathon URL, it researches requirements, generates ideas,
writes and tests code, and produces submission materials — entirely on its own.

Built on [nanobot](https://github.com/HKUDS/nanobot) for the
[UK AI Agent Hackathon EP4 × OpenClaw](https://dorahacks.io/hackathon/1985) (March 2026).

---

## Requirements

- Python 3.11 via [conda](https://docs.conda.io)
- API key: FLock.io (primary LLM)

## Setup

```bash
conda create -n 0xclaw python=3.11 -y
conda activate 0xclaw
pip install -e nanobot/
pip install -e .

cp .env.example .env
# Edit .env — fill in FLOCK_API_KEY at minimum
```

## Run

```bash
conda activate 0xclaw
./scripts/start.sh
```

Verify everything is configured correctly first:

```bash
./scripts/verify_setup.sh
```

## Structure

```
0xclaw/          Entry point and config
workspace/       Agent identity, skills, and pipeline state
  skills/        hackathon-research, idea, planner, coder, tester, doc
  hackathon/     Runtime outputs (gitignored)
nanobot/         Framework (nanobot-ai, Python OpenClaw implementation)
scripts/         start.sh, verify_setup.sh
```

## Sponsors

| Sponsor | Tier | Role in 0xClaw |
|---------|------|----------------|
| [FLock.io](https://flock.io) | Gold | Primary LLM for orchestration |
| [Sierra.ai](https://sierra.ai) | Gold | — |
| [Z.ai](https://z.ai) | Gold | — |
| [Cantor8](https://cantor8.ai) | Gold | — |
| The Compression Company | Silver | — |
| Animoca Brands | Silver | — |
| Lovable | Silver | — |
| SuperCell | Silver | — |
| [Virtual Protocol](https://virtuals.io) | Bronze | On-chain agent identity |
| [Unibase](https://unibase.io) | Bronze | Persistent on-chain memory |
