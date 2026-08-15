"""Small, deterministic guards for detecting a stalled UI phase.

The game screen contains animated backgrounds, so a raw screenshot hash is not
useful for deciding whether an action made progress.  This module tracks a
caller-provided *semantic* phase key instead.  Repeated input does not reset
the timer; only a new phase does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NETWORK_STALL_SECONDS = 30.0
NETWORK_PROBE_COOLDOWN_SECONDS = 15.0


@dataclass
class NetworkStallTracker:
    """Track how long one logical UI phase has remained unchanged.

    ``phase_key`` should describe a semantic state such as
    ``("chest", "open_chest", "chestFlag")``.  Calling :meth:`observe` with
    the same key does not move the start time, even when the caller pressed a
    button in between.  A probe is allowed after the configured stall period,
    then at most once per cooldown period while the phase remains unchanged.
    """

    stall_seconds: float = NETWORK_STALL_SECONDS
    probe_cooldown_seconds: float = NETWORK_PROBE_COOLDOWN_SECONDS
    phase_key: Any = None
    phase_started_at: float | None = None
    last_probe_at: float | None = None

    def observe(self, phase_key: Any, now: float) -> bool:
        """Record a phase and return whether it changed since the last call."""

        if self.phase_key != phase_key or self.phase_started_at is None:
            self.phase_key = phase_key
            self.phase_started_at = float(now)
            self.last_probe_at = None
            return True
        return False

    def stalled(self, now: float) -> bool:
        """Return whether the current phase exceeded the stall threshold."""

        if self.phase_started_at is None:
            return False
        return float(now) - self.phase_started_at >= self.stall_seconds

    def should_probe(self, now: float) -> bool:
        """Return whether a network probe is due for the current phase."""

        if not self.stalled(now):
            return False
        if self.last_probe_at is None:
            return True
        return float(now) - self.last_probe_at >= self.probe_cooldown_seconds

    def mark_probe(self, now: float) -> None:
        """Record a probe attempt without treating it as UI progress."""

        self.last_probe_at = float(now)
