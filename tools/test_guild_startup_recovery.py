"""Replay guild entry and restart recovery without sending device input."""

import ast
import queue
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from tools.test_server_maintenance import _ExtractFunctions
from recovery import RecoverySupervisor
from screen_health import ScreenHealth, classify_screen
from mod.telegram_remote_control.models import CheckpointKind, RemoteStopSignal, StartReason, TaskExitReason
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime, remote_stop_checkpoint


ROOT = Path(__file__).resolve().parents[1]


class GuildStartupRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / "src/script.py").read_text(encoding="utf-8"))
        names = {
            "CutRoI", "_check", "CheckIf", "CheckIfAtThreshold", "StopTaskWithError",
            "FindCoordsOrElseExecuteFallbackAndWait", "WaitForGameStartup",
            "restartGame", "RestartableSequenceExecution", "RestartSignal", "TaskStoppedException",
        }
        nodes = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
        module = _ExtractFunctions().visit(ast.Module(body=nodes, type_ignores=[]))
        cls.code = compile(ast.fix_missing_locations(module), "<guild-startup>", "exec")

    def harness(self):
        event = threading.Event()
        runtime = RemoteRuntime("guild-startup", StartReason.LOCAL, "Scorpionesses",
                                queue.Queue(), event, None, "test")
        clock = SimpleNamespace(now=0.0)
        images = {}

        def template(name):
            if name not in images:
                images[name] = cv2.imread(str(ROOT / "resources" / "images" / f"{name}.png"))
                assert images[name] is not None, name
            return images[name]

        def screen(name=None, x=350, y=700):
            image = np.full((1600, 900, 3), 60, dtype=np.uint8)
            if name:
                tile = template(name)
                h, w = tile.shape[:2]
                image[y:y+h, x:x+w] = tile
            return image

        def sleep(seconds=1):
            if event.is_set():
                raise namespace["TaskStoppedException"]()
            clock.now += seconds

        context = SimpleNamespace(_CRASHCOUNTER=0, _RECOVERY_SUPERVISOR=RecoverySupervisor())
        namespace = {
            "cv2": cv2, "np": np, "time": SimpleNamespace(monotonic=lambda: clock.now, time=lambda: clock.now),
            "classify_screen": classify_screen, "ScreenHealth": ScreenHealth,
            "setting": SimpleNamespace(_FORCESTOPING=event, _REMOTE_RUNTIME=runtime,
                                       MAX_TRY_LIMIT=25, MAX_CRASH_LIMIT=10),
            "runtimeContext": context, "TaskExitReason": TaskExitReason,
            "CheckpointKind": CheckpointKind, "RemoteStopSignal": RemoteStopSignal,
            "remote_stop_checkpoint": remote_stop_checkpoint,
            "LoadTemplateImage": template, "_": lambda value: value,
            "Sleep": sleep, "logger": Mock(), "SaveImage": Mock(), "AddImportantInfo": Mock(),
            "Press": Mock(), "PressReturn": Mock(), "ResetDevice": Mock(),
            "ReloadStrategy": Mock(return_value=False),
            "DeviceShell": Mock(side_effect=lambda cmd: "package/activity" if "resolve-activity" in cmd else ""),
            "raise_if_remote_recovery_disallowed": Mock(),
            "DismissSetTrapScreen": Mock(return_value=False), "TryPressRetry": Mock(return_value=False),
            "CheckIf_fastForwardOff": Mock(return_value=None),
            "HandleSessionExpiry": Mock(return_value=False), "HandleBlockingOverlay": Mock(return_value=False),
        }
        exec(self.code, namespace)
        return namespace, runtime, clock, screen

    def test_guild_invitation_is_dismissed_before_any_fallback_tap(self):
        ns, runtime, _, screen = self.harness()
        dialogue = screen("guildDecline", 390, 972)
        guild = screen("guildRequest")
        ns["ScreenShot"] = Mock(side_effect=[dialogue, guild])
        position = ns["FindCoordsOrElseExecuteFallbackAndWait"]("guildRequest", ["guild", [1, 1]], 1)
        self.assertIsNotNone(position)
        ns["Press"].assert_called_once_with([451, 991])
        ns["DeviceShell"].assert_not_called()
        self.assertIsNone(runtime.exit_reason)

    def test_quest_specific_choice_is_not_declined(self):
        ns, _, _, screen = self.harness()
        dialogue = screen("guildDecline", 390, 972)
        ns["ScreenShot"] = Mock(side_effect=[dialogue, screen("guildRequest")])
        ns["FindCoordsOrElseExecuteFallbackAndWait"](["COS/Okay", "guildRequest"], ["guild", [1, 1]], 1)
        self.assertNotIn(unittest.mock.call([451, 991]), ns["Press"].call_args_list)

    def test_stuck_guild_choice_stops_after_three_taps_without_restart(self):
        ns, runtime, _, screen = self.harness()
        ns["ScreenShot"] = Mock(return_value=screen("guildDecline", 390, 972))
        with self.assertRaises(ns["TaskStoppedException"]):
            ns["FindCoordsOrElseExecuteFallbackAndWait"]("guildRequest", ["guild", [1, 1]], 1)
        self.assertEqual(ns["Press"].call_count, 3)
        self.assertEqual(runtime.failure_phase, "guild_dialog_stuck")
        self.assertEqual(runtime.exit_reason, TaskExitReason.ERROR)
        ns["DeviceShell"].assert_not_called()

    def test_restart_waits_past_normal_retry_budget_then_resumes_guild_entry(self):
        ns, _, clock, screen = self.harness()
        loading = screen()
        # Actual 19:05:49 loading frame; its progress bar also resembles Close.
        crop = cv2.imread(str(ROOT / "tools" / "fixtures" / "game_startup_loading.png"))
        self.assertEqual(crop.shape, (1490, 900, 3))
        loading[:1490] = crop
        ns["HandleBlockingOverlay"].side_effect = AssertionError("generic Close matching during loading")
        start = loading.copy()
        tile = ns["LoadTemplateImage"]("tabtostart")
        h, w = tile.shape[:2]
        start[1340:1340+h, 340:340+w] = tile
        dialogue = screen("guildDecline", 390, 972)
        guild = screen("guildRequest")
        ns["ScreenShot"] = Mock(side_effect=[loading] * 40 + [start, dialogue, dialogue, dialogue, guild])
        attempts = []

        def operation():
            attempts.append(clock.now)
            if len(attempts) == 1:
                ns["restartGame"](skip_screenshot=True)
            ns["FindCoordsOrElseExecuteFallbackAndWait"]("guildRequest", ["guild", [1, 1]], 1)

        ns["RestartableSequenceExecution"](operation)
        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(attempts[1], 50)
        taps = [call.args[0] for call in ns["Press"].call_args_list]
        self.assertEqual(taps, [[340+w//2, 1340+h//2], [451, 991]])
        restarts = [call for call in ns["DeviceShell"].call_args_list if "am force-stop" in call.args[0]]
        self.assertEqual(len(restarts), 1)
        self.assertEqual(ns["runtimeContext"]._CRASHCOUNTER, 1)
        ns["ResetDevice"].assert_not_called()
        ns["HandleBlockingOverlay"].assert_not_called()

    def test_loading_timeout_stops_without_additional_restart(self):
        ns, runtime, clock, screen = self.harness()
        ns["ScreenShot"] = Mock(return_value=screen("titlelogo", 336, 467))
        # Advance the fake clock in large steps; recognition is exercised by
        # the restart test, while this case verifies the elapsed-time bound.
        ns["Sleep"] = lambda seconds: setattr(clock, "now", clock.now + 100 * seconds)
        with self.assertRaises(ns["TaskStoppedException"]):
            ns["WaitForGameStartup"]()
        self.assertEqual(clock.now, 300)
        self.assertEqual(runtime.failure_phase, "game_startup_timeout")
        self.assertTrue(runtime.worker_force_stop_event.is_set())
        ns["Press"].assert_not_called()
        ns["DeviceShell"].assert_not_called()
        self.assertEqual(ns["runtimeContext"]._CRASHCOUNTER, 0)

    def test_local_and_remote_stop_interrupt_startup_wait(self):
        from mod.telegram_remote_control.models import RemoteStopSignal
        for remote in (False, True):
            with self.subTest(remote=remote):
                ns, runtime, clock, screen = self.harness()
                ns["ScreenShot"] = Mock(return_value=screen("titlelogo", 336, 467))
                def stop_after_sleep(seconds):
                    clock.now += seconds
                    if remote:
                        runtime.request_stop(None, clock.now, None)
                    else:
                        runtime.worker_force_stop_event.set()
                ns["Sleep"] = stop_after_sleep
                with self.assertRaises(RemoteStopSignal if remote else ns["TaskStoppedException"]):
                    ns["WaitForGameStartup"]()
                ns["ScreenShot"].assert_called_once()
                ns["DeviceShell"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
