"""Pure helpers for the combat-strategy queue.

The screen-driving code lives in :mod:`script`, but the decision to switch to
full auto must depend only on whether the configured queue is actually empty.
Keeping that rule here makes it small enough to test without an emulator.
"""

from enum import Enum


class SkillExecutionResult(Enum):
    """Outcome of one configured character action."""

    SUCCESS = "success"
    FAILED = "failed"
    FALLBACK = "fallback"


def should_activate_auto_combat(current_strategy, full_auto_group_name):
    """Return whether a strategy is ready for unrestricted auto combat."""

    if not current_strategy:
        return True
    if current_strategy.get("group_name", "") == full_auto_group_name:
        return True
    return not current_strategy.get("skill_settings", [])


def should_preserve_strategy_progress(
    reload_mode, per_dungeon_auto_mode, reason, current_strategy
):
    """Keep a per-dungeon queue across recovery inside the same dungeon."""

    return (
        reload_mode == per_dungeon_auto_mode
        and reason in {"game_restart", "character_death"}
        and bool(current_strategy)
    )


def should_skip_dungeon_strategy_reload(
    reload_mode, per_dungeon_auto_mode, recovery_pending
):
    """Return whether a recovery re-entry must keep the preserved queue."""

    return reload_mode == per_dungeon_auto_mode and bool(recovery_pending)


def complete_strategy_skill(current_strategy, target_skill, result):
    """Remove exactly ``target_skill`` after success or an explicit fallback.

    Identity comparison is deliberate. Two rows may have identical values, and
    completing one row must not accidentally remove a different equal row.
    """

    if result not in {
        SkillExecutionResult.SUCCESS,
        SkillExecutionResult.FALLBACK,
    }:
        return False

    queue = current_strategy.get("skill_settings", [])
    for index, queued_skill in enumerate(queue):
        if queued_skill is target_skill:
            queue.pop(index)
            return True
    return False


def register_skill_failure(failure_counts, target_skill, attempt_limit=2):
    """Record a failed cast and report whether its bounded retry is exhausted.

    ``target_skill`` is keyed by identity because equal strategy rows are still
    independent actions.  The mapping belongs to runtime state and is never
    persisted to the user's strategy configuration.
    """

    attempt_limit = max(1, int(attempt_limit))
    key = id(target_skill)
    attempts = failure_counts.get(key, 0) + 1
    failure_counts[key] = attempts
    return attempts, attempts >= attempt_limit


def clear_skill_failure(failure_counts, target_skill):
    """Forget transient retry state after a strategy row is resolved."""

    failure_counts.pop(id(target_skill), None)
