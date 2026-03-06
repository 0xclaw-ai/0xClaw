from __future__ import annotations

from pathlib import Path


def test_resume_from_cancelled_phase(tmp_path, state_mod, session_mod):
    workspace = tmp_path / "workspace"
    hackathon = workspace / "hackathon"
    hackathon.mkdir(parents=True)

    store = state_mod.PipelineStateStore(hackathon)
    store.set_phase_status("research", "done")
    store.set_phase_status("idea", "done")
    store.set_phase_status("planning", "cancelled", last_error="ctrl+c")

    ctl = session_mod.SessionControl(store)
    decision = ctl.get_resume_decision()

    assert decision.phase == "planning"
    assert decision.command == "plan architecture"


def test_session_persists_after_reload(tmp_path):
    import sys
    import types

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "0xclaw" / "framework"))
    if "loguru" not in sys.modules:
        fake_logger = types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        )
        sys.modules["loguru"] = types.SimpleNamespace(logger=fake_logger)
    from nanobot.session.manager import SessionManager

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    sm = SessionManager(workspace)
    s = sm.get_or_create("cli:direct")
    s.add_message("user", "hello")
    sm.save(s)

    sm2 = SessionManager(workspace)
    s2 = sm2.get_or_create("cli:direct")
    assert len(s2.messages) == 1
    assert s2.messages[0]["content"] == "hello"


def test_main_stop_routes_to_agentloop():
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    assert 'lower == "/stop"' in content
    assert '_send_and_wait_traced(' in content


def test_main_has_router_and_state_gate():
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    assert "router.route(user_input)" in content
    assert "validate_phase_entry(route.phase)" in content


def test_main_wraps_phase_command_in_envelope():
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    assert "Envelope.from_command(" in content
    assert "You are executing a single pipeline phase." in content


def test_main_phase_wait_guard_for_spawn_started():
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    assert "_is_spawn_started_message(" in content
    assert "do not spawn duplicates" in content


def test_main_new_clears_session_and_hackathon_outputs():
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")
    assert '"/new", "/reset"' in content or '"/reset"' in content
    assert '_send_and_wait_traced(' in content
    assert "_reset_hackathon_outputs()" in content
    assert "_reset_workspace_runtime_outputs()" in content
