"""Wait for conversational activity while preserving explicit phase budgets."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


async def wait_for_turn(
    done: asyncio.Event,
    *,
    started_at: float,
    last_activity: Callable[[], float],
    timeout_s: float,
    phase: str | None = None,
) -> str | None:
    """Return the timeout reason, or None when the turn finishes.

    Conversation activity renews the idle deadline. A phase also retains its
    original wall-clock deadline, including any adjustment by BudgetRouter.
    """
    while not done.is_set():
        now = time.monotonic()
        idle_remaining = last_activity() + timeout_s - now
        remaining = idle_remaining
        if phase is not None:
            phase_remaining = started_at + timeout_s - now
            if phase_remaining <= 0:
                return "phase"
            remaining = min(remaining, phase_remaining)
        if idle_remaining <= 0:
            return "idle"
        try:
            await asyncio.wait_for(done.wait(), timeout=min(5.0, remaining))
        except asyncio.TimeoutError:
            pass
    return None
