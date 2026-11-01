"""Reproduce the final merge review with fake I/O and real lifecycle ownership."""
import logging
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

import main
import utils
from mod.telegram_remote_control.command_service import TelegramCommandService
from mod.telegram_remote_control.models import (
    ConnectionTestRequest, ConnectionTestResult, ControlState, NotificationPriority,
    OutboundMessage, RemoteCommand, TelegramCommandPayload, TelegramSettings,
)
from tools import test_web_ui

ROOT = Path(__file__).resolve().parents[1]


class MergeReviewTests(unittest.TestCase):
    def web_fixture(self):
        test_web_ui.WebUiTests.setUp(self)
        self.addCleanup(lambda: self.app.set_language('script', 'ko_KR'))

    def test_gui_owner_delivers_real_info_summary_to_ui_and_log_file(self):
        self.web_fixture()
        logger = utils.logger
        old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
        logfile = Path(self.temp.name) / 'session.log'
        manager = utils.LogListenerManager()
        logger.setLevel(logging.WARNING)

        def startup():
            logger.info('review-summary', extra={'summary_data': {'complete_times': 7}})
            self.controller.request_shutdown()

        self.controller.remote_feature.start.side_effect = startup
        try:
            with patch.object(main, 'LOG_LISTENER_MGR', manager), patch.object(utils, 'SetupFileHandle',
                    side_effect=lambda: logging.FileHandler(logfile, encoding='utf-8')), \
                    patch.object(sys, 'stdout', sys.stdout), patch.object(sys, 'stderr', sys.stderr):
                self.controller._owner_loop()
                self.assertFalse(manager.started, 'shutdown must flush and close the file listener')
            summaries = [event for event in self.app.poll() if event['type'] == 'summary']
            self.assertEqual([event['data']['complete_times'] for event in summaries], [7])
            self.assertIn('review-summary', logfile.read_text(encoding='utf-8'))
        finally:
            manager.stop()
            for handler in logger.handlers[:]:
                if handler not in old_handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.setLevel(old_level)
            logger.propagate = old_propagate

    def test_main_script_language_switch_updates_telegram_menu_and_selection(self):
        self.web_fixture()
        # CLI/frozen entrypoints define the controller in __main__, not main.
        entrypoint = types.ModuleType('__main__')
        entrypoint.__dict__.update(main.__dict__)
        entrypoint.__name__ = '__main__'
        methods = {'__module__': '__main__'}
        for name in ('_list_quest_targets', '_select_quest_target'):
            original = getattr(main.AppController, name)
            methods[name] = types.FunctionType(original.__code__, entrypoint.__dict__, name)
        self.controller.__class__ = type('AppController', (main.AppController,), methods)
        self.addCleanup(lambda: setattr(self.controller, '__class__', main.AppController))
        with patch.dict(sys.modules, {'__main__': entrypoint}):
            self.assertTrue(self.app.set_language('script', 'en_US')['ok'])
            menu = self.controller._list_quest_targets()
            fish = next(item for item in menu if item.code == 'fishing')
            expected = utils.QUEST_DATA['fishing']['questName_en_US']
            self.assertEqual(fish.display_name, expected)
            self.assertTrue(self.controller._select_quest_target('fishing'))
            self.assertEqual(self.app.bootstrap()['targetId'], 'fishing')

    def test_full_ui_queue_does_not_block_state_callbacks_or_shutdown(self):
        self.web_fixture()
        for _ in range(self.app._events.maxsize):
            self.app._events.put_nowait({'type': 'old_log'})
        self.app._active_test_request_id = 'review-test'
        completed = threading.Event()
        errors = []

        def owner():
            try:
                self.app.show_connection_test_result(ConnectionTestResult('review-test', True, 'Connected'))
                self.app.apply_remote_control_state(ControlState.IDLE)
                self.controller.request_shutdown()
                self.controller.process_once()
                completed.set()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=owner, daemon=True)
        thread.start()
        try:
            self.assertTrue(completed.wait(.5), 'owner blocked behind a stalled UI consumer')
            self.assertEqual(errors, [])
            self.assertTrue(self.controller._closing)
            self.assertIsNone(self.app._active_test_request_id)
            self.assertEqual(self.app._remote_state, ControlState.IDLE.value)
        finally:
            # Release the old blocking implementation after observing RED.
            for _ in range(4):
                try:
                    self.app._events.get_nowait()
                except queue.Empty:
                    break
            thread.join(2)
            stop = self.controller._service_stop_thread
            if stop:
                stop.join(2)

    def make_controller(self):
        with patch.object(main, 'AutoUpdater') as updater:
            updater.return_value.cancel_event = threading.Event()
            controller = main.AppController(False, 'unused-fixture.json')
        controller.main_window = Mock()
        controller._force_exit = Mock()
        return controller

    def check_blocked_service_shutdown(self, operation, expire=False):
        controller = self.make_controller()
        reached, release = threading.Event(), threading.Event()
        client = Mock()
        client.get_me.return_value = {}
        client.get_updates.return_value = []

        def blocked(*args, **kwargs):
            reached.set()
            release.wait(5)
            return [] if operation == 'poll' else {}

        getattr(client, {'poll': 'get_updates', 'send': 'send_message', 'test': 'get_me'}[operation]).side_effect = blocked
        service = TelegramCommandService(controller.msg_queue, Mock(), lambda *_: client)
        controller.remote_feature.service = service
        settings = TelegramSettings(True, '123456789:' + 'A' * 35, '123456789')
        if operation == 'test':
            service.start_connection_test(ConnectionTestRequest('review-test', settings))
        else:
            if operation == 'send':
                # A quiet poller waits cooperatively instead of spinning.
                client.get_updates.side_effect = lambda **kwargs: (release.wait(5), [])[1]
            service.start(settings)
            if operation == 'send':
                service.enqueue(OutboundMessage('review', settings.allowed_chat_id, 'fixture', NotificationPriority.ACKNOWLEDGEMENT))
        now = [0.0]
        controller._clock = lambda: now[0]
        try:
            self.assertTrue(reached.wait(1))
            controller._begin_shutdown()
            controller._service_stop_thread.join(.1)
            controller._poll_shutdown()
            controller.main_window.destroy.assert_not_called()
            self.assertFalse(controller._shutdown_done.is_set())
            if expire:
                now[0] = 36
                controller._poll_shutdown()
                controller._force_exit.assert_called_once_with(1)
                controller.main_window.destroy.assert_not_called()
            release.set()
            controller._service_stop_thread.join(2)
            controller._poll_shutdown()
            if not expire:
                controller.main_window.destroy.assert_called_once()
                controller._force_exit.assert_not_called()
            if operation == 'test':
                client.send_message.assert_not_called()
        finally:
            release.set()
            service.stop()
            for thread in (service._poll_thread, service._send_thread, controller._service_stop_thread):
                if thread:
                    thread.join(2)

    def test_shutdown_waits_for_actual_poll_worker(self):
        self.check_blocked_service_shutdown('poll')

    def test_shutdown_waits_for_actual_send_worker(self):
        self.check_blocked_service_shutdown('send')

    def test_shutdown_cancels_connection_test_before_send_and_joins_worker(self):
        self.check_blocked_service_shutdown('test')

    def test_hung_actual_service_obeys_controller_shutdown_deadline(self):
        self.check_blocked_service_shutdown('poll', expire=True)

    def test_shutdown_cancels_and_joins_emulator_reboot(self):
        from datetime import datetime, timezone
        controller = self.make_controller()
        feature = controller.remote_feature
        feature.service = Mock()
        reached, release = threading.Event(), threading.Event()
        seen_setting = []
        controller._load_latest_setting = Mock(return_value=types.SimpleNamespace())

        def recover(setting, *args, **kwargs):
            seen_setting.append(setting)
            reached.set()
            release.wait(5)
            return None

        payload = TelegramCommandPayload(RemoteCommand.REBOOT, 1, '123456789', datetime.now(timezone.utc), 0)
        with patch.object(main, 'CheckAndRecoverDevice', side_effect=recover):
            try:
                feature._handle_reboot(payload)
                self.assertTrue(reached.wait(1))
                controller._begin_shutdown()
                controller._service_stop_thread.join(.1)
                controller._poll_shutdown()
                controller.main_window.destroy.assert_not_called()
                self.assertTrue(seen_setting[0]._FORCESTOPING.is_set())
                release.set()
                controller._service_stop_thread.join(2)
                controller._poll_shutdown()
                controller.main_window.destroy.assert_called_once()
                controller._force_exit.assert_not_called()
            finally:
                release.set()
                if controller._service_stop_thread:
                    controller._service_stop_thread.join(2)

    def test_fork_version_keeps_existing_prerelease_publication_policy(self):
        workflow = (ROOT / '.github/workflows/build-executable.yml').read_text(encoding='utf-8')
        expression = re.search(r'^\s*(\$is_prerelease\s*=.+)$', workflow, re.MULTILINE).group(1).strip()
        # Evaluate the actual workflow expression; do not invoke any CI action.
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "$version = '3.2.1-momo.1'\n" + expression + '\n$is_prerelease'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'True')


if __name__ == '__main__':
    unittest.main()
