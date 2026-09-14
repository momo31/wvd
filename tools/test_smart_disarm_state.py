import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import analyze_smart_disarm  # noqa: E402
import smart_disarm  # noqa: E402
from chest_guard import ChestGuardAction, decide_chest_guard_action  # noqa: E402
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

    def test_plan_includes_return_pass_after_too_early_crossing(self):
        disarm = self.make_disarm()
        # 첫 교차는 주입/감속 리드보다 이르지만, 반사 뒤 같은 구간은 조준 가능하다.
        safes = [(125, 325), (575, 775)]
        for x, direction, earliest, center, reach in (
                (650, 1, 0.35, 675, 0.467),
                (250, -1, 0.35, 225, 0.443),
                (650, 1, 4.0, 225, 4.437),
                (650, 1, 0.025, 675, 0.025)):
            with self.subTest(x=x, direction=direction, earliest=earliest):
                estimate = {"x": x, "speed": 1000.0, "dir": direction}
                plan = disarm.plan_tap(estimate, safes, 16, 896, 0.4, earliest)
                self.assertIsNotNone(plan)
                self.assertEqual(plan["center"], center)
                self.assertAlmostEqual(plan["reach"], reach)
                predicted, _ = disarm._propagate(x, 1000, direction, reach, 16, 896)
                self.assertAlmostEqual(predicted, center)

        estimate = {"x": 650, "speed": 1000.0, "dir": 1}
        disarm.cfg = smart_disarm.DisarmConfig()
        disarm.cfg.pw_thresh = 0.12
        self.assertIsNotNone(disarm.plan_tap(estimate, safes, 16, 896, 0.4, 0.35))
        disarm.cfg.pw_thresh = 0.11
        self.assertIsNone(disarm.plan_tap(estimate, safes, 16, 896, 0.4, 0.35))


class SmartDisarmRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.previous_press_latency = smart_disarm._PRESS_LAT["ema"]
        self.previous_adjustment = smart_disarm._STOP_LEAD["adj"]
        smart_disarm._PRESS_LAT["ema"] = None
        smart_disarm._STOP_LEAD["adj"] = 0.0

    def tearDown(self):
        smart_disarm._PRESS_LAT["ema"] = self.previous_press_latency
        smart_disarm._STOP_LEAD["adj"] = self.previous_adjustment

    def make_running_disarm(self, config, positions, fallback_fn=None, safes=None):
        state = {"captures": 0, "presses": 0, "done": False, "fallbacks": 0}
        safes = safes or [(180, 300), (600, 740)]

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
                "safes": safes,
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

    def test_finished_first_frame_with_false_gauge_never_taps_or_falls_back(self):
        config = self.base_config()
        config.bypass_fast_game = True
        disarm, state = self.make_running_disarm(
            config, [686], safes=[(453, 870)],
        )
        disarm.is_done = lambda _image: True
        auditor = mock.Mock()
        disarm.audit = auditor
        self.assertTrue(disarm.run())
        self.assertEqual(state["captures"], 1)
        self.assertEqual(state["presses"], 0)
        self.assertEqual(state["fallbacks"], 0)
        auditor.on_end_frame.assert_called_once()
        self.assertEqual(state["fallbacks"], 0)

    def test_safe_width_bypass_keeps_the_existing_boundary(self):
        def run(width):
            config = self.base_config()
            config.bypass_fast_game = True
            config.max_total_samples = 5
            disarm, state = self.make_running_disarm(
                config,
                [100, 220, 340, 460, 580],
                safes=[(180, 180 + width), (600, 740)],
            )
            disarm.estimate = lambda *_args: {"x": 460, "speed": 500.0, "dir": 1}
            disarm._est_consistent = lambda *_args: True
            disarm.plan_tap = lambda *_args, min_reach=0.0, **_kwargs: {
                "reach": min_reach + 0.2,
                "center": 205.0,
                "half": width / 2.0,
                "margin": 5.0,
            }
            with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                    mock.patch.object(smart_disarm.time, "sleep", return_value=None):
                self.assertTrue(disarm.run())
            return state

        self.assertEqual(run(101)["presses"], 1)
        self.assertEqual(run(100)["fallbacks"], 1)

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

    def test_second_tap_cursor_loss_waits_for_result_without_fallback(self):
        config = self.base_config()
        config.max_total_samples = 20
        config.max_total_samples_extended = 20
        positions = [
            100, 220, 340, 460, 460, 460,
            100, 220, 340, 460, 460, 460,
            None, 460,
        ]
        disarm, state = self.make_running_disarm(config, positions)
        disarm.press = lambda _position: state.__setitem__("presses", state["presses"] + 1) or True
        capture = disarm.cap

        def delayed_result_capture():
            image = capture()
            if state["presses"] >= 2 and state["captures"] >= 14:
                state["done"] = True
            return image

        disarm.cap = delayed_result_capture
        original_detect = disarm.detect
        disarm.detect = lambda image: (
            {**original_detect(image), "cursors": []}
            if positions[min(int(image[0, 0, 0]) - 1, len(positions) - 1)] is None
            else original_detect(image)
        )
        disarm.estimate = lambda *_args: {"x": 460, "speed": 500.0, "dir": 1}
        disarm._est_consistent = lambda *_args: True
        disarm.plan_tap = lambda *_args, min_reach=0.0, **_kwargs: {
            "reach": min_reach + 0.2,
            "center": 240.0,
            "half": 60.0,
            "margin": 6.0,
        }
        disarm.detect_remaining_chances = lambda _image: 2
        auditor = mock.Mock()
        disarm.audit = auditor

        with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())

        self.assertEqual(state["presses"], 2)
        self.assertEqual(state["fallbacks"], 0)
        auditor.on_end_frame.assert_called_once()

    def test_latest_settle_frame_is_reused_once_with_its_capture_time(self):
        for extra_checks, missing_last, done_in_extra in (
                (2, False, False), (2, True, False),
                (2, False, True), (0, False, False)):
            with self.subTest(extra_checks=extra_checks, missing_last=missing_last,
                              done_in_extra=done_in_extra):
                config = self.base_config()
                config.settle_extra_checks = extra_checks
                config.settle_extra_interval = 0.2
                config.max_total_samples = config.max_total_samples_extended = 8
                first_retry = 8 if extra_checks else 7
                first_retry += int(missing_last)
                sample_ids = [1, 2, 3, 4]
                if not done_in_extra:
                    sample_ids += list(range(first_retry, first_retry + 4))
                positions = [700] * 13
                for index, marker in enumerate(sample_ids):
                    positions[marker - 1] = 100 + (index % 4) * 200
                disarm, state = self.make_running_disarm(config, positions)
                clock = [0.0]
                capture_times = {}
                original_capture = disarm.cap

                def capture():
                    started = clock[0]
                    clock[0] += 0.5
                    image = original_capture()
                    marker = state["captures"]
                    capture_times[marker] = started + config.capture_grab_frac * 0.5
                    return None if missing_last and marker == 8 else image

                def press(_position):
                    state["presses"] += 1
                    return True

                disarm.cap = capture
                disarm.press = press
                disarm.now = lambda: clock[0]
                disarm.is_done = lambda _image: (
                    state["presses"] == 2
                    or (done_in_extra and state["captures"] == 8)
                )
                disarm.detect_remaining_chances = lambda _image: 4
                auditor = mock.Mock()
                disarm.audit = auditor
                with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                        mock.patch.object(smart_disarm.time, "sleep",
                                          side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
                    self.assertTrue(disarm.run())

                self.assertEqual(state["captures"], 8 if done_in_extra else first_retry + 4)
                self.assertEqual(state["presses"], 1 if done_in_extra else 2)
                self.assertEqual(state["fallbacks"], 0)
                self.assertEqual(
                    [(call.args[0], call.args[1]) for call in auditor.on_sample.call_args_list],
                    [(capture_times[marker], positions[marker - 1]) for marker in sample_ids],
                )
                auditor.on_end_frame.assert_called_once()

    def test_chance_drop_is_failure_and_fallback_saves_final_frame(self):
        config = self.base_config()
        config.max_total_samples = 4
        config.max_total_samples_extended = 4
        disarm, state = self.make_running_disarm(config, [100, 220, 340, 460, 460, 460])
        disarm.is_done = lambda _image: False
        disarm.estimate = lambda *_args: {"x": 460, "speed": 500.0, "dir": 1}
        disarm._est_consistent = lambda *_args: True
        disarm.plan_tap = lambda *_args, min_reach=0.0, **_kwargs: {
            "reach": min_reach + 0.2,
            "center": 240.0,
            "half": 60.0,
            "margin": 6.0,
        }
        disarm.detect_remaining_chances = mock.Mock(side_effect=[2, 1])
        auditor = mock.Mock()
        disarm.audit = auditor

        with mock.patch.object(smart_disarm.os.path, "exists", return_value=True), \
                mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())

        auditor.on_tap_outcome.assert_called_once_with(False)
        auditor.on_end_frame.assert_called_once()

    def test_unchanged_last_chance_does_not_confirm_success(self):
        config = self.base_config()
        config.max_total_samples = config.max_total_samples_extended = 4
        disarm, state = self.make_running_disarm(config, [100, 220, 340, 460])
        disarm.is_done = lambda _image: False
        disarm.estimate = lambda *_args: {"x": 460, "speed": 500.0, "dir": 1}
        disarm._est_consistent = lambda *_args: True
        disarm.detect_remaining_chances = lambda _image: 1
        auditor = mock.Mock()
        disarm.audit = auditor
        with mock.patch.object(smart_disarm.time, "sleep", return_value=None):
            self.assertTrue(disarm.run())
        self.assertEqual(state["presses"], 1)
        auditor.on_tap_outcome.assert_not_called()


