import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).parents[1] / "0xclaw/orchestration/phase_controls.py"
spec = importlib.util.spec_from_file_location("phase_controls_under_test", path)
controls = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = controls
spec.loader.exec_module(controls)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("OXCLAW_PHASE_CONTROLS", raising=False)
    monkeypatch.delenv("OXCLAW_ENABLE_BUDGET_DEADLINE", raising=False)


def test_disabled_does_not_discover_or_load_plugins(monkeypatch, tmp_path):
    monkeypatch.setattr(controls, "entry_points", lambda **kw: pytest.fail("discovery when disabled"))
    profile = object()
    run = controls.load_phase_controls(root=tmp_path, workspace=tmp_path).prepare("coding", "build", profile)
    assert run.profile is profile
    assert run.frame("original message") == "original message"


def test_missing_enabled_plugin_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setenv("OXCLAW_PHASE_CONTROLS", "missing")
    monkeypatch.setattr(controls, "entry_points", lambda **kw: [])
    with pytest.raises(RuntimeError, match="installation instructions"):
        controls.load_phase_controls(root=tmp_path, workspace=tmp_path)


def test_plugin_order_shared_context_and_separate_runs(monkeypatch, tmp_path):
    events = []

    class Plugin:
        def __init__(self, name):
            self.name = name

        def prepare(self, phase, command, profile, context):
            events.append(self.name)
            context[self.name] = command
            return profile + 1

        def frame(self, phase, message, context):
            return message + self.name + context[self.name]

    entries = [SimpleNamespace(name=n, load=lambda n=n: lambda **kw: Plugin(n)) for n in ["first", "second"]]
    monkeypatch.setattr(controls, "entry_points", lambda **kw: entries)
    monkeypatch.setenv("OXCLAW_PHASE_CONTROLS", "first,second,first")
    loaded = controls.load_phase_controls(root=tmp_path, workspace=tmp_path)
    one = loaded.prepare("coding", "one", 10)
    two = loaded.prepare("testing", "two", 20)
    assert events == ["first", "second", "first", "second"]
    assert (one.profile, two.profile) == (12, 22)
    assert one.frame("task:") == "task:firstonesecondone"
    assert two.frame("task:") == "task:firsttwosecondtwo"


def test_combined_shorthand_loads_router_before_framer(monkeypatch, tmp_path):
    loaded = []
    entries = [SimpleNamespace(name=n, load=lambda n=n: lambda **kw: loaded.append(n))
               for n in ["deadline-framer", "budget-router"]]
    monkeypatch.setattr(controls, "entry_points", lambda **kw: entries)
    monkeypatch.setenv("OXCLAW_ENABLE_BUDGET_DEADLINE", "1")
    controls.load_phase_controls(root=tmp_path, workspace=tmp_path)
    assert loaded == ["budget-router", "deadline-framer"]
