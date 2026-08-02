import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from combat_strategy import (  # noqa: E402
    SkillExecutionResult,
    clear_skill_failure,
    complete_strategy_skill,
    register_skill_failure,
    should_activate_auto_combat,
    should_preserve_strategy_progress,
    should_skip_dungeon_strategy_reload,
)


class CombatStrategyQueueTests(unittest.TestCase):
    def test_unmatched_character_replays_previous_action_without_defending(self):
        script_path = ROOT / "src" / "script.py"
        tree = ast.parse(
            script_path.read_text(encoding="utf-8"), filename=str(script_path)
        )
        unmatched_branch = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "highest_match_rate"
        )
        calls = [node for node in ast.walk(unmatched_branch) if isinstance(node, ast.Call)]
        call_names = {
            call.func.id for call in calls if isinstance(call.func, ast.Name)
        }

        self.assertIn("AutoThisChar", call_names)
        self.assertNotIn("DefendThisChar", call_names)
        self.assertTrue(
            any(
                isinstance(call.func, ast.Name)
                and call.func.id == "SetAutoCombat"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value is False
                for call in calls
            )
        )

    def test_pending_skills_prevent_auto_combat(self):
        strategy = {
            "group_name": "custom",
            "skill_settings": [{"role_var": "one"}],
        }

        self.assertFalse(should_activate_auto_combat(strategy, "full-auto"))

    def test_empty_or_full_auto_strategy_activates_auto_combat(self):
        self.assertTrue(should_activate_auto_combat({}, "full-auto"))
        self.assertTrue(
            should_activate_auto_combat(
                {"group_name": "full-auto", "skill_settings": [{"role_var": "one"}]},
                "full-auto",
            )
        )
        self.assertTrue(
            should_activate_auto_combat(
                {"group_name": "custom", "skill_settings": []}, "full-auto"
            )
        )

    def test_failed_action_keeps_skill_pending(self):
        skill = {"role_var": "one"}
        strategy = {"group_name": "custom", "skill_settings": [skill]}

        completed = complete_strategy_skill(
            strategy, skill, SkillExecutionResult.FAILED
        )

        self.assertFalse(completed)
        self.assertEqual(strategy["skill_settings"], [skill])

    def test_successful_action_removes_only_the_exact_row(self):
        first = {"role_var": "same", "skill_var": "same"}
        second = {"role_var": "same", "skill_var": "same"}
        strategy = {"group_name": "custom", "skill_settings": [first, second]}

        completed = complete_strategy_skill(
            strategy, second, SkillExecutionResult.SUCCESS
        )

        self.assertTrue(completed)
        self.assertEqual(len(strategy["skill_settings"]), 1)
        self.assertIs(strategy["skill_settings"][0], first)

    def test_successful_last_skill_enables_auto_decision(self):
        skill = {"role_var": "last"}
        strategy = {"group_name": "custom", "skill_settings": [skill]}

        self.assertTrue(
            complete_strategy_skill(strategy, skill, SkillExecutionResult.SUCCESS)
        )
        self.assertTrue(should_activate_auto_combat(strategy, "full-auto"))

    def test_explicit_fallback_resolves_an_unusable_skill(self):
        skill = {"role_var": "unusable"}
        strategy = {"group_name": "custom", "skill_settings": [skill]}

        self.assertTrue(
            complete_strategy_skill(
                strategy, skill, SkillExecutionResult.FALLBACK
            )
        )
        self.assertEqual(strategy["skill_settings"], [])

    def test_skill_failure_retry_is_bounded_and_cleared(self):
        failures = {}
        skill = {"role_var": "one"}

        self.assertEqual(register_skill_failure(failures, skill, 2), (1, False))
        self.assertEqual(register_skill_failure(failures, skill, 2), (2, True))

        clear_skill_failure(failures, skill)
        self.assertEqual(failures, {})

    def test_equal_rows_have_independent_failure_counts(self):
        failures = {}
        first = {"role_var": "same"}
        second = {"role_var": "same"}

        self.assertEqual(register_skill_failure(failures, first, 2), (1, False))
        self.assertEqual(register_skill_failure(failures, second, 2), (1, False))

    def test_first_failure_of_sixth_skill_cannot_hold_the_queue(self):
        skills = [{"role_var": f"role-{number}"} for number in range(6)]
        last = skills[-1]
        strategy = {"group_name": "custom", "skill_settings": list(skills)}
        failures = {}

        for skill in skills[:-1]:
            self.assertTrue(
                complete_strategy_skill(
                    strategy, skill, SkillExecutionResult.SUCCESS
                )
            )

        attempts, exhausted = register_skill_failure(failures, last, 1)
        self.assertEqual((attempts, exhausted), (1, True))
        self.assertTrue(
            complete_strategy_skill(strategy, last, SkillExecutionResult.FALLBACK)
        )
        self.assertTrue(should_activate_auto_combat(strategy, "full-auto"))

    def test_six_character_queue_carries_across_battles(self):
        skills = [{"role_var": f"role-{number}"} for number in range(6)]
        strategy = {"group_name": "custom", "skill_settings": list(skills)}

        for skill in skills[:3]:
            self.assertTrue(
                complete_strategy_skill(
                    strategy, skill, SkillExecutionResult.SUCCESS
                )
            )

        self.assertEqual(len(strategy["skill_settings"]), 3)
        self.assertFalse(should_activate_auto_combat(strategy, "full-auto"))

        for skill in skills[3:]:
            self.assertTrue(
                complete_strategy_skill(
                    strategy, skill, SkillExecutionResult.SUCCESS
                )
            )

        self.assertTrue(should_activate_auto_combat(strategy, "full-auto"))

    def test_per_dungeon_progress_survives_recovery_only(self):
        strategy = {"group_name": "custom", "skill_settings": [{"role": "one"}]}

        self.assertTrue(
            should_preserve_strategy_progress(
                "per-dungeon-auto", "per-dungeon-auto", "game_restart", strategy
            )
        )
        self.assertTrue(
            should_preserve_strategy_progress(
                "per-dungeon-auto", "per-dungeon-auto", "character_death", strategy
            )
        )
        self.assertFalse(
            should_preserve_strategy_progress(
                "per-dungeon-auto", "per-dungeon-auto", "explicit", strategy
            )
        )
        self.assertFalse(
            should_preserve_strategy_progress(
                "per-dungeon-auto", "per-dungeon-auto", "game_restart", {}
            )
        )

    def test_recovery_reentry_does_not_reset_preserved_queue(self):
        self.assertTrue(
            should_skip_dungeon_strategy_reload(
                "per-dungeon-auto", "per-dungeon-auto", True
            )
        )
        self.assertFalse(
            should_skip_dungeon_strategy_reload(
                "per-dungeon-auto", "per-dungeon-auto", False
            )
        )
        self.assertFalse(
            should_skip_dungeon_strategy_reload(
                "per-battle", "per-dungeon-auto", True
            )
        )


if __name__ == "__main__":
    unittest.main()
