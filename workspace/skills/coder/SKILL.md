---
name: coder
description: Implement a specific feature or component with production-grade Python code
metadata: {"nanobot": {"always": false}}
---

# Coder Agent Skill

## Purpose
Implement a specific task from the project plan. Write complete, runnable, tested code.
No stubs. No TODOs. No placeholders.

## When to Use
When orchestrator assigns a specific epic or task from `workspace/hackathon/tasks.json`.

## Spawn Task Template

Replace `{EPIC_ID}`, `{TASK_DESCRIPTION}`, and `{COMPONENT}` before spawning.

```
[CODER AGENT — {EPIC_ID}]
Goal: Implement {TASK_DESCRIPTION}

Step 1 — Load context:
  read_file("workspace/hackathon/selected_idea.json")
  read_file("workspace/hackathon/plan.md")
  read_file("workspace/hackathon/tasks.json")
  list_dir("workspace/hackathon/project/")

Step 2 — Check existing code:
  If workspace/hackathon/project/{COMPONENT}/ exists, read relevant files first.
  Never overwrite working code — extend it.

Step 3 — Implement:
  Write to workspace/hackathon/project/{COMPONENT}/
  All code must:
  - Have type hints on all function signatures
  - Handle exceptions with meaningful error messages
  - Use async/await for all I/O operations
  - Include docstrings on public functions

Step 4 — Verify imports:
  exec("cd workspace/hackathon/project && python -c 'import {MODULE}; print(\"OK\")'")
  If import fails, fix the issue before proceeding.

Step 5 — Run any existing tests:
  exec("cd workspace/hackathon/project && python -m pytest tests/ -x -q 2>&1 | head -30")
  Fix any regressions before finishing.

--- SPONSOR INTEGRATION PATTERNS ---

## FLock.io (use as PRIMARY inference)
```python
import os
from openai import AsyncOpenAI

flock_client = AsyncOpenAI(
    api_key=os.environ["FLOCK_API_KEY"],
    base_url="https://api.flock.io/v1",
    default_headers={"x-litellm-api-key": os.environ["FLOCK_API_KEY"]},
)

async def flock_complete(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = await flock_client.chat.completions.create(
        model="qwen3-30b-a3b-instruct-2507",
        messages=messages,
        max_tokens=2048,
    )
    return response.choices[0].message.content
```

## Virtuals Protocol (agent identity + GAME framework)
```python
from virtuals_sdk import game

agent = game.Agent(
    api_key=os.environ["VIRTUALS_API_KEY"],
    goal="...",
    description="...",
    world_info="UK AI Hackathon EP4, March 2026",
)
```

## Unibase (persistent on-chain memory)
```python
# Set in environment:
# MEMBASE_ID=0xclaw-{agent_name}
# MEMBASE_ACCOUNT=<bnb-wallet>
# MEMBASE_SECRET_KEY=<key>
```

--- OUTPUT STRUCTURE ---
All files go to: workspace/hackathon/project/{COMPONENT}/
Keep each module focused: one responsibility per file.
Always include: requirements.txt (or update existing), __init__.py
```

## Output Directory
- `workspace/hackathon/project/{component}/`
