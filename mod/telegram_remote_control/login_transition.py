"""Safe login/start gate for Telegram-triggered runs."""

from __future__ import annotations

import re
import time
from typing import Any

from .constants import (
    APP_START_SETTLE_SECONDS,
    DEFAULT_GAME_ACTIVITY,
    GAME_PACKAGE,
    INPUT_COOLDOWN_SECONDS,
    LOGIN_ATTEMPT_TIMEOUT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    TITLE_TAP_FALLBACK_POSITION,
    TO_TITLE_DIALOG_ROI,
    TO_TITLE_DIALOG_THRESHOLD,
    TO_TITLE_PRIMARY_ROI,
    TO_TITLE_PRIMARY_THRESHOLD,
)
from .models import (
    CheckpointKind,
    ControlState,
    RemoteStopSignal,
    TransitionOutcome,
    TransitionStatus,
)
from .title_screen import (
    match_startup_disclaimer,
    match_title_logo,
    match_title_tap,
)


def ensure_game_ready(adapter: Any, runtime: Any) -> TransitionOutcome:
    for attempt in range(MAX_LOGIN_ATTEMPTS):
        try:
            if runtime.is_stop_requested():
                _raise_stop_for_current_screen(adapter, runtime)
            if not _process_running(adapter):
                activity = _resolve_activity(adapter)
                adapter.control_shell(["am", "start", "-n", activity])
                _interruptible_sleep(adapter, runtime, APP_START_SETTLE_SECONDS)
            result = _wait_for_ready(adapter, runtime)
            if result is not None:
                return result
        except RemoteStopSignal:
            raise
        except adapter.local_stop_exception_type:
            return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 요청되었습니다.", "local_stop")
        except Exception:
            pass
        if attempt + 1 < MAX_LOGIN_ATTEMPTS:
            try:
                adapter.control_shell(["am", "force-stop", GAME_PACKAGE])
            except Exception:
                pass
    try:
        adapter.save_failure_frame(adapter.screenshot(), "login_gate")
    except Exception:
        pass
    return TransitionOutcome(TransitionStatus.ERROR, "저장된 게임 세션으로 자동 진입하지 못했습니다.", "login_gate")


def prepare_telegram_run(adapter: Any, runtime: Any) -> bool:
    result = ensure_game_ready(adapter, runtime)
    if result.status is TransitionStatus.GAME_READY:
        runtime.report_progress(ControlState.RUNNING, "게임 로그인과 매크로 준비가 완료되었습니다.")
        return True
    if result.status is TransitionStatus.AT_TITLE and runtime.is_stop_requested():
        runtime.mark_exit("remote_stop", result.detail)
    elif result.status is TransitionStatus.FALLBACK_COMPLETE:
        runtime.mark_exit("remote_stop_fallback", result.detail, result.failure_phase)
    elif result.status is TransitionStatus.LOCAL_ABORT:
        runtime.mark_exit("local_stop", result.detail, result.failure_phase)
    else:
        runtime.mark_exit("error", result.detail or "게임 로그인에 실패했습니다.", result.failure_phase or "login_gate")
    return False


def _wait_for_ready(adapter, runtime) -> TransitionOutcome | None:
    deadline = time.monotonic() + LOGIN_ATTEMPT_TIMEOUT_SECONDS
    startup_disclaimer_tapped = False
    last_session_expiry_tap_at = -float("inf")
    last_title_tap_at = -float("inf")
    while time.monotonic() < deadline:
        if runtime.is_stop_requested():
            _raise_stop_for_current_screen(adapter, runtime)
        screen = adapter.screenshot()
        position = _match(adapter, screen, "totitle", TO_TITLE_PRIMARY_ROI, TO_TITLE_PRIMARY_THRESHOLD)
        if position is None:
            position = _match(adapter, screen, "totitle", TO_TITLE_DIALOG_ROI, TO_TITLE_DIALOG_THRESHOLD)
        if position:
            now = time.monotonic()
            if now - last_session_expiry_tap_at >= INPUT_COOLDOWN_SECONDS:
                _tap_if_allowed(adapter, runtime, position)
                last_session_expiry_tap_at = now
        elif _ready_screen(adapter, screen):
            return TransitionOutcome(TransitionStatus.GAME_READY, "게임 화면을 확인했습니다.")
        elif disclaimer := match_startup_disclaimer(adapter, screen):
            # The disclaimer accepts one tap. Do not repeat it while a delayed
            # transition leaves the same frame visible.
            if not startup_disclaimer_tapped:
                _tap_if_allowed(adapter, runtime, disclaimer)
                startup_disclaimer_tapped = True
        elif match_title_logo(adapter, screen):
            now = time.monotonic()
            if now - last_title_tap_at >= INPUT_COOLDOWN_SECONDS:
                position = match_title_tap(adapter, screen)
                if position is None:
                    # The text blinks, but its touch area is fixed. A stable
                    # logo match makes this fallback safe.
                    position = list(TITLE_TAP_FALLBACK_POSITION)
                _tap_if_allowed(adapter, runtime, position)
                last_title_tap_at = now
        elif _match(adapter, screen, "retry") or _match(adapter, screen, "retry_blank"):
            adapter.try_press_retry(screen)
        elif _is_loading(adapter, screen):
            pass
        adapter.sleep(1)
    return None


