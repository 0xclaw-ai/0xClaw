# 0xClaw Orchestration Protocol

## Full Hackathon Pipeline

Trigger this pipeline ONLY when user says: "run full pipeline", "run all phases", "start pipeline",
"run complete hackathon pipeline", or "go" with no other phase qualifier.

IMPORTANT: "run hackathon research", "run research", "phase 1", etc. trigger ONLY Phase 1.
Do NOT run the full pipeline for single-phase commands.

## Skill Composition Model (Important)

Use this rule to avoid confusion when many skills exist:

1. Base skill = one phase owner. Each phase has exactly one primary role skill:
   `hackathon-research` -> `idea` -> `planner` -> `coder` -> `tester` -> `doc`
2. Overlay skills = shared methods that can be attached to many phases:
   - `iterative-retrieval`: iterative context gathering before major decisions
   - `tdd-workflow`: RED -> GREEN -> REFACTOR coding loop
   - `eval-harness`: define and run explicit acceptance checks
   - `coding-standards`: consistent structure/style/quality gate
3. Call order inside a phase:
   - Pre-step (optional): `iterative-retrieval`
   - Execute phase owner (base skill)
   - Validate/normalize (overlay): `eval-harness` or `coding-standards` as needed

### Phase 1 — Research
Trigger cues:
- "phase 1"
- "run research"
- "start with hackathon analysis"
- "先做调研"

Base skill:
- Use `hackathon-research` to spawn a research agent.

Overlay skills:
- Use `iterative-retrieval` before finalizing report fields.

Output:
- `hackathon/context.json`

### Phase 2 — Ideation
Trigger cues:
- "phase 2"
- "generate ideas"
- "brainstorm 3 ideas"
- "开始创意阶段"

Base skill:
- Use `idea` to spawn an idea agent.

Overlay skills:
- Optional `iterative-retrieval` if sponsor/API context is weak.

Output:
- `hackathon/ideas.json`

### Phase 3 — Selection (Orchestrator)
Trigger cues:
- "phase 3"
- "pick the best idea"
- "select idea"
- "帮我选题"

Read `ideas.json`. Select the idea with the highest composite score.
Confirm with user if score difference < 0.5.
Write: `hackathon/selected_idea.json`

### Phase 4 — Planning
Trigger cues:
- "phase 4"
- "plan architecture"
- "make implementation plan"
- "开始技术规划"

Base skill:
- Use `planner` to spawn a planner agent.

Overlay skills:
- Use `iterative-retrieval` for API/docs clarification before freezing architecture.
- Use `eval-harness` to define acceptance criteria for each epic/task.

Outputs:
- `hackathon/plan.md`
- `hackathon/tasks.json`

### Phase 5 — Implementation
Trigger cues:
- "phase 5"
- "start coding"
- "implement tasks"
- "开始实现"

Default execution mode:
- Use a single coding executor for the whole phase.
- The coding executor owns the full implementation flow for Phase 5 and writes directly to `hackathon/project/{component}/`.
- Apply `tdd-workflow` inside the coding execution.
- Apply `coding-standards` before marking each task done.
- Prefer completing the implementation in one continuous coding run instead of decomposing into multiple spawned coders.

Legacy fallback mode:
- Only if the active coding backend cannot execute the phase directly, fall back to the older orchestrated mode.
- In legacy fallback mode only, use the `coder` skill to spawn one coder agent per epic with priority `critical` or `high`.
- In legacy fallback mode only, run epics in parallel where no dependencies exist.

Completion rule for Phase 5:
- Do not treat partial files in `hackathon/project/` as coding completion.
- Do not treat a started sub-agent, partial implementation, or intermediate progress update as coding completion.
- Keep Phase 5 in progress until all required `critical` and `high` epics in `hackathon/tasks.json` are completed, or explicitly deferred with a written reason.
- If a spawned coder is still running, explicitly say coding is still in progress and do not imply completion.
- When unsure whether coding is complete, prefer reporting "still in progress" over "complete".
- Only report a final coding completion summary after implementation scope has actually been finished.

Execution guardrails for Phase 5:
- Do not spawn coder sub-agents when the active coding backend is a direct executor such as Claude Code.
- Do not mix "direct executor mode" and "spawned coder mode" in the same Phase 5 run unless a backend failure forces an explicit fallback.
- If direct executor mode fails and fallback mode is activated, state that clearly in the progress update before spawning any coders.

### Phase 6 — Testing
Trigger cues:
- "phase 6"
- "run tests"
- "validate build"
- "开始测试"

Base skill:
- Use `tester` to spawn a tester agent.

Overlay skills:
- Use `eval-harness` to run acceptance checks defined in Phase 4.

Output:
- `hackathon/test_results.json`

If status is "fail", spawn targeted fix agents using `coder` (+ `tdd-workflow`).

Execution rule for Phase 6:
- Do not treat waiting, polling, repeated `ls`, or `sleep` loops as valid testing work.
- Do not use `spawn()` while executing the testing phase itself.
- Do not modify implementation files under `hackathon/project/` during testing.
- Run the available validation commands immediately and summarize the results.
- If dependencies are missing, tests cannot run, or validation is only partial, still write `hackathon/test_results.json` with a clear `status` and explanation, then stop.
- Prefer producing a partial or failed testing report over getting stuck waiting for more project changes.

### Phase 7 — Documentation
Trigger cues:
- "phase 7"
- "prepare docs"
- "generate submission package"
- "开始文档与提交材料"

Base skill:
- Use `doc` to spawn a doc agent.

Overlay skills:
- Apply `coding-standards` for consistent structure/tone/terminology.

Outputs:
- `hackathon/submission/README.md`
- `hackathon/submission/SUBMISSION.md`

---

## State Convention

All inter-agent data lives in `hackathon/`:

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

Use `hackathon/progress.md` as a running log:
- Append a line when each phase completes: `[HH:MM] Phase X complete: <summary>`
- Check this file to understand current state when resuming
