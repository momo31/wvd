from __future__ import annotations

import queue
import sys
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
        gui_source = (SRC / "gui.py").read_text(encoding="utf-8")

        self.assertIn(
            'return _("停止") if busy else _("脚本, 启动!")',
            gui_source,
        )
        self.assertNotIn('_("중지") if busy else _("시작")', gui_source)
        self.assertIn("text=task_button_text(False)", gui_source)
        self.assertIn("text=task_button_text(busy)", gui_source)

    def test_local_start_creates_runtime_before_handoff_check(self):
        runtime = _Runtime()
        controller = _Controller(runtime)
        setting = _Setting()

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
        self.assertEqual(runtime.handoff_checks, 0)
        self.assertEqual(controller.remote_feature.started, [runtime])
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

    def test_remote_target_updates_gui_through_existing_selection_event(self):
        window = SimpleNamespace(
            farm_target_category_combo=_Combo(),
            farm_target_combo=_Combo(),
            FARM_TARGET_TEXT=_Variable(),
            FARM_TARGET=_Variable(),
            TASK_SPECIFIC_CONFIG=_Variable(),
        )
        with mock.patch.object(gui, "_targets_for_category_display", return_value=["raw target"]), mock.patch.object(
            gui,
            "trans_tgt",
            return_value="표시 목표",
        ), mock.patch.object(gui, "_quest_code_for_target_display", return_value="quest-code"):
            selected = gui.ConfigPanelApp.select_farm_target_from_remote(
                window,
                "표시 분류",
                "표시 목표",
            )

        self.assertTrue(selected)
        self.assertEqual(window.farm_target_category_combo.value, "표시 분류")
        self.assertEqual(window.farm_target_combo["values"], ["표시 목표"])
        self.assertEqual(window.FARM_TARGET.value, "quest-code")
        self.assertFalse(window.TASK_SPECIFIC_CONFIG.value)
        self.assertEqual(window.farm_target_combo.events, ["<<ComboboxSelected>>"])

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


if __name__ == "__main__":
    unittest.main()
