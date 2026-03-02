---
name: idea
description: Generate and score 3 innovative hackathon project ideas aligned with sponsor technologies
metadata: {"nanobot": {"always": false}}
---

# Idea Generation Skill

## Purpose
Generate 3 creative, feasible, and sponsor-integrated project ideas for a hackathon.
Score each idea on multiple dimensions and recommend the best one.

## When to Use
After hackathon research is complete (`workspace/hackathon/context.json` exists).

## Spawn Task Template

```
[IDEA AGENT]
Goal: Generate 3 winning project ideas for the hackathon.

Step 1 — Load Context:
  read_file("workspace/hackathon/context.json")

Step 2 — Analyze sponsor landscape:
  - Identify Gold sponsors (highest priority for integration)
  - List the unique API capabilities of each sponsor
  - Find complementary sponsor pairs (e.g., FLock inference + Unibase memory)

Step 3 — Generate 3 distinct ideas across these archetypes:
  Idea A — "AI Infrastructure": A platform/protocol that other agents can use
  Idea B — "AI Application": A user-facing tool that solves a real problem autonomously
  Idea C — "Web3 x AI Hybrid": Combines on-chain mechanics with AI intelligence

  For each idea, ensure:
  - 2+ sponsor technologies are CORE to the mechanism (not add-ons)
  - Problem is real and well-defined
  - MVP is achievable in 5 days of coding
  - Demo moment is clear and visual

Step 4 — Score each idea on these dimensions (1-5 each):
  - innovation: how novel is the concept? (5 = never seen before)
  - feasibility: can it be built in 7 days solo? (5 = straightforward)
  - sponsor_depth: how integral are sponsor APIs? (5 = can't work without them)
  - demo_impact: how impressive is the live demo? (5 = judges will remember it)
  - market_fit: does it solve a real problem people care about? (5 = obvious pain point)

  composite = (innovation*1.5 + feasibility*2.0 + sponsor_depth*2.0 + demo_impact*2.0 + market_fit*1.5) / 9.0

Step 5 — Write output to workspace/hackathon/ideas.json:
{
  "ideas": [
    {
      "id": "idea_a",
      "archetype": "infrastructure|application|web3_ai",
      "name": "string",
      "tagline": "one compelling sentence",
      "problem": "what pain point this solves (2-3 sentences)",
      "solution": "how it works at a high level (3-4 sentences)",
      "tech_stack": {
        "backend": "string",
        "frontend": "string or null",
        "ai_models": ["string"],
        "blockchain": "string or null",
        "storage": "string"
      },
      "sponsor_integrations": {
        "flock": "exact role in the system",
        "virtuals": "exact role or null",
        "unibase": "exact role or null",
        "other": "any other confirmed sponsor integrated, or null"
      },
      "architecture_sketch": "ASCII text diagram of key components",
      "mvp_scope": "exactly what can be demoed in 7 days",
      "wow_factor": "the one thing that makes judges say 'I've never seen this'",
      "risks": ["list of top 3 risks"],
      "scores": {
        "innovation": 4,
        "feasibility": 3,
        "sponsor_depth": 5,
        "demo_impact": 4,
        "market_fit": 3,
        "composite": 3.89
      }
    }
  ],
  "recommendation": "idea_X",
  "recommendation_rationale": "2-3 sentences explaining the choice",
  "generated_at": "ISO timestamp"
}
```

## Output File
- `workspace/hackathon/ideas.json`
