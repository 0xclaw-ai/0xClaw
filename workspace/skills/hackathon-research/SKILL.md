---
name: hackathon-research
description: Research hackathon requirements, APIs, prizes, and judging criteria
metadata: {"openclaw": {"always": false}}
---

# Hackathon Research Skill

## Purpose
Compile a complete intelligence report on the hackathon using known URLs and workspace context.
Do NOT use web_search (may be unavailable). Use web_fetch on the specific URLs below.

## When to Use
When orchestrator needs to understand the hackathon before ideation begins.

## Spawn Task Template

```
[HACKATHON RESEARCH AGENT]
Goal: Produce a complete intelligence report and write context.json.

Do not ask clarifying questions. Proceed autonomously through all steps.

Step 1 — Load existing workspace context (do this first):
  read_file("AGENTS.md")
  read_file("memory/MEMORY.md")
  read_file("SOUL.md")

Step 2 — Fetch the hackathon pages using web_fetch:
  web_fetch("https://dorahacks.io/hackathon/1985/detail")
  web_fetch("https://luma.com/54b06cos")

Step 3 — Research key platform/API docs using web_fetch:
  web_fetch("https://docs.flock.io/flock-products/api-platform/getting-started")

Step 4 — Synthesize everything into context.json.
  Use this exact schema:

{
  "hackathon": {
    "name": "UK AI Agent Hackathon EP4 x OpenClaw",
    "url": "https://dorahacks.io/hackathon/1985",
    "submission_deadline": "2026-03-07T23:59:00",
    "demo_day": "2026-03-07",
    "format": "hybrid",
    "tracks": [
      {"id": "02", "name": "Build Apps for Humans", "description": "I'm an Agent — build production-ready AI agents that solve real problems"}
    ],
    "judging_criteria": [
      {"criterion": "Technical Innovation", "weight": "high", "notes": "Novel use of AI/agent tech"},
      {"criterion": "Integration Depth", "weight": "high", "notes": "Depth of platform/API usage"},
      {"criterion": "Demo Impact", "weight": "high", "notes": "Live demo wow factor"},
      {"criterion": "Market Fit", "weight": "medium", "notes": "Real problem, real users"},
      {"criterion": "Code Quality", "weight": "medium", "notes": "Production-ready, not a prototype"}
    ],
    "submission_requirements": [
      "Working demo (video or live)",
      "Public GitHub repo",
      "DoraHacks BUIDL submission with description",
      "README with setup instructions"
    ]
  },
  "integrations": [
    {
      "name": "FLock.io",
      "tier": "gold",
      "api_available": true,
      "api_base_url": "https://api.flock.io/v1",
      "auth_method": "custom_header",
      "auth_header": "x-litellm-api-key",
      "available_models": ["qwen3-30b-a3b-instruct-2507"],
      "integration_complexity": 2,
      "key_capability": "Decentralized AI model hub, OpenAI-compatible, cost-effective inference",
      "sdk_install": null,
      "example_use_case": "Primary LLM for all agent reasoning and code generation"
    }
  ],
  "strategic_notes": "The meta-story is our strongest differentiator: 0xClaw is an AI agent that autonomously competed in its own hackathon. Focus on depth of FLock integration and a compelling live demo.",
  "recommended_integration_priority": ["FLock.io"],
  "quick_wins": [
    "FLock as drop-in OpenAI replacement — trivial to integrate"
  ]
}

Step 5 — Write output files:
  write_file("hackathon/context.json", <the JSON above, filled with real data from fetched pages>)
  write_file("hackathon/research_summary.md", <human-readable 1-page summary>)

IMPORTANT: Write the files even if web_fetch partially fails. Use workspace context to fill gaps.

STOP HERE. Do NOT proceed to idea generation, planning, or any other phase.
Your task is complete once context.json and research_summary.md are written.
```

## Output Files
- `hackathon/context.json` — structured data for downstream agents
- `hackathon/research_summary.md` — human-readable summary
