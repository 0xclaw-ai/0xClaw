#!/usr/bin/env python3
"""Regression checks for pipeline reconcile (GitHub-style issues #29 / #30).

#29: ``running`` must stay ``running`` while completion artifacts are still missing
     (``/status`` must not infer ``done`` too early).

#30: ``cancelled`` (and ``failed``) must never be overwritten to ``done`` when
     artifacts imply a higher checkpoint.

Also: bogus ``done``/``complete`` with no artifacts anywhere resets to ``pending``.

Run from repo root::

    PYTHONPATH=0xclaw python scripts/verify_reconcile_issues_29_30.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.state import (  # noqa: E402
    PHASES,
    PipelineStateStore,
    reconcile_pipeline_state,
)


def _fat(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text if len(text) > 10 else text + "x" * (12 - len(text))
    path.write_text(body, encoding="utf-8")


def _minimal_research_artifacts(h: Path) -> None:
    ctx = json.dumps({"sources": [], "title": "t" * 20}, ensure_ascii=False)
    _fat(h / "context.json", ctx)
    _fat(h / "research_summary.md", "# Summary\n\n" + "y" * 20)


def _minimal_ideas_json(h: Path) -> None:
    _fat(h / "ideas.json", json.dumps({"ideas": [{"id": 1, "title": "x" * 30}]}, ensure_ascii=False))


def _set_all_phase_statuses(store: PipelineStateStore, status: str) -> None:
    state = store.load()
    for row in state["phases"]:
        row["status"] = status
    store.save(state)


def _set_phase_status(store: PipelineStateStore, name: str, status: str) -> None:
    state = store.load()
    for row in state["phases"]:
        if row["name"] == name:
            row["status"] = status
            break
    store.save(state)


def _status_map(store: PipelineStateStore) -> dict[str, str]:
    return {r["name"]: r["status"] for r in store.load()["phases"]}


def main() -> int:
    import tempfile

    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        h = root / "hackathon"
        h.mkdir(parents=True)
        store = PipelineStateStore(h)

        # --- #29a: no artifacts, phase running → stays running ---
        _set_phase_status(store, "research", "running")
        reconcile_pipeline_state(store)
        m = _status_map(store)
        if m["research"] != "running":
            failures.append(f"#29a expected research=running, got {m['research']!r}")

        # --- #29b: research complete, idea running without ideas.json → idea stays running ---
        _minimal_research_artifacts(h)
        _set_phase_status(store, "research", "done")
        _set_phase_status(store, "idea", "running")
        reconcile_pipeline_state(store)
        m = _status_map(store)
        if m.get("idea") != "running":
            failures.append(f"#29b expected idea=running, got {m.get('idea')!r}")

        # --- #30: research cancelled but artifacts exist through idea → research stays cancelled ---
        _minimal_ideas_json(h)
        _set_phase_status(store, "research", "cancelled")
        _set_phase_status(store, "idea", "pending")
        reconcile_pipeline_state(store)
        m = _status_map(store)
        if m.get("research") != "cancelled":
            failures.append(f"#30 expected research=cancelled, got {m.get('research')!r}")
        if m.get("idea") != "done":
            failures.append(f"#30 expected idea=done (artifacts present), got {m.get('idea')!r}")

        # --- bogus done with zero artifacts: fresh store ---
        h2 = root / "hackathon2"
        h2.mkdir(parents=True)
        store2 = PipelineStateStore(h2)
        _set_all_phase_statuses(store2, "done")
        reconcile_pipeline_state(store2)
        m2 = _status_map(store2)
        for p in PHASES:
            if m2.get(p) != "pending":
                failures.append(f"bogus-done reset: expected {p}=pending, got {m2.get(p)!r}")

        # --- running + failed unchanged with no artifacts ---
        store3 = PipelineStateStore(root / "hackathon3")
        _set_phase_status(store3, "research", "running")
        _set_phase_status(store3, "idea", "failed")
        reconcile_pipeline_state(store3)
        m3 = _status_map(store3)
        if m3.get("research") != "running":
            failures.append(f"no-artifacts running: expected research=running, got {m3.get('research')!r}")
        if m3.get("idea") != "failed":
            failures.append(f"no-artifacts failed: expected idea=failed, got {m3.get('idea')!r}")

    if failures:
        print("FAIL:\n" + "\n".join(f"  - {f}" for f in failures))
        return 1
    print("OK: reconcile issues #29 / #30 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
