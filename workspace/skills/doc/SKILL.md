---
name: doc
description: Generate project README, technical docs, and DoraHacks submission materials
metadata: {"openclaw": {"always": false}}
---

# Documentation Agent Skill

## Purpose
Generate all materials needed for a compelling hackathon submission:
README, technical architecture doc, and DoraHacks BUIDL description.

## When to Use
After the project passes testing (`test_results.json` status is "pass" or "partially_ready").

## Spawn Task Template

```
[DOC AGENT]
Goal: Generate complete submission documentation for the hackathon project.

TOOL CONSTRAINTS: DO NOT call web_search — it is not configured. Use web_fetch(url) only for specific known URLs. All required context is in local workspace files.

Step 1 — Load all context:
  read_file("hackathon/selected_idea.json")
  read_file("hackathon/plan.md")
  read_file("hackathon/test_results.json")
  list_dir("hackathon/project/")

Step 2 — Read key source files to understand what was actually built:
  Read the main entry point, key modules, and any README that exists.
  Note: document what IS built, not what was planned.

Step 3 — Generate README.md:
  Structure:
  # {Project Name}
  > {One-line tagline}

  ## The Problem
  {Clear problem statement — 2-3 sentences, specific and relatable}

  ## Our Solution
  {How it works — what the agent does, what the user experiences}

  ## Architecture
  {ASCII diagram of key components}

  ## Sponsor Technology Integrations
  ### FLock.io (Gold Sponsor)
  {Exactly how FLock is used — specific API calls, models, role in system}

  ### Virtuals Protocol (Bronze Sponsor)
  {Exactly how Virtuals is used}

  ### Unibase (Bronze Sponsor)
  {Exactly how Unibase is used}

  ## Demo
  {Step-by-step instructions to reproduce the demo, 5-10 steps}

  ## Tech Stack
  {Clean table: Component | Technology | Why}

  ## How to Run
  ```bash
  git clone ...
  pip install -r requirements.txt
  cp .env.example .env  # Fill in API keys
  python main.py
  ```

  ## About 0xClaw
  This project was built autonomously by 0xClaw, an AI agent system built on
  the 0xClaw agent system (OpenClaw ecosystem).
  0xClaw participated in and submitted to this very hackathon.

  Built with: FLock.io | Virtual Protocol | Unibase

Step 4 — Generate SUBMISSION.md:
  - DoraHacks BUIDL tagline (< 160 characters, compelling)
  - Full project description (< 500 words)
  - Sponsor bounties to apply for (justify each one)
  - What makes this submission win-worthy (3 specific points)
  - Demo video outline (30-second script)
  - Team: "0xClaw autonomous agent + {human developer name}"

Step 5 — Generate PITCH.md:
  - 2-minute elevator pitch (written out verbatim)
  - Top 3 technical differentiators
  - Impact story: who benefits and how

Step 6 — Write all files to hackathon/submission/:
  write_file("hackathon/submission/README.md", ...)
  write_file("hackathon/submission/SUBMISSION.md", ...)
  write_file("hackathon/submission/PITCH.md", ...)

  Also copy README.md to hackathon/project/README.md
```

## Output Files
- `hackathon/submission/README.md`
- `hackathon/submission/SUBMISSION.md`
- `hackathon/submission/PITCH.md`
- `hackathon/project/README.md` (copy)
