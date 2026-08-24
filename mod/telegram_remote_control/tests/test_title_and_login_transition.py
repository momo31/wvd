from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from mod.telegram_remote_control.adapters import image_root
from mod.telegram_remote_control.constants import (
    CLOSE_APP_PROMPT_TEMPLATE,
    DEFAULT_GAME_ACTIVITY,
    GAME_PACKAGE,
    STARTUP_DISCLAIMER_TEMPLATE,
    TITLE_LOGO_TEMPLATE,
    TITLE_TAP_FALLBACK_POSITION,
    TITLE_TAP_TEMPLATE,
)
from mod.telegram_remote_control.login_transition import _wait_for_ready, ensure_game_ready
from mod.telegram_remote_control.models import TransitionOutcome, TransitionStatus
from mod.telegram_remote_control.title_screen import title_visible
from mod.telegram_remote_control.title_transition import (
    TitleTransitionScreen,
    classify_title_transition_screen,
    return_town_to_title,
)


class _Runtime:
    def __init__(self):
        self.worker_force_stop_event = threading.Event()
        self.stop_deadline_monotonic = time.perf_counter() + 600
        self.progress = []

    def is_stop_requested(self):
        return False

    def is_timeout_fallback_started(self):
        return False

    def report_progress(self, state, detail):
        self.progress.append((state, detail))


class _Adapter:
    local_stop_exception_type = RuntimeError

    def __init__(self, screens, process_outputs=()):
        self.screens = iter(screens)
        self.process_outputs = list(process_outputs)
        self.presses = []
        self.back_presses = 0
        self.mod_calls = []
        self.base_calls = []
        self.shell_commands = []
        self.failure_frames = []

    def screenshot(self):
        return next(self.screens)

    def match_mod(self, screen, name, roi, threshold):
        self.mod_calls.append((screen, name, roi, threshold))
        if screen == "disclaimer" and name == STARTUP_DISCLAIMER_TEMPLATE:
            return [450, 597]
        if screen == "title" and name == TITLE_LOGO_TEMPLATE:
            return [452, 497]
        if screen == "expired" and name == TITLE_LOGO_TEMPLATE:
            return [452, 497]
        # Simulate a blink frame where the title is stable but the prompt is
        # temporarily invisible.
        if screen == "title" and name == TITLE_TAP_TEMPLATE:
            return None
        return None

    def match_base(self, screen, name, roi, threshold):
        self.base_calls.append((screen, name, roi, threshold))
        if screen in {"close_app", "close_app_no_ok"} and name == CLOSE_APP_PROMPT_TEMPLATE:
            return [450, 735]
        if screen in {"close_app", "generic_ok"} and name == "OK":
            return [291, 895]
        if screen == "expired" and name == "totitle":
            return [447, 897]
        if screen in {"ready", "town"} and name == "Inn":
            return [100, 100]
        return None

    def press(self, position):
        self.presses.append(list(position))
        return True

    def sleep(self, _seconds):
        return None

    def press_back(self):
        self.back_presses += 1

    def local_stop_requested(self):
        return False

    def is_black_frame(self, _screen):
        return False

    def try_press_retry(self, _screen):
        return False

    def control_shell(self, command):
        self.shell_commands.append(list(command))
        if list(command) == ["pidof", GAME_PACKAGE]:
            return self.process_outputs.pop(0) if self.process_outputs else ""
        if list(command)[:4] == ["cmd", "package", "resolve-activity", "--brief"]:
            return DEFAULT_GAME_ACTIVITY
        return ""

    def save_failure_frame(self, screen, phase):
        self.failure_frames.append((screen, phase))
        return "failure.png"


