"""Deterministic chest-screen guard decisions.

Chest interaction markers always take precedence over the small, generic
``dialogueNext`` icon.  The latter can correlate with animated dungeon
backgrounds, so it is only probed after every chest marker is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


CHEST_INTERACTION_PATTERNS = (
    "chestFlag",
    "whowillopenit",
    "chestOpening",
)
DIALOGUE_NEXT_ROI = [[750, 1400, 150, 200]]
DIALOGUE_NEXT_THRESHOLD = 0.95
MAX_DIALOGUE_SKIP_ATTEMPTS = 3


class ChestGuardAction(Enum):
    NONE = "none"
    OPEN_CHEST = "open_chest"
    KEEP_CHEST_STATE = "keep_chest_state"
    SKIP_DIALOGUE = "skip_dialogue"


@dataclass(frozen=True)
class ChestGuardDecision:
    action: ChestGuardAction
    position: Any = None
    marker: str | None = None


def decide_chest_guard_action(
    screen: Any,
    check_if: Callable[..., Any],
    check_if_at_threshold: Callable[..., Any],
) -> ChestGuardDecision:
    """Classify the actionable chest phase without allowing dialogue steals."""

    for marker in CHEST_INTERACTION_PATTERNS:
        position = check_if(screen, marker)
        if position:
            action = (
                ChestGuardAction.OPEN_CHEST
                if marker == "chestFlag"
                else ChestGuardAction.KEEP_CHEST_STATE
            )
            return ChestGuardDecision(action, position, marker)

    dialogue_position = check_if_at_threshold(
        screen,
        "dialogueNext",
        threshold=DIALOGUE_NEXT_THRESHOLD,
        roi=DIALOGUE_NEXT_ROI,
    )
    if dialogue_position:
        return ChestGuardDecision(
            ChestGuardAction.SKIP_DIALOGUE,
            dialogue_position,
            "dialogueNext",
        )

    return ChestGuardDecision(ChestGuardAction.NONE)
