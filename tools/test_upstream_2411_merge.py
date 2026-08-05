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
        self.assertIn("__version__ = '2.4.11-momo.1'", self.main_source)
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

    def test_new_changelog_entries_are_translated_for_supported_languages(self):
        expected = {
            "en_US": {
                "挖矿任务现已加入矿石统计.": "Mining now includes ore statistics.",
                "不忘初心, 朋友们.": "Stay true to the original goal, friends.",
            },
            "ko_KR": {
                "挖矿任务现已加入矿石统计.": "광석 채굴 작업에 광석 통계가 추가되었습니다.",
                "不忘初心, 朋友们.": "여러분, 초심을 잃지 맙시다.",
            },
            "zh_CN": {
                "挖矿任务现已加入矿石统计.": "挖矿任务现已加入矿石统计.",
                "不忘初心, 朋友们.": "不忘初心, 朋友们.",
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
