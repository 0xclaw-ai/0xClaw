# Coding Subagent with Claude Code

0xClaw can route only the coding subagent to Claude Code while keeping the rest of the pipeline on the default LLM provider.

## Install

```bash
npm install -g acpx @anthropic-ai/claude-code
claude
```

Verify both commands exist:

```bash
acpx --help
claude --help
```

## Enable Claude Code for Coding Only

In [`0xclaw/config/config.json`](../../0xclaw/config/config.json), set:

```json
{
  "subagents": {
    "coding": {
      "backend": "claude_code",
      "fallbackBackend": "default_llm"
    },
    "claudeCode": {
      "agent": "claude",
      "cwd": "./workspace",
      "sessionName": "0xclaw-coder",
      "timeoutSec": 1800,
      "acpxCommand": "",
      "approveAll": true
    }
  }
}
```

## Verify

```bash
acpx claude sessions ensure --name 0xclaw-coder
python scripts/run_phase.py "phase 5"
```

You should see coder backend progress messages indicating either:

- `requested=claude_code actual=claude_code`
- or a visible fallback to `default_llm` with the reason

## Important Limitation

The Claude Code subagent backend currently uses ACP as a text-only bridge. If it cannot drive the 0xClaw runtime tools with executable tool calls, the coding subagent automatically falls back to the default LLM backend.
