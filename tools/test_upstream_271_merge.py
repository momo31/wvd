"""Regression checks for the upstream 2.7.1 integration."""

from __future__ import annotations

import ast
import gettext
import os
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class Upstream271MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (SRC / "main.py").read_text(encoding="utf-8")
        cls.gui = (SRC / "gui.py").read_text(encoding="utf-8")
        cls.script = (SRC / "script.py").read_text(encoding="utf-8")
        cls.utils = (SRC / "utils.py").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")

    def test_release_keeps_standard_logging_and_drops_unused_scipy(self):
        requirements = set(
            (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        )
        self.assertIn("__version__ = '2.7.1-momo.1'", self.main)
        self.assertIn("==v2.7.1-momo.1==", self.changelog)
        self.assertNotIn("scipy", requirements)
        self.assertNotIn("loguru", requirements)
        self.assertNotIn("from scipy", self.script)
        self.assertNotIn("from loguru", self.utils)
        self.assertIn("logging.handlers.QueueListener", self.utils)
        self.assertIn("SummaryLogFilter", self.gui)
        self.assertIn('extra={"summary": True}', self.script)
        self.assertTrue((SRC / "smart_disarm.py").is_file())

    def test_sandman_quest_has_explicit_korean_data(self):
        import json

        quests = json.loads(
            (ROOT / "resources" / "quest" / "quest.json").read_text(
                encoding="utf-8"
            )
        )
        sandman = quests["sandman"]
        self.assertEqual(sandman["questName_ko_KR"], "[인연] 샌드맨")
        self.assertEqual(sandman["questCategory_ko_KR"], "메인 시나리오 1~3장")
        self.assertIsNone(HAN_PATTERN.search(sandman["questName_ko_KR"]))
        self.assertIn('"[缘]沙人": "[인연] 샌드맨"', self.gui)

        sys.path.insert(0, str(SRC))
        try:
            import utils

            previous_language = utils.LANGUAGE
            previous_data = utils.QUEST_DATA
            try:
                utils.LANGUAGE = "ko_KR"
                utils.QUEST_DATA = quests
                reflected = utils.BuildQuestReflection()
            finally:
                utils.LANGUAGE = previous_language
                utils.QUEST_DATA = previous_data
        finally:
            sys.path.remove(str(SRC))

        self.assertEqual(
            reflected["메인 시나리오 1~3장"]["[인연] 샌드맨"],
            "sandman",
        )

    def test_upstream_assets_are_present(self):
        expected_sizes = {
            "Triumph.png": 42394,
            "bondmate_close.png": 17280,
            "sandman/sandman_1.png": 19633,
            "sandman/sandman_2.png": 9560,
            "sandman/sandman_bondmate.png": 763525,
            "stair_fortress3f.png": 45434,
        }
        image_root = ROOT / "resources" / "images"
        for relative_path, size in expected_sizes.items():
            with self.subTest(relative_path=relative_path):
                self.assertEqual((image_root / relative_path).stat().st_size, size)
        self.assertFalse((image_root / "Economy_替换.png").exists())

    def test_wrong_floor_queues_one_actionable_exit(self):
        search_start = self.script.index("def StateMapSearch(")
        search_end = self.script.index("def StateChest(", search_start)
        search = self.script[search_start:search_end]
        self.assertIn('target != "dungFlag"', search)
        self.assertIn('return None, "WRONGFLOOR"', search)
        self.assertIn('if target == "dungFlag":', search)
        self.assertIn('return None, "DONE"', search)

        map_start = self.script.index("case DungeonState.Map:")
        map_end = self.script.index("case DungeonState.Chest:", map_start)
        map_state = self.script[map_start:map_end]
        self.assertIn('case "DONE":', map_state)
        self.assertIn('case "WRONGFLOOR":', map_state)
        self.assertIn('targetInfoList.insert(0, TargetInfo("dungFlag"))', map_state)
        self.assertNotIn("StateSearch(", self.script)
        self.assertNotIn('"quit_dungeon"', self.script)

    def test_sandman_callback_and_time_leap_order(self):
        self.assertIn(
            'Press(CheckIf(screen,"bondmate_close",[[277,751,330,600]]))',
            self.script,
        )
        self.assertIn("quest._SPECIALDIALOGOPTION_CALLBACK(option)", self.script)

        start = self.script.index('case "sandman":')
        end = self.script.index("##########################", start)
        sandman = self.script[start:end]
        self.assertIn('if option == "sandman/sandman_bondmate":', sandman)
        self.assertIn("while not setting._FORCESTOPING.is_set():", sandman)
        self.assertIn("StateDungeon(list(quest._TARGETINFOLIST))", sandman)
        completion = sandman.index("if not sandman_complete:")
        request_leap = sandman.index('target="requestToRescueTheDuke"')
        triumph_leap = sandman.index('target="Triumph"')
        self.assertLess(completion, request_leap)
        self.assertLess(request_leap, triumph_leap)

    def test_emulator_path_check_accepts_supported_executables(self):
        tree = ast.parse(self.gui)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_is_known_emulator_executable"
        )
        namespace = {"os": os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "gui.py", "exec"), namespace)
        is_known = namespace["_is_known_emulator_executable"]

        self.assertTrue(is_known(r"C:\Program Files\BlueStacks\HD-Player.exe"))
        self.assertTrue(is_known("C:/MuMu Player 12/shell/MuMuPlayer.exe"))
        self.assertTrue(is_known(r"C:\MuMu\shell\MuMuNxDevice.exe"))
        self.assertFalse(is_known(r"C:\Unknown\emulator.exe"))

    def test_new_messages_are_compiled_for_every_locale(self):
        messages = {
            "选择可执行文件": {
                "en_US": "Select executable",
                "ko_KR": "실행 파일 선택",
                "zh_CN": "选择可执行文件",
            },
            "楼层错误.": {
                "en_US": "Wrong dungeon floor detected.",
                "ko_KR": "잘못된 던전 층이 감지되었습니다.",
                "zh_CN": "检测到错误的地下城楼层。",
            },
            (
                "警告: 设置的模拟器路径可能不正确.\n"
                "如果你遇到无法启动模拟器, 请尝试重新设置路径."
            ): {
                "en_US": (
                    "Warning: The selected emulator path may be incorrect.\n"
                    "If the emulator does not start, select its executable again."
                ),
                "ko_KR": (
                    "경고: 선택한 에뮬레이터 경로가 올바르지 않을 수 있습니다.\n"
                    "에뮬레이터가 시작되지 않으면 실행 파일을 다시 선택하세요."
                ),
                "zh_CN": (
                    "警告：设置的模拟器路径可能不正确。\n"
                    "如果无法启动模拟器，请重新选择执行文件。"
                ),
            },
            "由于触发了特殊对话, 使用了回调函数.": {
                "en_US": "A special dialogue option was selected; running its callback.",
                "ko_KR": "특수 대화 선택지가 선택되어 콜백을 실행합니다.",
                "zh_CN": "已选择特殊对话选项，正在执行回调函数。",
            },
            "已完成{a}次沙人缘.\n用时{b:.2f}秒.": {
                "en_US": "Completed Sandman bondmate {a} time(s).\nElapsed: {b:.2f}s.",
                "ko_KR": "샌드맨 인연을 {a}회 완료했습니다.\n경과 시간: {b:.2f}초.",
                "zh_CN": "已完成{a}次沙人缘。\n用时{b:.2f}秒。",
            },
        }
        for language, catalog_messages in (
            (language, {key: values[language] for key, values in messages.items()})
            for language in ("en_US", "ko_KR", "zh_CN")
        ):
            catalog_path = ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            with catalog_path.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            for message_id, expected in catalog_messages.items():
                with self.subTest(language=language, message_id=message_id):
                    translated = catalog.gettext(message_id)
                    self.assertEqual(translated, expected)
                    if language == "ko_KR":
                        self.assertIsNone(HAN_PATTERN.search(translated))


if __name__ == "__main__":
    unittest.main()
