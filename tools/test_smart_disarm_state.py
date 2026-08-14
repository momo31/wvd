import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import smart_disarm  # noqa: E402
from smart_disarm_audit import SmartDisarmAuditor  # noqa: E402


class RecordingLogger:
    def __init__(self):
        self.lines = []

    def _record(self, message, *args):
        self.lines.append(message % args if args else str(message))

    def debug(self, message, *args):
        self._record(message, *args)

    def info(self, message, *args):
        self._record(message, *args)

    def warning(self, message, *args):
        self._record(message, *args)

    def error(self, message, *args):
        self._record(message, *args)


class SmartDisarmCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.previous_adjustment = smart_disarm._STOP_LEAD["adj"]

    def tearDown(self):
        smart_disarm._STOP_LEAD["adj"] = self.previous_adjustment

    def make_disarm(self, config=None):
        return smart_disarm.SmartDisarm(
            lambda: None,
            lambda _position: True,
            lambda: 0.0,
            RecordingLogger(),
            config=config,
        )

    def test_new_chest_decays_and_clamps_carried_stop_adjustment(self):
        config = smart_disarm.DisarmConfig()
        config.stop_adj_carry_decay = 0.5
        config.stop_adj_carry_max = 0.08

        smart_disarm._STOP_LEAD["adj"] = 0.156
        disarm = self.make_disarm(config)

        self.assertAlmostEqual(smart_disarm._STOP_LEAD["adj"], 0.078)
        self.assertEqual(disarm._carried_stop_adj, (0.156, 0.078))

        smart_disarm._STOP_LEAD["adj"] = -0.35
        disarm = self.make_disarm(config)

        self.assertAlmostEqual(smart_disarm._STOP_LEAD["adj"], -0.08)
        self.assertEqual(disarm._carried_stop_adj, (-0.35, -0.08))

    def test_failure_evidence_is_not_shared_between_chests(self):
        smart_disarm._STOP_LEAD["adj"] = 0.0
        first = self.make_disarm()
        first._prev_tap_meas = False
        first._resid_ewma = 60.0

        step, reason = first._blind_fail_step(0.0)

        self.assertEqual(step, first.cfg.blind_fail_step)
        self.assertIn("잔차 추이", reason)

        second = self.make_disarm()

        self.assertTrue(second._prev_tap_meas)
        self.assertIsNone(second._resid_ewma)
        self.assertEqual(second._blind_fail_step(0.0), (0.0, None))


class SmartDisarmRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.previous_press_latency = smart_disarm._PRESS_LAT["ema"]
        self.previous_adjustment = smart_disarm._STOP_LEAD["adj"]
        smart_disarm._PRESS_LAT["ema"] = None
        smart_disarm._STOP_LEAD["adj"] = 0.0

    def tearDown(self):
        smart_disarm._PRESS_LAT["ema"] = self.previous_press_latency
        smart_disarm._STOP_LEAD["adj"] = self.previous_adjustment

    def make_running_disarm(self, config, positions, fallback_fn=None):
        state = {"captures": 0, "presses": 0, "done": False, "fallbacks": 0}

        def capture():
            state["captures"] += 1
            return np.full((260, 900, 3), state["captures"], dtype=np.uint8)

        def press(_position):
            state["presses"] += 1
            state["done"] = True
            return True

        def fallback():
            state["fallbacks"] += 1
            if fallback_fn is not None:
                fallback_fn()

        class Clock:
            value = 0.0

            def __call__(self):
                self.value += 0.01
                return self.value

        disarm = smart_disarm.SmartDisarm(
            capture,
            press,
            Clock(),
            RecordingLogger(),
            is_done_fn=lambda _image: state["done"],
            fallback_fn=fallback,
            config=config,
        )

        def detect(image):
            marker = int(image[0, 0, 0])
            cursor = positions[min(marker - 1, len(positions) - 1)]
            return {
                "bar": (16, 896),
                "y": (40, 140),
                "cursors": [(cursor, 10)],
                "safes": [(180, 300), (600, 740)],
            }

        disarm.detect = detect
        disarm._measure_after_tap = lambda *args, **kwargs: None
        return disarm, state

    @staticmethod
    def base_config():
        config = smart_disarm.DisarmConfig()
        config.sample_interval = 0.0
        config.input_delay = 0.0
        config.stop_time = 0.0
        config.pw_thresh = 3.0
        config.settle_after_tap = 0.0
        config.settle_extra_checks = 0
        config.max_no_progress_samples = 0
        return config

    def test_fold_failure_retries_with_overlapping_window(self):
        config = self.base_config()
        config.max_total_samples = 5
        config.max_total_samples_extended = 5
        disarm, state = self.make_running_disarm(
            config,
            [100, 220, 340, 460, 580],
        )
        consistency_checks = []
        disarm.estimate = lambda *_args: {"x": 460, "speed": 500.0, "dir": 1}

        def is_consistent(*_args):
            consistency_checks.append(True)
            return len(consistency_checks) > 1

        disarm._est_consistent = is_consistent
        disarm.plan_tap = lambda *_args, min_reach=0.0, **_kwargs: {
            "reach": min_reach + 0.2,
            "center": 240.0,
            "half": 60.0,
            "margin": 6.0,
        }

        with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())

        self.assertEqual(len(consistency_checks), 2)
        self.assertEqual(state["presses"], 1)

    def test_confirmed_fast_game_still_aims_when_bypass_is_disabled(self):
        config = self.base_config()
        config.max_total_samples = 5
        config.max_total_samples_extended = 5
        config.fast_game_fail_limit = 2
        config.fast_game_k = 100.0
        config.bypass_fast_game = False
        disarm, state = self.make_running_disarm(
            config,
            [100, 260, 420, 580, 740],
        )
        disarm.estimate = lambda *_args: {"x": 580, "speed": 2000.0, "dir": 1}
        disarm._est_consistent = lambda *_args: True
        disarm.plan_tap = lambda *_args, min_reach=0.0, **_kwargs: {
            "reach": min_reach + 0.2,
            "center": 670.0,
            "half": 70.0,
            "margin": 7.0,
        }

        with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())

        self.assertEqual(state["presses"], 1)
        self.assertEqual(state["fallbacks"], 0)

    def test_no_progress_uses_fallback_before_full_sample_cap(self):
        config = self.base_config()
        config.max_total_samples = 40
        config.max_no_progress_samples = 4
        config.bypass_fast_game = False
        disarm, state = self.make_running_disarm(
            config,
            [100, 220, 340, 460],
        )
        disarm.estimate = lambda *_args: None

        with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())

        self.assertEqual(state["captures"], 4)
        self.assertEqual(state["presses"], 0)
        self.assertEqual(state["fallbacks"], 1)


class SmartDisarmAuditTests(unittest.TestCase):
    def test_game_outcome_relabels_unknown_tap_images(self):
        logger = RecordingLogger()
        image = np.zeros((260, 900, 3), dtype=np.uint8)
        plan = {"center": 225, "half": 150, "margin": 15}
        estimate = {"x": 400, "speed": 1200, "dir": -1}
        safes = [(56, 395), (507, 843)]

        with tempfile.TemporaryDirectory() as output_dir:
            auditor = SmartDisarmAuditor(logger, out_dir=output_dir)
            auditor.on_start()
            auditor.tag = "test"

            auditor.on_tap(image, None, plan, estimate, safes, (16, 896))
            unknown = Path(output_dir, "disarm_test_1_unk.png")
            missed = Path(output_dir, "disarm_test_1_miss.png")
            self.assertTrue(unknown.is_file())

            auditor.on_tap_outcome(False)
            self.assertFalse(unknown.exists())
            self.assertTrue(missed.is_file())

            auditor.on_tap(image, None, plan, estimate, safes, (16, 896))
            second_unknown = Path(output_dir, "disarm_test_2_unk.png")
            hit = Path(output_dir, "disarm_test_2_hit.png")
            self.assertTrue(second_unknown.is_file())

            auditor.on_tap_outcome(True)
            self.assertFalse(second_unknown.exists())
            self.assertTrue(hit.is_file())

        self.assertTrue(any("게임 판정=실패" in line for line in logger.lines))
        self.assertTrue(any("게임 판정=성공" in line for line in logger.lines))


if __name__ == "__main__":
    unittest.main()
