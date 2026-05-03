# Coding Subagent with Claude Code

0xClaw can route the coding and testing subagents to Claude Code while keeping the rest of the pipeline on the default LLM provider. The integration uses the official `claude-agent-sdk` Python package.

## Install

```bash
npm install -g @anthropic-ai/claude-code
claude
```

Verify the CLI is available:

```bash
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
      "model": "",
      "cwd": "./workspace/hackathon/project",
      "timeoutSec": 1800,
      "permissionMode": "acceptEdits",
      "seedAgents": [
        "install-and-smoketest",
        "package-for-submission",
        "dependency-fixer"
      ]
    }
  }
}
```

### Claude Code config fields

- `model` — `""` (SDK default) — Model alias for the SDK session (e.g. `"sonnet"`, `"opus"`)
- `cwd` — `"./workspace/hackathon/project"` — Working directory for the Claude Code session
- `timeoutSec` — `1800` — Maximum seconds for a single phase run
- `permissionMode` — `"acceptEdits"` — Claude Code permission mode
- `seedAgents` — 3 default agents — Subagent names to seed under `<cwd>/.claude/agents/`
- `baseUrl` — `""` — Optional Anthropic-compatible endpoint override
- `authTokenEnv` — `""` — Env var name holding the bearer token for custom endpoints

## Verify

```bash
python -m unittest tests.test_router -v
```

You should see coder backend progress messages indicating either:

- `requested=claude_code actual=claude_code`
- or a visible fallback to `default_llm` with the reason

## How It Works

The `ClaudeCodeExecutor` spawns a `ClaudeSDKClient` session for each phase run. Phase-specific system prompts (coding, testing) are assembled and sent as a single query. The executor streams progress messages back to the main agent loop and returns the final assistant text as the phase result.
