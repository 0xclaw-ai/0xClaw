from __future__ import annotations

import json


def test_profile_resolution(model_mod):
    resolver = model_mod.ModelProfileResolver(__import__("pathlib").Path("0xclaw/config/model_profiles.json"))
    p = resolver.resolve("planning")
    assert p is not None
    assert p.phase == "planning"
    assert p.model


def test_profile_fallback(model_mod, tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "phase": "research",
                        "provider": "flock",
                        "model": "m1",
                        "max_tokens": 100,
                        "temperature": 0.1,
                        "timeout_s": 60,
                        "fallback": "doc",
                    },
                    {
                        "phase": "doc",
                        "provider": "flock",
                        "model": "m2",
                        "max_tokens": 100,
                        "temperature": 0.1,
                        "timeout_s": 60,
                        "fallback": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    resolver = model_mod.ModelProfileResolver(path)
    p = resolver.resolve_with_fallback("research", failed=True)
    assert p is not None
    assert p.phase == "doc"


def test_metrics_logger_writes_jsonl(model_mod, tmp_path):
    metrics = model_mod.MetricsLogger(tmp_path / "metrics.jsonl")
    metrics.log({"phase": "idea", "model": "m", "status": "done", "duration_s": 1.2})
    lines = (tmp_path / "metrics.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["phase"] == "idea"
    assert "ts" in row
