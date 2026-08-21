"""Pure helpers for the combat-strategy queue.

The screen-driving code lives in :mod:`script`, but the decision to switch to
full auto must depend only on whether the configured queue is actually empty.
Keeping that rule here makes it small enough to test without an emulator.
"""

from enum import Enum


def target_probe_points(next_position):
    """Return deterministic tap points around the combat target selector.

    The selector arrow can be detected a few pixels differently between
    emulator frames.  A fixed, bounded probe sequence is safer than random
    taps because it is reproducible and keeps every retry inside the intended
    target row.
    """

    if not isinstance(next_position, (list, tuple)) or len(next_position) != 2:
        return ()
    try:
        x, y = (int(next_position[0]), int(next_position[1]))
    except (TypeError, ValueError):
        return ()

    points = (
        (x, y + 150),
        (x, y + 125),
        (x - 72, y + 150),
        (x + 72, y + 150),
        (x, y + 200),
    )
    unique = []
    for point in points:
        if point not in unique:
            unique.append(point)
    return tuple(unique)


class SkillExecutionResult(Enum):
    """Outcome of one configured character action."""

    SUCCESS = "success"
    FAILED = "failed"
    FALLBACK = "fallback"


class AutoCombatVisualState(Enum):
    """What can currently be established from the auto-combat control."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    NOT_ACTIONABLE = "not_actionable"
    UNKNOWN = "unknown"


class AutoCombatTransitionAction(Enum):
    """The next non-blocking action for an auto-combat state request."""

    CONFIRMED = "confirmed"
    PRESS = "press"
    WAIT = "wait"
    TIMED_OUT = "timed_out"


class AutoCombatTransitionTracker:
    """Track an auto-combat toggle across frames where its button disappears.

    A character action can hide the control immediately after a successful tap.
    The transition therefore remains pending until a later actionable frame
    confirms the requested state.  Timeouts are emitted only once per request.
    """

    def __init__(self, retry_seconds=1.0, timeout_seconds=10.0, max_commands=2):
        self.retry_seconds = max(0.0, float(retry_seconds))
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.max_commands = max(1, int(max_commands))
        self.reset()

    def reset(self):
        self.desired_enabled = None
        self.started_at = 0.0
        self.last_command_at = None
        self.command_count = 0
        self.opposite_observation_count = 0
        self.warning_emitted = False

    def _start(self, desired_enabled, now):
        self.desired_enabled = bool(desired_enabled)
        self.started_at = float(now)
        self.last_command_at = None
        self.command_count = 0
        self.opposite_observation_count = 0
        self.warning_emitted = False

    def pending_seconds(self, now):
        if self.desired_enabled is None:
            return 0.0
        return max(0.0, float(now) - self.started_at)

    def mark_command(self, desired_enabled, now):
        """Record a toggle sent outside :meth:`request`, such as a short pulse."""

        desired_enabled = bool(desired_enabled)
        if self.desired_enabled != desired_enabled:
            self._start(desired_enabled, now)
        self.command_count += 1
        self.opposite_observation_count = 0
        self.last_command_at = float(now)

    def request(self, desired_enabled, visual_state, now):
        """Return the next action without sleeping or guessing on a hidden UI."""

        desired_enabled = bool(desired_enabled)
        now = float(now)
        if self.desired_enabled != desired_enabled:
            self._start(desired_enabled, now)

        target_state = (
            AutoCombatVisualState.ENABLED
            if desired_enabled
            else AutoCombatVisualState.DISABLED
        )
        opposite_state = (
            AutoCombatVisualState.DISABLED
            if desired_enabled
            else AutoCombatVisualState.ENABLED
        )

        if visual_state is target_state:
            self.reset()
            return AutoCombatTransitionAction.CONFIRMED

        if visual_state is opposite_state:
            first_command = self.command_count == 0
            if not first_command:
                self.opposite_observation_count += 1
            retry_ready = (
                self.command_count < self.max_commands
                and self.last_command_at is not None
                and now - self.last_command_at >= self.retry_seconds
                and self.opposite_observation_count >= 2
            )
            if first_command or retry_ready:
                self.command_count += 1
                self.opposite_observation_count = 0
                self.last_command_at = now
                return AutoCombatTransitionAction.PRESS
        else:
            self.opposite_observation_count = 0

        if (
            not self.warning_emitted
            and self.pending_seconds(now) >= self.timeout_seconds
        ):
            self.warning_emitted = True
            return AutoCombatTransitionAction.TIMED_OUT

        return AutoCombatTransitionAction.WAIT


def should_activate_auto_combat(current_strategy, full_auto_group_name):
    """Return whether a strategy is ready for unrestricted auto combat."""

    if not current_strategy:
        return True
    if current_strategy.get("group_name", "") == full_auto_group_name:
        return True
    return not current_strategy.get("skill_settings", [])


def normalize_strategy_options(
    strategies,
    *,
    legacy_dungeon_reload=False,
    legacy_combat_reload=False,
):
    """Add the per-strategy 2.6 options without overwriting newer settings.

    Versions before 2.6 stored dungeon/combat reload behavior in one global
    setting.  Existing user strategies therefore need defaults derived from
    that legacy value, while strategies already saved by 2.6 must retain their
    explicit choices.
    """

    if not isinstance(strategies, list):
        return strategies

    normalized = []
    for strategy in strategies:
        if not isinstance(strategy, dict):
            normalized.append(strategy)
            continue

        item = strategy.copy()
        item.setdefault(
            "need_reload_when_dungeon_begins", bool(legacy_dungeon_reload)
        )
        item.setdefault(
            "need_reload_when_combat_begins", bool(legacy_combat_reload)
        )
        item.setdefault("complete_one_as_all", False)
        normalized.append(item)
    return normalized


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
            if current_strategy.get("complete_one_as_all", False):
                queue.clear()
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
