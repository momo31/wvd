from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mod.telegram_remote_control.command_service import (
    normalize_command,
    parse_command,
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
