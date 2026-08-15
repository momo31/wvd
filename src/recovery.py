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
    """Track, pace, and cap recovery until a stable screen appears."""

    def __init__(
        self,
        *,
        restart_window_seconds=180.0,
        rapid_restart_limit=4,
        minimum_restart_interval_seconds=90.0,
        emulator_restart_backoff_seconds=45.0,
        max_emulator_restart_backoff_seconds=360.0,
        max_emulator_restarts_without_stable=3,
        clock=None,
    ):
        self.restart_window_seconds = float(restart_window_seconds)
        self.rapid_restart_limit = int(rapid_restart_limit)
        self.minimum_restart_interval_seconds = max(
            0.0, float(minimum_restart_interval_seconds)
        )
        self.emulator_restart_backoff_seconds = max(
            0.0, float(emulator_restart_backoff_seconds)
        )
        self.max_emulator_restart_backoff_seconds = max(
            self.emulator_restart_backoff_seconds,
            float(max_emulator_restart_backoff_seconds),
        )
        self.max_emulator_restarts_without_stable = max(
            1, int(max_emulator_restarts_without_stable)
        )
        self._clock = clock or time.monotonic
        self._restart_times = []
        self._emulator_restarts_without_stable = 0
        self._last_app_restart_at = None

    @property
    def restart_times(self):
        """Return the current in-window app restart timestamps."""

        return tuple(self._restart_times)

    @property
    def emulator_restarts_without_stable(self):
        return self._emulator_restarts_without_stable

    @property
    def emulator_restart_delay_seconds(self):
        """Return the exponential wait before the next emulator reset.

        The first reset waits for the base interval.  Each subsequent reset
        without a stable screen doubles the delay up to the configured cap.
        The counter is reset by :meth:`mark_stable`.
        """

        attempt = max(self._emulator_restarts_without_stable - 1, 0)
        if attempt >= 30:
            return self.max_emulator_restart_backoff_seconds
        delay = self.emulator_restart_backoff_seconds * (2**attempt)
        return min(delay, self.max_emulator_restart_backoff_seconds)

    def _now(self, now):
        return float(self._clock() if now is None else now)

    def _prune(self, now):
        cutoff = now - self.restart_window_seconds
        self._restart_times = [stamp for stamp in self._restart_times if stamp >= cutoff]

    def app_restart_cooldown(self, now=None):
        """Return the remaining minimum interval before another app restart."""

        now = self._now(now)
        if self._last_app_restart_at is None:
            return 0.0
        elapsed = max(0.0, now - self._last_app_restart_at)
        return max(0.0, self.minimum_restart_interval_seconds - elapsed)

    def note_app_restart(self, now=None):
        """Record an app restart and report whether it is occurring rapidly."""

        now = self._now(now)
        self._prune(now)
        self._restart_times.append(now)
        self._last_app_restart_at = now
        return len(self._restart_times) >= self.rapid_restart_limit

    def request_emulator_restart(self):
        """Allow a bounded emulator reset until a stable screen is observed."""

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
        self._last_app_restart_at = None
