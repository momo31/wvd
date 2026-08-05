import ast
import gettext
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from recovery import RecoveryPlan, RecoveryReason, RecoverySupervisor


class RecoveryPlanTests(unittest.TestCase):
    def test_combat_still_requests_recovery_when_chest_recovery_is_skipped(self):
        plan = RecoveryPlan()

        self.assertFalse(
            plan.request(RecoveryReason.CHEST, enabled=False)
        )
        self.assertTrue(
            plan.request(RecoveryReason.COMBAT, enabled=True)
        )

        self.assertTrue(plan.should_recover)
        self.assertEqual(plan.reasons, (RecoveryReason.COMBAT,))

    def test_multiple_enabled_reasons_produce_one_pending_plan(self):
        plan = RecoveryPlan()

        plan.request(RecoveryReason.CHEST)
        plan.request(RecoveryReason.COMBAT)
        plan.request(RecoveryReason.COMBAT)

        self.assertEqual(
            plan.reasons,
            (RecoveryReason.CHEST, RecoveryReason.COMBAT),
        )

        plan.complete()

        self.assertFalse(plan.should_recover)
        self.assertEqual(plan.reasons, ())


class RecoverySupervisorTests(unittest.TestCase):
    def test_rapid_restarts_escalate_without_discarding_history(self):
        supervisor = RecoverySupervisor()

        self.assertFalse(supervisor.note_app_restart(0.0))
        self.assertFalse(supervisor.note_app_restart(30.0))
        self.assertFalse(supervisor.note_app_restart(60.0))
        self.assertTrue(supervisor.note_app_restart(90.0))
        self.assertEqual(supervisor.restart_times, (0.0, 30.0, 60.0, 90.0))

    def test_repeated_emulator_recovery_trips_the_circuit_breaker(self):
        supervisor = RecoverySupervisor(max_emulator_restarts_without_stable=2)

        self.assertTrue(supervisor.request_emulator_restart())
        self.assertTrue(supervisor.request_emulator_restart())
        self.assertFalse(supervisor.request_emulator_restart())

    def test_stable_state_clears_restart_and_emulator_history(self):
        supervisor = RecoverySupervisor()

        supervisor.note_app_restart(0.0)
        supervisor.request_emulator_restart()
        supervisor.mark_stable()

        self.assertEqual(supervisor.restart_times, ())
        self.assertEqual(supervisor.emulator_restarts_without_stable, 0)
        self.assertTrue(supervisor.request_emulator_restart())


class RecoveryScreenReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_path = SRC / "script.py"
        cls.source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(cls.source, filename=str(script_path))
        cls.function_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "ReturnToDungeonAfterRecovery"
        )

    def build_function(self, screens):
        screen_iter = iter(screens)
        back_presses = []

        class FakeClock:
            current = 0.0

            @classmethod
            def time(cls):
                cls.current += 0.05
                return cls.current

        namespace = {
            "ScreenShot": lambda: next(screen_iter),
            "CheckIf": lambda screen, pattern: (
                pattern == "dungflag" and screen == "dungeon"
            ),
            "PressReturn": lambda: back_presses.append("back"),
            "Sleep": lambda _seconds: None,
            "time": FakeClock,
            "logger": type(
                "FakeLogger",
                (),
                {"warning": staticmethod(lambda _message: None)},
            ),
            "_": lambda message: message,
        }
        module = ast.Module(body=[self.function_node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<recovery-return>", "exec"), namespace)
        return namespace["ReturnToDungeonAfterRecovery"], back_presses

    def test_already_returned_dungeon_does_not_press_back(self):
        return_to_dungeon, back_presses = self.build_function(["dungeon"])

        self.assertTrue(return_to_dungeon())
        self.assertEqual(back_presses, [])

    def test_stops_pressing_back_as_soon_as_dungeon_is_visible(self):
        return_to_dungeon, back_presses = self.build_function(
            ["recovery", "character", "dungeon"]
        )

        self.assertTrue(return_to_dungeon())
        self.assertEqual(back_presses, ["back", "back"])

    def test_recovery_log_reports_only_the_final_decision(self):
        self.assertNotIn('logger.info(_("进行开启宝箱后的恢复."))', self.source)
        self.assertEqual(self.source.count('logger.info(_("进行恢复. 原因: {a}."'), 2)

    def test_recovery_messages_are_localized(self):
        message_ids = (
            "恢复后未能确认地下城画面. 将重新识别状态.",
            "开启宝箱后",
            "战斗后",
            "进入地下城时",
            "复活后",
            "进行恢复. 原因: {a}.",
        )

        for language in ("en_US", "ko_KR"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message_id in message_ids:
                self.assertNotEqual(translations.gettext(message_id), message_id)


if __name__ == "__main__":
    unittest.main()
