# 0xClaw usage guide

[Back to README](README.md)

## 🚀 Quick start

```bash
conda create -n 0xclaw python=3.11 -y
conda activate 0xclaw
pip install -e .
cp .env.example .env
./scripts/verify_setup.sh
```

Fill `.env` from the table below. Optional dev tools: `pip install -e .[dev]` (Ruff). Entry point: **`0xclaw`** (also `python launcher/__main__.py`).

| Variable / tool | Role | Where to get it | When needed |
| --- | --- | --- | --- |
| `ZAI_API_KEY` | Z.ai inference (Coding Plan in the example configuration) | [Z.ai](https://z.ai/model-api) · [docs](https://docs.z.ai/) | Default `config.json` |
| `FLOCK_API_KEY` | Secondary provider | [FLock](https://platform.flock.io) · [docs](https://docs.flock.io/flock-products/api-platform/getting-started) | When using FLock |
| `FIRECRAWL_API_KEY` | Research scraping via `firecrawl-mcp` | [Firecrawl](https://www.firecrawl.dev) | Heavy / gated sponsor docs |
| `E2B_API_KEY` | Phase 6 sandbox tests | [E2B](https://e2b.dev/docs/api-key) | `subagents.testing.sandbox = "e2b"` |
| `BRAVE_API_KEY` | Optional web search | [Brave Search API](https://brave.com/search/api/) | Brave tool enabled |
| `claude` CLI | Claude Code backend | [Anthropic docs](https://docs.anthropic.com/en/docs/claude-code/getting-started) | Coding/testing `backend = "claude_code"` |

**Suggested order:** `ZAI_API_KEY` first → add `FIRECRAWL_API_KEY` before research on doc-heavy tracks → `E2B_API_KEY` before sandbox testing → FLock / Brave only if you turn those on.

The example configuration uses the Z.ai Coding Plan endpoint
`https://api.z.ai/api/coding/paas/v4` for OpenAI-compatible requests. For a
standard API account, set `providers.zhipu.apiBase` (and `providers.custom.apiBase`
if using that provider) to `https://api.z.ai/api/paas/v4` instead. The Claude Code
backend uses the separate Anthropic-compatible endpoint
`https://api.z.ai/api/anthropic`. Choose the endpoint and key appropriate to your
account; see the [official endpoint guide](https://docs.z.ai/devpack/tool/others).

```bash
npm install -g @anthropic-ai/claude-code
claude   # one-time login
```

Firecrawl is spawned from `0xclaw/config/config.json` with `npx -y firecrawl-mcp`, so **Node/npm** must be available when that path is enabled. It can still hit CAPTCHA / Cloudflare; pass stable doc roots with `docs=<url1>,<url2>` on the research command when possible.

**Limits (short):** E2B does not bypass third-party auth or private registries — put anything the build needs into the generated project’s `.env.example` / README. Run `python -m pytest tests` after installing dev extras; install both optional components to include their CLI compatibility tests. These tests simulate external model responses. There is no checked-in CI workflow yet.

`requirements.txt` mirrors runtime deps for non-editable installs.

---

## 🦀 Run

```bash
conda activate 0xclaw
0xclaw                 # interactive CLI
0xclaw --logs          # verbose logging
0xclaw gateway         # messaging channels (see config)
0xclaw whatsapp login  # QR login; state under ~/.0xclaw/
```

- **`./scripts/start.sh`** — optional wrapper (conda + `.env` + `0xclaw`).
- **`./scripts/verify_setup.sh`** — preflight only, not the runtime.
- **`scripts/run_phase.py`** — single-phase debugging.
- **`scripts/hackathon_runner.py`** — legacy path; prefer the main CLI + `/resume`.

Telegram: set `channels.telegram` in `0xclaw/config/config.json`, then `0xclaw gateway` (long polling, no public webhook). WhatsApp: configure `channels.whatsapp`, run `0xclaw whatsapp login`, then gateway.

---


### Optional BudgetRouter and DeadlineFramer

The paper's control layer is distributed in separate repositories. The default
0xClaw installation runs without these components or model dependencies.

| Component | Download and installation | Purpose |
| --- | --- | --- |
| BudgetRouter | [budget-router](https://github.com/0xclaw-ai/budget-router) | Local model inference and phase budget adjustment |
| DeadlineFramer | [deadline-framer](https://github.com/0xclaw-ai/deadline-framer) | Deadline guidance from control tokens and prior phase usage |
| Training pipeline | [budget-router-trainer](https://github.com/0xclaw-ai/budget-router-trainer) | Dataset preparation and LoRA training |
| Trained adapter | [Hugging Face](https://huggingface.co/0xclaw-ai/budgetrouter-qwen3.5-2b-lora) | LoRA weights for [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) |
| Sanitized dataset | [Hugging Face Dataset](https://huggingface.co/datasets/0xclaw-ai/budgetrouter-hackrep) | Redacted training splits, provenance, and source license notes |

Install each component into the same Python environment as 0xClaw:

```bash
git clone https://github.com/0xclaw-ai/budget-router.git
git clone https://github.com/0xclaw-ai/deadline-framer.git
python -m pip install -e ./budget-router -e ./deadline-framer
```

Download the base model and adapter using the commands in the
[BudgetRouter README](https://github.com/0xclaw-ai/budget-router/blob/main/USAGE.md#download-the-model).
Set their local paths in the shell, or add these settings to the 0xClaw `.env`:

```dotenv
OXCLAW_PHASE_CONTROLS=budget-router,deadline-framer
OXCLAW_BUDGET_ROUTER_MODEL_PATH=./models/qwen3.5-2b
OXCLAW_BUDGET_ROUTER_ADAPTER_PATH=./models/budgetrouter-lora
```

Model paths are relative to the 0xClaw checkout. Launch `0xclaw` as usual.
The component hooks run for normal phase commands, `/resume`, and `/redo` in
the interactive pipeline. Gateway messages and the legacy single-phase scripts
do not use these hooks.

Use `OXCLAW_PHASE_CONTROLS=budget-router` for budget adjustment alone. For
DeadlineFramer without model inference, follow its
[standalone instructions](https://github.com/0xclaw-ai/deadline-framer/blob/main/USAGE.md#use-with-0xclaw).
Leave `OXCLAW_PHASE_CONTROLS` empty and unset `OXCLAW_ENABLE_BUDGET_DEADLINE` to
disable both. `OXCLAW_ENABLE_BUDGET_DEADLINE=1` is also accepted as shorthand
for enabling both installed components in the order shown above.

Component logs stay under `workspace/hackathon/` and are ignored by Git.

---

## 👾 Demo Video

<div align="center">
  <a href="https://www.youtube.com/watch?v=jmamrAxRuec">
    <img src="https://img.youtube.com/vi/jmamrAxRuec/maxresdefault.jpg" alt="0xClaw Demo Video" style="width:80%;">
  </a>
</div>

Example prompts:

```text
research <hackathon_url> docs=<sponsor_docs>,<sdk_docs>
generate project ideas
plan the architecture
implement the project
run tests
write the documentation
```

Research uses sitemap expansion in `0xclaw/orchestration/doc_explorer.py` for `docs=` roots; `workspace/skills/hackathon-research/SKILL.md` defines scraping and `sources[]` citation rules.

---

## ⌨️ CLI

Sessions are JSONL under `workspace/sessions/` (`cli:…` keys). Each launch starts a fresh `cli:run-…` until you attach another thread.

| Command | Meaning |
| --- | --- |
| `/status` | Pipeline state, active session, token usage |
| `/resume` · `/resume N` | Pick a conversation, then continue from `pipeline_state.json` |
| `/sessions` · `/sessions N` | List or switch session without running the pipeline |
| `/session …` | Switch, rename, or picker — see `/help` |
| `/redo <phase>` | Reset phase and downstream, then re-run |
| `/new` | Clear hackathon artefacts + new CLI thread + agent `/new` |
| `/stop` | Cancel current work |
| `/help` · `?` | Help |
| `!<cmd>` | Shell passthrough (same privileges as your user) |

At the `/resume` row prompt, `cancel` / `q` or Ctrl+C aborts without changing the active thread. Long phases may continue in the background; Ctrl+C interrupts the current wait, not the whole CLI — use `/exit` to quit.

After all seven phases finish, continue in chat to iterate on the existing project.
Follow-up turns may update `hackathon/project/` and `hackathon/progress.md`; use an
explicit phase command for other pipeline artifacts. Active conversation output
renews the idle timeout. Phase execution retains its configured time budget,
including adjustments made by BudgetRouter.

---

## 🧠 Models

Default pipeline model is **`glm-5.1`** (see `0xclaw/config/model_profiles.json` for per-phase overrides and timeouts). Inference is wired for **Z.ai** and **FLock.io** via `0xclaw/config/config.json`.

Per-phase model, timeout, and token settings are defined in `0xclaw/config/model_profiles.json` (source of truth).

## 💬 Channels

Runtime includes adapters for **Telegram, Discord, Slack, Email, Feishu, DingTalk, Matrix, WeChat Work, QQ, WhatsApp** (coverage varies by platform). Enable each in `0xclaw/config/config.json` plus the matching env / token from provider docs.
