import ast
import gettext
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from post_combat import PostCombatDecision, PostCombatTracker


class PostCombatTrackerTests(unittest.TestCase):
    def test_stable_dungeon_confirms_no_chest(self):
        tracker = PostCombatTracker(stable_dungeon_seconds=2.5)

        self.assertEqual(
            tracker.observe(10.0, dungeon_active=True),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(12.49, dungeon_active=True),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(12.5, dungeon_active=True),
            PostCombatDecision.DUNGEON,
        )

    def test_transient_dungeon_does_not_hide_delayed_chest(self):
        tracker = PostCombatTracker(stable_dungeon_seconds=2.5)

        self.assertEqual(
            tracker.observe(20.0, dungeon_active=True),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(22.0, dungeon_active=True),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(22.1),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(28.0, chest_active=True),
            PostCombatDecision.CHEST,
        )

    def test_chest_wins_when_dungeon_flag_is_also_visible(self):
        tracker = PostCombatTracker()

        self.assertEqual(
            tracker.observe(
                30.0,
                combat_active=True,
                chest_active=True,
                dungeon_active=True,
            ),
            PostCombatDecision.CHEST,
        )

    def test_combat_resets_dungeon_stability(self):
        tracker = PostCombatTracker(stable_dungeon_seconds=2.5)

        tracker.observe(40.0, dungeon_active=True)
        tracker.observe(42.0, dungeon_active=True)
        self.assertEqual(
            tracker.observe(42.1, combat_active=True),
            PostCombatDecision.COMBAT,
        )
        self.assertEqual(
            tracker.observe(43.0, dungeon_active=True),
            PostCombatDecision.WAIT,
        )
        self.assertEqual(
            tracker.observe(45.5, dungeon_active=True),
            PostCombatDecision.DUNGEON,
        )

    def test_dungeon_loops_use_fast_post_combat_resolution(self):
        script_path = SRC / "script.py"
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))
        resolver_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ResolvePostCombatState"
        ]

        self.assertGreaterEqual(len(resolver_calls), 4)

        combat_end_start = source.index('logger.debug(_("战斗已结束."))')
        combat_end_finish = source.index("highest_match_rate = 0", combat_end_start)
        self.assertIn("return True", source[combat_end_start:combat_end_finish])

        fallback_start = source.index("if highest_match_rate < 0.80:")
        fallback_finish = source.index(
            'if target_skill.get("skill_var")', fallback_start
        )
        self.assertNotIn("return True", source[fallback_start:fallback_finish])
        self.assertGreaterEqual(
            source.count('if recover_pos := CheckIf(ScreenShot(),"recover"):'),
            2,
        )
        self.assertGreaterEqual(source.count("Press(recover_pos)"), 2)

    def test_post_combat_messages_are_localized(self):
        message_ids = (
            "战斗结束后检测到宝箱. 开箱后再恢复.",
            "战斗结束后确认没有宝箱. 立即恢复.",
            "战斗结束后的画面在{a}秒内未稳定. 重新识别状态.",
        )

        for language in ("en_US", "ko_KR"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message_id in message_ids:
                self.assertNotEqual(translations.gettext(message_id), message_id)


if __name__ == "__main__":
    unittest.main()
