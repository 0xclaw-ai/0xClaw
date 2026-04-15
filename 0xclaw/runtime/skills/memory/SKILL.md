---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

```bash
grep -i "keyword" memory/HISTORY.md
```

Use the `exec` tool to run grep. Combine patterns: `grep -iE "meeting|deadline" memory/HISTORY.md`

## When to Update MEMORY.md

Write only durable cross-session facts:
- User preferences ("I prefer Chinese", "Use FastAPI by default")
- Stable working conventions ("Prefer pytest", "Use pnpm in this repo family")
- Long-lived relationships ("Alice is the project lead")

Do NOT write transient execution state:
- Hackathon research results
- Current pipeline phase or task progress
- Generated artifact lists
- Temporary implementation/debug status
- Anything that should reset with `/new`

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts may be extracted to MEMORY.md, but only durable preferences and enduring facts belong there.
