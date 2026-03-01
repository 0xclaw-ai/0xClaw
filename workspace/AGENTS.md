# 0xClaw Orchestration Protocol

## Full Hackathon Pipeline

Trigger this pipeline when user says: "run hackathon", "start pipeline", "go",
or provides a hackathon URL.

### Phase 1 — Research
Use the `hackathon-research` skill to spawn a research agent.
The agent produces: `workspace/hackathon/context.json`

### Phase 2 — Ideation
Use the `idea` skill to spawn an idea agent.
The agent reads context.json and produces: `workspace/hackathon/ideas.json`

### Phase 3 — Selection (Orchestrator)
Read `ideas.json`. Select the idea with the highest composite score.
Confirm with user if score difference < 0.5.
Write: `workspace/hackathon/selected_idea.json`

### Phase 4 — Planning
Use the `planner` skill to spawn a planner agent.
Produces: `workspace/hackathon/plan.md` and `workspace/hackathon/tasks.json`

### Phase 5 — Implementation
Read tasks.json. For each epic with priority "critical" or "high":
- Use the `coder` skill to spawn one coder agent per epic
- Agents write to `workspace/hackathon/project/{component}/`
- Run epics in parallel where no dependencies exist

### Phase 6 — Testing
Use the `tester` skill to spawn a tester agent.
Produces: `workspace/hackathon/test_results.json`
If status is "fail": spawn targeted fix agents using the `coder` skill.

### Phase 7 — Documentation
Use the `doc` skill to spawn a doc agent.
Produces: `workspace/hackathon/submission/README.md` and `SUBMISSION.md`

---

## State Convention

All inter-agent data lives in `workspace/hackathon/`:

| File | Written by | Read by |
|------|-----------|---------|
| `context.json` | Research Agent | Idea Agent, Planner Agent |
| `ideas.json` | Idea Agent | Orchestrator |
| `selected_idea.json` | Orchestrator | Planner, Coder, Doc Agents |
| `plan.md` | Planner Agent | Coder, Doc Agents |
| `tasks.json` | Planner Agent | Orchestrator, Coder Agents |
| `project/` | Coder Agents | Tester Agent |
| `test_results.json` | Tester Agent | Orchestrator |
| `submission/` | Doc Agent | Human submitter |

---

## Sponsor Integration Requirements

These are non-negotiable for maximum scoring:

**FLock.io (Gold Sponsor)**
- Use as primary LLM inference in the generated project
- API: `https://api.flock.io/v1` (OpenAI-compatible)
- Auth: `x-litellm-api-key: $FLOCK_API_KEY`
- Preferred model: `qwen3-30b-a3b-instruct-2507`

**Venice.ai (Silver Sponsor)**
- Use for privacy-sensitive operations and when the project needs built-in web search
- API: `https://api.venice.ai/api/v1` (OpenAI-compatible, Bearer token)
- Preferred model: `llama-3.3-70b` (general); `qwen3-coder-480b-a35b-instruct-turbo` (coding)
- Key differentiator: pass `extra_body={"venice_parameters": {"enable_web_search": "auto", "include_venice_system_prompt": False}}` for live search with no extra API key

**Virtuals Protocol (Bronze Sponsor)**
- Create on-chain agent identities via GAME SDK
- SDK: `pip install virtuals_sdk`
- Use for multi-agent coordination with on-chain provenance

**Unibase (Bronze Sponsor)**
- Persistent cross-session agent memory on-chain
- SDK: `pip install git+https://github.com/unibaseio/aip-agent`
- Use to store agent decisions with verifiable history

---

## Spawn Task Guidelines

When spawning sub-agents:
1. Always include the full task context in the task string (sub-agents have no shared memory)
2. Reference workspace files by absolute path
3. Include sponsor integration patterns in the task when relevant
4. Set specific output file paths — never assume defaults

## Error Recovery

If a sub-agent fails:
1. Read the error from the announced result
2. Diagnose: missing dependency? API key not set? Logic error?
3. Spawn a targeted fix agent with the specific error context
4. After 2 failed attempts on the same task, simplify the scope and retry

## Progress Tracking

Use `workspace/hackathon/progress.md` as a running log:
- Append a line when each phase completes: `[HH:MM] Phase X complete: <summary>`
- Check this file to understand current state when resuming
