"""Dedicated town-to-title state machine."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from .constants import (
    EXIT_MENU_TIMEOUT_SECONDS,
    INPUT_COOLDOWN_SECONDS,
    MAX_EXIT_MENU_BACK_PRESSES,
    STABLE_FRAME_COUNT,
    STABLE_FRAME_INTERVAL_SECONDS,
    TITLE_LOAD_TIMEOUT_SECONDS,
    TOWN_CONFIRM_TIMEOUT_SECONDS,
)
from .fallback import force_stop_game_once
from .models import ControlState, RemoteRecoverySuppressed, TransitionOutcome, TransitionStatus
from .title_screen import title_visible


class TitleTransitionPhase(str, Enum):
    VERIFY_TOWN = "verify_town"
    OPEN_EXIT_MENU = "open_exit_menu"
    WAIT_FOR_TITLE = "wait_for_title"


class TitleTransitionScreen(str, Enum):
    TITLE = "title"
    TO_TITLE_BUTTON = "to_title_button"
    TOWN = "town"
    LOADING = "loading"
    RETRY_DIALOG = "retry_dialog"
    UNKNOWN = "unknown"


def classify_title_transition_screen(adapter: Any, screen: Any) -> tuple[TitleTransitionScreen, list[int] | None]:
    if title_visible(adapter, screen):
        return TitleTransitionScreen.TITLE, None
    position = adapter.match_base(screen, "totitle", ((300, 820, 300, 170),), 0.86)
    if position:
        return TitleTransitionScreen.TO_TITLE_BUTTON, position
    position = adapter.match_base(screen, "totitle", ((180, 650, 540, 500),), 0.92)
    if position:
        return TitleTransitionScreen.TO_TITLE_BUTTON, position
    try:
        if adapter.is_black_frame(screen) or adapter.match_base(screen, "abyssReadying", None, 0.80):
            return TitleTransitionScreen.LOADING, None
    except Exception:
        pass
    position = adapter.match_base(screen, "retry", None, 0.80) or adapter.match_base(screen, "retry_blank", None, 0.80)
    if position:
        return TitleTransitionScreen.RETRY_DIALOG, position
    if any(adapter.match_base(screen, name, None, 0.80) for name in ("Inn", "City_RoyalCityLuknalia", "City_fortress", "City_DHI", "City_portTownGrandLegion")):
        return TitleTransitionScreen.TOWN, None
    return TitleTransitionScreen.UNKNOWN, None


def return_town_to_title(adapter: Any, runtime: Any) -> TransitionOutcome:
    overall_deadline = runtime.stop_deadline_monotonic
    if overall_deadline is None:
        return TransitionOutcome(TransitionStatus.ERROR, "원격 정지 제한 시간이 설정되지 않았습니다.", "missing_stop_deadline")
    phase = TitleTransitionPhase.VERIFY_TOWN
    phase_deadline = min(overall_deadline, time.monotonic() + TOWN_CONFIRM_TIMEOUT_SECONDS)
    back_attempts = 0
    stable_town = 0
    stable_title = 0
    last_input_at = -float("inf")
    title_reopen_used = False
    last_screen = None
    runtime.report_progress(ControlState.RETURNING_TO_TITLE, "타이틀 화면으로 이동 중입니다.")
    try:
        while time.monotonic() < overall_deadline:
            if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
                return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 요청되었습니다.", "local_stop")
            if runtime.is_timeout_fallback_started():
                return force_stop_game_once(adapter, runtime, failure_phase=phase.value)
            screen = adapter.screenshot()
            last_screen = screen
            state, position = classify_title_transition_screen(adapter, screen)
            if state is TitleTransitionScreen.TITLE:
                stable_title += 1
                if stable_title >= STABLE_FRAME_COUNT:
                    return TransitionOutcome(TransitionStatus.AT_TITLE, "타이틀 화면을 확인했습니다.")
                adapter.sleep(STABLE_FRAME_INTERVAL_SECONDS)
                continue
            stable_title = 0
            if phase is TitleTransitionPhase.VERIFY_TOWN:
                stable_town = stable_town + 1 if state is TitleTransitionScreen.TOWN else 0
                if stable_town >= STABLE_FRAME_COUNT:
                    phase = TitleTransitionPhase.OPEN_EXIT_MENU
                    phase_deadline = min(overall_deadline, time.monotonic() + EXIT_MENU_TIMEOUT_SECONDS)
                    continue
            elif phase is TitleTransitionPhase.OPEN_EXIT_MENU:
                if state is TitleTransitionScreen.TO_TITLE_BUTTON:
                    _press(adapter, runtime, position)
                    phase = TitleTransitionPhase.WAIT_FOR_TITLE
                    phase_deadline = min(overall_deadline, time.monotonic() + TITLE_LOAD_TIMEOUT_SECONDS)
                    continue
                if state is TitleTransitionScreen.TOWN and back_attempts < MAX_EXIT_MENU_BACK_PRESSES and time.monotonic() - last_input_at >= INPUT_COOLDOWN_SECONDS:
                    _press_back(adapter, runtime)
                    back_attempts += 1
                    last_input_at = time.monotonic()
                    adapter.sleep(2)
                    continue
            else:
                if state is TitleTransitionScreen.RETRY_DIALOG:
                    _press(adapter, runtime, position)
                elif state is TitleTransitionScreen.TOWN and not title_reopen_used:
                    title_reopen_used = True
                    phase = TitleTransitionPhase.OPEN_EXIT_MENU
                    phase_deadline = min(overall_deadline, time.monotonic() + EXIT_MENU_TIMEOUT_SECONDS)
                    continue
                elif state is TitleTransitionScreen.LOADING:
                    adapter.sleep(0.75)
            if time.monotonic() >= phase_deadline:
                break
            adapter.sleep(0.5)
        if last_screen is not None:
            adapter.save_failure_frame(last_screen, phase.value)
        return force_stop_game_once(adapter, runtime, failure_phase=phase.value)
    except adapter.local_stop_exception_type:
        return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 요청되었습니다.", "local_stop")
    except RemoteRecoverySuppressed as exc:
        return force_stop_game_once(adapter, runtime, failure_phase=f"suppressed_{exc.operation}")
    except Exception:
        if last_screen is not None:
            adapter.save_failure_frame(last_screen, f"{phase.value}_error")
        return force_stop_game_once(adapter, runtime, failure_phase=f"{phase.value}_error")


def _press(adapter, runtime, position):
    if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
        raise adapter.local_stop_exception_type()
    return adapter.press(position)


def _press_back(adapter, runtime):
    if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
        raise adapter.local_stop_exception_type()
    adapter.press_back()

