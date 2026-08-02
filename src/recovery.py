"""Pure state for collecting dungeon recovery requests."""

from enum import Enum


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
