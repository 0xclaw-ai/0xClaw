from __future__ import annotations

import importlib
import os


def _load_mod():
    mod = importlib.import_module("0xclaw.observability.anyway")
    return importlib.reload(mod)


def test_init_disabled_without_key(monkeypatch):
    mod = _load_mod()
    monkeypatch.delenv("ANYWAY_API_KEY", raising=False)
    assert mod.init_anyway_from_env() is False


def test_init_uses_endpoint_priority(monkeypatch):
    mod = _load_mod()
    calls = []

    class FakeTraceloop:
        @staticmethod
        def init(**kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("ANYWAY_API_KEY", "k")
    monkeypatch.setenv("ANYWAY_API_ENDPOINT", "https://trace-dev-collector.anyway.sh/")
    monkeypatch.setenv("ANYWAY_COLLECTOR", "https://legacy-collector.anyway.sh/")
    monkeypatch.setenv("ANYWAY_APP_NAME", "app-from-env")
    monkeypatch.setattr(mod, "_get_traceloop_cls", lambda: FakeTraceloop)

    assert mod.init_anyway_from_env(app_name_override="override-app") is True
    assert len(calls) == 1
    assert calls[0]["api_endpoint"] == "https://trace-dev-collector.anyway.sh/"
    assert calls[0]["app_name"] == "override-app"
    assert calls[0]["headers"] == {"Authorization": "k"}


def test_init_is_idempotent(monkeypatch):
    mod = _load_mod()
    counter = {"n": 0}

    class FakeTraceloop:
        @staticmethod
        def init(**_kwargs):
            counter["n"] += 1

    monkeypatch.setenv("ANYWAY_API_KEY", "k")
    monkeypatch.setattr(mod, "_get_traceloop_cls", lambda: FakeTraceloop)

    assert mod.init_anyway_from_env() is True
    assert mod.init_anyway_from_env() is True
    assert counter["n"] == 1


def test_init_failure_degrades_gracefully(monkeypatch):
    mod = _load_mod()

    class BrokenTraceloop:
        @staticmethod
        def init(**_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setenv("ANYWAY_API_KEY", "k")
    monkeypatch.setattr(mod, "_get_traceloop_cls", lambda: BrokenTraceloop)

    assert mod.init_anyway_from_env() is False


def test_metrics_disabled_by_default(monkeypatch):
    mod = _load_mod()

    class FakeTraceloop:
        @staticmethod
        def init(**_kwargs):
            return None

    monkeypatch.setenv("ANYWAY_API_KEY", "k")
    monkeypatch.delenv("ANYWAY_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("TRACELOOP_METRICS_ENABLED", raising=False)
    monkeypatch.setattr(mod, "_get_traceloop_cls", lambda: FakeTraceloop)

    assert mod.init_anyway_from_env() is True
    assert os.getenv("TRACELOOP_METRICS_ENABLED") == "false"
