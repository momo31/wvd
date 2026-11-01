from __future__ import annotations

import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main  # noqa: E402
import gui  # noqa: E402


class _Runtime:
    def __init__(self):
        self.run_id = "local-run"
        self.worker_force_stop_event = object()
        self.handoff_target = None
        self.handoff_checks = 0

    def is_handoff_requested(self, _target):
        self.handoff_checks += 1
        return False

    def mark_exit(self, *_args):
        raise AssertionError("the fake thread must start successfully")


class _Setting:
    FARM_TARGET_TEXT = "test target"


class _Feature:
    def __init__(self):
        self.started = []

    def on_task_started(self, runtime):
        self.started.append(runtime)


class _Thread:
    def __init__(self, *, target, args, daemon, name):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


class _Variable:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _Combo(dict):
    def __init__(self):
        super().__init__()
        self.value = None
        self.events = []

    def set(self, value):
        self.value = value

    def event_generate(self, event):
        self.events.append(event)


class _Controller:
    def __init__(self, runtime):
        self.runtime = runtime
        self.msg_queue = queue.Queue()
        self.quest_threading = None
        self.quest_setting = None
        self._active_runtime = None
        self._active_latch = None
        self._completion_enqueued = set()
        self.remote_feature = _Feature()

    def _task_is_alive(self):
        return False

    def _new_local_runtime(self, _setting):
        return self.runtime


class MainControllerTests(unittest.TestCase):
    def test_korean_quest_catalog_has_no_chinese_fallback(self):
        targets = main.AppController._list_quest_targets(object())

        self.assertEqual(len(targets), sum(len(items) for items in main.DUNGEON_TARGETS.values()))
        sandman = next(target for target in targets if target.code == "sandman")
        if main.LANGUAGE == "ko_KR":
            self.assertEqual(sandman.category, "메인 시나리오 1~3장")
            self.assertEqual(sandman.display_name, "[인연] 샌드맨")
            self.assertFalse(
                [
                    target
                    for target in targets
                    if any("\u4e00" <= char <= "\u9fff" for char in target.category + target.display_name)
                ]
            )

    def test_task_button_uses_one_localized_label_source(self):
        with mock.patch('builtins._', side_effect=lambda text: {'停止': 'STOP', '脚本, 启动!': 'START'}[text]):
            self.assertEqual(gui.task_button_text(False), 'START')
            self.assertEqual(gui.task_button_text(True), 'STOP')

    def test_local_start_creates_runtime_before_handoff_check(self):
        from tools.test_quest_handoff import make_controller, make_runtime
        runtime = make_runtime()
        runtime.is_handoff_requested = mock.Mock(wraps=runtime.is_handoff_requested)
        controller = make_controller()
        controller._new_local_runtime = mock.Mock(return_value=runtime)
        setting = SimpleNamespace(FARM_TARGET='7000G', FARM_TARGET_TEXT='test target')

        with mock.patch.object(main, "Factory", return_value=object()), mock.patch.object(
            main.threading,
            "Thread",
            _Thread,
        ):
            started = main.AppController._start_task(
                controller,
                setting,
                main.StartReason.LOCAL,
                "",
                None,
            )

        self.assertTrue(started)
        self.assertIs(controller._active_runtime, runtime)
        self.assertIs(setting._REMOTE_RUNTIME, runtime)
        self.assertIs(setting._FORCESTOPING, runtime.worker_force_stop_event)
        self.assertIsNone(setting._REMOTE_HANDOFF_TARGET)
        runtime.is_handoff_requested.assert_not_called()
        controller.remote_feature.on_task_started.assert_called_once_with(runtime)
        self.assertTrue(controller.quest_threading.started)

    def test_remote_target_selection_preserves_config_and_disables_task_specific(self):
        raw = {
            "GENERAL": {
                "FARM_TARGET": "old",
                "FARM_TARGET_TEXT": "old name",
                "TASK_SPECIFIC_CONFIG": True,
                "TELEGRAM_BOT_TOKEN": "secret",
            },
            "old": {"MAX_TRY_LIMIT": 7},
            "new": {"MAX_TRY_LIMIT": 9},
        }
        controller = SimpleNamespace(config_path="custom.json", main_window=None)

        with mock.patch.object(main, "DUNGEON_TARGETS", {"분류": {"새 목표": "new"}}), mock.patch.object(
            main,
            "LoadRawConfigFromFile",
            return_value=raw,
        ), mock.patch.object(main, "SaveConfigToFile", return_value=True) as save:
            selected = main.AppController._select_quest_target(controller, "new")

        self.assertTrue(selected)
        self.assertEqual(raw["GENERAL"]["FARM_TARGET"], "new")
        self.assertEqual(raw["GENERAL"]["FARM_TARGET_TEXT"], "새 목표")
        self.assertFalse(raw["GENERAL"]["TASK_SPECIFIC_CONFIG"])
        self.assertEqual(raw["GENERAL"]["TELEGRAM_BOT_TOKEN"], "secret")
        self.assertEqual(raw["old"], {"MAX_TRY_LIMIT": 7})
        self.assertEqual(raw["new"], {"MAX_TRY_LIMIT": 9})
        save.assert_called_once_with(raw, "custom.json")

    def test_remote_target_updates_web_selection_without_starting(self):
        from tools import test_web_ui as fixture
        fixture.WebUiTests.setUp(self)
        self.controller._start_task = mock.Mock()
        selected = self.app.select_farm_target_from_remote('category', 'fishing')
        self.assertTrue(selected)
        self.assertEqual(self.bridge.bootstrap()['targetId'], 'fishing')
        self.assertFalse(self.bridge.bootstrap()['taskSpecific'])
        self.controller._start_task.assert_not_called()

    def test_remote_target_does_not_replace_an_invalid_config(self):
        controller = SimpleNamespace(config_path="broken.json", main_window=None)
        with mock.patch.object(main, "DUNGEON_TARGETS", {"분류": {"목표": "new"}}), mock.patch.object(
            main,
            "LoadRawConfigFromFile",
            return_value={},
        ), mock.patch.object(main, "SaveConfigToFile") as save:
            selected = main.AppController._select_quest_target(controller, "new")

        self.assertFalse(selected)
        save.assert_not_called()


