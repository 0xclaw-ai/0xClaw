# 🦀 0xClaw — Autonomous AI Hackathon Competitor

<div align="center">

<img src="assets/0xClaw_combine.png" alt="0xClaw" width="600" />

<br />

<!-- <img src="assets/banner.svg" alt="0xClaw" />

<br /> -->

**🏆 1st Place Winner – Z.ai Bounty @ UK AI Agent Hackathon × OpenClaw 🦞.**

**🏆 Finalist Winner – Anyway Bounty @ UK AI Agent Hackathon × OpenClaw 🦞.**

**Give 0xClaw a hackathon URL — it researches, codes, tests, and submits, all on its own.**

<br />

[![Discord](https://img.shields.io/badge/Discord-Join%20Us-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/rdnYEVdRHe)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](./LICENSE)
[![Z.ai](https://img.shields.io/badge/Z.ai-inference-5b6cf9?style=flat-square)](http://z.ai)
[![FLock.io](https://img.shields.io/badge/FLock.io-inference-7c3aed?style=flat-square)](https://flock.io)

</div>

---

## ⚙️ Setup

```bash
conda create -n 0xclaw python=3.11 -y
conda activate 0xclaw
pip install -e .
cp .env.example .env
./scripts/verify_setup.sh
```

Then fill in the API keys needed for the workflow you want to run:

| Key / tool | Used for | Get it from | Required when |
| --- | --- | --- | --- |
| `ZAI_API_KEY` | Default Z.ai model provider and Claude-compatible coding endpoint | [Z.ai Open Platform](https://z.ai/model-api) / [Z.ai API docs](https://docs.z.ai/) | Running the default config |
| `FLOCK_API_KEY` | Secondary model provider | [FLock Platform](https://platform.flock.io) / [FLock API docs](https://docs.flock.io/flock-products/api-platform/getting-started) | Using the FLock provider |
| `FIRECRAWL_API_KEY` | Research-phase scraping through `firecrawl-mcp` | [Firecrawl dashboard](https://www.firecrawl.dev) / [Firecrawl docs](https://docs.firecrawl.dev/api-reference/v2-introduction) | Researching JS-heavy sponsor docs or protected pages |
| `E2B_API_KEY` | Phase 6 cloud sandbox testing | [E2B dashboard/docs](https://e2b.dev/docs/api-key) | `subagents.testing.sandbox = "e2b"` |
| `BRAVE_API_KEY` | Optional web search fallback | [Brave Search API](https://brave.com/search/api/) | Using the built-in Brave search tool |
| `claude` CLI | Claude Code direct executor | [Claude Code setup docs](https://docs.anthropic.com/en/docs/claude-code/getting-started) | `subagents.coding.backend` or `subagents.testing.backend = "claude_code"` |

Minimal setup flow:

1. Create `.env` from `.env.example`.
2. Add `ZAI_API_KEY` first; the default config uses Z.ai for normal inference
   and for the Claude-compatible coding endpoint.
3. Add `FIRECRAWL_API_KEY` before running research on sponsor/docs-heavy
   hackathons.
4. Add `E2B_API_KEY` before Phase 6 if sandbox testing is enabled.
5. Add `FLOCK_API_KEY` or `BRAVE_API_KEY` only when you enable those providers
   or tools.
6. Install Claude Code if coding/testing is routed through Claude Code.

Install the Claude Code CLI once if you use the Claude Code backend:

```bash
npm install -g @anthropic-ai/claude-code
claude
```

Python packages are installed by `pip install -e .`; development tooling such
as Ruff is installed by `pip install -e .[dev]`. The Firecrawl MCP server is
started from `config.json` with `npx -y firecrawl-mcp`, so Node/npm must also
be available when that tool is enabled.

`Context7` is not required for the current research pipeline. Firecrawl can
still be blocked by CAPTCHA/Cloudflare-style protection, especially on free
plans; pass sponsor docs explicitly with `docs=<url1>,<url2>` so the pipeline
can scrape the API documentation directly.

External service limits to expect:

- Firecrawl is used for research scraping. It may fail on sites protected by
  CAPTCHA, Cloudflare, login walls, or aggressive anti-bot rules. When that
  happens, provide stable sponsor/API documentation roots via `docs=...` and
  treat the blocked hackathon page as requiring human review.
- E2B is used for isolated Phase 6 testing. It needs `E2B_API_KEY` plus enough
  quota, runtime, and network access for dependency installs, test commands,
  and optional smoke servers. E2B is not a bypass for third-party API limits:
  protected websites, private package registries, login-gated services, and
  sponsor APIs still require their own credentials.
- Secrets are explicit. The sandbox does not automatically inherit every local
  credential; document any project-specific keys in the generated project's
  `.env.example` and README so testing can reproduce the environment.

For a quick sanity check after installation:

```bash
python launcher/__main__.py --help
0xclaw --help
```

`pip install -e .` installs both the runtime dependencies and the local CLI in editable mode.
If you also want development tooling such as Ruff, use `pip install -e .[dev]`.
`requirements.txt` is kept as a compatibility mirror of the same runtime dependency set.

## 🚀 Launch

```bash
conda activate 0xclaw
0xclaw           # interactive CLI
0xclaw --logs    # with debug output
0xclaw gateway   # start Telegram/other chat channels from repo config
0xclaw whatsapp login   # start WhatsApp bridge and scan QR
```

`0xclaw` is the canonical runtime entrypoint.
`./scripts/start.sh` is an optional convenience wrapper that activates conda, loads `.env`, then runs `0xclaw`.
`./scripts/verify_setup.sh` is a preflight checker.

Legacy scripts:
- `scripts/run_phase.py`: single-phase engineering/debug runner.
- `scripts/hackathon_runner.py`: deprecated compatibility path; avoid for normal workflow.

Integration docs:
- Claude Code coding backend: `docs/integrations/claude-code-subagent.md`.
- Docs index: `docs/README.md`.


## 👾 Demo Video

<div align="center">
  <a href="https://www.youtube.com/watch?v=jmamrAxRuec">
    <img src="https://img.youtube.com/vi/jmamrAxRuec/maxresdefault.jpg" alt="0xClaw Demo Video" style="width:80%;">
  </a>
</div>

## 🔄 Pipeline

The agent runs a 7-phase pipeline to produce a complete hackathon submission.
Trigger any phase with natural language — routing is automatic.

<div align="center">
<table>
<tr><th>#</th><th>Phase</th><th>Output</th></tr>
<tr><td>1</td><td><b>research</b></td><td><code>hackathon/context.json</code></td></tr>
<tr><td>2</td><td><b>idea</b></td><td><code>hackathon/ideas.json</code></td></tr>
<tr><td>3</td><td><b>selection</b></td><td><code>hackathon/selected_idea.json</code></td></tr>
<tr><td>4</td><td><b>planning</b></td><td><code>hackathon/plan.md</code> · <code>hackathon/tasks.json</code></td></tr>
<tr><td>5</td><td><b>coding</b></td><td><code>hackathon/project/</code></td></tr>
<tr><td>6</td><td><b>testing</b></td><td><code>hackathon/test_results.json</code></td></tr>
<tr><td>7</td><td><b>doc</b></td><td><code>hackathon/submission/</code></td></tr>
</table>
</div>

```
Useful phase prompts:

research <hackathon_url> docs=<sponsor_docs_url>,<sdk_docs_url>
generate project ideas
plan the architecture
implement the project
run tests
write the documentation
```

The research phase now uses deterministic sitemap expansion in
`0xclaw/orchestration/doc_explorer.py`: user-provided `docs=` roots are expanded
before the agent runs, then `workspace/skills/hackathon-research/SKILL.md`
requires those URLs to be scraped and cited in `sources[]`.

## ⌨️ Commands

<div align="center">
<table>
<tr><td><code>/status</code></td><td>Pipeline progress + session token usage</td></tr>
<tr><td><code>/resume</code></td><td>Resume from last checkpoint</td></tr>
<tr><td><code>/redo &lt;phase&gt;</code></td><td>Reset phase and all downstream, then re-run</td></tr>
<tr><td><code>/new</code></td><td>Clear all outputs, fresh start</td></tr>
<tr><td><code>/stop</code></td><td>Cancel running task</td></tr>
<tr><td><code>/help</code></td><td>Show all commands</td></tr>
<tr><td><code>?</code></td><td>Alias for /help</td></tr>
<tr><td><code>!&lt;cmd&gt;</code></td><td>Run a shell command without leaving the agent (e.g. <code>!git status</code>)</td></tr>
</table>
</div>

Long-running phases hand off to the background after the first reply — you can keep chatting while work continues.
**Ctrl+C** interrupts the current task but never exits — type `/exit` to quit.

---

## 🧠 Models

Inference powered by **FLock.io** and **Z.AI**

<div align="center">
<table>
<tr><th>Phases</th><th>Model</th><th>Context</th></tr>
<tr><td>research · idea · selection · doc</td><td><code>minimax-m2.1</code></td><td>196k</td></tr>
<tr><td>planning · coding · testing</td><td><code>minimax-m2.5</code></td><td>205k</td></tr>
</table>
</div>

Per-phase timeout and fallback behavior are defined in `0xclaw/config/model_profiles.json` (source of truth).

## 💬 Channels

The runtime has built-in support for 10 messaging platforms (2/10 now passed solid test). Enable any via `config.json` + one env var:

<div align="center">
<table>
<tr><td>$\color{#25D366}{\textbf{Telegram}}$</td><td><b>Discord</b></td><td><b>Slack</b></td><td><b>Email</b></td><td><b>Feishu</b></td></tr>
<tr><td><b>DingTalk</b></td><td><b>Matrix</b></td><td><b>WeChat Work</b></td><td><b>QQ</b></td><td>$\color{#25D366}{\textbf{WhatsApp}}$</td></tr>
</table>
</div>

Telegram uses long polling — no public IP or webhook required.
Configure it in `0xclaw/config/config.json` under `channels.telegram`, then run `0xclaw gateway`.

WhatsApp uses a local bridge process. Configure `channels.whatsapp`, run `0xclaw whatsapp login` to scan the QR code, then start `0xclaw gateway`. Bridge assets and auth state are stored under `~/.0xclaw/`.

---

<div align="center">

<img src="assets/banner.svg" alt="0xClaw" width="330" />

</div>

<div align="center">
<sub>Built for <a href="https://dorahacks.io/hackathon/1985">UK AI Agent Hackathon EP4</a> in collaboration with 🦞 <a href="https://github.com/openclaw/openclaw">OpenClaw</a>  · Thanks to 🐈 <a href="https://github.com/HKUDS/nanobot">NanoBot</a> Framework</sub>
</div>
