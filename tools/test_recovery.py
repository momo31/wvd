import ast
import gettext
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from recovery import RecoveryPlan, RecoveryReason, RecoverySupervisor
from screen_health import ScreenHealth, classify_screen


from utils import ResolveTemplatePath


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

    def test_repeated_emulator_recovery_is_hard_capped(self):
        supervisor = RecoverySupervisor(
            emulator_restart_backoff_seconds=5.0,
            max_emulator_restart_backoff_seconds=20.0,
            max_emulator_restarts_without_stable=3,
        )

        for expected_delay in (5.0, 10.0, 20.0):
            self.assertTrue(supervisor.request_emulator_restart())
            self.assertEqual(
                supervisor.emulator_restart_delay_seconds,
                expected_delay,
            )
        self.assertFalse(supervisor.request_emulator_restart())
        self.assertEqual(supervisor.emulator_restarts_without_stable, 3)

    def test_app_restarts_have_a_minimum_interval(self):
        supervisor = RecoverySupervisor(minimum_restart_interval_seconds=30.0)

        self.assertEqual(supervisor.app_restart_cooldown(0.0), 0.0)
        supervisor.note_app_restart(0.0)
        self.assertEqual(supervisor.app_restart_cooldown(0.0), 30.0)
        self.assertEqual(supervisor.app_restart_cooldown(10.0), 20.0)
        self.assertEqual(supervisor.app_restart_cooldown(30.0), 0.0)

    def test_stable_state_clears_restart_and_emulator_history(self):
        supervisor = RecoverySupervisor()

        supervisor.note_app_restart(0.0)
        supervisor.request_emulator_restart()
        supervisor.mark_stable()

        self.assertEqual(supervisor.restart_times, ())
        self.assertEqual(supervisor.emulator_restarts_without_stable, 0)
        self.assertEqual(supervisor.emulator_restart_delay_seconds, 45.0)
        self.assertEqual(supervisor.app_restart_cooldown(0.0), 0.0)
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
        cls.dismiss_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "DismissSetTrapScreen"
        )
        cls.fallback_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "FindCoordsOrElseExecuteFallbackAndWait"
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

        def dismiss_settrap(screen):
            if screen != "settrap":
                return False
            back_presses.append("back")
            return True

        namespace = {
            "ScreenShot": lambda: next(screen_iter),
            "CheckIf": lambda screen, pattern: (
                pattern == "dungflag" and screen in {"dungeon", "settrap"}
            ),
            "DismissSetTrapScreen": dismiss_settrap,
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

    def test_settrap_overlay_is_closed_before_accepting_its_dungeon_flag(self):
        return_to_dungeon, back_presses = self.build_function(
            ["settrap", "dungeon"]
        )

        self.assertTrue(return_to_dungeon())
        self.assertEqual(back_presses, ["back"])

    def test_settrap_dismissal_uses_android_back_once(self):
        back_presses = []
        sleeps = []
        namespace = {
            "ScreenShot": lambda: "settrap",
            "CheckIf": lambda screen, pattern: (
                screen == "settrap" and pattern == "settrap"
            ),
            "PressReturn": lambda: back_presses.append("back"),
            "Sleep": sleeps.append,
            "logger": type(
                "FakeLogger",
                (),
                {"info": staticmethod(lambda _message: None)},
            ),
            "_": lambda message: message,
        }
        module = ast.Module(body=[self.dismiss_node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<settrap-dismiss>", "exec"), namespace)
        dismiss = namespace["DismissSetTrapScreen"]

        self.assertFalse(dismiss("dungeon"))
        self.assertTrue(dismiss("settrap"))
        self.assertEqual(back_presses, ["back"])
        self.assertEqual(sleeps, [0.5])

    def test_settrap_dismissal_is_shared_by_state_and_recovery_paths(self):
        required_blocks = {
            "fallback": ("def FindCoordsOrElseExecuteFallbackAndWait", "def restartGame"),
            "overlay": ("def HandleBlockingOverlay", "def IdentifyState"),
            "post_combat": ("def ResolvePostCombatState", "def StateInn"),
            "recovery": ("counter_trychar = -1", "########### 防止卡空气墙"),
        }

        for name, (start_marker, end_marker) in required_blocks.items():
            with self.subTest(path=name):
                start = self.source.index(start_marker)
                end = self.source.index(end_marker, start)
                self.assertIn(
                    "DismissSetTrapScreen(",
                    self.source[start:end],
                )

        self.assertTrue((Path(ResolveTemplatePath('settrap.png'))).is_file())

    def test_fallback_loop_checks_remote_stop_before_screenshot(self):
        calls = []
        runtime = object()

        class StopRequested(Exception):
            pass

        class Event:
            @staticmethod
            def is_set():
                return False

        class Setting:
            MAX_TRY_LIMIT = 25
            _FORCESTOPING = Event()
            _REMOTE_RUNTIME = runtime

        def checkpoint(current_runtime, kind):
            calls.append((current_runtime, kind))
            raise StopRequested()

        namespace = {
            "setting": Setting(),
            "TaskStoppedException": RuntimeError,
            "remote_stop_checkpoint": checkpoint,
            "CheckpointKind": type("CheckpointKind", (), {"BETWEEN_OPERATIONS": "between"}),
        }
        module = ast.Module(body=[self.fallback_node], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<fallback-stop-checkpoint>", "exec"), namespace)

        with self.assertRaises(StopRequested):
            namespace["FindCoordsOrElseExecuteFallbackAndWait"]("target", None, 0)

        self.assertEqual(calls, [(runtime, "between")])

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
            "检测到猎人的陷阱设置画面. 返回关闭后继续恢复.",
        )

        for language in ("en_US", "ko_KR"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message_id in message_ids:
                self.assertNotEqual(translations.gettext(message_id), message_id)


class PartyReunionTests(unittest.TestCase):
    def build_reunion(self, party_name, *, dialogue=True, stuck=False):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        names = {
            "reunionParty", "FindCoordsOrElseExecuteFallbackAndWait",
            "RestartableSequenceExecution", "RestartSignal",
        }
        nodes = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in names
        ]
        selection = [137, 590] if party_name else [137, 290]
        screens = {
            "town": {"guild": [156, 844]},
            "dialogue": {"guildDecline": [451, 991]},
            "guild": {"Edit": [450, 610]},
            "edit": {"PartyManagement": [450, 1100]},
            "party": {
                "PartyManagementTitle": [450, 110],
                "FFXI/FFXIStone": selection,
            },
            "selected": {"AssembleParty": [650, 1500]},
            "confirm": {"ok": [450, 900]},
            "done": {},
            "returned": {"Inn": [200, 700]},
        }
        transitions = {
            ("town", (156, 844)): "dialogue" if dialogue else "guild",
            ("dialogue", (451, 991)): "dialogue" if stuck else "guild",
            ("guild", (450, 610)): "edit",
            ("edit", (450, 1100)): "party",
            ("party", tuple(selection)): "selected",
            ("selected", (650, 1500)): "confirm",
            ("confirm", (450, 900)): "done",
            ("done", "back"): "returned",
        }
        state = {"screen": "town", "presses": [], "restarts": 0}

        def press(position):
            if position is None:
                return False
            key = position if position == "back" else tuple(position)
            state["presses"].append((state["screen"], key))
            state["screen"] = transitions.get(
                (state["screen"], key), state["screen"]
            )
            return True

        def restart():
            state["restarts"] += 1
            raise RuntimeError("recovery requested")

        namespace = {
            "setting": SimpleNamespace(
                MAX_TRY_LIMIT=6, _FORCESTOPING=threading.Event(),
            ),
            "classify_screen": classify_screen,
            "ScreenHealth": ScreenHealth,
            "ScreenShot": lambda: state["screen"],
            "CheckIf": lambda screen, pattern: screens[screen].get(pattern),
            "Press": press,
            "PressReturn": lambda: press("back"),
            "Sleep": lambda *args: None,
            "DismissSetTrapScreen": lambda screen: False,
            "TryPressRetry": lambda screen: False,
            "CheckIf_fastForwardOff": lambda screen: None,
            "remote_stop_checkpoint": lambda *args: None,
            "CheckpointKind": SimpleNamespace(BETWEEN_OPERATIONS="between"),
            "TaskStoppedException": RuntimeError,
            "restartGame": restart,
            "logger": SimpleNamespace(info=lambda *args: None),
            "time": time,
            "_": lambda message: message,
        }
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<party-reunion>", "exec"), namespace)
        return namespace["reunionParty"], state

    def test_named_and_default_parties_reassemble_through_guild_dialogue(self):
        for party_name in (None, "FFXI/FFXIStone"):
            for dialogue, start in (
                (False, "town"), (True, "town"),
                (True, "dialogue"), (False, "party"),
            ):
                with self.subTest(party_name=party_name, dialogue=dialogue, start=start):
                    reunion, state = self.build_reunion(
                        party_name, dialogue=dialogue,
                    )
                    state["screen"] = start
                    reunion(party_name)
                    self.assertEqual(state["screen"], "returned")
                    self.assertEqual(state["restarts"], 0)
                    self.assertEqual(
                        state["presses"].count(("dialogue", (451, 991))),
                        int(dialogue),
                    )

    def test_unresponsive_guild_choice_keeps_the_existing_retry_bound(self):
        reunion, state = self.build_reunion("FFXI/FFXIStone", stuck=True)
        state["screen"] = "dialogue"
        with self.assertRaisesRegex(RuntimeError, "recovery requested"):
            reunion("FFXI/FFXIStone")
        self.assertEqual(state["restarts"], 1)
        self.assertEqual(
            state["presses"].count(("dialogue", (451, 991))), 6,
        )


if __name__ == "__main__":
    unittest.main()
