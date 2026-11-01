"""Exercise maintenance detection and task completion without a device or bot."""

import ast
import copy
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recovery import RecoverySupervisor
from mod.telegram_remote_control.login_transition import prepare_telegram_run
from mod.telegram_remote_control.models import (
    CheckpointKind, ControlState, RemoteRecoverySuppressed, RemoteStopSignal,
    StartReason, TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime, remote_stop_checkpoint
from mod.telegram_remote_control.worker import TaskCompletionLatch, run_farm_worker


from utils import ResolveTemplatePath


class _ExtractFunctions(ast.NodeTransformer):
    def visit_Nonlocal(self, node):
        # Execute the real nested functions against one controlled namespace.
        return ast.copy_location(ast.Global(names=node.names), node)


class ServerMaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "src" / "script.py").read_text(encoding="utf-8")
        names = {
            "CutRoI", "_check", "CheckIfAtThreshold", "StopIfServerMaintenance", "StopTaskWithError",
            "ScreenShot", "FindCoordsOrElseExecuteFallbackAndWait", "StateEoT",
            "RestartableSequenceExecution", "RestartSignal", "TaskStoppedException", "Farm",
        }
        nodes = [
            copy.deepcopy(node) for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        ]
        assert {node.name for node in nodes} == names
        module = _ExtractFunctions().visit(ast.Module(body=nodes, type_ignores=[]))
        cls.code = compile(ast.fix_missing_locations(module), "<maintenance-runtime>", "exec")
        crop = cv2.imread(str(ROOT / "tools" / "fixtures" / "server_maintenance_ko.png"))
        assert crop is not None and crop.shape == (440, 500, 3)
        cls.screen = np.zeros((1600, 900, 3), dtype=np.uint8)
        cls.screen[580:1020, 200:700] = crop

    def build_runtime(self, start_reason=StartReason.LOCAL, *, remote=True, save_fails=False):
        event = threading.Event()
        events = queue.Queue()
        runtime = RemoteRuntime("maintenance-test", start_reason, "FFXI-Org", events, event, None, "test")
        latch = TaskCompletionLatch(events, runtime.run_id)
        setting = SimpleNamespace(
            _FORCESTOPING=event, _REMOTE_RUNTIME=runtime if remote else None,
            _FINISHINGCALLBACK=latch.callback, FARM_TARGET="FFXI-Org", MAX_TRY_LIMIT=25,
            _ADBDEVICE=SimpleNamespace(serial="test", client=SimpleNamespace(host="127.0.0.1", port=5037)),
        )
        supervisor = RecoverySupervisor()
        supervisor.note_app_restart(1.0)
        supervisor.request_emulator_restart()
        context = SimpleNamespace(
            _LAST_GAME_FOCUS_CHECK=time.monotonic(), _SKIP_SCREENSHOT_WARNING=False,
            _CRASHCOUNTER=10, _RECOVERY_SUPERVISOR=supervisor,
        )
        quest = SimpleNamespace(
            _TYPE="quest", _preEOTcheck=None,
            _EOT=[["press", "EVENT", "FFXI/EVENT_GCN", 1], ["press", "FFXI/ZONE2", [1, 1], 1]],
        )
        namespace = {
            "cv2": cv2, "np": np, "struct": struct, "subprocess": subprocess, "time": time,
            "setting": setting, "runtimeContext": context, "RuntimeContext": lambda: context,
            "quest": quest, "FarmConfig": SimpleNamespace, "LoadQuest": lambda _: quest,
            "TaskExitReason": TaskExitReason, "StartReason": StartReason, "ControlState": ControlState,
            "RemoteStopSignal": RemoteStopSignal, "RemoteRecoverySuppressed": RemoteRecoverySuppressed,
            "CheckpointKind": CheckpointKind, "remote_stop_checkpoint": remote_stop_checkpoint,
            "prepare_telegram_run": prepare_telegram_run, "_": lambda value: value,
            "consecutive_failures": 0, "orientation_failures": 0, "MAX_SCREENSHOT_RETRIES": 5,
            "LoadTemplateImage": lambda name: cv2.imread(str(Path(ResolveTemplatePath(f'{name}.png')))),
            "SaveImage": Mock(side_effect=OSError("disk full") if save_fails else None),
            "AddImportantInfo": Mock(), "logger": Mock(), "Sleep": Mock(), "ReloadStrategy": Mock(),
            "ResetDevice": Mock(return_value=True), "restartGame": Mock(side_effect=AssertionError("unexpected restart")),
            "DeviceShell": Mock(side_effect=AssertionError("unexpected device command")),
            "Press": Mock(), "PressReturn": Mock(), "CheckIf": Mock(return_value=None),
            "DismissSetTrapScreen": Mock(return_value=False), "TryPressRetry": Mock(return_value=False),
            "CheckIf_fastForwardOff": Mock(return_value=None),
        }
        exec(self.code, namespace)
        adapter = SimpleNamespace(
            screenshot=namespace["ScreenShot"], local_stop_exception_type=namespace["TaskStoppedException"],
            control_shell=Mock(return_value="123"),
        )
        namespace["BuildRemoteAdapter"] = lambda: adapter
        namespace["QuestFarm"] = lambda: namespace["RestartableSequenceExecution"](namespace["StateEoT"])
        return namespace, runtime, latch, adapter

    def capture_patch(self, screen):
        raw = struct.pack("<III", 900, 1600, 1) + cv2.cvtColor(screen, cv2.COLOR_BGR2RGBA).tobytes()
        connection = Mock()
        connection.recv.side_effect = [b"OKAY", b"OKAY", raw, b""]
        return patch.object(socket, "socket", return_value=connection)

    def test_to_title_without_maintenance_text_does_not_stop_capture(self):
        screen = self.screen.copy()
        # Retain the dialog's real To Title button, but remove the maintenance sentences.
        screen[580:720, 200:700] = 0
        namespace, runtime, _, _ = self.build_runtime()
        with self.capture_patch(screen):
            captured = namespace["ScreenShot"]()
        np.testing.assert_array_equal(captured, screen)
        self.assertFalse(namespace["setting"]._FORCESTOPING.is_set())
        self.assertIsNone(runtime.exit_reason)
        namespace["SaveImage"].assert_not_called()
        namespace["restartGame"].assert_not_called()

    def test_maintenance_stops_without_a_remote_runtime(self):
        namespace, _, _, _ = self.build_runtime(remote=False)
        with self.capture_patch(self.screen), self.assertRaises(namespace["TaskStoppedException"]):
            namespace["ScreenShot"]()
        self.assertTrue(namespace["setting"]._FORCESTOPING.is_set())
        namespace["SaveImage"].assert_called_once()
        namespace["ResetDevice"].assert_not_called()
        namespace["restartGame"].assert_not_called()

    def test_mining_and_telegram_login_stop_before_recovery_and_complete_once(self):
        for start_reason in (StartReason.LOCAL, StartReason.TELEGRAM):
            for save_fails in (False, True):
                with self.subTest(start_reason=start_reason, save_fails=save_fails):
                    namespace, runtime, latch, adapter = self.build_runtime(start_reason, save_fails=save_fails)
                    with self.capture_patch(self.screen):
                        run_farm_worker(namespace["Farm"], namespace["setting"], runtime, latch, namespace["logger"])
                    self.assertEqual(runtime.exit_reason, TaskExitReason.ERROR)
                    self.assertEqual(runtime.failure_phase, "server_maintenance")
                    self.assertIn("서버 점검", runtime.detail)
                    self.assertTrue(runtime.worker_force_stop_event.is_set())
                    self.assertEqual(namespace["runtimeContext"]._CRASHCOUNTER, 10)
                    supervisor = namespace["runtimeContext"]._RECOVERY_SUPERVISOR
                    self.assertEqual(supervisor.restart_times, (1.0,))
                    self.assertEqual(supervisor.emulator_restarts_without_stable, 1)
                    namespace["ResetDevice"].assert_called_once_with()  # Initial connection only.
                    namespace["restartGame"].assert_not_called()
                    namespace["DeviceShell"].assert_not_called()
                    namespace["Press"].assert_not_called()
                    namespace["PressReturn"].assert_not_called()
                    namespace["logger"].exception.assert_not_called()
                    namespace["SaveImage"].assert_called_once()
                    if start_reason is StartReason.TELEGRAM:
                        adapter.control_shell.assert_called_once_with(["pidof", "jp.co.drecom.wizardry.daphne"])
                    self.assertFalse(latch.callback())
                    completion = []
                    while not runtime.event_queue.empty():
                        event = runtime.event_queue.get_nowait()
                        if event[0] == "task_completion_requested":
                            completion.append(event)
                    self.assertEqual(completion, [("task_completion_requested", runtime.run_id)])


if __name__ == "__main__":
    unittest.main()
