"""Regression tests for the upstream 2.6.1 integration."""

from __future__ import annotations

import gettext
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class Upstream261MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = (SRC / "gui.py").read_text(encoding="utf-8")
        cls.script = (SRC / "script.py").read_text(encoding="utf-8")
        cls.utils = (SRC / "utils.py").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")

    def test_version_and_changelog_identify_the_fork_release(self):
        main = (SRC / "main.py").read_text(encoding="utf-8")
        self.assertIn("__version__ = '2.6.1-momo.1'", main)
        self.assertIn("==v2.6.1-momo.1==", self.changelog)
        self.assertIn(
            "Integrated upstream 2.6.1 checkbox styling and positive recovery controls.",
            self.changelog,
        )
        self.assertIn(
            "Existing skip-recovery settings are migrated automatically without changing behavior.",
            self.changelog,
        )

    def test_checkbox_styles_are_split_by_context(self):
        self.assertNotIn("Custom.TCheckbutton", self.gui)
        self.assertEqual(
            self.gui.count('style="CombatStrategy.TCheckbutton"'),
            3,
        )
        self.assertGreaterEqual(
            self.gui.count('style="Default.TCheckbutton"'),
            10,
        )
        self.assertIn('configure("Default.TCheckbutton")', self.gui)
        self.assertIn(
            'configure("CombatStrategy.TCheckbutton", background="#FFFFFF")',
            self.gui,
        )

    def test_positive_recovery_flags_keep_local_recovery_orchestration(self):
        self.assertIn(
            '["TEMPLATE",   "DO_COMBAT_RECOVER",       tk.BooleanVar, True]',
            self.script,
        )
        self.assertIn(
            '["TEMPLATE",   "DO_CHEST_RECOVER",        tk.BooleanVar, True]',
            self.script,
        )
        self.assertNotIn("setting.SKIP_COMBAT_RECOVER", self.script)
        self.assertNotIn("setting.SKIP_CHEST_RECOVER", self.script)
        self.assertEqual(
            self.script.count("enabled=setting.DO_COMBAT_RECOVER"),
            2,
        )
        self.assertEqual(
            self.script.count("enabled=setting.DO_CHEST_RECOVER"),
            2,
        )
        self.assertIn("recoveryPlan = RecoveryPlan()", self.script)
        self.assertIn(
            'logger.info(_("由于面板配置, 跳过了战后恢复."))',
            self.script,
        )
        self.assertIn(
            'logger.info(_("由于面板配置, 跳过了开启宝箱后恢复."))',
            self.script,
        )

    def test_recovery_config_migration_is_on_the_common_load_boundary(self):
        self.assertIn("def _migrate_recovery_settings(config_data):", self.utils)
        self.assertIn(
            '("SKIP_COMBAT_RECOVER", "DO_COMBAT_RECOVER")',
            self.utils,
        )
        self.assertIn(
            '("SKIP_CHEST_RECOVER", "DO_CHEST_RECOVER")',
            self.utils,
        )
        load_start = self.utils.index("def LoadRawConfigFromFile(")
        load_block = self.utils[load_start:]
        self.assertIn("_migrate_recovery_settings(config_data)", load_block)
        self.assertIn("_write_config_file(config_file_path, config_data)", load_block)

    def test_new_ui_and_changelog_messages_are_compiled(self):
        expected = {
            "en_US": {
                "在战斗结束后进行恢复.": "Recover after combat.",
                "在开箱后进行恢复.": "Recover after opening a chest.",
                "在进入地下城时进行恢复.": "Recover when entering the dungeon.",
                "Integrated upstream 2.6.1 checkbox styling and positive recovery controls.":
                    "Integrated upstream 2.6.1 checkbox styling and positive recovery controls.",
                "Existing skip-recovery settings are migrated automatically without changing behavior.":
                    "Existing skip-recovery settings are migrated automatically without changing behavior.",
                "Preserved local recovery orchestration, Telegram control, chest guards, and localized quest categories.":
                    "Preserved local recovery orchestration, Telegram control, chest guards, and localized quest categories.",
            },
            "ko_KR": {
                "在战斗结束后进行恢复.": "전투 종료 후 회복합니다.",
                "在开箱后进行恢复.": "상자 개봉 후 회복합니다.",
                "在进入地下城时进行恢复.": "던전 입장 시 회복합니다.",
                "Integrated upstream 2.6.1 checkbox styling and positive recovery controls.":
                    "업스트림 2.6.1의 체크박스 스타일과 긍정형 회복 설정을 통합했습니다.",
                "Existing skip-recovery settings are migrated automatically without changing behavior.":
                    "기존 회복 건너뛰기 설정은 동작이 바뀌지 않도록 자동으로 이전됩니다.",
                "Preserved local recovery orchestration, Telegram control, chest guards, and localized quest categories.":
                    "로컬 회복 순서 제어, Telegram 제어, 상자 보호 로직, 현지화된 퀘스트 분류를 유지했습니다.",
            },
            "zh_CN": {
                "在战斗结束后进行恢复.": "战斗结束后进行恢复。",
                "在开箱后进行恢复.": "开启宝箱后进行恢复。",
                "在进入地下城时进行恢复.": "进入地下城时进行恢复。",
                "Integrated upstream 2.6.1 checkbox styling and positive recovery controls.":
                    "集成了上游2.6.1的复选框样式和正向恢复选项。",
                "Existing skip-recovery settings are migrated automatically without changing behavior.":
                    "现有的跳过恢复设置将自动迁移，行为保持不变。",
                "Preserved local recovery orchestration, Telegram control, chest guards, and localized quest categories.":
                    "保留了本地恢复编排、Telegram控制、宝箱保护和本地化任务分类。",
            },
        }

        for language, messages in expected.items():
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            for message_id, translation in messages.items():
                with self.subTest(language=language, message_id=message_id):
                    localized = catalog.gettext(message_id)
                    self.assertEqual(localized, translation)
                    if language == "ko_KR":
                        self.assertIsNone(HAN_PATTERN.search(localized))


if __name__ == "__main__":
    unittest.main()
