"""Graceful return from the current game state to a stable town screen."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from .adapters import ModResourceError
from .constants import (
    DIALOGUE_ADVANCE_INTERVAL_SECONDS,
    DIALOGUE_NEXT_ROI,
    DIALOGUE_NEXT_THRESHOLD,
    EDGE_TO_TOWN_TIMEOUT_SECONDS,
    QUEST_RTT_TIMEOUT_SECONDS,
    STABLE_FRAME_COUNT,
    STABLE_FRAME_INTERVAL_SECONDS,
)
from .fallback import force_stop_game_once
from .models import (
    BoundedOperationTimeout,
    ControlState,
    RemoteRecoverySuppressed,
    RemoteStopSignal,
    TransitionOutcome,
    TransitionStatus,
)
from .runtime_bridge import run_bounded_operation
from .title_screen import title_visible


class ReturnScreen(str, Enum):
    TITLE = "title"
    COMBAT = "combat"
    CHEST = "chest"
    BLESSING = "blessing"
    DIALOGUE = "dialogue"
    RETURN_TEXT = "return_text"
    EDGE_TO_TOWN = "edge_to_town"
    MAP = "map"
    WORLD_MAP = "world_map"
    TOWN = "town"
    DUNGEON = "dungeon"
    RETRY = "retry"
    LOADING = "loading"
    UNKNOWN = "unknown"


def return_to_town(adapter: Any, runtime: Any, signal: RemoteStopSignal) -> TransitionOutcome:
    if runtime.stop_deadline_monotonic is None:
        return TransitionOutcome(TransitionStatus.ERROR, "원격 정지 제한 시간이 설정되지 않았습니다.", "missing_stop_deadline")
    runtime.report_progress(ControlState.RETURNING_TO_TOWN, "마을로 복귀 중입니다.")
    deadline = runtime.stop_deadline_monotonic
    last_screen = None
    town_frames = 0
    edge_deadline: float | None = None
    rtt_deadline: float | None = None
    last_edge_input = -float("inf")
    try:
        while time.monotonic() < deadline:
            if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
                return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 먼저 처리되었습니다.", "local_stop")
            if runtime.is_timeout_fallback_started():
                return force_stop_game_once(adapter, runtime, failure_phase="return_to_town")
            screen = adapter.screenshot()
            last_screen = screen
            state = _classify(adapter, screen)
            if state is ReturnScreen.TITLE:
                return TransitionOutcome(TransitionStatus.AT_TITLE, "이미 타이틀 화면입니다.")
            if state is ReturnScreen.TOWN:
                town_frames += 1
                if town_frames >= STABLE_FRAME_COUNT:
                    return TransitionOutcome(TransitionStatus.TOWN_READY, "마을 화면을 확인했습니다.")
                adapter.sleep(STABLE_FRAME_INTERVAL_SECONDS)
                continue
            town_frames = 0
            if state in (ReturnScreen.COMBAT, ReturnScreen.CHEST):
                phase = "finish_combat" if state is ReturnScreen.COMBAT else "finish_chest"
                try:
                    run_bounded_operation(
                        lambda: adapter.finish_combat_or_chest("combat" if state is ReturnScreen.COMBAT else "chest"),
                        runtime=runtime,
                        deadline_monotonic=min(deadline, time.monotonic() + EDGE_TO_TOWN_TIMEOUT_SECONDS),
                    )
                except BoundedOperationTimeout:
                    return force_stop_game_once(adapter, runtime, failure_phase=phase)
                continue
            if state is ReturnScreen.BLESSING:
                # The selected blessing can briefly remain visible behind its
                # detail popup. Prefer a real close button when present, as the
                # legacy global handler did, then select the blessing otherwise.
                position = (
                    _match(adapter, screen, "combatClose")
                    or _match(adapter, screen, "close")
                    or _match(adapter, screen, "blessing")
                )
                _press_if_allowed(adapter, runtime, position)
                adapter.sleep(DIALOGUE_ADVANCE_INTERVAL_SECONDS)
                continue
            if state is ReturnScreen.DIALOGUE:
                _press_if_allowed(
                    adapter,
                    runtime,
                    _match(
                        adapter,
                        screen,
                        "dialogueNext",
                        DIALOGUE_NEXT_ROI,
                        DIALOGUE_NEXT_THRESHOLD,
                    ),
                )
                adapter.sleep(DIALOGUE_ADVANCE_INTERVAL_SECONDS)
                continue
            if state is ReturnScreen.RETURN_TEXT:
                _press_if_allowed(adapter, runtime, _match(adapter, screen, "ReturnText"))
                adapter.sleep(0.5)
                continue
            if state is ReturnScreen.EDGE_TO_TOWN:
                if edge_deadline is None:
                    edge_deadline = min(deadline, time.monotonic() + EDGE_TO_TOWN_TIMEOUT_SECONDS)
                if time.monotonic() >= edge_deadline:
                    return force_stop_game_once(adapter, runtime, failure_phase="edge_to_town")
                if time.monotonic() - last_edge_input >= 2.0:
                    _press_if_allowed(adapter, runtime, [1, 1], back_first=True)
                    last_edge_input = time.monotonic()
                adapter.sleep(0.5)
                continue
            if state is ReturnScreen.MAP:
                _press_back_if_allowed(adapter, runtime)
                adapter.sleep(0.5)
                continue
            if state is ReturnScreen.WORLD_MAP:
                if rtt_deadline is None:
                    rtt_deadline = min(deadline, time.monotonic() + QUEST_RTT_TIMEOUT_SECONDS)
                try:
                    result = run_bounded_operation(
                        adapter.return_via_quest_rtt,
                        runtime=runtime,
                        deadline_monotonic=rtt_deadline,
                    )
                except BoundedOperationTimeout:
                    return force_stop_game_once(adapter, runtime, failure_phase="quest_rtt")
                if not result:
                    return force_stop_game_once(adapter, runtime, failure_phase="quest_rtt_unavailable")
                rtt_deadline = None
                adapter.sleep(0.5)
                continue
            if state is ReturnScreen.DUNGEON:
                _press_if_allowed(adapter, runtime, _match(adapter, screen, "leaveDung"))
                adapter.sleep(0.5)
                continue
            if state is ReturnScreen.RETRY:
                adapter.try_press_retry(screen)
                adapter.sleep(0.5)
                continue
            adapter.sleep(0.5)
        if last_screen is not None:
            adapter.save_failure_frame(last_screen, "return_to_town_deadline")
        return force_stop_game_once(adapter, runtime, failure_phase="return_to_town_deadline")
    except adapter.local_stop_exception_type:
        return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 요청되었습니다.", "local_stop")
    except RemoteRecoverySuppressed as exc:
        return force_stop_game_once(adapter, runtime, failure_phase=f"suppressed_{exc.operation}")
    except ModResourceError:
        if last_screen is not None:
            adapter.save_failure_frame(last_screen, "return_to_town_resource")
        return TransitionOutcome(TransitionStatus.ERROR, "원격 제어 화면 리소스를 불러오지 못했습니다.", "resource_missing")
    except Exception:
        if last_screen is not None:
            adapter.save_failure_frame(last_screen, "return_to_town_error")
        return force_stop_game_once(adapter, runtime, failure_phase="return_to_town_error")


def _match(adapter, screen, name: str, roi=None, threshold: float = 0.8):
    return adapter.match_base(screen, name, roi, threshold)


def _has(adapter, screen, name: str, roi=None, threshold: float = 0.8) -> bool:
    try:
        return bool(_match(adapter, screen, name, roi, threshold))
    except ModResourceError:
        raise
    except Exception:
        return False


def _classify(adapter, screen) -> ReturnScreen:
    if _title_visible(adapter, screen):
        return ReturnScreen.TITLE
    if _has(adapter, screen, "combatActive") or _has(adapter, screen, "someonedead"):
        return ReturnScreen.COMBAT
    if any(_has(adapter, screen, name) for name in ("chestFlag", "whowillopenit", "chestOpening")):
        return ReturnScreen.CHEST
    # The first return after the daily reset can show Harken's blessing
    # choices. It must win over dialogueNext and blind recovery taps.
    if _has(adapter, screen, "blessing"):
        return ReturnScreen.BLESSING
    # Loot/result pages can appear after the chest handler has returned and a
    # remote stop has already transferred ownership to this state machine.
    # Handle them before the expensive town/map probes so each result page is
    # advanced promptly. Active chest UI keeps priority above this branch.
    if _has(
        adapter,
        screen,
        "dialogueNext",
        DIALOGUE_NEXT_ROI,
        DIALOGUE_NEXT_THRESHOLD,
    ):
        return ReturnScreen.DIALOGUE
    if _has(adapter, screen, "ReturnText"):
        return ReturnScreen.RETURN_TEXT
    if _has(adapter, screen, "returntotown"):
        return ReturnScreen.EDGE_TO_TOWN
    if _has(adapter, screen, "mapFlag"):
        return ReturnScreen.MAP
    if _has(adapter, screen, "worldmapflag") or _has(adapter, screen, "openworldmap"):
        return ReturnScreen.WORLD_MAP
    if any(_has(adapter, screen, name) for name in ("Inn", "City_RoyalCityLuknalia", "City_fortress", "City_DHI", "City_portTownGrandLegion")):
        return ReturnScreen.TOWN
    if _has(adapter, screen, "dungFlag"):
        return ReturnScreen.DUNGEON
    if _has(adapter, screen, "retry") or _has(adapter, screen, "retry_blank"):
        return ReturnScreen.RETRY
    try:
        if adapter.is_black_frame(screen) or _has(adapter, screen, "abyssReadying"):
            return ReturnScreen.LOADING
    except Exception:
        pass
    return ReturnScreen.UNKNOWN


def _title_visible(adapter, screen) -> bool:
    return title_visible(adapter, screen)


def _press_if_allowed(adapter, runtime, position, *, back_first: bool = False) -> None:
    if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
        raise adapter.local_stop_exception_type()
    if back_first:
        adapter.press_back()
        adapter.sleep(0.2)
    if position:
        adapter.press(position)


def _press_back_if_allowed(adapter, runtime) -> None:
    if adapter.local_stop_requested() or runtime.worker_force_stop_event.is_set():
        raise adapter.local_stop_exception_type()
    adapter.press_back()
