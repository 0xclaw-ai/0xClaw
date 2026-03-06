# 0xClaw Project Memory

## Hackathon Facts
- Event: UK AI Agent Hackathon EP4 x OpenClaw (DoraHacks #1985)
- Dates: March 1-7, 2026 | Deadline: March 7, 23:59
- Venue: Imperial College London (Hybrid)
- Prize: $13,000 USD total pool
- Track: Challenge 02 "Build Apps for Humans" (I'm an Agent)
- Organizers: Imperial Blockchain Society + Imperial AI Group

## Framework
- Runtime: nanobot-ai (Python OpenClaw implementation) v0.1.4.post3
- Conda env: 0xclaw (Python 3.11)
- Entry point: 0xclaw/main.py | Config: 0xclaw/config/config.json

## Sponsors (from Luma — authoritative source)
- Gold: FLock.io, Sierra.ai, Z.ai, Cantor8
- Silver: The Compression Company, Animoca Brands, Lovable, Anyway, SuperCell, AfterQuery
- Bronze: Virtual Protocol, Unibase
- Co-hosts/Partners (not sponsors): ManusAI, CogX, BGA, BaseUK, SuperteamUK, Fabrics Ventures

## Sponsor APIs
- FLock.io (Gold): https://api.flock.io/v1 | header: x-litellm-api-key | model: qwen3-30b-a3b-instruct-2507
- Virtual Protocol (Bronze): pip install virtuals_sdk | GAME SDK
- Unibase (Bronze): pip install git+https://github.com/unibaseio/aip-agent | BNB testnet

## Project Status
- Day 1 (Mar 1): Project structure initialized. Pipeline not yet started.
- Day 6 (Mar 6): Phase 7 (Documentation) completed; Research phase (Phase 1) completed
- Selected Track: Challenge 02
- **DevAgent** - Terminal AI coding assistant that asks before it acts

## Project Details
- **Name:** DevAgent
- **Tagline:** "An autonomous coding agent you talk to in the terminal — it plans, scaffolds, and builds projects with you, asking before it acts."
- **Architecture:** CLI tool (Click + Rich) using FLock.io LLM, Unibase for on-chain memory, Virtuals Protocol for agent identity
- **Submission Materials Generated (Mar 6):**
  - `hackathon/transmission/README.md` - Full project documentation
  - `hackathon/transmission/SUBMISSION.md` - DoraHacks submission with sponsor bounty justifications
  - `hackathon/transmission/PITCH.md` - 2-minute elevator pitch
  - Synced `hackathon/project/README.md` with polished documentation
- **Research Outputs Generated (Mar 6):**
  - `hackathon/context.json` - Complete intelligence report with sponsor API details
  - `hackathon/research_summary.md` - Human-readable 1-page summary

## Key Decisions
- Use nanobot as runtime; position as "OpenClaw ecosystem (Python)"
- Primary LLM: FLock API (Gold sponsor + cost-effective)
- Orchestration: spawn() tool for all sub-agent tasks
- All state in workspace/hackathon/ as JSON/Markdown files
- Consent-first UX as key differentiator (asks before making irreversible decisions)

## Pipeline Status
- Phase 1 (Research): Complete ✓ - context.json and research_summary.md created
- Phase 2 (Ideation): Pending

## Strategic Insights
- **Meta-story is strongest differentiator**: 0xClaw is an AI agent that autonomously competed in its own hackathon
- **Sponsor Priority**: FLock.io (Gold) → Virtual Protocol → Unibase
- **Quick Wins**: FLock is drop-in OpenAI replacement; Unibase MultiMemory ~10 lines; Virtual Protocol creates on-chain narrative
- **Judging Criteria Focus**: Technical Innovation + Sponsor Integration (both high weight)