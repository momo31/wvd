"""Pure state helpers for bounded dungeon and device recovery."""

from enum import Enum
import time


class RecoveryReason(Enum):
    CHEST = "chest"
    COMBAT = "combat"
    DUNGEON_START = "dungeon_start"
    REVIVE = "revive"


class RecoveryPlan:
    """Keep enabled recovery reasons until recovery succeeds."""

    def __init__(self):
        self._reasons = []

    @property
    def reasons(self):
        return tuple(self._reasons)

    @property
    def should_recover(self):
        return bool(self._reasons)

    def request(self, reason, *, enabled=True):
        if not enabled:
            return False
        if reason not in self._reasons:
            self._reasons.append(reason)
        return True

    def complete(self):
        self._reasons.clear()


class RecoverySupervisor:
    """Bound repeated recovery actions until a stable screen is observed.

    The automation can recover from a transient game or emulator failure, but
    repeated recovery without ever reaching an actionable screen is itself a
    failure mode.  This small state machine keeps the policy independent from
    Tkinter/ADB code so the escalation and circuit-breaker behavior can be
    tested without an emulator.
    """

    def __init__(
        self,
        *,
        restart_window_seconds=180.0,
        rapid_restart_limit=4,
        max_emulator_restarts_without_stable=2,
        clock=None,
    ):
        self.restart_window_seconds = float(restart_window_seconds)
        self.rapid_restart_limit = int(rapid_restart_limit)
        self.max_emulator_restarts_without_stable = int(
            max_emulator_restarts_without_stable
        )
        self._clock = clock or time.monotonic
        self._restart_times = []
        self._emulator_restarts_without_stable = 0

    @property
    def restart_times(self):
        """Return the current in-window app restart timestamps."""

        return tuple(self._restart_times)

    @property
    def emulator_restarts_without_stable(self):
        return self._emulator_restarts_without_stable

    def _now(self, now):
        return float(self._clock() if now is None else now)

    def _prune(self, now):
        cutoff = now - self.restart_window_seconds
        self._restart_times = [stamp for stamp in self._restart_times if stamp >= cutoff]

    def note_app_restart(self, now=None):
        """Record an app restart and report whether it is occurring rapidly."""

        now = self._now(now)
        self._prune(now)
        self._restart_times.append(now)
        return len(self._restart_times) >= self.rapid_restart_limit

    def request_emulator_restart(self):
        """Allow one emulator escalation, or trip the circuit breaker."""

        if (
            self._emulator_restarts_without_stable
            >= self.max_emulator_restarts_without_stable
        ):
            return False
        self._emulator_restarts_without_stable += 1
        return True

    def mark_stable(self):
        """Clear recovery history after an actionable screen is identified."""

        self._restart_times.clear()
        self._emulator_restarts_without_stable = 0
