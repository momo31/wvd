import gettext
import hashlib
import json
import re
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chest_guard import ChestGuardAction, decide_chest_guard_action  # noqa: E402


HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def png_dimensions(path):
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


class Upstream260MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (SRC / "script.py").read_text(encoding="utf-8")
        cls.gui = (SRC / "gui.py").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")

    def test_version_changelog_and_party_management_asset(self):
        main = (SRC / "main.py").read_text(encoding="utf-8")
        self.assertIn("__version__ = '2.7.1-momo.1'", main)
        for version in (
            "2.6.2-momo.1",
            "2.6.1-momo.1",
            "2.6.0-momo.1",
            "2.5.13",
            "2.5.12",
        ):
            self.assertIn(f"==v{version}==", self.changelog)

        new_asset = ROOT / "resources" / "images" / "PartyManagementTitle.png"
        old_asset = ROOT / "resources" / "images" / "AdventurerGuild.png"
        self.assertTrue(new_asset.is_file())
        self.assertFalse(old_asset.exists())
        self.assertEqual(png_dimensions(new_asset), (549, 62))
        self.assertEqual(
            hashlib.sha256(new_asset.read_bytes()).hexdigest(),
            "c3bcc205d5c0b37cf18e915168f194263dfa58b79f4f1eed067e1f6b11613b21",
        )
        self.assertGreaterEqual(self.script.count('"PartyManagementTitle"'), 2)
        self.assertNotIn('"AdventurerGuild"', self.script)

    def test_left_ffxi_route_has_explicit_korean_data(self):
        quests = json.loads(
            (ROOT / "resources" / "quest" / "quest.json").read_text(
                encoding="utf-8"
            )
        )
        route = quests["FFXI-5F-2Elite-left"]
        self.assertEqual(
            [point[2] for point in route["_TARGETINFOLIST"]],
            [[30, 652], [80, 1130], [450, 392]],
        )
        self.assertEqual(
            route["questName_ko_KR"], "[악명] FFXI 5F 좌측 엘리트 2마리"
        )
        self.assertEqual(route["questCategory_ko_KR"], "최신 던전")
        self.assertIsNone(HAN_PATTERN.search(route["questName_ko_KR"]))
        self.assertIn(
            '"[恶名]FFXI 5F 左侧2精英": "[악명] FFXI 5F 좌측 엘리트 2마리"',
            self.gui,
        )

    def test_korean_category_reflection_merges_localized_category_aliases(self):
        import utils

        previous_language = utils.LANGUAGE
        try:
            utils.LANGUAGE = "ko_KR"
            categories = utils.BuildQuestReflection()
        finally:
            utils.LANGUAGE = previous_language

        self.assertNotIn("最新洞窟", categories)
        self.assertIn("최신 던전", categories)
        self.assertIn("FFXI-5F-2Elite-left", categories["최신 던전"].values())
        self.assertEqual(
            len([category for category in categories if category == "최신 던전"]),
            1,
        )
        self.assertIn("dict.fromkeys", self.gui)
        self.assertIn("_category_keys_for_display", self.gui)
        self.assertIn("_quest_code_for_target_display", self.gui)

    def test_per_strategy_controls_replace_the_visible_global_control(self):
        for option in (
            "need_reload_when_dungeon_begins",
            "need_reload_when_combat_begins",
            "complete_one_as_all",
        ):
            self.assertIn(option, self.gui)
            self.assertIn(option, self.script)
        self.assertNotIn("reload_strategy_combobox", self.gui)
        self.assertIn("_legacy_strategy_reload_defaults", self.gui)
        self.assertIn("normalize_strategy_options", self.gui)
        self.assertIn('"RELOAD_STRATEGY_WHEN"', self.script)

    def test_task_point_reload_and_all_refined_screenshot_are_integrated(self):
        target_complete = self.script.index("def TargetPointComplete(")
        dungeon_loop = self.script.index("while 1:", target_complete)
        target_block = self.script[target_complete:dungeon_loop]
        self.assertIn('== _(\n                "自定义任务点策略"', target_block)
        self.assertLess(
            target_block.index("runtimeContext.TASK_STEP_INDEX += 1"),
            target_block.index("ReloadStrategy()"),
        )

        mining_start = self.script.index('case "FFXI-Org":')
        mining = self.script[mining_start:]
        message = "All-refined ore detected; screenshot saved to {a}."
        message_at = mining.index(message)
        save_at = mining.rfind("file_path = SaveImage(scn)", 0, message_at)
        self.assertGreaterEqual(save_at, 0)

    def test_screenshot_restart_retries_without_weakening_other_restart_guards(self):
        screenshot_start = self.script.index("def ScreenShot():")
        screenshot_end = self.script.index("def _check(", screenshot_start)
        screenshot = self.script[screenshot_start:screenshot_end]
        self.assertIn("except RestartSignal:", screenshot)
        self.assertIn(
            "A game restart was triggered during screenshot capture; ", screenshot
        )
        self.assertIn(
            "if isinstance(e, (RestartSignal, TaskStoppedException)):\n"
            "                    raise",
            screenshot,
        )

    def test_chest_markers_still_win_over_dialogue_next(self):
        dialogue_calls = []

        def check_marker(_screen, marker):
            return [450, 1264] if marker == "chestFlag" else None

        decision = decide_chest_guard_action(
            "chest-selection",
            check_marker,
            lambda *args, **kwargs: dialogue_calls.append((args, kwargs)),
        )
        self.assertIs(decision.action, ChestGuardAction.OPEN_CHEST)
        self.assertEqual(dialogue_calls, [])

    def test_new_messages_are_compiled_for_every_supported_language(self):
        message_ids = (
            "该策略需要在进入地下城时进行重置.",
            "[高级]该策略需要在战斗开始前进行重置.\n"
            "确保你了解\"重复上一次\"功能, 否则请勿开启.",
            "[高级]该策略释放任一即视为完成.",
            "A game restart was triggered during screenshot capture; retrying the capture.",
            "The next task-point strategy is now active.",
            "The strategy was reloaded after entering the dungeon.",
            "The strategy was reloaded before combat.",
            "One configured action completed, so the remaining strategy queue was cleared.",
            "All-refined ore detected; screenshot saved to {a}.",
            "Integrated upstream 2.5.12 through 2.6.0 while preserving local recovery, Telegram control, and chest guards.",
            "Combat reset and completion behavior can now be configured per strategy.",
            "Custom task-point strategies switch immediately after each point is completed.",
            "Added the left-side FFXI 5F elite route and updated party-management detection.",
            "All-refined mining rewards now save a diagnostic screenshot.",
            "Temporarily disabled the legacy per-combat reset and saved screenshots for all-refined mining rewards.",
            "Recovered cleanly when a game restart is triggered during screenshot capture.",
            "Improved party switching when the sixth party slot is used without a pickaxe.",
            "Added the left-side two-elite FFXI 5F route.",
        )

        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            for message_id in message_ids:
                with self.subTest(language=language, message_id=message_id):
                    localized = catalog.gettext(message_id)
                    if language == "en_US" and not HAN_PATTERN.search(message_id):
                        self.assertEqual(localized, message_id)
                    else:
                        self.assertNotEqual(localized, message_id)
                    if language == "ko_KR":
                        self.assertIsNone(HAN_PATTERN.search(localized))
                    if "{a}" in message_id:
                        self.assertIn("{a}", localized)


if __name__ == "__main__":
    unittest.main()
