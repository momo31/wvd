import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class RuntimeGuardSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (SRC / "script.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(SRC / "script.py"))
        cls.overlay_node = next(
            node
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "HandleBlockingOverlay"
        )

    def build_overlay_handler(self, active_patterns=(), close_position=None):
        calls = {"press": [], "sleep": [], "threshold": [], "debug": []}

        class FakeArray:
            def __getitem__(self, _key):
                return self

            @staticmethod
            def mean():
                return 40.0

        class FakeNumpy:
            @staticmethod
            def asarray(_screen):
                return FakeArray()

        def check_at_threshold(_screen, pattern, threshold, roi=None):
            calls["threshold"].append((pattern, threshold, roi))
            if pattern in {"combatClose", "close"}:
                return close_position
            return False

        namespace = {
            "DismissSetTrapScreen": lambda _screen: False,
            "is_pause_overlay": lambda _screen: False,
            "CheckIf": lambda _screen, pattern: (
                [450, 1264] if pattern in active_patterns else False
            ),
            "CheckIfAtThreshold": check_at_threshold,
            "Press": calls["press"].append,
            "Sleep": calls["sleep"].append,
            "np": FakeNumpy,
            "logger": type(
                "FakeLogger",
                (),
                {
                    "info": staticmethod(lambda _message: None),
                    "debug": staticmethod(calls["debug"].append),
                },
            ),
        }
        module = ast.Module(body=[self.overlay_node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<blocking-overlay>", "exec"), namespace)
        return namespace["HandleBlockingOverlay"], calls

    def test_restart_state_cannot_reenter_stale_chest_screen(self):
        self.assertIn("runtimeContext._STATE_RESET_REQUIRED = True", self.source)
        self.assertIn("if classify_screen(screen) is ScreenHealth.BLACK:", self.source)
        self.assertIn("frame_health is ScreenHealth.BLACK", self.source)
        self.assertIn("runtimeContext._STATE_RESET_REQUIRED = False", self.source)

    def test_restart_signal_is_not_swallowed_by_screenshot_recovery(self):
        self.assertIn(
            "if isinstance(e, (RestartSignal, TaskStoppedException)):\n                    raise",
            self.source,
        )

    def test_long_wait_is_interruptible(self):
        self.assertNotIn("time.sleep(7300)", self.source)
        self.assertIn("time.sleep(min(remaining, 0.5))", self.source)

    def test_adb_recovery_keeps_retrying_after_transient_exception(self):
        function = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "CheckAndRecoverDevice"
        )
        source = ast.get_source_segment(self.source, function)
        self.assertIsNotNone(source)
        self.assertIn("Keep the bounded recovery loop alive", source)
        self.assertIn("continue", source)

    def test_post_restart_wait_counter_is_not_reset_before_the_guard(self):
        self.assertIn(
            "if not runtimeContext._STATE_RESET_REQUIRED:\n                startup_wait = 0",
            self.source,
        )
        self.assertIn("runtimeContext.mark_stable()", self.source)
        self.assertIn("BLACK_FRAME_MAX = 45", self.source)
        self.assertIn("POST_RESTART_STARTUP_MAX = 90", self.source)

    def test_emulator_recovery_rebinds_adb_and_uses_backoff_without_a_hard_limit(self):
        self.assertIn("if not ResetDevice(force_restart_emu=True):", self.source)
        self.assertIn("supervisor.request_emulator_restart()", self.source)
        self.assertIn("supervisor.emulator_restart_delay_seconds", self.source)
        self.assertIn("supervisor.app_restart_cooldown", self.source)
        self.assertNotIn("recovery circuit breaker tripped", self.source)
        self.assertNotIn("if not supervisor.request_emulator_restart()", self.source)

    def test_blocking_overlays_are_handled_before_state_templates(self):
        identify_start = self.source.index("def IdentifyState():")
        identify_end = self.source.index("def GameFrozenCheck(", identify_start)
        identify_block = self.source[identify_start:identify_end]

        self.assertIn("def CheckIfAtThreshold(", self.source)
        self.assertIn("from screen_health import ScreenHealth, classify_screen, is_pause_overlay", self.source)
        self.assertIn("if HandleBlockingOverlay(screen):", identify_block)
        self.assertIn("counter += 1", identify_block)
        self.assertIn("blocking overlay persisted; restarting the game", identify_block)
        self.assertLess(
            identify_block.index("HandleBlockingOverlay(screen)"),
            identify_block.index("identifyConfig ="),
        )
        self.assertIn('"spellskill/skillDetail", threshold=0.70', self.source)

    def test_return_dialog_is_not_misclassified_as_a_close_overlay(self):
        overlay_start = self.source.index("def HandleBlockingOverlay(")
        overlay_end = self.source.index("def IdentifyState():", overlay_start)
        overlay = self.source[overlay_start:overlay_end]

        self.assertIn('if CheckIf(screen, "returnText"):', overlay)
        self.assertIn(
            "# The dungeon travel dialog contains a dark horizontal row labelled",
            overlay,
        )
        self.assertLess(
            overlay.index('if CheckIf(screen, "returnText"):'),
            overlay.index("upper_mean ="),
        )

    def test_chest_dialogs_are_not_misclassified_as_close_overlays(self):
        overlay_start = self.source.index("def HandleBlockingOverlay(")
        overlay_end = self.source.index("def IdentifyState():", overlay_start)
        overlay = self.source[overlay_start:overlay_end]

        for pattern in ("chestFlag", "whowillopenit", "chestOpening"):
            with self.subTest(pattern=pattern):
                handler, calls = self.build_overlay_handler(
                    active_patterns={pattern},
                    close_position=[269, 1314],
                )

                self.assertFalse(handler("chest-screen"))
                self.assertEqual(calls["press"], [])
                self.assertFalse(
                    any(threshold == 0.60 for _, threshold, _ in calls["threshold"])
                )

        self.assertLess(
            overlay.index('chest_patterns = ("chestFlag", "whowillopenit", "chestOpening")'),
            overlay.index("upper_mean ="),
        )

        identify_start = self.source.index("identifyConfig =")
        identify_end = self.source.index("for pattern, state in identifyConfig:", identify_start)
        identify_config = self.source[identify_start:identify_end]
        self.assertIn('("chestOpening",  DungeonState.Chest)', identify_config)

    def test_real_blocking_modal_still_closes(self):
        handler, calls = self.build_overlay_handler(close_position=[269, 1314])

        self.assertTrue(handler("modal-screen"))
        self.assertEqual(calls["press"], [[269, 1314]])
        self.assertEqual(calls["sleep"], [0.7])
        self.assertTrue(
            any(threshold == 0.60 for _, threshold, _ in calls["threshold"])
        )

    def test_unresolved_state_is_the_only_path_for_frozen_and_elapsed_guards(self):
        dungeon_start = self.source.index("def StateDungeon(")
        dungeon_end = self.source.index("def StateAcceptRequest", dungeon_start)
        dungeon_block = self.source[dungeon_start:dungeon_end]

        self.assertIn(
            "if dungState is not None:\n                        continue",
            dungeon_block,
        )
        state_none_start = dungeon_block.index("case None:")
        state_none_end = dungeon_block.index("case DungeonState.Quit:", state_none_start)
        state_none = dungeon_block[state_none_start:state_none_end]
        self.assertIn("GameFrozenCheck", state_none)
        self.assertIn("_TIME_COMBAT", state_none)
        self.assertLess(state_none.index("if dungState is not None:"), state_none.index("GameFrozenCheck"))


if __name__ == "__main__":
    unittest.main()