class TitleAndLoginTransitionTests(unittest.TestCase):
    def test_required_templates_exist_with_exact_case(self):
        root = image_root()
        for name in (
            CLOSE_APP_PROMPT_TEMPLATE,
            STARTUP_DISCLAIMER_TEMPLATE,
            TITLE_LOGO_TEMPLATE,
            TITLE_TAP_TEMPLATE,
        ):
            self.assertTrue((root / f"{name}.png").is_file(), name)

    def test_title_decision_uses_stable_logo_without_blinking_prompt(self):
        adapter = _Adapter(["title"])

        self.assertTrue(title_visible(adapter, "title"))
        state, position = classify_title_transition_screen(adapter, "title")

        self.assertEqual(state, TitleTransitionScreen.TITLE)
        self.assertIsNone(position)
        matched_names = [call[1] for call in adapter.mod_calls]
        self.assertNotIn(TITLE_TAP_TEMPLATE, matched_names)

    def test_close_app_prompt_requires_prompt_before_matching_ok(self):
        adapter = _Adapter(["generic_ok"])

        state, position = classify_title_transition_screen(adapter, "generic_ok")

        self.assertEqual(state, TitleTransitionScreen.UNKNOWN)
        self.assertIsNone(position)
        self.assertNotIn("OK", [call[1] for call in adapter.base_calls])

    def test_close_app_prompt_returns_only_bounded_ok(self):
        adapter = _Adapter(["close_app"])

        state, position = classify_title_transition_screen(adapter, "close_app")

        self.assertEqual(state, TitleTransitionScreen.CLOSE_APP_CONFIRMATION)
        self.assertEqual(position, [291, 895])

    def test_close_app_prompt_restarts_and_stops_at_title(self):
        adapter = _Adapter(
            ["town", "town", "town", "close_app", "disclaimer", "title", "title"],
            process_outputs=["321", ""],
        )

        result = return_town_to_title(adapter, _Runtime())

        self.assertEqual(result.status, TransitionStatus.AT_TITLE)
        self.assertEqual(adapter.back_presses, 1)
        self.assertEqual(adapter.presses, [[291, 895], [450, 597]])
        self.assertIn(["am", "start", "-n", DEFAULT_GAME_ACTIVITY], adapter.shell_commands)
        self.assertNotIn(list(TITLE_TAP_FALLBACK_POSITION), adapter.presses)

    def test_close_app_prompt_without_ok_falls_back_without_tapping(self):
        adapter = _Adapter(["town", "town", "town", "close_app_no_ok"])
        fallback = TransitionOutcome(TransitionStatus.FALLBACK_COMPLETE, "fallback", "close_app_ok_missing")

        with patch("mod.telegram_remote_control.title_transition.force_stop_game_once", return_value=fallback) as force_stop:
            result = return_town_to_title(adapter, _Runtime())

        self.assertEqual(result, fallback)
        self.assertEqual(adapter.presses, [])
        self.assertEqual(adapter.failure_frames, [("close_app_no_ok", "close_app_ok_missing")])
        force_stop.assert_called_once()

    def test_close_app_that_does_not_exit_falls_back(self):
        adapter = _Adapter(["town", "town", "town", "close_app"])
        fallback = TransitionOutcome(TransitionStatus.FALLBACK_COMPLETE, "fallback", "close_app_exit")

        with (
            patch("mod.telegram_remote_control.title_transition._wait_for_game_exit", return_value=False),
            patch("mod.telegram_remote_control.title_transition.force_stop_game_once", return_value=fallback) as force_stop,
        ):
            result = return_town_to_title(adapter, _Runtime())

        self.assertEqual(result, fallback)
        self.assertEqual(adapter.presses, [[291, 895]])
        self.assertEqual(adapter.failure_frames, [("close_app", "close_app_exit")])
        self.assertNotIn(["am", "start", "-n", DEFAULT_GAME_ACTIVITY], adapter.shell_commands)
        force_stop.assert_called_once()

    def test_close_app_restart_that_bypasses_title_falls_back(self):
        adapter = _Adapter(["town", "town", "town", "close_app", "town", "town"])
        fallback = TransitionOutcome(TransitionStatus.FALLBACK_COMPLETE, "fallback", "restart_bypassed_title")

        with patch("mod.telegram_remote_control.title_transition.force_stop_game_once", return_value=fallback) as force_stop:
            result = return_town_to_title(adapter, _Runtime())

        self.assertEqual(result, fallback)
        self.assertEqual(adapter.failure_frames, [("town", "restart_bypassed_title")])
        self.assertIn(["am", "start", "-n", DEFAULT_GAME_ACTIVITY], adapter.shell_commands)
        force_stop.assert_called_once()

    def test_login_taps_disclaimer_once_then_uses_title_fallback(self):
        adapter = _Adapter(["disclaimer", "disclaimer", "title", "ready"])

        result = _wait_for_ready(adapter, _Runtime())

        self.assertEqual(result.status, TransitionStatus.GAME_READY)
        self.assertEqual(
            adapter.presses,
            [[450, 597], list(TITLE_TAP_FALLBACK_POSITION)],
        )

    def test_login_prioritizes_session_expiry_over_background_title(self):
        adapter = _Adapter(["expired", "expired", "ready"])

        with patch(
            "mod.telegram_remote_control.login_transition.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0],
        ):
            result = _wait_for_ready(adapter, _Runtime())

        self.assertEqual(result.status, TransitionStatus.GAME_READY)
        self.assertEqual(adapter.presses, [[447, 897]])
        self.assertNotIn(
            ("expired", TITLE_LOGO_TEMPLATE),
            [(screen, name) for screen, name, _roi, _threshold in adapter.mod_calls],
        )

    def test_login_restarts_once_then_saves_final_failure(self):
        adapter = _Adapter(["failure"])
        with (
            patch("mod.telegram_remote_control.login_transition._process_running", side_effect=[True, False]),
            patch("mod.telegram_remote_control.login_transition._resolve_activity", return_value=DEFAULT_GAME_ACTIVITY),
            patch("mod.telegram_remote_control.login_transition._interruptible_sleep"),
            patch("mod.telegram_remote_control.login_transition._wait_for_ready", return_value=None),
        ):
            result = ensure_game_ready(adapter, _Runtime())

        self.assertEqual(result.status, TransitionStatus.ERROR)
        self.assertEqual(
            adapter.shell_commands,
            [
                ["am", "force-stop", GAME_PACKAGE],
                ["am", "start", "-n", DEFAULT_GAME_ACTIVITY],
            ],
        )
        self.assertEqual(adapter.failure_frames, [("failure", "login_gate")])


if __name__ == "__main__":
    unittest.main()
