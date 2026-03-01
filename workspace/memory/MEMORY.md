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

## Sponsor APIs
- FLock.io (Gold): https://api.flock.io/v1 | header: x-litellm-api-key | model: qwen3-30b-a3b-instruct-2507
- Venice.ai (Silver): https://api.venice.ai/api/v1 | Bearer token (vapi_...)
  - General model: llama-3.3-70b | Coding: qwen3-coder-480b-a35b-instruct-turbo | Fast agents: zai-org-glm-4.7-flash
  - Key feature: venice_parameters.enable_web_search="auto" gives built-in web search, no extra API key
  - Privacy: no prompt/response logging on open-source model tier
- Virtuals Protocol (Bronze): pip install virtuals_sdk | GAME SDK
- Unibase (Bronze): pip install git+https://github.com/unibaseio/aip-agent | BNB testnet

## Project Status
- Day 1 (Mar 1): Project structure initialized. Pipeline not yet started.
- Selected Track: Challenge 02

## Key Decisions
- Use nanobot as runtime; position as "OpenClaw ecosystem (Python)"
- Primary LLM: FLock API (sponsor tech + cost-effective)
- Fallback LLM: Venice.ai (privacy angle for code gen)
- Orchestration: spawn() tool for all sub-agent tasks
- All state in workspace/hackathon/ as JSON/Markdown files
