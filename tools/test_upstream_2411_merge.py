import gettext
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Upstream2411MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_source = (ROOT / "src" / "script.py").read_text(encoding="utf-8")
        cls.main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        start = cls.script_source.index('case "FFXI-Org":')
        cls.mining_block = cls.script_source[start:]

    def test_version_and_mining_templates_are_integrated(self):
        self.assertIn("__version__ = '2.4.15-momo.1'", self.main_source)
        for template in (
            "FFXI/receive",
            "FFXI/nothingToDig2",
            "FFXI/nothingToDig3",
            "FFXI/org_fine",
            "FFXI/org_lesser_full",
        ):
            self.assertIn(template, self.mining_block)

    def test_mining_labels_have_a_korean_mapping(self):
        self.assertIn('"ko_KR": "특급 광석"', self.mining_block)
        self.assertIn('"ko_KR": "상급 광석"', self.mining_block)
        self.assertIn('"ko_KR": "기타"', self.mining_block)

    def test_unknown_reward_screenshot_path_is_created_before_logging(self):
        warning = self.mining_block.index(
            '"Unrecognized ore reward; screenshot saved to %s."'
        )
        assignment = self.mining_block.rfind("file_path = os.path.join", 0, warning)
        self.assertGreaterEqual(assignment, 0)

    def test_upstream_2414_and_2415_changelog_entries_are_preserved(self):
        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        self.assertIn("==v2.4.15==", changelog)
        self.assertIn("==v2.4.14==", changelog)
        self.assertIn("稍微增加了挖矿的截图时间, 以避免误报.", changelog)
        self.assertIn("修复了如果战斗画面没有next脚本会卡死的问题.", changelog)
        self.assertIn("1 购买9999个鹤嘴锄并保存在仓库里.", changelog)
        self.assertNotIn("1 购买999999个鹤嘴锄并保存在仓库里.", changelog)

    def test_single_target_selection_waits_and_uses_bounded_probe_points(self):
        skill_start = self.script_source.index(
            "def SkillLvlSelectAndDoubleCheck("
        )
        skill_end = self.script_source.index(
            "# 资源不足", skill_start
        )
        skill_block = self.script_source[skill_start:skill_end]

        self.assertIn("for underscore in range(5):", skill_block)
        self.assertIn("for target_pos in target_probe_points(next_pos):", skill_block)
        self.assertIn("if not target_selected:", skill_block)
        self.assertIn("for _ in range(2):", skill_block)
        self.assertIn("제한된 무작위 대상 선택으로 복구합니다.", skill_block)
        self.assertNotIn("Press([pos[0],pos[1]+40])", skill_block)

    def test_new_changelog_entries_are_translated_for_supported_languages(self):
        expected = {
            "en_US": {
                "挖矿任务现已加入矿石统计.": "Mining now includes ore statistics.",
                "不忘初心, 朋友们.": "Stay true to the original goal, friends.",
                "修复了出小改 全改的时候进行截图时截图路径出错导致脚本停止.": (
                    "Fixed the screenshot path error that stopped the script "
                    "when obtaining lesser/full refinement."
                ),
                "优化了单体选择. 现在会检测Next的位置并尝试点击next下方的箭头.": (
                    "Improved single-target selection. It now detects the Next "
                    "position and tries to click the arrow below Next."
                ),
                "稍微增加了挖矿的截图时间, 以避免误报.": (
                    "Slightly increased the mining screenshot delay to avoid "
                    "false positives."
                ),
                "修复了如果战斗画面没有next脚本会卡死的问题.": (
                    "Fixed a script hang when the battle screen has no Next "
                    "marker."
                ),
            },
            "ko_KR": {
                "挖矿任务现已加入矿石统计.": "광석 채굴 작업에 광석 통계가 추가되었습니다.",
                "不忘初心, 朋友们.": "여러분, 초심을 잃지 맙시다.",
                "修复了出小改 全改的时候进行截图时截图路径出错导致脚本停止.": (
                    "하급 개조/전체 개조 보상에서 스크린샷 경로 오류로 "
                    "스크립트가 중지되던 문제를 수정했습니다."
                ),
                "优化了单体选择. 现在会检测Next的位置并尝试点击next下方的箭头.": (
                    "단일 대상 선택을 개선했습니다. 이제 Next 위치를 감지하고 "
                    "Next 아래 화살표를 클릭합니다."
                ),
                "稍微增加了挖矿的截图时间, 以避免误报.": (
                    "오탐을 방지하기 위해 채굴 스크린샷 대기 시간을 조금 "
                    "늘렸습니다."
                ),
                "修复了如果战斗画面没有next脚本会卡死的问题.": (
                    "전투 화면에 Next가 없을 때 스크립트가 멈추던 문제를 "
                    "수정했습니다."
                ),
            },
            "zh_CN": {
                "挖矿任务现已加入矿石统计.": "挖矿任务现已加入矿石统计.",
                "不忘初心, 朋友们.": "不忘初心, 朋友们.",
                "修复了出小改 全改的时候进行截图时截图路径出错导致脚本停止.": (
                    "修复了出小改 全改的时候进行截图时截图路径出错导致脚本停止."
                ),
                "优化了单体选择. 现在会检测Next的位置并尝试点击next下方的箭头.": (
                    "优化了单体选择. 现在会检测Next的位置并尝试点击next下方的箭头."
                ),
                "稍微增加了挖矿的截图时间, 以避免误报.": (
                    "稍微增加了挖矿的截图时间, 以避免误报."
                ),
                "修复了如果战斗画面没有next脚本会卡死的问题.": (
                    "修复了如果战斗画面没有next脚本会卡死的问题."
                ),
            },
        }
        for language, messages in expected.items():
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message_id, translated in messages.items():
                self.assertEqual(translations.gettext(message_id), translated)


if __name__ == "__main__":
    unittest.main()
