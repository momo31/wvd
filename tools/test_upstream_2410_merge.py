import gettext
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def load_json_rejecting_duplicate_keys(path):
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=reject_duplicates)


class Upstream2410MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        cls.script_source = (SRC / "script.py").read_text(encoding="utf-8")

    def test_ffxi_mining_uses_the_royal_city_return_route(self):
        quest = self.quests["FFXI-Org"]

        self.assertEqual(
            quest["_RTT"],
            [
                "City_RoyalCityLuknalia",
                "input swipe 400 400 500 300",
                [500, 1100],
            ],
        )
        self.assertIn("9999", quest["_TIPS"])
        self.assertNotIn("999999", quest["_TIPS"])

    def test_ffxi_mining_recovery_steps_are_restartable(self):
        start = self.script_source.index('case "FFXI-Org":')
        end = self.script_source.index(
            "setting._FINISHINGCALLBACK()", start
        )
        block = self.script_source[start:end]

        self.assertIn("def LeaveMiningDungeon(result, phase):", block)
        self.assertIn('"ReturnText", [[1,1], "leaveDung", "donothing"], 1', block)
        self.assertIn('"OpenWorldMap",', block)
        self.assertIn("TeleportFromDungeonToCity(*quest._RTT)", block)
        self.assertIn("def RunMiningCycle():", block)
        self.assertIn("RestartableSequenceExecution(RunMiningCycle)", block)
        self.assertEqual(block.count('LeaveMiningDungeon(result, _("'), 2)

    def test_ffxi_mining_tip_is_localized(self):
        quests = json.loads((ROOT / 'resources/quest/quest.json').read_text(encoding='utf-8'))
        for language in ('en_US', 'ko_KR', 'zh_CN'):
            tip = quests['FFXI-Org']['_TIPS_' + language]
            self.assertIn('9999', tip.replace(',', ''))
            self.assertIn('FFXIStone', tip)
            if language != 'zh_CN': self.assertNotIn('请按照', tip)

    def test_new_changelog_section_is_localizable_and_consistent(self):
        from utils import LocalizeChangesLog

        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        current_section = changelog.split("==v2.4.10==", 1)[1].split(
            "==v2.4.9==", 1
        )[0]
        self.assertIn("9999", current_section)
        self.assertNotIn("999999", current_section)

        translations = {
            "修复了挖矿任务会卡死的问题.": "FFXI 채굴 작업이 멈추는 문제를 수정했습니다.",
        }
        localized = LocalizeChangesLog(
            "修复了挖矿任务会卡死的问题.\nunchanged\n",
            lambda value: translations.get(value, value),
        )
        self.assertEqual(
            localized,
            "FFXI 채굴 작업이 멈추는 문제를 수정했습니다.\nunchanged\n",
        )


if __name__ == "__main__":
    unittest.main()
