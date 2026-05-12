"""Helpers for CLI multi-conversation pickers (Claude Code–style session list)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from runtime.utils.helpers import safe_filename


def fresh_cli_run_session_key() -> str:
    """Ephemeral CLI thread id for a fresh run (no history until first save)."""
    return f"cli:run-{uuid.uuid4().hex[:12]}"


def cli_talk_key(slug: str) -> str:
    """Normalize user input into a ``cli:…`` session key."""
    slug = (slug or "").strip()
    if not slug or slug.lower() in ("direct", "default"):
        return "cli:direct"
    if slug.startswith("cli:"):
        rest = slug[4:].strip()
        if not rest:
            return "cli:direct"
        return "cli:" + safe_filename(rest)
    return "cli:" + safe_filename(slug)


def filter_cli_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only terminal CLI conversation keys (``cli:*``)."""
    out: list[dict[str, Any]] = []
    for s in sessions:
        key = str(s.get("key", ""))
        if key.startswith("cli:"):
            out.append(s)
    return out


def merge_cli_session_rows(
    sessions: list[dict[str, Any]],
    *,
    active_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Deduplicate by key, ensure ``cli:direct`` is listed for legacy picks, sort by ``sort_ts``.

    If ``active_key`` is set and not yet on disk, a synthetic row is added so the picker
    can show the current CLI thread first (Claude Code–style: new run until user attaches
    an older conversation).
    """
    by_key: dict[str, dict[str, Any]] = {}
    for s in filter_cli_sessions(sessions):
        k = str(s["key"])
        by_key[k] = dict(s)
    if "cli:direct" not in by_key:
        by_key["cli:direct"] = {
            "key": "cli:direct",
            "created_at": None,
            "updated_at": None,
            "path": "",
            "sort_ts": "",
            "display_name": "",
        }
    ak = str(active_key).strip() if active_key else ""
    if ak.startswith("cli:") and ak not in by_key:
        by_key[ak] = {
            "key": ak,
            "created_at": None,
            "updated_at": None,
            "path": "",
            "sort_ts": datetime.now(timezone.utc).isoformat(),
            "display_name": "This CLI run (new thread)",
        }
    rows = list(by_key.values())
    rows.sort(key=lambda x: str(x.get("sort_ts") or ""), reverse=True)
    if ak.startswith("cli:"):
        idx = next((i for i, r in enumerate(rows) if str(r["key"]) == ak), None)
        if idx is not None and idx > 0:
            rows.insert(0, rows.pop(idx))
    return rows


def resolve_session_pick(token: str, rows: list[dict[str, Any]]) -> str | None:
    """
    Resolve a user token to a session key.

    - ``"3"`` → 1-based index into ``rows`` (sorted list).
    - Exact key match (e.g. ``cli:direct``).
    - Otherwise treated as a slug for :func:`cli_talk_key`.
    """
    token = (token or "").strip()
    if token.startswith("/"):
        # Slash commands belong at the main prompt — never turn "/session …" into cli:_… keys.
        return None
    if not token:
        return str(rows[0]["key"]) if rows else None
    if token.isdigit():
        i = int(token)
        if 1 <= i <= len(rows):
            return str(rows[i - 1]["key"])
        return None
    for r in rows:
        if str(r["key"]) == token:
            return str(r["key"])
    return cli_talk_key(token)
