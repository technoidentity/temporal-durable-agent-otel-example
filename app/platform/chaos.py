"""Chaos / fault injection for the agent pipeline.

Faults are described by a small serializable spec that travels with the run
(inside the graph state), so they can be chosen per run and mixed and matched
from the demo UI. Applied inside agent activities:

* ``transient_error`` — fail on the first N attempts, then succeed (shows
  Temporal retrying and recovering);
* ``permanent_error`` — fail on every attempt (activity exhausts retries and the
  workflow fails);
* ``latency`` — sleep N seconds on the first N attempts (if the sleep exceeds the
  activity's start-to-close timeout this becomes a real Temporal timeout + retry);
* ``force_hitl`` — a workflow-level flag that trips the approval gate regardless
  of discount (handled in the order workflow).
"""

from __future__ import annotations

import time
from typing import Callable

MODES = {"none", "transient_error", "permanent_error", "latency"}


class ChaosError(RuntimeError):
    """Raised to simulate an injected failure inside an activity."""


def _current_attempt() -> int:
    """Temporal activity attempt (1-based), or 1 outside an activity context."""
    try:
        import temporalio.activity as activity

        return activity.info().attempt
    except Exception:
        return 1


def _applies_this_attempt(attempts: int) -> bool:
    # attempts == 0 -> apply on every attempt; else only on attempts <= N.
    return attempts == 0 or _current_attempt() <= attempts


def maybe_inject(role: str, chaos: dict | None, *, sleep: Callable[[float], None] = time.sleep) -> str | None:
    """Apply a fault for ``role`` if the spec targets it. Returns the applied
    action label for latency, ``None`` if nothing applied, and raises
    :class:`ChaosError` for error modes."""
    if not chaos:
        return None
    if chaos.get("target") != role:
        return None
    mode = chaos.get("mode", "none")
    if mode in ("none", "", None):
        return None
    if not _applies_this_attempt(int(chaos.get("attempts", 1))):
        return None

    if mode == "permanent_error":
        raise ChaosError(f"chaos permanent_error injected on '{role}'")
    if mode == "transient_error":
        raise ChaosError(f"chaos transient_error injected on '{role}' (attempt {_current_attempt()})")
    if mode == "latency":
        sleep(float(chaos.get("latency_seconds", 0.0)))
        return "latency"
    return None