class SmartDisarmDetectionTests(unittest.TestCase):
    def test_selection_frame_prioritizes_open_over_dialogue_coordinates(self):
        cv2 = smart_disarm.cv2
        template = cv2.imread(str(ROOT / "resources" / "images" / "chestFlag.png"))
        selection = np.zeros((1600, 900, 3), np.uint8)
        h, w = template.shape[:2]
        selection[900:900 + h, 100:100 + w] = template
        open_position = [100 + w // 2, 900 + h // 2]

        def check(screen, marker):
            if marker == "chestFlag" and cv2.minMaxLoc(cv2.matchTemplate(
                    screen, template, cv2.TM_CCOEFF_NORMED))[1] >= 0.8:
                return open_position

        dialogue = mock.Mock(return_value=[834, 1487])
        decision = decide_chest_guard_action(selection, check, dialogue)
        self.assertIs(decision.action, ChestGuardAction.OPEN_CHEST)
        self.assertEqual(decision.position, open_position)
        dialogue.assert_not_called()

    def test_reflection_estimate_must_fit_every_observed_point(self):
        disarm = smart_disarm.SmartDisarm(None, None, None, RecordingLogger())
        # 로그 재생: 가장 오래된 점의 오차 62px는 통과하지만 중간점은 155px 어긋난다.
        samples = [(0, 823), (0.516, 448), (1.039, 182), (1.595, 498)]
        estimate = disarm.estimate(samples, 16, 896)
        self.assertIsNotNone(estimate)
        self.assertFalse(disarm._est_consistent(estimate, samples, 16, 896))
        samples = [(0, 450), (0.25, 650), (0.5, 850), (0.75, 742)]
        estimate = disarm.estimate(samples, 16, 896)
        self.assertTrue(disarm._est_consistent(estimate, samples, 16, 896))

    def test_bright_chest_background_cannot_become_a_safe_zone(self):
        # 2026-09-05 18:10:16: 중앙 장식 x464~504를 목표 x484로 오인한 화면.
        image = np.full((260, 900, 3), (40, 175, 210), dtype=np.uint8)
        image[54:124, 16:897] = (10, 10, 80)  # 어두운 빨강 양끝도 반사 경계다.
        for left, right in [(109, 343), (559, 793)]:
            image[54:124, left:right] = (0, 210, 230)
        image[62:113, 688:702] = 240
        disarm = smart_disarm.SmartDisarm(None, None, None, RecordingLogger())
        detected = disarm.detect(image)
        self.assertEqual(detected["bar"], (16, 896))
        self.assertEqual(detected["safes"], [(109, 342), (559, 792)])
        self.assertEqual(detected["cursors"], [(694, 14)])
        image[:54] = 0
        image[124:] = 0
        self.assertEqual(disarm.detect(image), detected)

    def test_non_game_and_incomplete_frames_are_rejected(self):
        disarm = smart_disarm.SmartDisarm(None, None, None, RecordingLogger())
        for image in (None, np.zeros((0, 0, 3), np.uint8),
                      np.zeros((260, 900, 3), np.uint8)):
            self.assertIsNone(disarm.detect(image))


class SmartDisarmChanceTemplateTests(unittest.TestCase):
    def test_one_chance_template_is_distinct_and_detected(self):
        disarm = smart_disarm.SmartDisarm(
            lambda: None,
            lambda _position: True,
            lambda: 0.0,
            RecordingLogger(),
        )
        one = smart_disarm.cv2.imread(str(ROOT / "resources" / "images" / "smallgame_1.png"))
        two = smart_disarm.cv2.imread(str(ROOT / "resources" / "images" / "smallgame_2.png"))
        self.assertEqual(one.shape[:2], (36, 26))

        roi = np.zeros((80, 130, 3), dtype=np.uint8)
        roi[32:68, 43:69] = one
        self.assertEqual(disarm.detect_remaining_chances(roi), 1)

        roi[32:68, 43:69] = two
        self.assertEqual(disarm.detect_remaining_chances(roi), 2)


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
            missed = Path(output_dir, "disarm_test_1_game_miss.png")
            self.assertTrue(unknown.is_file())

            auditor.on_tap_outcome(False)
            self.assertFalse(unknown.exists())
            self.assertTrue(missed.is_file())

            auditor.on_tap(image, None, plan, estimate, safes, (16, 896))
            second_unknown = Path(output_dir, "disarm_test_2_unk.png")
            hit = Path(output_dir, "disarm_test_2_game_hit.png")
            self.assertTrue(second_unknown.is_file())

            auditor.on_tap_outcome(True)
            self.assertFalse(second_unknown.exists())
            self.assertTrue(hit.is_file())

            auditor.on_tap(image, 225, plan, estimate, safes, (16, 896), backcast_x=225)
            model_hit = Path(output_dir, "disarm_test_3_model_hit.png")
            game_miss = Path(output_dir, "disarm_test_3_game_miss.png")
            self.assertTrue(model_hit.is_file())

            auditor.on_tap_outcome(False)
            self.assertFalse(model_hit.exists())
            self.assertTrue(game_miss.is_file())

        self.assertTrue(any("게임 판정=실패" in line for line in logger.lines))
        self.assertTrue(any("게임 판정=성공" in line for line in logger.lines))


class SmartDisarmAnalyzerTests(unittest.TestCase):
    def test_structured_metrics_use_real_safe_width(self):
        log = "\n".join([
            "2026-09-04 12:00:00 - INFO - [audit] 스마트 개봉 시작 (tag=test)",
            "2026-09-04 12:00:01 - INFO - 개봉 탭: 목표구간중심x=225 "
            "margin=15 pw=0.400s 속도=920px/s press=0.030s 리드=0.285s",
            "2026-09-04 12:00:01 - DEBUG - [smart_disarm_metrics] tap=1 "
            "center=225 margin=15 safe_width=90 half_period=0.950 sample_dt=0.520 "
            "lag_comp=0.070 speed=920 press_wait=0.400 press_rtt=0.030 lead=0.285",
            "2026-09-04 12:00:02 - INFO - [ChallengeCheck] 기회 인식 결과: "
            "탭 전 2회 -> 탭 후 2회",
        ])
        with tempfile.TemporaryDirectory() as log_dir:
            Path(log_dir, "log_test.txt").write_text(log, encoding="utf-8")
            data = analyze_smart_disarm.parse_logs(log_dir)

        self.assertEqual(data["tap_widths"], [{"w": 90.0, "outcome": "unchanged"}])
        self.assertEqual(len(data["taplogs"]), 1)
        self.assertEqual(data["taplogs"][0]["half_period"], 0.95)
        self.assertEqual(data["taplogs"][0]["sample_dt"], 0.52)

    def test_end_frame_classifier_reuses_existing_templates(self):
        cv2 = smart_disarm.cv2
        receive = cv2.imread(str(ROOT / "resources" / "images" / "FFXI" / "receive.png"))
        dialogue = cv2.imread(str(ROOT / "resources" / "images" / "dialogueNext.png"))
        chest_templates = [cv2.imread(str(ROOT / "resources" / "images" / (name + ".png")))
                           for name in ("chestFlag", "whowillopenit", "chestOpening")]
        frame = np.zeros((1600, 900, 3), dtype=np.uint8)
        scaled_receive = cv2.resize(receive, None, fx=1.2, fy=1.2)
        rh, rw = scaled_receive.shape[:2]
        dh, dw = dialogue.shape[:2]

        reward = frame.copy()
        reward[1240:1240 + rh, 80:80 + rw] = scaled_receive
        reward[1470:1470 + dh, 820:820 + dw] = dialogue
        self.assertEqual(
            analyze_smart_disarm.classify_end_frame(reward, receive, dialogue, cv2, chest_templates),
            "reward_candidate",
        )

        trap = frame.copy()
        trap[1470:1470 + dh, 820:820 + dw] = dialogue
        self.assertEqual(
            analyze_smart_disarm.classify_end_frame(trap, receive, dialogue, cv2, chest_templates),
            "unknown",
        )
        self.assertEqual(
            analyze_smart_disarm.classify_end_frame(frame, receive, dialogue, cv2, chest_templates),
            "unknown",
        )
        for template in chest_templates:
            with self.subTest(chest_marker_shape=template.shape):
                selection = reward.copy()
                h, w = template.shape[:2]
                selection[900:900 + h, 100:100 + w] = template
                self.assertEqual(analyze_smart_disarm.classify_end_frame(
                    selection, receive, dialogue, cv2, chest_templates), "unknown")

    def test_missing_outcome_cannot_leak_across_log_files(self):
        metric = ("[smart_disarm_metrics] tap=1 center=225 margin=15 safe_width=90 "
                  "half_period=0.950 sample_dt=0.520 lag_comp=0.070 speed=920 "
                  "press_wait=0.400 press_rtt=0.030 lead=0.285\n")
        with tempfile.TemporaryDirectory() as log_dir:
            Path(log_dir, "log_a.txt").write_text(metric, encoding="utf-8")
            Path(log_dir, "log_b.txt").write_text(
                "[ChallengeCheck] 탭 실패\n" + metric
                + "[ChallengeCheck] 기회 인식 결과: 탭 전 2회 -> 탭 후 1회\n"
                + "[ChallengeCheck] 탭 실패\n"
                + "스마트 개봉 중단: 막대 미검출(비게임 화면 추정)\n"
                + "[audit] 결과: 중단: 막대 미검출(비게임 화면 추정) | "
                  "유효샘플 0건 | 탭 0회 (tag=test)\n", encoding="utf-8")
            data = analyze_smart_disarm.parse_logs(log_dir)
        self.assertEqual(data["tap_widths"], [
            {"w": 90.0, "outcome": None}, {"w": 90.0, "outcome": "fail"}])
        self.assertEqual(data["counts"]["무막대 즉시 반환"], 1)


if __name__ == "__main__":
    unittest.main()
