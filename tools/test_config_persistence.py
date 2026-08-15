"""Regression tests for settings persistence across frozen rebuilds."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import utils  # noqa: E402


class ConfigPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._had_frozen = hasattr(utils.sys, "frozen")
        self._frozen = getattr(utils.sys, "frozen", None)
        self._executable = utils.sys.executable
        self._config_file = utils.CONFIG_FILE
        self._fallback_candidates = utils._config_fallback_candidates
        self._environment = {
            name: os.environ.get(name)
            for name in ("WVDAS_CONFIG_PATH", "LOCALAPPDATA", "APPDATA")
        }
        setattr(utils.sys, "frozen", True)

    def tearDown(self):
        utils.CONFIG_FILE = self._config_file
        utils._config_fallback_candidates = self._fallback_candidates
        utils.sys.executable = self._executable
        if self._had_frozen:
            setattr(utils.sys, "frozen", self._frozen)
        else:
            delattr(utils.sys, "frozen")
        for name, value in self._environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_frozen_build_uses_stable_per_user_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            os.environ.pop("WVDAS_CONFIG_PATH", None)
            os.environ["LOCALAPPDATA"] = str(temporary_root / "local")
            os.environ.pop("APPDATA", None)
            utils.sys.executable = str(temporary_root / "dist" / "wvd.exe")

            self.assertEqual(
                Path(utils._config_file_path()),
                temporary_root / "local" / "WvDAS" / "config.json",
            )

    def test_staged_dist_build_checks_the_previous_conventional_install(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            utils.sys.executable = str(
                temporary_root / "dist" / "codex_config_build" / "wvd.exe"
            )
            candidates = [Path(path) for path in utils._config_fallback_candidates()]

            self.assertIn(temporary_root / "dist" / "wvd" / "config.json", candidates)

    def test_legacy_config_migrates_chat_id_and_is_written_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            canonical_path = temporary_root / "local" / "WvDAS" / "config.json"
            legacy_path = temporary_root / "dist" / "config.json"
            canonical_path.parent.mkdir(parents=True)
            legacy_path.parent.mkdir(parents=True)

            fresh_config = {
                "GENERAL": {
                    "EMU_PATH": "",
                    "EMU_INDEX": 0,
                    "ADB_ADRESS": "127.0.0.1:16384",
                    "FARM_TARGET": None,
                    "TELEGRAM_ENABLED": False,
                    "TELEGRAM_BOT_TOKEN": "",
                    "TELEGRAM_ALLOWED_CHAT_ID": "",
                }
            }
            legacy_config = {
                "GENERAL": {
                    "EMU_PATH": "C:/Emulator/HD-Player.exe",
                    "EMU_INDEX": 1,
                    "FARM_TARGET": "FFXI-2F-elite",
                    "TELEGRAM_ENABLED": True,
                    "TELEGRAM_BOT_TOKEN": "test-token",
                    "TELEGRAM_ALLOWED_CHAT_ID": "123456789",
                }
            }
            canonical_path.write_text(json.dumps(fresh_config), encoding="utf-8")
            legacy_path.write_text(json.dumps(legacy_config), encoding="utf-8")

            utils.CONFIG_FILE = str(canonical_path)
            utils._config_fallback_candidates = lambda: [str(legacy_path)]
            migrated = utils.LoadRawConfigFromFile(None)

            self.assertEqual(
                migrated["GENERAL"]["TELEGRAM_ALLOWED_CHAT_ID"], "123456789"
            )
            persisted = json.loads(canonical_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["GENERAL"]["TELEGRAM_ALLOWED_CHAT_ID"], "123456789"
            )

    def test_existing_newer_telegram_values_are_not_overwritten(self):
        current = {
            "GENERAL": {
                "EMU_PATH": "C:/Emulator/HD-Player.exe",
                "TELEGRAM_ENABLED": True,
                "TELEGRAM_BOT_TOKEN": "new-token",
                "TELEGRAM_ALLOWED_CHAT_ID": "999",
            }
        }
        legacy = {
            "GENERAL": {
                "TELEGRAM_ENABLED": True,
                "TELEGRAM_BOT_TOKEN": "old-token",
                "TELEGRAM_ALLOWED_CHAT_ID": "123",
            }
        }

        merged = utils._merge_telegram_settings(current, legacy)
        self.assertEqual(merged, current)

    def test_explicitly_cleared_chat_id_is_not_restored_from_legacy_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            canonical_path = temporary_root / "local" / "WvDAS" / "config.json"
            legacy_path = temporary_root / "dist" / "config.json"
            canonical_path.parent.mkdir(parents=True)
            legacy_path.parent.mkdir(parents=True)

            current = {
                "GENERAL": {
                    "EMU_PATH": "C:/Emulator/HD-Player.exe",
                    "FARM_TARGET": "FFXI-2F-elite",
                    "TELEGRAM_ENABLED": False,
                    "TELEGRAM_BOT_TOKEN": "",
                    "TELEGRAM_ALLOWED_CHAT_ID": "",
                }
            }
            legacy = {
                "GENERAL": {
                    "EMU_PATH": "C:/Emulator/HD-Player.exe",
                    "FARM_TARGET": "FFXI-2F-elite",
                    "TELEGRAM_ENABLED": True,
                    "TELEGRAM_BOT_TOKEN": "old-token",
                    "TELEGRAM_ALLOWED_CHAT_ID": "123456789",
                }
            }
            canonical_path.write_text(json.dumps(current), encoding="utf-8")
            legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

            utils.CONFIG_FILE = str(canonical_path)
            utils._config_fallback_candidates = lambda: [str(legacy_path)]
            loaded = utils.LoadRawConfigFromFile(None)

            self.assertEqual(loaded["GENERAL"]["TELEGRAM_ALLOWED_CHAT_ID"], "")


if __name__ == "__main__":
    unittest.main()
