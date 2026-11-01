"""Connection tests through the real web model; no Telegram network requests."""
import unittest

from tools import test_web_ui as web_fixture
from mod.telegram_remote_control.models import ConnectionTestResult, ControlState


class ConnectionTestUiTests(unittest.TestCase):
    setUp = web_fixture.WebUiTests.setUp

    def start_test(self):
        result = self.bridge.test_connection({'bot_token': '123456:' + 'x' * 20, 'chat_id': '123456789'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['telegram']['testEnabled'])
        return self.app._active_test_request_id

    def test_success_failure_and_timeout_restore_button_and_status(self):
        now = [0.0]
        self.controller._clock = lambda: now[0]
        for succeeded, message in ((True, 'connected'), (False, 'failed')):
            request = self.start_test()
            self.controller._show_connection_test_result(ConnectionTestResult(request, succeeded, message))
            state = self.bridge.bootstrap()['telegram']
            self.assertTrue(state['testEnabled'])
            self.assertEqual(state['message'], message)
            self.assertIsNone(self.app._active_test_request_id)
        self.start_test()
        now[0] = 19.99
        self.controller.process_once()
        self.assertIsNotNone(self.app._active_test_request_id)
        now[0] = 20
        self.controller.process_once()
        self.assertIsNone(self.app._active_test_request_id)
        self.assertTrue(self.bridge.bootstrap()['telegram']['testEnabled'])

    def test_stale_result_cannot_unlock_or_replace_new_request(self):
        request = self.start_test()
        self.controller._show_connection_test_result(ConnectionTestResult('previous', True, 'stale'))
        self.assertEqual(self.app._active_test_request_id, request)
        self.assertFalse(self.bridge.bootstrap()['telegram']['testEnabled'])
        self.assertNotEqual(self.bridge.bootstrap()['telegram']['message'], 'stale')

    def test_macro_running_keeps_button_disabled_after_result(self):
        request = self.start_test()
        self.app.push_event({'type': 'task_started', 'target': '7000G'})
        self.controller._show_connection_test_result(ConnectionTestResult(request, True, 'connected'))
        self.assertIsNone(self.app._active_test_request_id)
        self.assertFalse(self.bridge.bootstrap()['telegram']['testEnabled'])
        self.assertFalse(self.bridge.test_connection()['ok'])

    def test_idle_state_refresh_does_not_unlock_pending_test(self):
        request = self.start_test()
        self.app.apply_remote_control_state(ControlState.IDLE)
        self.assertFalse(self.bridge.bootstrap()['telegram']['testEnabled'])
        self.assertEqual(self.app._active_test_request_id, request)


if __name__ == '__main__':
    unittest.main()
