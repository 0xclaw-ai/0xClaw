---
name: hackathon-research
description: Research hackathon requirements, sponsors, prizes, and judging criteria from a URL
metadata: {"nanobot": {"always": false}}
---

# Hackathon Research Skill

## Purpose
Analyze a hackathon page and extract actionable intelligence: sponsors, APIs, judging
criteria, and submission requirements — all structured for downstream agents.

## When to Use
When orchestrator needs to understand a hackathon before ideation begins.

## Spawn Task Template

Replace `{HACKATHON_URL}` with the actual URL before spawning.

```
[HACKATHON RESEARCH AGENT]
Goal: Produce a complete intelligence report for the hackathon.

Target URL: {HACKATHON_URL}

Steps:

1. Fetch the hackathon page:
   web_fetch("{HACKATHON_URL}")

2. For each sponsor found, run a focused search:
   web_search("{SPONSOR_NAME} API SDK documentation developers")
   web_search("{SPONSOR_NAME} hackathon integration examples")

3. Extract and structure all information.

4. Write the complete report to workspace/hackathon/context.json with this exact schema:
{
  "hackathon": {
    "name": "string",
    "url": "string",
    "submission_deadline": "ISO datetime or human-readable",
    "demo_day": "date",
    "format": "online|hybrid|in-person",
    "tracks": [
      {"id": "string", "name": "string", "description": "string"}
    ],
    "judging_criteria": [
      {"criterion": "string", "weight": "string or number", "notes": "string"}
    ],
    "submission_requirements": ["string"]
  },
  "sponsors": [
    {
      "name": "string",
      "tier": "gold|silver|bronze|partner",
      "api_available": true,
      "api_base_url": "string or null",
      "auth_method": "bearer|custom_header|oauth|none",
      "auth_header": "string or null",
      "available_models": ["string"],
      "integration_complexity": 1,
      "key_capability": "one-sentence description",
      "sdk_install": "pip install ... or null",
      "example_use_case": "string",
      "bounty_available": true,
      "bounty_notes": "string or null"
    }
  ],
  "strategic_notes": "string — key insights for winning",
  "recommended_sponsor_priority": ["sponsor names in priority order"],
  "quick_wins": ["list of easiest high-value integrations"]
}

5. Also write a human-readable summary to workspace/hackathon/research_summary.md
```

## Output Files
- `workspace/hackathon/context.json` — structured data for agents
- `workspace/hackathon/research_summary.md` — human-readable summary
