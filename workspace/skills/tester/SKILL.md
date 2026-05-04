---
name: tester
description: Test the generated project inside an E2B cloud sandbox via Claude Code, apply fixes iteratively, and produce a quality report
metadata: {"openclaw": {"always": false}}
---

# Tester Agent Skill

## Purpose
Validate the generated project inside an E2B cloud sandbox: Claude Code installs
dependencies, runs tests, applies fixes iteratively, and writes a structured report.
The entire phase runs in an isolated Linux VM with full internet access.

## When to Use
After coder agents have finished implementing. Requires `hackathon/project/` to exist.

## Architecture (Phase 6)

Phase 6 uses `E2BTestingExecutor` which:

1. Creates an E2B cloud sandbox (Debian Linux VM with Claude Code pre-installed).
2. Uploads `hackathon/project/` and sibling artifacts (plan.md, tasks.json, etc.).
3. Runs `claude --dangerously-skip-permissions` inside the sandbox with the
   testing prompt — CC has full autonomy to install packages, run tests, fix
   issues, and start servers.
4. Streams progress back to the main agent loop.
5. Downloads `test_results.json` from the sandbox to the local workspace.
6. Kills the sandbox.

The sandbox provides full isolation from the host system with internet access,
so pip/npm install and server startup work without restrictions.

## Output File
- `hackathon/test_results.json`
