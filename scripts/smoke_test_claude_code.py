"""Minimal smoke test for Claude Code via ACP."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "0xclaw"))

from runtime.config.schema import Config
from runtime.providers.acp_provider import ACPConfig, ACPProvider

CONFIG_PATH = ROOT / "0xclaw" / "config" / "config.json"


def _load_config() -> Config:
    raw = CONFIG_PATH.read_text(encoding="utf-8")

    def _sub(match: re.Match[str]) -> str:
        import os

        return os.environ.get(match.group(1), "")

    raw = re.sub(r"\$\{([^}]+)\}", _sub, raw)
    data = json.loads(raw)
    data.setdefault("agents", {}).setdefault("defaults", {})["workspace"] = str(ROOT / "workspace")
    return Config.model_validate(data)


def _make_provider(config: Config) -> ACPProvider:
    claude_cfg = config.subagents.claude_code
    return ACPProvider(
        ACPConfig(
            agent=claude_cfg.agent,
            model_id=claude_cfg.model_id,
            cwd=claude_cfg.cwd,
            session_name=claude_cfg.session_name,
            timeout_sec=claude_cfg.timeout_sec,
            acpx_command=claude_cfg.acpx_command,
            approve_all=claude_cfg.approve_all,
        ),
        default_model=config.agents.defaults.model,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Claude Code ACP execution.")
    parser.add_argument(
        "--prompt",
        default=(
            "You are running inside the 0xClaw repository. "
            "Reply with exactly three lines: "
            "1) SMOKE_TEST_OK "
            "2) the absolute current working directory "
            "3) one sentence confirming you can inspect and edit this repo."
        ),
        help="Prompt to send to Claude Code via ACP.",
    )
    args = parser.parse_args()

    config = _load_config()
    provider = _make_provider(config)
    ok, message = provider.preflight()
    print(f"[preflight] {message}")
    if not ok:
        return 1

    try:
        response = await provider.run_prompt(args.prompt)
    except Exception as exc:  # noqa: BLE001
        print("[smoke] FAILED")
        print(str(exc))
        return 1
    finally:
        await provider.close()

    print("[smoke] OK")
    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
