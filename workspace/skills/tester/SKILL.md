---
name: tester
description: Test the generated project, validate sponsor integrations, and produce a quality report
metadata: {"nanobot": {"always": false}}
---

# Tester Agent Skill

## Purpose
Validate the generated project: syntax, imports, unit tests, and sponsor API connectivity.
Produce a structured report with actionable fix recommendations.

## When to Use
After coder agents have finished implementing. Requires `workspace/hackathon/project/` to exist.

## Spawn Task Template

```
[TESTER AGENT]
Goal: Test the hackathon project and produce a quality report.

Step 1 — Discovery:
  list_dir("workspace/hackathon/project/")
  Read requirements.txt files found.

Step 2 — Environment Setup:
  exec("cd workspace/hackathon/project && pip install -r requirements.txt -q 2>&1 | tail -10")

Step 3 — Syntax Check:
  exec("cd workspace/hackathon/project && python -m py_compile $(find . -name '*.py' | head -50) 2>&1")

Step 4 — Import Verification:
  For each Python module found, attempt: python -c 'import module; print("OK")'
  Report any import failures with specific error messages.

Step 5 — Unit Tests:
  exec("cd workspace/hackathon/project && python -m pytest tests/ -v --tb=short 2>&1")
  If no tests directory exists, note it as a gap.

Step 6 — Sponsor API Smoke Tests:
  FLock.io: Check FLOCK_API_KEY is set. If set, run a minimal completion request.
  Venice.ai: Check VENICE_API_KEY is set. If set, run a minimal completion request.
  Virtuals: Check VIRTUALS_API_KEY is set.
  Unibase: Check MEMBASE_ID and MEMBASE_ACCOUNT are set.

Step 7 — Write report to workspace/hackathon/test_results.json:
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
  "sponsor_integrations": {
    "flock": {"configured": true, "reachable": true, "notes": "string"},
    "venice": {"configured": false, "reachable": false, "notes": "API key missing"},
    "virtuals": {"configured": false, "reachable": null, "notes": "string"},
    "unibase": {"configured": false, "reachable": null, "notes": "string"}
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
  "fix_priority": [
    "1. Fix import error in agents/orchestrator.py line 12",
    "2. Add VENICE_API_KEY to environment"
  ],
  "demo_readiness": "not_ready|partially_ready|ready"
}
```

## Output File
- `workspace/hackathon/test_results.json`
