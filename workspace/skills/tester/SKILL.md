---
name: tester
description: Test the generated project, validate the implementation, and produce a quality report
metadata: {"openclaw": {"always": false}}
---

# Tester Agent Skill

## Purpose
Validate the generated project: syntax, imports, unit tests, and runtime readiness.
Produce a structured report. **Do not write new code or tests.**

## When to Use
After coder agents have finished implementing. Requires `hackathon/project/` to exist.

## CRITICAL: Execute Directly — DO NOT use spawn()

**Do NOT call spawn() for this task.**
**Do NOT write test files or any new code** — your only output is `hackathon/test_results.json`.
**Do NOT call message()** — just write the report file and stop.
Also: DO NOT call web_search — it is not configured.
**Do NOT use `sleep`, polling loops, or repeated `ls`/`list_dir` checks as a testing strategy.**
**Do NOT modify files under `hackathon/project/` during testing.**
If validation is incomplete, blocked, or partially successful, write `hackathon/test_results.json` anyway with `status: "partial"` or `status: "fail"` and explain why.

---

## Direct Execution Steps

**Step 1** — Discover project layout:
```
list_dir("hackathon/project/")
```
Read `hackathon/project/requirements.txt` if it exists.
After the initial discovery pass, avoid repeated directory polling unless a specific command just created a new artifact you need to inspect immediately.

**Step 2** — Install dependencies:
```
exec("cd hackathon/project && pip install -r requirements.txt -q 2>&1 | tail -10")
```

**Step 3** — Syntax check:
```
exec("cd hackathon/project && python -m py_compile $(find . -name '*.py' | head -50) 2>&1")
```

**Step 4** — Import verification:
For each top-level Python module found, attempt:
```
exec("cd hackathon/project && python -c 'import {module}; print(\"OK\")'")
```
Record any failures.

**Step 5** — Run existing unit tests (if any test files exist):
```
exec("cd hackathon/project && python -m pytest --tb=short -q 2>&1 | tail -30")
```
If no test files exist, record `tests_total: 0` and move on — do NOT write any test files.

**Step 6** — Runtime readiness checks:
- Check whether required env vars for the generated app are documented
- Record missing configuration as issues instead of blocking forever

**Step 7** — Write `hackathon/test_results.json`:
```json
{
  "status": "pass|fail|partial",
  "timestamp": "ISO datetime",
  "summary": "one-sentence overall assessment",
  "metrics": {
    "syntax_errors": 0,
    "import_errors": 0,
    "tests_total": 0,
    "tests_passed": 0,
    "tests_failed": 0,
    "test_coverage_estimate": "none|partial|good"
  },
  "runtime_readiness": {
    "env_documented": true,
    "env_missing": ["string"],
    "notes": "string"
  },
  "issues": [
    {
      "severity": "error|warning|info",
      "file": "string or null",
      "line": 0,
      "message": "string",
      "suggested_fix": "string"
    }
  ],
  "fix_priority": ["1. ...", "2. ..."],
  "demo_readiness": "not_ready|partially_ready|ready"
}
```

Your task is complete once `hackathon/test_results.json` is written. Stop immediately after.
If you cannot complete every validation step, write the best available report with explicit blockers and stop immediately after.

## Output File
- `hackathon/test_results.json`
