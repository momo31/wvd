"""All config operations use temporary files, never the user's settings."""

import json
import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import gui
import main
import utils


class CustomConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.default = Path(self.directory.name) / "config.json"
        self.custom = Path(self.directory.name) / "custom.json"
        for path, target in ((self.default, "default-task"), (self.custom, "custom-task")):
            path.write_text(json.dumps({
                "GENERAL": {"FARM_TARGET": target, "TASK_SPECIFIC_CONFIG": True,
                            "TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_ALLOWED_CHAT_ID": "123",
                            "LANGUAGE": "ko_KR"},
                target: {"MAX_TRY_LIMIT": 7}, "DEFAULT": {"MAX_TRY_LIMIT": 3},
                "other-task": {"MAX_TRY_LIMIT": 9},
            }), encoding="utf-8")
        self.before = self.default.read_bytes()
        default_patch = patch.object(utils, "CONFIG_FILE", str(self.default))
        default_patch.start()
        self.addCleanup(default_patch.stop)

    def test_config_migration_is_idempotent_and_preserves_custom_path(self):
        original = json.loads(self.custom.read_text())
        original['GENERAL'].update(SMART_DISARM_CHEST=True, BYPASS_FAST_GAME=True, ACTIVE_BEG_MONEY=True)
        self.custom.write_text(json.dumps(original), encoding='utf-8')
        migrated = utils.LoadRawConfigFromFile(str(self.custom))
        self.assertEqual(migrated['GENERAL'].get('LANGUAGE_SCRIPT'), 'ko_KR')
        self.assertEqual(migrated['GENERAL'].get('LANGUAGE_GAME'), 'en_US')
        for name, value in original['GENERAL'].items():
            self.assertEqual(migrated['GENERAL'][name], value)
        self.assertEqual(migrated['other-task'], original['other-task'])
        saved = self.custom.read_bytes()
        self.assertEqual(utils._migrate_language_settings(migrated), (migrated, False))
        self.assertEqual(utils.LoadRawConfigFromFile(str(self.custom)), migrated)
        self.assertEqual(self.custom.read_bytes(), saved)
        self.assertEqual(self.default.read_bytes(), self.before)
        explicit = {'GENERAL': {'LANGUAGE': 'ko_KR', 'LANGUAGE_SCRIPT': 'en_US', 'LANGUAGE_GAME': 'zh_CN'}}
        self.assertEqual(utils._migrate_language_settings(explicit), (explicit, False))

    def test_handoff_loads_target_settings_without_persisting_selection(self):
        from mod.telegram_remote_control import config
        original = json.loads(self.custom.read_text())
        original['fishing'] = {'MAX_TRY_LIMIT': 22, 'STRATEGY': [{'group_name': 'fishing-only'}]}
        self.custom.write_text(json.dumps(original), encoding='utf-8')
        before = self.custom.read_bytes()
        load_raw = lambda path: utils.LoadRawConfigFromFile(path, migrate_recovery=False)
        build = lambda data: SimpleNamespace(**data)
        setting = config.load_farm_setting_for_target(str(self.custom), 'fishing', load_raw, build)
        self.assertEqual((setting.FARM_TARGET, setting.MAX_TRY_LIMIT), ('fishing', 22))
        self.assertEqual(setting.STRATEGY, [{'group_name': 'fishing-only'}])
        self.assertEqual(setting._CONFIG_PATH, str(self.custom.resolve()))
        self.assertEqual(self.custom.read_bytes(), before)
        for target, enabled in [('missing-section', True), ('fishing', False)]:
            data = dict(original, GENERAL=dict(original['GENERAL'], TASK_SPECIFIC_CONFIG=enabled))
            result = config.load_farm_setting_for_target(str(self.custom), target, lambda path: data, build)
            self.assertEqual((result.FARM_TARGET, result.MAX_TRY_LIMIT), (target, 3))
            self.assertEqual(data['GENERAL']['FARM_TARGET'], 'custom-task')
        self.assertEqual(self.default.read_bytes(), self.before)

    def test_task_section_cannot_override_general_language_or_secrets(self):
        from mod.telegram_remote_control.config import load_farm_setting_for_target
        data = json.loads(self.custom.read_text())
        data['GENERAL'].update(LANGUAGE_GAME='zh_CN', LANGUAGE_SCRIPT='ko_KR')
        data['custom-task'].update(LANGUAGE_GAME='en_US', TELEGRAM_BOT_TOKEN='obsolete-task-token')
        self.custom.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_farm_setting_for_target(str(self.custom), 'custom-task', utils.LoadRawConfigFromFile,
                                               lambda values: SimpleNamespace(**values))
        self.assertEqual(loaded.LANGUAGE_GAME, 'zh_CN')
        self.assertEqual(loaded.TELEGRAM_BOT_TOKEN, 'fake-token')
        local = gui.LoadConfig(config_path=str(self.custom))
        self.assertEqual(local['LANGUAGE_GAME'], loaded.LANGUAGE_GAME)
        self.assertEqual(local['TELEGRAM_BOT_TOKEN'], loaded.TELEGRAM_BOT_TOKEN)

    def test_gui_remote_and_headless_load_same_custom_task(self):
        controller = SimpleNamespace(config_path=str(self.custom))
        with patch.object(main, "LoadSettingFromDict", side_effect=lambda data: SimpleNamespace(**data)):
            remote = main.AppController._load_latest_setting(controller)
            headless = main._load_headless_setting(str(self.custom))
        local = gui.LoadConfig(config_path=str(self.custom))
        self.assertEqual([remote.FARM_TARGET, headless.FARM_TARGET, local["FARM_TARGET"]], ["custom-task"] * 3)
        self.assertEqual([remote.MAX_TRY_LIMIT, headless.MAX_TRY_LIMIT, local["MAX_TRY_LIMIT"]], [7] * 3)
        for setting in (remote, headless):
            self.assertEqual(setting._CONFIG_PATH, str(self.custom.resolve()))
            utils.SetOneVarInGeneralConfig("KARMA_ADJUST", "+1", setting._CONFIG_PATH)
        self.assertEqual(self.default.read_bytes(), self.before)
        saved = json.loads(self.custom.read_text())
        self.assertEqual(saved["GENERAL"]["KARMA_ADJUST"], "+1")
        self.assertEqual(saved["GENERAL"]["TELEGRAM_BOT_TOKEN"], "fake-token")
        self.assertEqual(saved["other-task"], {"MAX_TRY_LIMIT": 9})

    def test_gui_save_preserves_telegram_and_other_tasks_in_custom_file(self):
        controller = SimpleNamespace(config_path=str(self.custom), msg_queue=__import__('queue').Queue(), _active_runtime=None)
        window = gui.ConfigPanelApp(controller, '3.2.1-momo.1', controller.msg_queue)
        try:
            result = window.save({'KARMA_ADJUST': '+2', 'MAX_TRY_LIMIT': 11})
            self.assertTrue(result['ok'])
        finally:
            window.destroy()
        saved = json.loads(self.custom.read_text())
        self.assertEqual(saved['custom-task']['MAX_TRY_LIMIT'], 11)
        self.assertEqual(saved['GENERAL']['FARM_TARGET'], 'custom-task')
        self.assertEqual(saved['GENERAL']['TELEGRAM_ALLOWED_CHAT_ID'], '123')
        self.assertEqual(saved['other-task']['MAX_TRY_LIMIT'], 9)
        self.assertEqual(self.default.read_bytes(), self.before)

    def test_explicit_missing_or_invalid_file_never_falls_back_or_overwrites(self):
        for content in (None, "{broken", "[]"):
            with self.subTest(content=content):
                path = Path(self.directory.name) / "invalid.json"
                if content is not None:
                    path.write_text(content, encoding="utf-8")
                with self.assertRaises((OSError, ValueError)):
                    gui.LoadConfig(config_path=str(path))
                with self.assertRaises((OSError, ValueError)):
                    utils.SetOneVarInGeneralConfig("KARMA_ADJUST", "+9", str(path))
                if content is not None:
                    self.assertEqual(path.read_text(), content)
        self.assertEqual(self.default.read_bytes(), self.before)

    def test_default_path_still_loads_and_saves_when_no_override_is_given(self):
        self.assertEqual(gui.LoadConfig()["FARM_TARGET"], "default-task")
        utils.SetOneVarInGeneralConfig("KARMA_ADJUST", "+3")
        self.assertEqual(json.loads(self.default.read_text())["GENERAL"]["KARMA_ADJUST"], "+3")

    def test_startup_reads_custom_language_before_gui_import(self):
        data = json.loads(self.custom.read_text())
        data["GENERAL"]["LANGUAGE"] = "en_US"
        self.custom.write_text(json.dumps(data), encoding="utf-8")
        path = Path(main.__file__)
        before_gui_import = path.read_text(encoding="utf-8").split("from script import *", 1)[0]
        with patch.object(sys, "argv", [str(path), "-config", str(self.custom)]), patch.object(utils, "LANGUAGE"), patch.object(
            utils, "trans",
        ), patch.object(builtins, "_", builtins._):
            namespace = {"__name__": "__main__", "__file__": str(path)}
            exec(compile(before_gui_import, str(path), "exec"), namespace)
            self.assertEqual(utils.LANGUAGE, "en_US")
        self.assertEqual(self.default.read_bytes(), self.before)

    def test_locale_read_and_explicit_path_never_migrate_another_config(self):
        with patch.object(utils.sys, "frozen", True, create=True), patch.object(utils, "_find_config_fallback") as fallback:
            utils.GetOneVarInGeneralConfig("LANGUAGE", "ko_KR")
            self.assertEqual(self.default.read_bytes(), self.before)
            utils.LoadRawConfigFromFile(str(self.custom))
        fallback.assert_not_called()
        self.assertEqual(self.default.read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
