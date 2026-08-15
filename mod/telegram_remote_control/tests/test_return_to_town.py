from __future__ import annotations

import threading
import time
import unittest

from mod.telegram_remote_control.constants import (
    DIALOGUE_NEXT_ROI,
    DIALOGUE_NEXT_THRESHOLD,
)
from mod.telegram_remote_control.models import (
    CheckpointKind,
    ControlState,
    RemoteStopSignal,
    TransitionStatus,
)
from mod.telegram_remote_control.return_to_town import (
    ReturnScreen,
    _classify,
    return_to_town,
)


class _Runtime:
    def __init__(self):
        self.stop_deadline_monotonic = time.monotonic() + 10
        self.worker_force_stop_event = threading.Event()
        self.progress = []

    def report_progress(self, state, message):
        self.progress.append((state, message))

    def is_timeout_fallback_started(self):
        return False


class _Adapter:
    local_stop_exception_type = RuntimeError

    def __init__(self, screens):
        self.screens = iter(screens)
        self.presses = []
        self.base_calls = []

    def screenshot(self):
        return next(self.screens)

    def match_mod(self, _screen, _name, _roi, _threshold):
        return None

    def match_base(self, screen, name, roi, threshold):
        self.base_calls.append((screen, name, roi, threshold))
        if screen in {"blessing", "blessing-and-dialogue"} and name == "blessing":
            return [377, 1100]
        if screen == "blessing-and-dialogue" and name == "dialogueNext":
            return [834, 1487]
        if screen == "return-text" and name == "ReturnText":
            return [450, 1110]
        if screen == "loot" and name == "dialogueNext":
            return [834, 1487]
        if screen == "chest-and-dialogue" and name in {"chestOpening", "dialogueNext"}:
            return [74, 168] if name == "chestOpening" else [834, 1487]
        if screen == "town" and name == "Inn":
            return [100, 100]
        return None

    def press(self, position):
        self.presses.append(list(position))
        return True

    def press_back(self):
        raise AssertionError("press_back must not be used for a loot page")

    def sleep(self, _seconds):
        return None

    def local_stop_requested(self):
        return False

    def is_black_frame(self, _screen):
        return False

    def try_press_retry(self, _screen):
        return False

    def finish_combat_or_chest(self, _kind):
        return True

    def return_via_quest_rtt(self):
        return True

    def save_failure_frame(self, _screen, _phase):
        return None


class ReturnToTownTests(unittest.TestCase):
    def test_loot_dialogue_is_advanced_before_town_and_map_probes(self):
        adapter = _Adapter(["loot", "town", "town"])
        runtime = _Runtime()

        result = return_to_town(
            adapter,
            runtime,
            RemoteStopSignal(CheckpointKind.BETWEEN_OPERATIONS),
        )

        self.assertEqual(result.status, TransitionStatus.TOWN_READY)
        self.assertEqual(adapter.presses, [[834, 1487]])
        self.assertEqual(runtime.progress[0][0], ControlState.RETURNING_TO_TOWN)
        dialogue_calls = [call for call in adapter.base_calls if call[1] == "dialogueNext"]
        self.assertTrue(dialogue_calls)
        self.assertTrue(all(call[2] == DIALOGUE_NEXT_ROI for call in dialogue_calls))
        self.assertTrue(all(call[3] == DIALOGUE_NEXT_THRESHOLD for call in dialogue_calls))
        first_loot_names = [call[1] for call in adapter.base_calls if call[0] == "loot"]
        self.assertNotIn("ReturnText", first_loot_names)
        self.assertNotIn("worldmapflag", first_loot_names)

    def test_active_chest_keeps_priority_over_dialogue_icon(self):
        adapter = _Adapter([])

        state = _classify(adapter, "chest-and-dialogue")

        self.assertEqual(state, ReturnScreen.CHEST)
        checked = [call[1] for call in adapter.base_calls]
        self.assertNotIn("dialogueNext", checked)

    def test_blessing_choice_precedes_dialogue_and_reaches_town(self):
        adapter = _Adapter(["blessing", "return-text", "town", "town"])
        runtime = _Runtime()

        result = return_to_town(
            adapter,
            runtime,
            RemoteStopSignal(CheckpointKind.BETWEEN_OPERATIONS),
        )

        self.assertEqual(result.status, TransitionStatus.TOWN_READY)
        self.assertEqual(adapter.presses, [[377, 1100], [450, 1110]])

        priority_adapter = _Adapter([])
        self.assertEqual(
            _classify(priority_adapter, "blessing-and-dialogue"),
            ReturnScreen.BLESSING,
        )
        checked = [call[1] for call in priority_adapter.base_calls]
        self.assertNotIn("dialogueNext", checked)


if __name__ == "__main__":
    unittest.main()
