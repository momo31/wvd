from __future__ import annotations

import queue
import threading
import unittest
from datetime import datetime, timezone

from mod.telegram_remote_control.adapters import ControllerPorts
from mod.telegram_remote_control.feature import TelegramRemoteFeature
from mod.telegram_remote_control.models import (
    ControlState,
    RemoteCommand,
    StartReason,
    TelegramCommandPayload,
    TelegramSettings,
    TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime


class _Ports:
    def __init__(self, events):
        self.events = events
        self.started = None

    def load_raw(self, _path):
        return {"GENERAL": {"TELEGRAM_ENABLED": False}}

    def load_setting(self):
        return type("Setting", (), {"FARM_TARGET": "task", "FARM_TARGET_TEXT": "Task"})()

    def start_task(self, setting, reason, run_id, runtime):
        self.started = runtime
        return True

    def alive(self):
        return False

    def sync(self, state):
        self.events.append(state)

    def after(self, _delay, callback):
        callback()


class FeatureTests(unittest.TestCase):
    def test_remote_stop_transitions_to_at_title_after_finished(self):
        events = []
        ports = _Ports(events)
        event_queue = queue.Queue()
        feature = TelegramRemoteFeature(
            event_queue,
            None,
            ControllerPorts(ports.load_raw, ports.load_setting, ports.start_task, ports.alive, ports.sync, ports.after),
            None,
            "ko_KR",
        )
        feature.current_settings = TelegramSettings(True, "123:" + "x" * 20, "1")
        runtime = RemoteRuntime(
            "run-1", StartReason.TELEGRAM, "Task", event_queue, threading.Event(), None, "", datetime.now(timezone.utc), 0.0, "1"
        )
        feature.on_task_started(runtime)
        self.assertEqual(feature.state, ControlState.STARTING)
        feature.handle_event(
            "telegram_command",
            TelegramCommandPayload(RemoteCommand.STOP, 1, "1", datetime.now(timezone.utc), feature.service.generation),
        )
        self.assertEqual(feature.state, ControlState.STOP_REQUESTED)
        runtime.mark_exit(TaskExitReason.REMOTE_STOP, "done")
        feature.handle_event("task_finished", runtime.build_finished_payload(finished_monotonic=1.0))
        self.assertEqual(feature.state, ControlState.AT_TITLE)


if __name__ == "__main__":
    unittest.main()
