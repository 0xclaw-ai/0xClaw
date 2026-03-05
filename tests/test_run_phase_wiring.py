from __future__ import annotations

from pathlib import Path


def test_run_phase_non_json_result_gating_logic_present():
    content = Path("scripts/run_phase.py").read_text(encoding="utf-8")
    assert "output_ready: bool = False" in content
    assert "if output_ready:" in content
    assert 'data = {"raw_response": response, "format": "text"}' in content
    assert "kind = \"result\"" in content


def test_run_phase_response_envelope_passes_output_ready():
    content = Path("scripts/run_phase.py").read_text(encoding="utf-8")
    assert "output_ready = _output_exists(output_file)" in content
    assert "output_ready=output_ready" in content


def test_run_phase_has_idle_nudge_flow():
    content = Path("scripts/run_phase.py").read_text(encoding="utf-8")
    assert "IDLE_NUDGE_TIMEOUT_S = 30" in content
    assert "def _is_intent_only_response(response: str) -> bool:" in content
    assert '"has been spawned"' in content
    assert "if auto_nudge_pending and nudge_count < 1:" in content
    assert "await send(CONTINUATION_PROMPT)" in content
