# 0xClaw Heartbeat Tasks

## Active Tasks

### pipeline-progress
Every 6 hours, check `hackathon/progress.md` and report:
- Current phase and completion percentage
- Hours remaining until the hackathon deadline (read deadline from `hackathon/context.json`)
- Any blockers or risks
- Recommended next action

If `progress.md` doesn't exist yet: report "Pipeline not started. Ready to begin."

### sponsor-integration-check
Once per day, verify:
- Primary LLM API key is set and reachable (test with a minimal completion request)
- Report status to user

---

## Completed Tasks
(move finished tasks here)