class ControllerLifecycleTests(unittest.TestCase):
    def make_controller(self):
        with mock.patch.object(main, 'TelegramRemoteFeature') as feature, mock.patch.object(main, 'AutoUpdater') as updater:
            feature.return_value.handle_event.return_value = False
            feature.return_value.emulator_reboot_in_progress = False
            updater.return_value.cancel_event = threading.Event()
            c = main.AppController(True, 'fixture.json')
        c._force_exit = mock.Mock()
        return c

    def test_controller_serializes_start_stop_and_stale_completion(self):
        c = self.make_controller()
        reached, release = threading.Event(), threading.Event()
        def farm(setting):
            reached.set()
            release.wait(2)
        with mock.patch.object(main, 'Factory', return_value=farm), mock.patch.object(main, 'ValidateQuestResources', return_value=[]):
            setting = SimpleNamespace(FARM_TARGET='7000G', LANGUAGE_GAME='en_US')
            c.msg_queue.put(('start_quest', setting))
            c.msg_queue.put(('start_quest', setting))
            c.process_once()
            self.assertTrue(reached.wait(1))
            runtime = c._active_runtime
            self.assertEqual(runtime.worker_generation, 1)
            c.msg_queue.put(('task_completion_requested', 'previous-run'))
            c.msg_queue.put(('stop_quest', None))
            c.process_once()
            self.assertIs(c._active_runtime, runtime)
            self.assertTrue(runtime.worker_force_stop_event.is_set())
            self.assertFalse(c._active_latch.called)
            release.set()
            c.quest_threading.join(2)

    def test_close_cancels_workers_before_destroy(self):
        c = self.make_controller()
        c.main_window = mock.Mock()
        stopped = threading.Event()
        c._active_runtime = main.RemoteRuntime('run', main.StartReason.LOCAL, '', c.msg_queue, stopped, None, '')
        c.quest_threading = mock.Mock(is_alive=mock.Mock(return_value=True))
        c.schedule_after(0, lambda: self.fail('callback ran after shutdown began'))
        c.request_shutdown()
        c.process_once()
        self.assertTrue(stopped.is_set())
        self.assertTrue(c.updater.cancel_event.is_set())
        c.main_window.destroy.assert_not_called()
        with mock.patch.object(c, '_start_task') as start:
            for name in ('start_quest', 'switch_quest', 'restart_ready'):
                c.msg_queue.put((name, None))
            c.process_once()
            start.assert_not_called()
        c.quest_threading.is_alive.return_value = False
        c._service_stop_thread.join(1)
        c.process_once()
        c.main_window.destroy.assert_called_once()
        c._force_exit.assert_not_called()

    def test_shutdown_deadlines_are_bounded(self):
        self.assertEqual(main.CONTROLLER_TICK_MILLISECONDS, 100)
        for kind, limit in [('worker', 15), ('service', 36), ('download', 45)]:
            with self.subTest(kind=kind):
                c = self.make_controller()
                now = [0.0]
                c._clock = lambda: now[0]
                c.request_shutdown()
                c.process_once()
                # Keep the shutdown pending with exactly one synthetic worker.
                c._shutdown_done.clear()
                hung = mock.Mock(is_alive=mock.Mock(return_value=True))
                c._shutdown_started = 0.0
                if kind == 'worker': c.quest_threading = hung
                elif kind == 'service': c._service_stop_thread = hung
                else: c._download_thread = hung
                now[0] = limit - .01
                c._poll_shutdown()
                c._force_exit.assert_not_called()
                now[0] = limit
                c._poll_shutdown()
                c._force_exit.assert_called_once_with(1)

    def test_scheduled_callbacks_run_on_the_owner_thread(self):
        c = self.make_controller()
        seen = []
        now = [0.0]
        c._clock = lambda: now[0]
        thread = threading.Thread(target=lambda: c.schedule_after(100, lambda: seen.append(threading.get_ident())))
        thread.start()
        thread.join(1)
        c.process_once()
        self.assertEqual(seen, [])
        now[0] = .1
        c.process_once()
        self.assertEqual(seen, [threading.get_ident()])

    def test_import_does_not_load_gui_or_start_external_services(self):
        import os
        import subprocess
        env = dict(os.environ, PYTHONPATH=str(SRC) + os.pathsep + str(ROOT))
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
            "import sys, threading; import main; assert 'gui' not in sys.modules; assert 'webview' not in sys.modules; assert not any(t.name.startswith(('farm-', 'remote-')) for t in threading.enumerate())"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
