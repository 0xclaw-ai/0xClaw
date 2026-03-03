---
name: planner
description: Create detailed system architecture and 7-day sprint task breakdown for a hackathon project
metadata: {"nanobot": {"always": false}}
---

# Project Planner Skill

## Purpose
Transform a selected project idea into a complete technical blueprint:
system architecture, tech stack decisions, and a day-by-day implementation plan.

## When to Use
After `hackathon/selected_idea.json` exists.

## Spawn Task Template

```
[PLANNER AGENT]
Goal: Create a complete technical plan for the selected hackathon project.

Step 1 — Load inputs:
  read_file("hackathon/selected_idea.json")
  read_file("hackathon/context.json")

Step 2 — Architecture Design:
  Define system components and their responsibilities.
  Draw a data flow diagram using ASCII art.
  Specify all API integration points with exact endpoints and auth methods.
  Define core data models (as Python dataclasses or JSON schemas).
  List all external dependencies and their versions.

Step 3 — Tech Stack Decision:
  For each component, specify technology and rationale:
  - Backend: language + framework (prefer Python FastAPI or similar)
  - AI inference: FLock API (primary)
  - Storage: SQLite (local), PostgreSQL (if scale needed), or Redis (caching)
  - Blockchain: specify chain, SDK, and specific contract/API calls
  - Frontend: minimal (Gradio/Streamlit preferred for speed), or None if pure API
  - Infrastructure: local + Docker (for portability)

Step 4 — Task Breakdown:
  Create epics. Each epic maps to one system component.
  Each task must have:
  - Clear deliverable: what does "done" look like exactly?
  - Estimated hours (be realistic: 1 hour = 45 minutes of real coding)
  - Component tag: backend | frontend | ai | blockchain | infra | testing
  - Priority: critical (blocks everything) | high (needed for MVP) | medium (polish)
  - Dependencies: list task IDs that must complete first (empty list if none)

Step 5 — 7-Day Timeline:
  Map tasks to days. Guard against overloading any single day.
  Day 1: Setup + scaffold + CI (max 6 hours coding)
  Day 2: Core backend APIs + data models
  Day 3: AI integration (FLock) + core agent logic
  Day 4: Blockchain integration (Virtuals + Unibase)
  Day 5: Frontend/demo layer + error handling + edge cases
  Day 6: Testing + README + submission prep
  Day 7: Final polish + video demo + DoraHacks submission

Step 6 — Write outputs:

  write_file("hackathon/plan.md", <full architecture + rationale in markdown>)

  write_file("hackathon/tasks.json", <task structure>):
  {
    "project_name": "string",
    "architecture_summary": "2-3 sentences",
    "tech_stack": {
      "backend": "Python 3.11 + FastAPI",
      "ai_primary": "FLock API (qwen3-30b-a3b-instruct-2507)",
      "ai_privacy": null,
      "blockchain": "string or null",
      "storage": "string",
      "frontend": "string or null"
    },
    "epics": [
      {
        "id": "E1",
        "name": "string",
        "component": "backend|frontend|ai|blockchain|infra|testing",
        "day_target": 1,
        "tasks": [
          {
            "id": "T1.1",
            "title": "string",
            "description": "what exactly to build",
            "deliverable": "what done looks like",
            "component": "string",
            "estimated_hours": 2,
            "priority": "critical|high|medium",
            "dependencies": [],
            "day": 1
          }
        ]
      }
    ],
    "risk_register": [
      {"risk": "string", "probability": "high|medium|low", "mitigation": "string"}
    ]
  }
```

## Output Files
- `hackathon/plan.md` — human-readable architecture doc
- `hackathon/tasks.json` — machine-readable task list
