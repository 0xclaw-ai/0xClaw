"""Phase-aware filesystem write guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .state import OrchestratorStateMachine

WriteGuard = Callable[[str], str | None]
PhaseGetter = Callable[[], str | None]


def build_phase_write_guard(
    *,
    workspace: Path,
    state_machine: OrchestratorStateMachine,
    get_phase: PhaseGetter,
) -> WriteGuard:
    workspace_root = workspace.resolve()

    def _guard(path: str) -> str | None:
        phase = get_phase()
        if not phase:
            return None

        p = Path(path).expanduser()
        if not p.is_absolute():
            p = workspace_root / p
        resolved = p.resolve()

        try:
            rel = resolved.relative_to(workspace_root).as_posix()
        except ValueError:
            return f"Path '{path}' is outside workspace"

        try:
            state_machine.assert_write_allowed(phase, rel)
        except PermissionError as e:
            return str(e)
        return None

    return _guard


def install_phase_write_guards(registry: Any, guard: WriteGuard) -> None:
    """Wrap write/edit tools so path checks run before file mutations."""
    for tool_name in ("write_file", "edit_file"):
        tool = registry.get(tool_name)
        if tool is None:
            continue

        original = tool.execute

        async def guarded_execute(*args, __original=original, **kwargs):  # type: ignore[no-untyped-def]
            path = kwargs.get("path")
            if isinstance(path, str):
                err = guard(path)
                if err:
                    return f"Error: {err}"
            return await __original(*args, **kwargs)

        tool.execute = guarded_execute  # type: ignore[method-assign]
