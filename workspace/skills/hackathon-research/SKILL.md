---
name: hackathon-research
description: Research a hackathon using a user-supplied URL plus optional doc URLs (sitemap-driven scrape).
metadata: {"openclaw": {"always": true}}
---

# Hackathon Research Skill

## Purpose
Compile a hackathon intelligence report from URLs the USER explicitly provides.
The user knows which hackathon and which sponsor docs matter — autonomous
discovery through CAPTCHA-walled SPAs is unreliable, so this skill leans on
human input plus deterministic sitemap parsing instead of search-engine guesswork.

## Input format (fixed — only these two forms)
1. `research <hackathon_url>`
2. `research <hackathon_url> docs=<url1>,<url2>,<url3>`

If the user uses form 2, the URLs after `docs=` are sponsor / SDK / framework
documentation roots that the research agent MUST explore. Comma-separated, no
spaces inside the list.

## Available tools
- `firecrawl_scrape` — primary content fetcher (handles JS, returns markdown).
- `web_fetch` — fallback when Firecrawl is unavailable.
- `read_file` / `write_file`.

The orchestrator pre-expands `docs=<u1>,<u2>` into a concrete `scrape_urls`
list (sitemap-driven, keyword-filtered, capped) BEFORE the spawn task is
constructed. The agent never has to fetch sitemaps or filter URLs itself —
those steps are deterministic Python in `0xclaw/orchestration/doc_explorer.py`.

## Spawn Task Template

```
[HACKATHON RESEARCH AGENT]
Goal: Produce a hackathon intelligence report grounded in URLs the user gave.

Inputs you receive from the orchestrator (envelope payload):
  - user_command: full original user input (for reference)
  - phase: "research"
  - doc_roots: list of doc-site roots the user provided (may be empty/missing)
  - scrape_urls: pre-filtered concrete URLs already expanded from doc_roots
                 via sitemap.xml + keyword filter (may be empty/missing)

Do not ask clarifying questions. Proceed autonomously.

Step 1 — Workspace context:
  read_file("AGENTS.md")
  read_file("SOUL.md")

Step 2 — Hackathon page (best-effort):
  firecrawl_scrape(HACKATHON_URL, formats=["markdown","links"])
  If the scrape returns < 2000 chars or a CAPTCHA/Cloudflare wall:
    Try once more with formats=["html","markdown"], wait_for=3000.
    If still blocked: record under unresolved.requires_human and proceed —
    do NOT search-engine-guess facts. The user's DOC_URLS will be the
    authoritative source instead.

Step 3 — Scrape pre-expanded doc URLs:
  For EACH url in scrape_urls (the orchestrator already filtered these
  down from sitemap.xml — do NOT re-discover, do NOT skip any):
    firecrawl_scrape(url, formats=["markdown"])
    Append a sources[] entry: {url, fetched_at, type="scrape", used_for}.
    Extract from the markdown: SDK names, integration patterns, code
    examples, prerequisites, auth/key requirements.

  If scrape_urls is empty AND doc_roots is non-empty, the sitemap fetch
  failed during orchestrator pre-expansion. In that case:
    For each root in doc_roots: firecrawl_scrape(root, formats=["markdown"])
    Append to sources[] and proceed with whatever you got.

  If both scrape_urls and doc_roots are empty, the user only gave a
  hackathon URL (form 1). Skip this step.

Step 4 — Discord / private channel:
  If the hackathon page mentions a Discord invite or "join channel for codes",
  record under unresolved.requires_human. Do NOT try to join.

Step 5 — Synthesize context.json (NO hardcoded defaults — empty/null if not
sourced from a real scrape):

{
  "hackathon": {
    "name": null, "url": null, "host_platform": null,
    "submission_deadline": null, "demo_day": null, "format": null,
    "tracks": [], "judging_criteria": [],
    "submission_requirements": [], "prizes": []
  },
  "sponsors": [],          // [{name, url, integration_notes}]
  "starters": [],          // [{repo, url, language, summary}]
  "sdks_to_investigate": [],
  "strategic_notes": null,
  "recommended_integration_priority": [],
  "quick_wins": [],
  "unresolved": {
    "requires_human": [],
    "open_questions": []
  },
  "sources": [
    // {"url", "fetched_at": <real UTC NOW, never invented>,
    //  "type": "scrape" | "search_snippet",
    //  "used_for": "<field path or sponsor:NAME or starter:REPO>"}
  ]
}

Step 6 — Write outputs:
  write_file("hackathon/context.json", <the JSON, real values only>)
  write_file("hackathon/research_summary.md",
    <human-readable summary including: overview, sponsors, SDKs to use,
     Sources section listing every URL in sources[], Requires-human section
     if non-empty, and a "⚠️ DEGRADED RESEARCH" banner at top if Step 2
     was blocked>)

STOP HERE. Do NOT proceed to ideation, planning, or coding.
```

## Hard rules (validation — these are non-negotiable)

- `sources[]` must be non-empty. Every non-null hackathon field needs ≥1
  matching `sources[]` entry whose `used_for` references it.
- `type="search_snippet"` is allowed ONLY for these three fields:
  `hackathon.name`, `hackathon.prizes` (total pool), `hackathon.submission_deadline`.
  Anywhere else (sponsors, starters, sdks, judging_criteria, tracks) it is a
  hard violation — drop the entry rather than weaken its provenance.
- `type` must be one of: `scrape`, `search_snippet`. Do NOT invent values
  like `search`, `inferred`, `fetch`.
- `fetched_at` must be the actual current UTC timestamp at fetch time. Do NOT
  invent or backdate (e.g. `2025-06-17` when today is `2026-04`).
- Hackathon-specific fields (`judging_criteria`, `tracks`, `prizes`,
  `submission_requirements`) stay `[]`/null unless a successfully scraped page
  literally states them. Never copy from search snippets, never infer from
  "what hackathons usually have", never carry over from prior runs.
- `starters[]` entries: each `url` must be linked from a scraped hackathon
  page or a scraped sponsor doc page. Otherwise drop.
- `research_summary.md` is REQUIRED. Phase will not be marked complete
  without it (enforced in `state.py`).

## Output Files
- `hackathon/context.json` — structured data + audit trail
- `hackathon/research_summary.md` — human summary

## Notes for maintainers
- Sitemap-first design replaced the older search-driven discovery loop.
  Search engines can't index links inside CAPTCHA-walled SPAs, so the agent
  was unreliable at finding sponsor docs autonomously. Letting the user
  pass `docs=...` removes that whole class of failure.
- Keyword filter is intentionally generic (`/introduction`, `/quickstart`,
  `/api`, etc.). If a hackathon has unusual SDK terminology, edit the
  default keyword string in Step 3a — do not push that complexity onto the
  spawn caller.
- Cap of 15 URLs per doc-root prevents the agent from spidering an entire
  doc site. Tune here, not at the call site.
