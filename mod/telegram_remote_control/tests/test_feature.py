from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mod.telegram_remote_control.adapters import ControllerPorts
from mod.telegram_remote_control.feature import (
    PERIODIC_SUMMARY_SECONDS,
    TelegramRemoteFeature,
)
from mod.telegram_remote_control.models import (
    ControlState,
    ForceStopResult,
    QuestTarget,
    RemoteCommand,
    StartReason,
    TelegramCallbackPayload,
    TelegramCommandPayload,
    TelegramSettings,
    TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime


class _Ports:
    def __init__(self, events):
        self.events = events
        self.started = None
        self.reboot_calls = 0
        self.alive_value = False
        self.selected_targets = []
        self.quest_targets = [
            QuestTarget("quest-a", "분류 A", "목표 A"),
            QuestTarget("quest-b", "분류 A", "목표 B"),
            QuestTarget("custom", "사용자 정의", "사용자 목표"),
        ]

    def load_raw(self, _path):
        return {"GENERAL": {"TELEGRAM_ENABLED": False}}

    def load_setting(self):
        return type("Setting", (), {"FARM_TARGET": "task", "FARM_TARGET_TEXT": "Task"})()

    def start_task(self, setting, reason, run_id, runtime):
        self.started = runtime
        return True

    def alive(self):
        return self.alive_value

    def sync(self, state):
        self.events.append(state)

    def after(self, _delay, callback):
        callback()

    def reboot_emulator(self):
        self.reboot_calls += 1
        return True

    def list_targets(self):
        return self.quest_targets

    def select_target(self, code):
        self.selected_targets.append(code)
        return True


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
            ControllerPorts(
                ports.load_raw,
                ports.load_setting,
                ports.start_task,
                ports.alive,
                ports.sync,
                ports.after,
                reboot_emulator=ports.reboot_emulator,
                list_quest_targets=ports.list_targets,
                select_quest_target=ports.select_target,
            ),
            None,
            "ko_KR",
        )
        feature.service = _RecordingService()
        feature.current_settings = TelegramSettings(True, "123456:" + "x" * 20, "123456789")
        return feature, ports

    @staticmethod
    def callback_payload(data, update_id, feature):
        return TelegramCallbackPayload(
            data,
            f"callback-{update_id}",
            update_id,
            "123456789",
            datetime.now(timezone.utc),
            feature.service.generation,
        )

    def test_quest_menu_selects_and_saves_without_starting(self):
        feature, ports = self.make_feature()
        feature.handle_event(
            "telegram_command",
            TelegramCommandPayload(
                RemoteCommand.QUEST,
                20,
                "123456789",
                datetime.now(timezone.utc),
                feature.service.generation,
            ),
        )
        categories = feature.service.messages[-1]
        category_buttons = categories.reply_markup["inline_keyboard"]
        self.assertEqual([row[0]["text"] for row in category_buttons], ["분류 A", "사용자 정의"])
        self.assertTrue(all(len(row[0]["callback_data"].encode("utf-8")) <= 64 for row in category_buttons))

        feature.handle_event(
            "telegram_callback",
            self.callback_payload(category_buttons[0][0]["callback_data"], 21, feature),
        )
        targets = feature.service.messages[-1]
        target_buttons = targets.reply_markup["inline_keyboard"]
        self.assertEqual([row[0]["text"] for row in target_buttons[:-1]], ["목표 A", "목표 B"])
        self.assertTrue(all(len(row[0]["callback_data"].encode("utf-8")) <= 64 for row in target_buttons))
        self.assertEqual(target_buttons[-1][0]["callback_data"], "quest:root")

        feature.handle_event(
            "telegram_callback",
            self.callback_payload(target_buttons[0][0]["callback_data"], 22, feature),
        )

        self.assertEqual(ports.selected_targets, ["quest-a"])
        self.assertIsNone(ports.started)
        self.assertIn("/start", feature.service.messages[-1].text)

    def test_quest_selection_is_blocked_while_busy_and_rejects_stale_data(self):
        feature, ports = self.make_feature()
        ports.alive_value = True
        feature.handle_event(
            "telegram_command",
            TelegramCommandPayload(
                RemoteCommand.QUEST,
                30,
                "123456789",
                datetime.now(timezone.utc),
                feature.service.generation,
            ),
        )
        self.assertIsNone(feature.service.messages[-1].reply_markup)
        self.assertIn("완전히 정지", feature.service.messages[-1].text)

        ports.alive_value = False
        feature.handle_event(
            "telegram_callback",
            self.callback_payload("quest:target:stale", 31, feature),
        )
        self.assertEqual(ports.selected_targets, [])
        self.assertIn("다시 여세요", feature.service.messages[-1].text)

    def test_local_start_from_terminal_state_transitions_to_running(self):
        terminal_states = (
            ControlState.AT_TITLE,
            ControlState.GAME_STOPPED_FALLBACK,
            ControlState.ERROR,
        )
        for index, terminal_state in enumerate(terminal_states):
            with self.subTest(terminal_state=terminal_state):
                events = []
                feature, _ports = self.make_feature(events)
                feature.state = terminal_state
                runtime = RemoteRuntime(
                    f"local-restart-{index}",
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

                self.assertEqual(feature.state, ControlState.RUNNING)
                self.assertEqual(events[-1], ControlState.RUNNING)

    def test_periodic_summary_sends_latest_dungeon_update_every_three_hours(self):
        feature, _ports = self.make_feature()
        runtime = RemoteRuntime(
            "summary-run",
            StartReason.LOCAL,
            "Task",
            feature.event_queue,
            threading.Event(),
            None,
            "",
            datetime.now(timezone.utc),
            100.0,
        )
        feature.on_task_started(runtime)
        feature.handle_event("dungeon_summary", (runtime.run_id, "첫 번째 요약"))
        feature.handle_event("dungeon_summary", ("stale-run", "다른 실행의 요약"))

        feature.tick(100.0 + PERIODIC_SUMMARY_SECONDS - 0.1)
        self.assertEqual(feature.service.messages, [])

        feature.handle_event("dungeon_summary", (runtime.run_id, "최신 요약"))
        feature.tick(100.0 + PERIODIC_SUMMARY_SECONDS)
        feature.tick(100.0 + PERIODIC_SUMMARY_SECONDS + 1.0)

        self.assertEqual(len(feature.service.messages), 1)
        message = feature.service.messages[0]
        self.assertEqual(message.chat_id, "123456789")
        self.assertEqual(message.text, "최신 요약")
        self.assertEqual(message.key, "periodic-summary:summary-run:0")

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
        self.assertIn("reboot", message.text)
        self.assertIn("/quest", message.text)
        self.assertIn("menu", message.text)

    def test_reboot_runs_emulator_port_and_reports_completion(self):
        feature, ports = self.make_feature()
        payload = TelegramCommandPayload(
            RemoteCommand.REBOOT,
            12,
            "123456789",
            datetime.now(timezone.utc),
            feature.service.generation,
        )

        feature.handle_event("telegram_command", payload)

        self.assertTrue(feature.emulator_reboot_in_progress)
        self.assertIn("재부팅을 시작", feature.service.messages[-1].text)
        feature.handle_event(
            "telegram_command",
            TelegramCommandPayload(
                RemoteCommand.START,
                13,
                payload.chat_id,
                datetime.now(timezone.utc),
                feature.service.generation,
            ),
        )
        self.assertIsNone(ports.started)
        self.assertIn("이미 진행 중", feature.service.messages[-1].text)
        command, result = feature.event_queue.get(timeout=1)
        self.assertEqual(command, "emulator_reboot_finished")
        feature.handle_event(command, result)

        self.assertFalse(feature.emulator_reboot_in_progress)
        self.assertEqual(ports.reboot_calls, 1)
        self.assertEqual(feature.service.messages[-1].key, "reboot-complete:12")
        self.assertIn("재부팅이 완료", feature.service.messages[-1].text)

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
