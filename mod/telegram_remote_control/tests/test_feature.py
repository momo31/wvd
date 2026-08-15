from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mod.telegram_remote_control.adapters import ControllerPorts
from mod.telegram_remote_control.feature import TelegramRemoteFeature
from mod.telegram_remote_control.models import (
    ControlState,
    ForceStopResult,
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


class _RecordingService:
    def __init__(self):
        self.generation = 0
        self.messages = []
        self._keys = set()

    def enqueue(self, message):
        if message.key in self._keys:
            return False
        self._keys.add(message.key)
        self.messages.append(message)
        return True


class FeatureTests(unittest.TestCase):
    def make_feature(self, events=None):
        events = [] if events is None else events
        ports = _Ports(events)
        feature = TelegramRemoteFeature(
            queue.Queue(),
            None,
            ControllerPorts(ports.load_raw, ports.load_setting, ports.start_task, ports.alive, ports.sync, ports.after),
            None,
            "ko_KR",
        )
        feature.service = _RecordingService()
        feature.current_settings = TelegramSettings(True, "123456:" + "x" * 20, "123456789")
        return feature, ports

    def test_remote_stop_transitions_to_at_title_after_finished(self):
        events = []
        feature, _ports = self.make_feature(events)
        event_queue = feature.event_queue
        runtime = RemoteRuntime(
            "run-1", StartReason.TELEGRAM, "Task", event_queue, threading.Event(), None, "", datetime.now(timezone.utc), 0.0, "123456789"
        )
        feature.on_task_started(runtime)
        self.assertEqual(feature.state, ControlState.STARTING)
        feature.handle_event(
            "telegram_command",
            TelegramCommandPayload(RemoteCommand.STOP, 1, "123456789", datetime.now(timezone.utc), feature.service.generation),
        )
        self.assertEqual(feature.state, ControlState.STOP_REQUESTED)
        runtime.mark_exit(TaskExitReason.REMOTE_STOP, "done")
        feature.handle_event("task_finished", runtime.build_finished_payload(finished_monotonic=1.0))
        self.assertEqual(feature.state, ControlState.AT_TITLE)

    def test_stat_returns_only_recent_log_and_redacts_secrets(self):
        feature, _ports = self.make_feature()
        now = datetime.now()
        token = feature.current_settings.bot_token
        chat_id = feature.current_settings.allowed_chat_id
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            feature.log_directory = log_dir
            (log_dir / "log_current.txt").write_text(
                f"{now - timedelta(seconds=80):%Y-%m-%d %H:%M:%S} - INFO - old entry\n"
                f"{now - timedelta(seconds=5):%Y-%m-%d %H:%M:%S} - INFO - running token={token} chat={chat_id}\n",
                encoding="utf-8",
            )
            stat_payload = TelegramCommandPayload(
                RemoteCommand.STAT,
                10,
                chat_id,
                datetime.now(timezone.utc),
                feature.service.generation,
            )
            feature.handle_event("telegram_command", stat_payload)
            status_payload = TelegramCommandPayload(
                RemoteCommand.STATUS,
                11,
                chat_id,
                datetime.now(timezone.utc),
                feature.service.generation,
            )
            feature.handle_event("telegram_command", status_payload)

        messages = {message.key: message for message in feature.service.messages}
        self.assertEqual(set(messages), {"stat:10", "status:11"})
        for message in messages.values():
            self.assertIn("최근 60초", message.text)
            self.assertIn("UI 메시지", message.text)
            self.assertIn("running", message.text)
            self.assertNotIn("old entry", message.text)
            self.assertNotIn(token, message.text)
            self.assertNotIn(chat_id, message.text)
            self.assertLessEqual(len(message.text), 3900)

    def test_menu_owns_command_list(self):
        feature, _ports = self.make_feature()
        payload = TelegramCommandPayload(
            RemoteCommand.MENU,
            11,
            "123456789",
            datetime.now(timezone.utc),
            feature.service.generation,
        )
        feature.handle_event("telegram_command", payload)
        message = feature.service.messages[-1]
        self.assertIn("명령 메뉴", message.text)
        self.assertIn("stat", message.text)
        self.assertIn("menu", message.text)

    def test_local_macro_error_notifies_configured_chat_once(self):
        feature, _ports = self.make_feature()
        runtime = RemoteRuntime(
            "local-error",
            StartReason.LOCAL,
            "Task",
            feature.event_queue,
            threading.Event(),
            None,
            "",
            datetime.now(timezone.utc),
            0.0,
        )
        feature.on_task_started(runtime)
        runtime.mark_exit(TaskExitReason.ERROR, "unexpected worker error", "farm_worker")
        payload = runtime.build_finished_payload(finished_monotonic=5.0)
        feature.handle_event("task_finished", payload)
        feature.handle_event("task_finished", payload)

        messages = [message for message in feature.service.messages if message.key == "abnormal-exit:local-error"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].chat_id, "123456789")
        self.assertIn("비정상 종료", messages[0].text)
        self.assertIn("unexpected worker error", messages[0].text)
        self.assertIn("farm_worker", messages[0].text)

    def test_failed_remote_stop_fallback_notifies_abnormal_exit(self):
        feature, _ports = self.make_feature()
        runtime = RemoteRuntime(
            "fallback-error",
            StartReason.TELEGRAM,
            "Task",
            feature.event_queue,
            threading.Event(),
            None,
            "",
            datetime.now(timezone.utc),
            0.0,
            "123456789",
        )
        feature.on_task_started(runtime)
        runtime.mark_exit(TaskExitReason.REMOTE_STOP_FALLBACK, "fallback attempted", "stop_watchdog")
        feature.handle_event("task_finished", runtime.build_finished_payload(finished_monotonic=5.0))
        feature.handle_event(
            "remote_force_stop_result",
            ForceStopResult(runtime.run_id, False, "not stopped"),
        )

        message = feature.service.messages[-1]
        self.assertEqual(message.key, "abnormal-exit:fallback-error")
        self.assertIn("게임 종료 확인에 실패", message.text)


if __name__ == "__main__":
    unittest.main()
