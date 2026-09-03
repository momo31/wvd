from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mod.telegram_remote_control.command_service import (
    COMMAND_MENU_TEXT,
    UNKNOWN_COMMAND_TEXT,
    normalize_command,
    parse_command,
    parse_update_callback,
    parse_update_command,
)
from mod.telegram_remote_control.config import (
    TelegramConfigError,
    load_latest_farm_setting,
    validate_telegram_settings,
)
from mod.telegram_remote_control.models import RemoteCommand, TelegramSettings


class ConfigAndCommandTests(unittest.TestCase):
    def test_command_normalization_and_authorization(self):
        self.assertEqual(normalize_command("  /start@my_bot args"), "/start")
        self.assertIs(parse_command("/start"), RemoteCommand.START)
        self.assertIs(parse_command("reboot"), RemoteCommand.REBOOT)
        self.assertIs(parse_command("/REBOOT@my_bot"), RemoteCommand.REBOOT)
        self.assertIs(parse_command("/QUEST@my_bot"), RemoteCommand.QUEST)
        self.assertIs(parse_command("퀘스트"), RemoteCommand.QUEST)
        self.assertIsNone(parse_command("reset"))
        self.assertIs(parse_command("stat"), RemoteCommand.STAT)
        self.assertIs(parse_command("/STAT@my_bot"), RemoteCommand.STAT)
        self.assertIs(parse_command("menu"), RemoteCommand.MENU)
        self.assertIs(parse_command("/menu"), RemoteCommand.MENU)
        self.assertIs(parse_command("메뉴"), RemoteCommand.MENU)
        self.assertIn("/start", COMMAND_MENU_TEXT)
        self.assertIn("stat", COMMAND_MENU_TEXT)
        self.assertIn("reboot", COMMAND_MENU_TEXT)
        self.assertIn("/quest", COMMAND_MENU_TEXT)
        self.assertIn("menu", UNKNOWN_COMMAND_TEXT)
        self.assertNotIn("/start", UNKNOWN_COMMAND_TEXT)
        settings = TelegramSettings(True, "123:" + "x" * 20, "987")
        update = {
            "update_id": 5,
            "message": {
                "chat": {"id": 987, "type": "private"},
                "from": {"is_bot": False},
                "text": "/stop",
            },
        }
        payload, unknown = parse_update_command(update, settings, 3)
        self.assertFalse(unknown)
        self.assertEqual(payload.command, RemoteCommand.STOP)
        self.assertEqual(payload.service_generation, 3)

        update["message"]["chat"]["id"] = 988
        payload, unknown = parse_update_command(update, settings, 3)
        self.assertIsNone(payload)
        self.assertFalse(unknown)

    def test_callback_authorization(self):
        settings = TelegramSettings(True, "123:" + "x" * 20, "987")
        update = {
            "update_id": 8,
            "callback_query": {
                "id": "callback-8",
                "from": {"id": 987, "is_bot": False},
                "message": {"chat": {"id": 987, "type": "private"}},
                "data": "quest:root",
            },
        }

        payload = parse_update_callback(update, settings, 4)

        self.assertEqual(payload.data, "quest:root")
        self.assertEqual(payload.callback_query_id, "callback-8")
        self.assertEqual(payload.service_generation, 4)
        update["callback_query"]["from"]["id"] = 988
        self.assertIsNone(parse_update_callback(update, settings, 4))

    def test_settings_validation_rejects_invalid_enabled_values(self):
        with self.assertRaises(TelegramConfigError):
            validate_telegram_settings(TelegramSettings(True, "bad", "1"))
        with self.assertRaises(TelegramConfigError):
            validate_telegram_settings(TelegramSettings(True, "123:" + "x" * 20, "-1"))
        self.assertEqual(
            validate_telegram_settings(TelegramSettings(False, "", "")),
            TelegramSettings(False, "", ""),
        )

    def test_latest_setting_merges_general_and_selected_task(self):
        raw = {
            "GENERAL": {"FARM_TARGET": "task-a", "TASK_SPECIFIC_CONFIG": True},
            "task-a": {"MAX_TRY_LIMIT": 7},
            "DEFAULT": {"MAX_TRY_LIMIT": 99},
        }

        class Setting:
            def __init__(self, values):
                self.__dict__.update(values)

        setting = load_latest_farm_setting(None, lambda _path: raw, Setting)
        self.assertEqual(setting.FARM_TARGET, "task-a")
        self.assertEqual(setting.MAX_TRY_LIMIT, 7)


if __name__ == "__main__":
    unittest.main()
