"""Compose town/title transitions and map their result to task exit reasons."""

from __future__ import annotations

from typing import Any

from .fallback import force_stop_game_once
from .models import (
    RemoteRecoverySuppressed,
    RemoteStopSignal,
    TaskExitReason,
    TransitionOutcome,
    TransitionStatus,
)
from .return_to_town import return_to_town
from .title_transition import return_town_to_title


def execute_remote_stop(adapter: Any, runtime: Any, signal: RemoteStopSignal) -> TransitionOutcome:
    result = return_to_town(adapter, runtime, signal)
    if result.status is TransitionStatus.TOWN_READY:
        result = return_town_to_title(adapter, runtime)
    _record_result(runtime, result)
    return result


def execute_recovery_suppressed_fallback(
    adapter: Any,
    runtime: Any,
    suppressed: RemoteRecoverySuppressed,
) -> TransitionOutcome:
    phase = f"suppressed_{suppressed.operation}"
    result = force_stop_game_once(adapter, runtime, failure_phase=phase)
    _record_result(runtime, result, phase)
    return result


def _record_result(runtime: Any, result: TransitionOutcome, phase: str | None = None) -> None:
    failure_phase = result.failure_phase or phase
    if result.status is TransitionStatus.AT_TITLE:
        runtime.mark_exit(TaskExitReason.REMOTE_STOP, result.detail, failure_phase)
    elif result.status is TransitionStatus.FALLBACK_COMPLETE:
        runtime.mark_exit(TaskExitReason.REMOTE_STOP_FALLBACK, result.detail, failure_phase)
    elif result.status is TransitionStatus.LOCAL_ABORT:
        runtime.mark_exit(TaskExitReason.LOCAL_STOP, result.detail, failure_phase)
    else:
        runtime.mark_exit(TaskExitReason.ERROR, result.detail or "안전 정지 작업에 실패했습니다.", failure_phase or "stop_orchestrator")

