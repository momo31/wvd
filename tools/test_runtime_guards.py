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

    def test_emulator_recovery_rebinds_adb_and_has_a_circuit_breaker(self):
        self.assertIn("if not ResetDevice(force_restart_emu=True):", self.source)
        self.assertIn("supervisor.request_emulator_restart()", self.source)
        self.assertIn("recovery circuit breaker tripped", self.source)


if __name__ == "__main__":
    unittest.main()
