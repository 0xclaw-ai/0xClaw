---
name: planner
description: Create detailed system architecture and 7-day sprint task breakdown for a hackathon project
metadata: {"openclaw": {"always": false}}
---

# Project Planner Skill

## Purpose
Transform a selected project idea into a complete technical blueprint:
system architecture, tech stack decisions, and a day-by-day implementation plan.

## When to Use
After `hackathon/selected_idea.json` exists.

## CRITICAL: Execute Directly — DO NOT use spawn()

**Do NOT call spawn() for this task.**
Run all steps in this single phase execution and write the files directly.

**Do NOT run monitoring loops** such as:
- `exec("sleep ...")`
- repeated `list_dir(...)` polling
- tailing logs/envelopes to wait for subagents

**Do NOT call web_search.**
Use local files as primary truth. `web_fetch` is optional only if a known URL is strictly needed.

**Completion condition is strict:**
Your task is complete only after both files exist and are non-empty:
- `hackathon/plan.md`
- `hackathon/tasks.json`

If context is incomplete, produce a best-effort v1 plan from available inputs and explicitly mark assumptions.

---

## Direct Execution Steps

**Step 1 — Load Inputs (must do first):**
```
read_file("hackathon/selected_idea.json")
read_file("hackathon/context.json")
list_dir("hackathon/")
```

**Step 2 — Draft Architecture (`plan.md`)**
Include all sections below:
- Project objective and MVP boundary
- System components with responsibilities
- End-to-end data flow (ASCII diagram)
- Sponsor integrations with exact roles:
  - FLock: inference path and model call surface
  - Virtual Protocol: on-chain agent identity flow
  - Unibase: persistent memory flow
- Core data models (JSON schema or dataclass-like spec)
- API boundaries (endpoints, input/output shape, auth notes)
- Dependency list with versions (or pinned target versions)
- Risks + mitigations
- Assumptions (explicit)

**Step 3 — Build Executable Task Plan (`tasks.json`)**
Requirements:
- At least 4 epics
- Each epic has at least 3 tasks
- Every task has concrete deliverable and dependency list
- Priorities use only: `critical | high | medium`
- Components use only: `backend | frontend | ai | blockchain | infra | testing`
- Day allocation must be 1..7 and realistic
- Include acceptance-ready tasks for testing and demo prep

Use this JSON shape:
```json
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
          "component": "backend|frontend|ai|blockchain|infra|testing",
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

**Step 4 — Write Files (no delay, no waiting):**
```
write_file("hackathon/plan.md", <markdown plan>)
write_file("hackathon/tasks.json", <valid JSON string>)
```

**Step 5 — Sanity Check and Stop**
- Optionally run one quick parse check for JSON validity.
- Do not spawn anything after writing files.
- Do not ask questions; do not wait for further input.

## Output Files
- `hackathon/plan.md` — human-readable architecture doc
- `hackathon/tasks.json` — machine-readable task list
