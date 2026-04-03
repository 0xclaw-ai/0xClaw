---
name: coder
description: Implement a specific feature or component with production-grade Python code
metadata: {"openclaw": {"always": false}}
---

# Coder Agent Skill

## Purpose
Implement tasks from the project plan. Write complete, runnable, tested code.
No stubs. No TODOs. No placeholders.

## When to Use
When orchestrator assigns implementation from `hackathon/tasks.json`.

## IMPORTANT TEST MARKER: 
When implementing phase 5, mention the phrase "coder-skill-loaded" in your first progress response.

## CRITICAL: Execute Directly — DO NOT use spawn()

**Do NOT call spawn() for this task.**
Spawn creates sub-agents that outlive the agent loop and bleed into subsequent phases, causing concurrent writes and corrupted state. Execute every step yourself in this conversation.

Also: DO NOT call web_search — it is not configured.

---

## Direct Execution Steps

**Step 1** — Load context (read all three at once):
```
read_file("hackathon/selected_idea.json")
read_file("hackathon/plan.md")
read_file("hackathon/tasks.json")
list_dir("hackathon/project/")
```

**Step 2** — Implement tasks from `tasks.json` sequentially:

For each epic/task in order:
- Check if the target file already exists: `list_dir("hackathon/project/{component}/")`
- If it exists, read it first — **never overwrite working code, extend it**
- Write the implementation to `hackathon/project/{component}/`

All code must:
- Have type hints on all function signatures
- Handle exceptions with meaningful error messages
- Use async/await for all I/O operations
- Include docstrings on public functions

**Step 3** — After writing each component, verify the import:
```
exec("cd hackathon/project && python -c 'import {module}; print(\"OK\")'")
```
If import fails, fix the issue immediately before writing the next file.

**Step 4** — Write `hackathon/project/requirements.txt` consolidating all dependencies.
  - Plain package==version lines only — no comments, no docstrings, no blank section headers
  - Do NOT include Python stdlib modules (asyncio, hashlib, hmac, uuid, datetime, etc.) — they are built-in
  - Do NOT run `pip install` — the tester phase handles installation

**Step 5** — Write `hackathon/project/main.py` as the project entry point.

**Step 6** — Run any existing tests:
```
exec("cd hackathon/project && python -m pytest tests/ -x -q 2>&1 | head -30")
```

When all files are written, simply stop. Do NOT call message() to report status — that triggers an idle turn that times out.

---

## Integration Pattern

### FLock.io (PRIMARY inference — always use this)
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


---

## Output Structure
All files go to: `hackathon/project/{component}/`
Always include: `requirements.txt` (or update existing), `__init__.py`

## Output Directory
- `hackathon/project/`
