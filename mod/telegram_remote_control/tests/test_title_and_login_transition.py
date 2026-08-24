from __future__ import annotations

import unittest
from unittest.mock import patch

from mod.telegram_remote_control.adapters import image_root
from mod.telegram_remote_control.constants import (
    DEFAULT_GAME_ACTIVITY,
    GAME_PACKAGE,
    STARTUP_DISCLAIMER_TEMPLATE,
    TITLE_LOGO_TEMPLATE,
    TITLE_TAP_FALLBACK_POSITION,
    TITLE_TAP_TEMPLATE,
)
from mod.telegram_remote_control.login_transition import _wait_for_ready, ensure_game_ready
from mod.telegram_remote_control.models import TransitionStatus
from mod.telegram_remote_control.title_screen import title_visible
from mod.telegram_remote_control.title_transition import (
    TitleTransitionScreen,
    classify_title_transition_screen,
)


class _Runtime:
    def is_stop_requested(self):
        return False


class _Adapter:
    local_stop_exception_type = RuntimeError

    def __init__(self, screens):
        self.screens = iter(screens)
        self.presses = []
        self.mod_calls = []
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

    def match_base(self, screen, name, _roi, _threshold):
        if screen == "expired" and name == "totitle":
            return [447, 897]
        if screen == "ready" and name == "Inn":
            return [100, 100]
        return None

    def press(self, position):
        self.presses.append(list(position))
        return True

    def sleep(self, _seconds):
        return None

    def local_stop_requested(self):
        return False

    def is_black_frame(self, _screen):
        return False

    def try_press_retry(self, _screen):
        return False

    def control_shell(self, command):
        self.shell_commands.append(list(command))
        return ""

    def save_failure_frame(self, screen, phase):
        self.failure_frames.append((screen, phase))
        return "failure.png"


class TitleAndLoginTransitionTests(unittest.TestCase):
    def test_required_templates_exist_with_exact_case(self):
        root = image_root()
        for name in (
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
