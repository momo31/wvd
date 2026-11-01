"""Real web model and bridge with temporary configuration and a fake controller."""
import copy
import json
import logging
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import gui
import main
import utils


class WebUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'custom.json'
        self.original = {
            'GENERAL': {'FARM_TARGET': '7000G', 'LANGUAGE_SCRIPT': 'ko_KR', 'LANGUAGE_GAME': 'en_US',
                        'TELEGRAM_ENABLED': False, 'TELEGRAM_BOT_TOKEN': 'fixture-secret',
                        'TELEGRAM_ALLOWED_CHAT_ID': '1234567', 'future_option': 42},
            'DEFAULT': {'SMART_DISARM_CHEST': True, 'BYPASS_FAST_GAME': True,
                        'STRATEGY': [{'group_name': 'custom', 'need_reload_when_dungeon_begins': True,
                                      'skill_settings': [{'role_var': 'alice', 'skill_var': '双击自动',
                                                          'target_var': '低生命值', 'freq_var': '每次副本仅一次', 'skill_lvl': 3}]}]},
            'fishing': {'MAX_TRY_LIMIT': 77, 'unknown_task_option': 5},
        }
        self.path.write_text(json.dumps(self.original), encoding='utf-8')
        with patch.object(main, 'TelegramRemoteFeature') as feature, patch.object(main, 'AutoUpdater') as updater:
            feature.return_value.handle_event.return_value = False
            feature.return_value.emulator_reboot_in_progress = False
            updater.return_value.cancel_event = threading.Event()
            self.controller = main.AppController(False, str(self.path))
        self.controller._owner_ident = threading.get_ident()
        self.controller._force_exit = Mock()
        self.app = gui.ConfigPanelApp(self.controller, '3.2.1-momo.1', self.controller.msg_queue)
        self.controller.main_window = self.app
        self.bridge = gui.WebBridge(self.app)
        self.addCleanup(self.app.destroy)

    def stored(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_release_notifications_are_shown_until_dismissed(self):
        self.app.push_event({'type': 'update_manual'})
        self.app.push_event({'type': 'update_available', 'data': {'version': '3.2.1-momo.2'}})
        kinds = [event['type'] for event in self.bridge.poll()]
        self.assertIn('update_manual', kinds)
        self.assertIn('update_available', kinds)
        self.assertEqual(self.bridge.bootstrap()['update']['latest'], '3.2.1-momo.2')

    def test_dismissal_persists_while_running_and_filters_queued_notices(self):
        self.app.push_event({'type': 'update_manual'})
        self.app.push_event({'type': 'update_available', 'data': {'version': '3.2.1-momo.2'}})
        self.app._quest_active = True
        result = self.bridge.save({'RELEASE_NOTICES_DISMISSED': True})
        self.assertTrue(result['ok'])
        self.assertTrue(self.stored()['GENERAL'].get('RELEASE_NOTICES_DISMISSED'))
        self.assertIsNone(result['update'])
        self.assertNotIn('update_manual', [event['type'] for event in self.bridge.poll()])
        self.assertEqual(self.stored()['fishing'], self.original['fishing'])

    def test_dismissed_notifications_stay_hidden_after_reopening(self):
        self.assertTrue(self.bridge.save({'RELEASE_NOTICES_DISMISSED': True})['ok'])
        reopened = gui.ConfigPanelApp(self.controller, '3.2.1-momo.2', self.controller.msg_queue)
        self.addCleanup(reopened.destroy)
        reopened.push_event({'type': 'update_manual'})
        reopened.push_event({'type': 'update_available', 'data': {'version': '3.2.1-momo.3'}})
        reopened.push_event({'type': 'download_finished'})
        kinds = [event['type'] for event in reopened.poll()]
        self.assertNotIn('update_manual', kinds)
        self.assertNotIn('update_available', kinds)
        self.assertIn('download_finished', kinds)
        self.assertIsNone(reopened.bootstrap()['update'])

    def test_telegram_errors_and_results_follow_ui_language(self):
        from mod.telegram_remote_control.models import ConnectionTestResult
        self.bridge.set_language('script', 'en_US')
        result = self.bridge.save_telegram({'enabled': True, 'bot_token': 'invalid'})
        self.assertEqual(result['error'], 'The Bot Token format is invalid.')
        self.app._active_test_request_id = 'current'
        self.app.show_connection_test_result(ConnectionTestResult('current', True, '연결됨'))
        events = self.bridge.poll()
        self.assertEqual(next(e for e in events if e['type'] == 'connection_test')['message'], 'Connected')
        self.bridge.set_language('script', 'ko_KR')

    def test_every_character_label_has_a_compiled_korean_translation(self):
        import gettext, re
        trans = gettext.translation('messages', str(Path(gui.__file__).resolve().parents[1] / 'locale'), languages=['ko_KR'])
        for character in utils.CHAR_LIST:
            self.assertIsNone(re.search(r'[\u4e00-\u9fff]', trans.gettext(character)), character)

    def test_choose_emulator_saves_supported_path_without_warning(self):
        import webview
        self.app._window = Mock()
        self.app._window.create_file_dialog.return_value = ['C:/fake/HD-Player.exe']
        result = self.bridge.choose_emu_path()
        self.assertTrue(result['ok'], result)
        self.assertIsNone(result.get('warning'))
        self.assertEqual(self.stored()['GENERAL']['EMU_PATH'], 'C:/fake/HD-Player.exe')

    def test_bridge_uses_controller_and_masks_secrets(self):
        with patch.object(self.controller, 'call_on_owner', wraps=self.controller.call_on_owner) as call, patch.object(self.controller, '_start_task', return_value=False):
            self.assertFalse(self.bridge.start_quest()['ok'])
            self.assertFalse(self.bridge.bootstrap()['running'])
            self.assertTrue(call.called)
        snap = self.bridge.bootstrap()
        self.assertNotIn('fixture-secret', json.dumps(snap))
        self.assertNotIn('TELEGRAM_BOT_TOKEN', snap['values'])
        record = logging.LogRecord('test', logging.INFO, '', 0, 'secret fixture-secret', (), None)
        record.summary_data = {'total_time': 3, 'complete_times': 1}
        record.summary_events = {'event': 1}
        record.summary = True
        self.app._log_handler.emit(record)
        events = self.bridge.poll()
        self.assertNotIn('fixture-secret', json.dumps(events))
        summary = next(event for event in events if event['type'] == 'summary')
        self.assertEqual(summary['data']['complete_times'], 1)

    def test_blank_telegram_token_preserves_and_explicit_clear_removes(self):
        self.assertTrue(self.bridge.save_telegram({'bot_token': '', 'enabled': False})['ok'])
        self.assertEqual(self.stored()['GENERAL']['TELEGRAM_BOT_TOKEN'], 'fixture-secret')
        self.assertEqual(self.stored()['GENERAL']['future_option'], 42)
        self.assertEqual(self.stored()['fishing'], self.original['fishing'])
        self.assertTrue(self.bridge.save_telegram({'clear_token': True, 'enabled': False})['ok'])
        self.assertEqual(self.stored()['GENERAL']['TELEGRAM_BOT_TOKEN'], '')

    def test_korean_ui_and_strategy_round_trip(self):
        expected = copy.deepcopy(self.stored()['DEFAULT']['STRATEGY'])
        for language in ('en_US', 'zh_CN', 'ko_KR'):
            self.assertTrue(self.bridge.set_language('script', language)['ok'])
            snap = self.bridge.bootstrap()
            self.assertEqual(snap['targetId'], '7000G')
            self.assertTrue(snap['values']['SMART_DISARM_CHEST'])
            self.assertEqual(self.stored()['DEFAULT']['STRATEGY'], expected)
            self.assertTrue(self.bridge.save_plans(snap['plans'])['ok'])
            self.assertEqual(self.stored()['DEFAULT']['STRATEGY'], expected)
        self.assertEqual({item['value'] for item in snap['uiLanguages']}, {'ko_KR', 'en_US', 'zh_CN'})
        self.assertEqual({item['value'] for item in snap['gameLanguages']}, {'en_US', 'zh_CN'})
        self.assertFalse(self.bridge.set_language('game', 'ko_KR')['ok'])
        self.assertEqual(snap['i18n']['停止脚本'], '스크립트 중지')
        for category in snap['categories']:
            for text in [category['name']] + [item['text'] for item in category['targets']]:
                self.assertFalse(any('\u4e00' <= char <= '\u9fff' for char in text), text)

    def test_auto_handoff_display_does_not_overwrite_saved_selection(self):
        self.app.push_event({'type': 'task_started', 'target': 'fishing', 'run_id': 'fixture'})
        self.assertEqual(self.bridge.bootstrap()['runningTargetId'], 'fishing')
        self.assertTrue(self.bridge.save({'DARK_THEME': True})['ok'])
        self.app.save_config()
        self.assertEqual(self.stored()['GENERAL']['FARM_TARGET'], '7000G')
        self.assertTrue(self.stored()['GENERAL']['DARK_THEME'])

    def test_game_language_is_applied_before_worker_start(self):
        self.assertTrue(self.bridge.set_language('game', 'zh_CN')['ok'])
        self.assertEqual(utils.LANGUAGE_GAME, 'zh_CN')
        self.assertTrue(self.bridge.set_language('game', 'en_US')['ok'])
        self.assertEqual(utils.LANGUAGE_GAME, 'en_US')

    def test_target_selection_is_explicit_and_preserves_task_config(self):
        self.assertTrue(self.bridge.select_target('fishing')['ok'])
        self.assertEqual(self.stored()['GENERAL']['FARM_TARGET'], 'fishing')
        self.assertEqual(self.stored()['fishing'], self.original['fishing'])
        self.assertFalse(self.stored()['GENERAL']['TASK_SPECIFIC_CONFIG'])
        self.assertTrue(self.bridge.set_task_specific(True)['ok'])
        self.assertEqual(self.bridge.bootstrap()['values']['MAX_TRY_LIMIT'], 77)
        self.assertEqual(self.stored()['fishing']['unknown_task_option'], 5)

    def test_all_quest_instructions_have_language_specific_text(self):
        for target, item in utils.QUEST_DATA.items():
            if not item.get('_TIPS'):
                continue
            for language in ('ko_KR', 'en_US', 'zh_CN'):
                text = item.get('_TIPS_' + language)
                self.assertTrue(text, (target, language))
                if language != 'zh_CN':
                    self.assertFalse(any('\u4e00' <= char <= '\u9fff' for char in text), (target, language))


if __name__ == '__main__':
    unittest.main()