def _raise_stop_for_current_screen(adapter, runtime) -> None:
    screen = adapter.screenshot()
    if match_title_logo(adapter, screen):
        raise RemoteStopSignal(CheckpointKind.BETWEEN_OPERATIONS)
    if _match(adapter, screen, "Inn") or any(_match(adapter, screen, name) for name in ("City_RoyalCityLuknalia", "City_fortress", "City_DHI", "City_portTownGrandLegion")):
        raise RemoteStopSignal(CheckpointKind.TOWN_STABLE)
    if _match(adapter, screen, "dungFlag") or _match(adapter, screen, "mapFlag") or _match(adapter, screen, "worldmapflag"):
        raise RemoteStopSignal(CheckpointKind.DUNGEON_STABLE)
    if _match(adapter, screen, "combatActive"):
        adapter.finish_combat_or_chest("combat")
        raise RemoteStopSignal(CheckpointKind.DUNGEON_STABLE)
    if any(_match(adapter, screen, name) for name in ("chestFlag", "whowillopenit", "chestOpening")):
        adapter.finish_combat_or_chest("chest")
        raise RemoteStopSignal(CheckpointKind.DUNGEON_STABLE)
    # If the screen is an unrecognized splash/loading frame, still hand
    # control to the bounded return state machine instead of waiting for the
    # entire login timeout with a stop request pending.
    raise RemoteStopSignal(CheckpointKind.BETWEEN_OPERATIONS)


def _process_running(adapter) -> bool:
    try:
        output = str(adapter.control_shell(["pidof", GAME_PACKAGE]) or "").strip()
        return bool(re.search(r"\b\d+\b", output))
    except Exception:
        return True


def _resolve_activity(adapter) -> str:
    try:
        output = str(adapter.control_shell(["cmd", "package", "resolve-activity", "--brief", GAME_PACKAGE]) or "").strip()
        for line in reversed(output.splitlines()):
            line = line.strip()
            if re.fullmatch(r"jp\.co\.drecom\.wizardry\.daphne/[A-Za-z0-9_.$]+", line):
                return line
    except Exception:
        pass
    return DEFAULT_GAME_ACTIVITY


def _ready_screen(adapter, screen) -> bool:
    return any(
        _match(adapter, screen, name)
        for name in (
            "Inn",
            "City_RoyalCityLuknalia",
            "City_fortress",
            "City_DHI",
            "City_portTownGrandLegion",
            "dungFlag",
            "mapFlag",
            "worldmapflag",
            "openworldmap",
            "returntotown",
            "combatActive",
            "chestFlag",
        )
    )


def _is_loading(adapter, screen):
    try:
        return adapter.is_black_frame(screen) or bool(_match(adapter, screen, "abyssReadying"))
    except Exception:
        return False


def _match(adapter, screen, name, roi=None, threshold=0.80):
    try:
        return adapter.match_base(screen, name, roi, threshold)
    except Exception:
        return None


def _tap_if_allowed(adapter, runtime, position):
    if not position or runtime.is_stop_requested() or adapter.local_stop_requested():
        return
    adapter.press(position)


def _interruptible_sleep(adapter, runtime, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if runtime.is_stop_requested() or adapter.local_stop_requested():
            raise adapter.local_stop_exception_type()
        adapter.sleep(min(0.5, deadline - time.monotonic()))
