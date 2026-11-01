"""Exercise the real nested Farm/ResetDevice/DeviceShell without an emulator."""

import ast
import queue
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2

from mod.telegram_remote_control.models import (
    CheckpointKind, ControlState, RemoteRecoverySuppressed, RemoteStopSignal,
    StartReason, TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime, raise_if_remote_recovery_disallowed
from mod.telegram_remote_control.worker import TaskCompletionLatch, run_farm_worker


class AdbFailureTests(unittest.TestCase):
    def build(self, recoveries):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "src/script.py").read_text(encoding="utf-8"))
        names = {"Farm", "ResetDevice", "DeviceShell", "TaskStoppedException", "RestartSignal"}
        nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]

        class Extract(ast.NodeTransformer):
            def visit_Nonlocal(self, node):
                if set(node.names) <= {"setting", "runtimeContext", "quest"}:
                    return ast.copy_location(ast.Global(node.names), node)
                return node

        events = queue.Queue()
        runtime = RemoteRuntime("adb-test", StartReason.LOCAL, "quest", events, threading.Event(), "123", "test")
        latch = TaskCompletionLatch(events, runtime.run_id)
        setting = SimpleNamespace(
            _REMOTE_RUNTIME=runtime, _FORCESTOPING=runtime.worker_force_stop_event,
            _FINISHINGCALLBACK=latch.callback, FARM_TARGET="quest",
        )
        ns = dict(
            setting=setting, runtimeContext=SimpleNamespace(), RuntimeContext=SimpleNamespace, FarmConfig=SimpleNamespace,
            Sleep=Mock(), ReloadStrategy=Mock(), logger=Mock(), cv2=cv2,
            TaskExitReason=TaskExitReason, StartReason=StartReason, ControlState=ControlState,
            RemoteStopSignal=RemoteStopSignal, RemoteRecoverySuppressed=RemoteRecoverySuppressed,
            CheckpointKind=CheckpointKind, raise_if_remote_recovery_disallowed=raise_if_remote_recovery_disallowed,
            CheckAndRecoverDevice=Mock(side_effect=recoveries), BuildRemoteAdapter=Mock(),
            LoadQuest=lambda _: SimpleNamespace(_TYPE="quest"), QuestFarm=Mock(),
            Event=threading.Event, Thread=threading.Thread, time=SimpleNamespace(sleep=Mock()),
            _=lambda s: s,
        )
        module = Extract().visit(ast.Module(nodes, type_ignores=[]))
        exec(compile(ast.fix_missing_locations(module), "<adb-runtime>", "exec"), ns)
        return ns, runtime, latch

    def run_farm(self, ns, runtime, latch):
        run_farm_worker(ns["Farm"], ns["setting"], runtime, latch, ns["logger"])
        completions = [event for event in list(runtime.event_queue.queue) if event[0] == "task_completion_requested"]
        self.assertEqual(completions, [("task_completion_requested", runtime.run_id)])

    def test_initial_connection_failure_reports_error_once(self):
        ns, runtime, latch = self.build([None])
        self.run_farm(ns, runtime, latch)
        self.assertEqual(runtime.exit_reason, TaskExitReason.ERROR)
        self.assertEqual(runtime.failure_phase, "reset_device")
        self.assertFalse(runtime.worker_force_stop_event.is_set())
        ns["QuestFarm"].assert_not_called()

    def test_running_shell_recovery_failure_keeps_error_reason(self):
        device = SimpleNamespace(create_connection=Mock(side_effect=ConnectionResetError()))
        ns, runtime, latch = self.build([device, None])
        ns["QuestFarm"] = lambda: ns["DeviceShell"]("fake command")
        self.run_farm(ns, runtime, latch)
        self.assertEqual(runtime.exit_reason, TaskExitReason.ERROR)
        self.assertEqual(runtime.failure_phase, "reset_device")
        self.assertEqual(ns["CheckAndRecoverDevice"].call_count, 2)

    def test_real_local_stop_is_not_reported_as_device_error(self):
        ns, runtime, latch = self.build([None])
        runtime.worker_force_stop_event.set()
        self.run_farm(ns, runtime, latch)
        self.assertEqual(runtime.exit_reason, TaskExitReason.LOCAL_STOP)
        self.assertIsNone(runtime.failure_phase)

    def test_existing_error_survives_recovery_failure(self):
        ns, runtime, latch = self.build([None])
        runtime.mark_exit(TaskExitReason.ERROR, "earlier error", "specific_error")
        self.run_farm(ns, runtime, latch)
        self.assertEqual(runtime.failure_phase, "specific_error")

    def test_emulator_recovery_keeps_specific_boot_timeout_phase(self):
        ns, runtime, _ = self.build([None])
        self.assertFalse(ns["ResetDevice"](force_restart_emu=True))
        self.assertEqual(runtime.exit_reason, TaskExitReason.ERROR)
        self.assertEqual(runtime.failure_phase, "adb_boot_timeout")

    def test_manual_stop_during_recovery_does_not_return_as_a_boot_error(self):
        ns, runtime, _ = self.build([None])
        ns["CheckAndRecoverDevice"].side_effect = lambda *_: runtime.worker_force_stop_event.set()
        with self.assertRaises(ns["TaskStoppedException"]):
            ns["ResetDevice"](force_restart_emu=True)
        self.assertIsNone(runtime.exit_reason)

    def test_remote_stop_still_suppresses_recovery(self):
        ns, runtime, _ = self.build([None])
        runtime.request_stop(None, 0, "123")
        runtime.adapter = Mock()
        with self.assertRaises(RemoteRecoverySuppressed):
            ns["ResetDevice"]()
        ns["CheckAndRecoverDevice"].assert_not_called()
        self.assertIsNone(runtime.exit_reason)


if __name__ == "__main__":
    unittest.main()
