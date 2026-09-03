import gettext
import hashlib
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def png_dimensions(path):
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Upstream2511MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_source = (SRC / "script.py").read_text(encoding="utf-8")
        cls.main_source = (SRC / "main.py").read_text(encoding="utf-8")
        mining_start = cls.script_source.index('case "FFXI-Org":')
        mining_end = cls.script_source.index(
            "##########################", mining_start
        )
        cls.mining_block = cls.script_source[mining_start:mining_end]

    def test_version_and_upstream_images_are_integrated(self):
        self.assertIn("__version__ = '2.7.1-momo.1'", self.main_source)

        next_image = ROOT / "resources" / "images" / "next.png"
        position_image = (
            ROOT / "resources" / "images" / "FFXI" / "org_position.png"
        )
        self.assertEqual(png_dimensions(next_image), (34, 24))
        self.assertEqual(
            sha256(next_image),
            "04ba9f4e7819531f189e299a2b8e02f33950572a5c8e24bcd73e89952a69fd31",
        )
        self.assertEqual(png_dimensions(position_image), (82, 82))
        self.assertEqual(
            sha256(position_image),
            "274bfb2e93537d3de76a1590a155320d6ade5febd2f4a3df50c6d96358de6a11",
        )

    def test_combat_next_target_keeps_bounded_local_fallbacks(self):
        skill_start = self.script_source.index("def SkillLvlSelectAndDoubleCheck(")
        skill_end = self.script_source.index("def ActivateCombatSpeed(", skill_start)
        skill_block = self.script_source[skill_start:skill_end]

        self.assertIn(
            "(next_pos[0] + 15, next_pos[1] + 50)", skill_block
        )
        self.assertIn("target_probe_points(next_pos)", skill_block)
        self.assertIn("if not target_selected:", skill_block)
        self.assertIn("for random_pass in range(2):", skill_block)

    def test_mining_route_requires_the_position_marker(self):
        self.assertIn(
            '["theRouteToTheDestinationCannotBeFound", "openworldmap"]',
            self.mining_block,
        )
        self.assertIn('"FFXI/org_position"', self.mining_block)
        self.assertIn("[[692,68,140,140]]", self.mining_block)

        route_check = self.mining_block.index('"FFXI/org_position"')
        first_mining_tap = self.mining_block.index("Press([450,600])")
        self.assertLess(route_check, first_mining_tap)

    def test_mining_checks_pre_and_post_click_frames_without_double_counting(self):
        self.assertIn("def CheckMiningState(scn, record_reward=True):", self.mining_block)
        self.assertIn("if not record_reward:", self.mining_block)
        self.assertIn("record_reward=not reward_visible", self.mining_block)
        self.assertGreaterEqual(self.mining_block.count("CheckMiningState("), 3)
        for template in (
            "FFXI/nothingToDig",
            "FFXI/nothingToDig2",
            "FFXI/nothingToDig3",
            "FFXI/needpickaxe",
        ):
            self.assertIn(template, self.mining_block)

        pre_check = self.mining_block.index("result = CheckMiningState(")
        mining_tap = self.mining_block.index("Press([450,600])", pre_check)
        post_check = self.mining_block.index(
            "result = CheckMiningState(", pre_check + 1
        )
        self.assertLess(pre_check, mining_tap)
        self.assertLess(mining_tap, post_check)

    def test_mining_cycle_recovers_without_swallowing_restart_signal(self):
        self.assertIn("def RunMiningCycle():", self.mining_block)
        self.assertIn(
            "RestartableSequenceExecution(RunMiningCycle)", self.mining_block
        )

        screenshot_start = self.script_source.index("def ScreenShot():")
        screenshot_end = self.script_source.index("def _check(", screenshot_start)
        screenshot_block = self.script_source[screenshot_start:screenshot_end]
        self.assertIn(
            "if isinstance(e, (RestartSignal, TaskStoppedException)):",
            screenshot_block,
        )
        self.assertNotIn("pass # TODO", screenshot_block)

    def test_diagnostic_images_use_the_runtime_log_directory(self):
        self.assertNotRegex(
            self.script_source,
            re.compile(r"^\s*cv2\.imwrite\(", re.MULTILINE),
        )

        import utils

        original_log_dir = utils.LOGS_FOLDER_NAME
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                utils.LOGS_FOLDER_NAME = temp_dir
                image = np.zeros((4, 4, 3), dtype=np.uint8)
                saved = Path(utils.SaveImage(image, "../unsafe-name"))
                self.assertEqual(saved.parent.resolve(), Path(temp_dir).resolve())
                self.assertEqual(saved.name, "unsafe-name.png")
                self.assertTrue(saved.is_file())
                self.assertIsNone(utils.SaveImage(None, "ignored"))
        finally:
            utils.LOGS_FOLDER_NAME = original_log_dir

    def test_new_runtime_and_changelog_messages_are_compiled(self):
        runtime_messages = {
            "Obtained {a}.": "{a} 획득.",
            "Detected an all-refined ore reward.": "전체 개조 광석 보상을 감지했습니다.",
            "Unrecognized ore reward; screenshot saved to {a}.": (
                "광석 보상을 판별하지 못했습니다. 스크린샷을 {a}에 저장했습니다."
            ),
            "No usable pickaxe was detected in the {a} frame; leaving the dungeon.": (
                "{a} 프레임에서 사용할 곡괭이가 없음을 감지해 던전에서 나갑니다."
            ),
            "No ore to mine was detected in the {a} frame; leaving the dungeon.": (
                "{a} 프레임에서 채굴할 광석이 없음을 감지해 던전에서 나갑니다."
            ),
            "Mining position was not confirmed; restarting the mining cycle.": (
                "채굴 위치를 확인하지 못해 채굴 사이클을 다시 시작합니다."
            ),
            "pre-click": "클릭 전",
            "post-click": "클릭 후",
            "The result dialogue did not change after {a} skip attempts; re-identifying the screen.": (
                "결과창 스킵을 {a}회 시도했지만 화면이 바뀌지 않아 화면 상태를 다시 식별합니다."
            ),
            "The post-combat result dialogue did not change after the bounded skips; re-identifying the screen.": (
                "제한된 전투 결과창 스킵 후에도 화면이 바뀌지 않아 화면 상태를 다시 식별합니다."
            ),
            "The chest screen remained unidentified for 150 seconds; returning to state detection.": (
                "상자 화면을 150초 동안 식별하지 못해 상태 판정으로 돌아갑니다."
            ),
            "Chest markers are still visible; stopping result skips and re-identifying the chest state.": (
                "상자 표식이 남아 있어 결과창 스킵을 중단하고 상자 상태를 다시 식별합니다."
            ),
        }
        changelog_messages = (
            "Integrated upstream 2.5.11 mining-position checks and restart recovery.",
            "Improved the combat Next target image and mining result detection.",
            "Preserved Telegram control, persistent settings, and network recovery.",
            "Simplified route-readiness detection so slow screenshots do not misclassify transient route errors.",
            "Added a recovery boundary so mining can continue after a game restart during dungeon entry.",
            "Mining results are now checked in both the pre-click and post-click frames.",
            "Updated the Next image and mining-result detection.",
            "Centralized diagnostic screenshots and adjusted the mining wait interval.",
            "Combat now uses bounded fallback targeting when the Next marker remains visible.",
            "Kept chest interaction markers ahead of bounded result-dialogue skips.",
        )

        catalog_path = ROOT / "locale" / "ko_KR" / "LC_MESSAGES" / "messages.mo"
        with catalog_path.open("rb") as stream:
            translations = gettext.GNUTranslations(stream)

        for message_id, expected in runtime_messages.items():
            localized = translations.gettext(message_id)
            self.assertEqual(localized, expected)
            self.assertIsNone(re.search(r"[一-鿿]", localized), message_id)
        for message_id in changelog_messages:
            localized = translations.gettext(message_id)
            self.assertNotEqual(localized, message_id)
            self.assertIsNone(re.search(r"[一-鿿]", localized), message_id)

        all_messages = tuple(runtime_messages) + changelog_messages
        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            for message_id in all_messages:
                localized = catalog.gettext(message_id)
                if language == "en_US":
                    self.assertEqual(localized, message_id)
                else:
                    self.assertNotEqual(localized, message_id)
                if "{a}" in message_id:
                    self.assertIn("{a}", localized)

    def test_changelog_and_korean_readme_describe_the_merged_behavior(self):
        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        for version in range(5, 12):
            self.assertIn(f"==v2.5.{version}", changelog)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("가장 어두움부터 25% 밝기 사이", readme)

        workflow = (
            ROOT / ".github" / "workflows" / "build-executable.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python-version: '3.14'", workflow)


if __name__ == "__main__":
    unittest.main()
