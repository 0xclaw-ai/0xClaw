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
- Selected Track: Challenge 02

## Key Decisions
- Use nanobot as runtime; position as "OpenClaw ecosystem (Python)"
- Primary LLM: FLock API (Gold sponsor + cost-effective)
- Orchestration: spawn() tool for all sub-agent tasks
- All state in workspace/hackathon/ as JSON/Markdown files
