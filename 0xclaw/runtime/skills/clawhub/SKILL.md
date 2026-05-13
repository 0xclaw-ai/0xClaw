---
name: clawhub
description: Search and install agent skills from ClawHub, the public skill registry.
homepage: https://clawhub.ai
metadata: {"openclaw":{"emoji":"🦞"}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search).

## Workspace `--workdir` (pick one)

- **0xClaw hackathon repo checkout**: point ClawHub at your clone’s `workspace/` directory (next to `workspace/skills/`), e.g. `--workdir /path/to/0xClaw/workspace`.
- **Runtime-only / global layout**: use `~/.0xclaw/workspace` (matches the runtime default from `get_workspace_path()`).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## Install

```bash
# Typical 0xClaw repo (replace with your clone path):
npx --yes clawhub@latest install <slug> --workdir /path/to/0xClaw/workspace

# Global runtime layout instead:
# npx --yes clawhub@latest install <slug> --workdir ~/.0xclaw/workspace
```

Replace `<slug>` with the skill name from search results. Skills are written under `<workdir>/skills/`. Always pass an explicit `--workdir`.

## Update

```bash
npx --yes clawhub@latest update --all --workdir /path/to/0xClaw/workspace
```

## List installed

```bash
npx --yes clawhub@latest list --workdir /path/to/0xClaw/workspace
```

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- `--workdir` must target the **same** directory the agent loads as its workspace; mismatching `~/.0xclaw/workspace` vs `<repo>/workspace` is a common footgun.
- After install, remind the user to start a new session to load the skill.
