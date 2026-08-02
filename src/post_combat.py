from enum import Enum


class PostCombatDecision(Enum):
    WAIT = "wait"
    COMBAT = "combat"
    CHEST = "chest"
    DUNGEON = "dungeon"


class PostCombatTracker:
    """Distinguish a real dungeon return from the brief pre-chest frame."""

    def __init__(self, stable_dungeon_seconds=2.5):
        self.stable_dungeon_seconds = stable_dungeon_seconds
        self._dungeon_since = None

    def observe(
        self,
        now,
        *,
        combat_active=False,
        chest_active=False,
        dungeon_active=False,
    ):
        if chest_active:
            self._dungeon_since = None
            return PostCombatDecision.CHEST

        if combat_active:
            self._dungeon_since = None
            return PostCombatDecision.COMBAT

        if not dungeon_active:
            self._dungeon_since = None
            return PostCombatDecision.WAIT

        if self._dungeon_since is None:
            self._dungeon_since = now
            return PostCombatDecision.WAIT

        if now - self._dungeon_since >= self.stable_dungeon_seconds:
            return PostCombatDecision.DUNGEON

        return PostCombatDecision.WAIT
