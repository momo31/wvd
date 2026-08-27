import ast
import gettext
import json
import queue
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


def assigned_string(path, variable_name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == variable_name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{variable_name} assignment was not found in {path}")


def contains_han(text):
    return any("\u3400" <= character <= "\u9fff" for character in text)


class Upstream249MergeTests(unittest.TestCase):
    def test_quest_catalog_excludes_1f_and_preserves_upstream_entries(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )

        ffxi_quests = (
            "FFXI-2F",
            "FFXI-2F-elite",
            "FFXI-5F-4Elite",
            "FFXI-5F-2Elite-mid",
            "FFXI-5F-2Elite-bottom",
            "FFXI-5F-Elite",
        )
        self.assertNotIn("ff-collabo-dungeon1f", quests)
        for quest_key in ffxi_quests:
            self.assertIn(quest_key, quests)

        self.assertEqual(quests["FFXI-5F-4Elite"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-2Elite-mid"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-2Elite-bottom"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-Elite"]["_EOT"][1][1], "FFXI/zone5")
        for quest_key in ffxi_quests:
            self.assertEqual(
                quests[quest_key]["_EOT"][0],
                ["press", "EVENT", "FFXI/EVENT_GCN", 1],
            )
            self.assertEqual(quests[quest_key]["_RTT"], ["FFXI/EVENT_VNH"])

        self.assertEqual(
            quests["FFXI-5F-2Elite-mid"]["questName"],
            "[恶名]FFXI 5F 中部2精英",
        )
        self.assertEqual(
            quests["FFXI-5F-2Elite-bottom"]["questName"],
            "[恶名]FFXI 5F 底部2精英",
        )

    def test_korean_quest_list_does_not_expose_chinese_names(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        category_translations = assigned_string(
            SRC / "gui.py", "KO_CATEGORY_TRANSLATIONS"
        )
        target_translations = assigned_string(
            SRC / "gui.py", "KO_TARGET_TRANSLATIONS"
        )

        for quest_key, quest in quests.items():
            category = quest.get(
                "questCategory_ko_KR",
                category_translations.get(
                    quest["questCategory"], quest["questCategory"]
                ),
            )
            target = quest.get(
                "questName_ko_KR",
                target_translations.get(quest["questName"], quest["questName"]),
            )

            self.assertFalse(
                contains_han(category),
                f"Korean category is not localized for {quest_key}: {category}",
            )
            self.assertFalse(
                contains_han(target),
                f"Korean target is not localized for {quest_key}: {target}",
            )

    def test_ffxi_templates_exist_and_load(self):
        from utils import LoadTemplateImage

        for template_name in (
            "EVENT",
            "FFXI/EVENT_GCN",
            "FFXI/EVENT_VNH",
            "FFXI/zone5",
            "FFXI/org_full",
        ):
            image_path = (
                ROOT / "resources" / "images" / f"{template_name}.png"
            )
            self.assertTrue(image_path.is_file())

            image = LoadTemplateImage(template_name)
            self.assertIsNotNone(image)
            self.assertGreater(image.size, 0)

    def test_ffxi_tip_is_localized_in_supported_catalogs(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        tip = quests["FFXI-5F-Elite"]["_TIPS"]

        expected_translations = {
            "en_US": (
                'This quest rests in the small village. Disable "Stay in '
                'Royal Suite" and "Reassemble the first party at the tavern '
                'every 6 hours".'
            ),
            "ko_KR": (
                '이 퀘스트는 작은 마을에서 숙박합니다. "로얄 스위트룸 투숙"과 '
                '"6시간마다 주점의 첫 번째 파티 재소집"을 비활성화하세요.'
            ),
            "zh_CN": tip,
        }

        for language, expected in expected_translations.items():
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            self.assertEqual(translations.gettext(tip), expected)

        gui_source = (SRC / "gui.py").read_text(encoding="utf-8")
        self.assertIn("tip = _(tip)", gui_source)

    def test_missing_language_key_returns_default(self):
        utils_path = SRC / "utils.py"
        tree = ast.parse(utils_path.read_text(encoding="utf-8"), filename=str(utils_path))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "GetOneVarInGeneralConfig"
        )
        isolated_module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        namespace = {
            "LoadRawConfigFromFile": lambda **_kwargs: {"GENERAL": {}}
        }
        exec(compile(isolated_module, str(utils_path), "exec"), namespace)
        getter = namespace["GetOneVarInGeneralConfig"]

        self.assertEqual(getter("LANGUAGE", "zh_CN"), "zh_CN")
        namespace["LoadRawConfigFromFile"] = lambda **_kwargs: {}
        self.assertEqual(getter("LANGUAGE", "zh_CN"), "zh_CN")

    def test_packaged_config_path_and_korean_default_are_stable(self):
        utils_source = (SRC / "utils.py").read_text(encoding="utf-8")
        script_source = (SRC / "script.py").read_text(encoding="utf-8")
        self.assertIn("os.path.abspath(sys.executable)", utils_source)
        self.assertIn("def _config_has_runtime_settings(config_data):", utils_source)
        self.assertIn("WVDAS_CONFIG_PATH", utils_source)
        self.assertIn("LOCALAPPDATA", utils_source)
        self.assertIn("def _find_config_fallback():", utils_source)
        self.assertIn("def _merge_telegram_settings(config_data, fallback_data):", utils_source)
        self.assertIn("GetOneVarInGeneralConfig('LANGUAGE', \"ko_KR\")", utils_source)
        self.assertIn('["GENERAL",   "LANGUAGE",                 tk.StringVar, "ko_KR"]', script_source)

    def test_fork_version_keeps_upstream_update_comparison(self):
        version = assigned_string(SRC / "main.py", "__version__")
        self.assertEqual(version, "2.6.2-momo.1")

        from auto_updater import AutoUpdater

        updater = AutoUpdater(queue.Queue(), "owner", "repo", version)
        self.assertFalse(updater._is_newer_version("2.4.9"))
        self.assertFalse(updater._is_newer_version("2.4.10"))
        self.assertFalse(updater._is_newer_version("2.4.11"))
        self.assertFalse(updater._is_newer_version("2.4.12"))
        self.assertFalse(updater._is_newer_version("2.4.13"))
        self.assertFalse(updater._is_newer_version("2.4.14"))
        self.assertFalse(updater._is_newer_version("2.4.15"))
        self.assertFalse(updater._is_newer_version("2.5.0"))
        self.assertFalse(updater._is_newer_version("2.5.1"))
        self.assertFalse(updater._is_newer_version("2.5.2"))
        self.assertFalse(updater._is_newer_version("2.5.4"))
        self.assertFalse(updater._is_newer_version("2.5.5"))
        self.assertFalse(updater._is_newer_version("2.5.11"))
        self.assertFalse(updater._is_newer_version("2.5.12"))
        self.assertFalse(updater._is_newer_version("2.6.0"))
        self.assertFalse(updater._is_newer_version("2.6.1"))
        self.assertFalse(updater._is_newer_version("2.6.2"))
        self.assertTrue(updater._is_newer_version("2.6.3"))

    def test_per_combat_strategy_reload_happens_after_combat(self):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        combat_start = source.index("def StateCombat():")
        combat_end = source.index("def StateMap_FindSwipeClick", combat_start)
        combat_block = source[combat_start:combat_end]
        self.assertNotIn(
            'if setting.RELOAD_STRATEGY_WHEN == _("每场战斗前"):',
            combat_block,
        )

        dungeon_start = source.index("def StateDungeon(")
        dungeon_end = source.index('case "darkLight":', dungeon_start)
        dungeon_block = source[dungeon_start:dungeon_end]
        self.assertIn(
            'runtimeContext.CURRENT_STRATEGY.get(\n'
            '                            "need_reload_when_combat_begins", False',
            dungeon_block,
        )
        self.assertNotIn(
            'setting.RELOAD_STRATEGY_WHEN == _("每场战斗前")',
            dungeon_block,
        )

    def test_same_reassembly_period_does_not_exit_farm(self):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        factory_start = source.index("def Factory():")
        inn_start = source.index("case State.Inn:", factory_start)
        inn_end = source.index("case State.EoT:", inn_start)
        inn_block = source[inn_start:inn_end]

        self.assertIn(
            "if runtimeContext._LAST_BAGCLEAR != period:",
            inn_block,
        )
        self.assertNotIn(
            "if runtimeContext._LAST_BAGCLEAR == period:",
            inn_block,
        )
        self.assertNotIn("\n                            return", inn_block)

    def test_compatible_upstream_runtime_guards_are_present(self):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        self.assertIn(
            'FindCoordsOrElseExecuteFallbackAndWait(["openworldmap","dungFlag"]',
            source,
        )
        mining_start = source.index('case "FFXI-Org":')
        mining_end = source.index('##########################', mining_start)
        mining_block = source[mining_start:mining_end]
        self.assertIn("if setting._FORCESTOPING.is_set():", mining_block)
        self.assertIn('all_refined_match = CheckHow(\n                            scn, "FFXI/org_full"', mining_block)
        self.assertIn(
            "TeleportFromDungeonToCity(*quest._RTT)",
            mining_block,
        )

    def test_new_quest_names_have_korean_mappings(self):
        translations = assigned_string(SRC / "gui.py", "KO_TARGET_TRANSLATIONS")
        self.assertIn("[恶名]FFXI 5F 中部2精英", translations)
        self.assertIn("[恶名]FFXI 5F 底部2精英", translations)
        self.assertEqual(translations["[骨头]战士灵庙"], "[뼈] 전사 영묘")
        self.assertFalse(contains_han(translations["[骨头]战士灵庙"]))

    def test_upstream_253_mining_patch_and_changelog_are_localized(self):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        self.assertIn("if TryPressRetry(scn):", source)
        self.assertEqual(quests["LMG-FT"]["questName"], "[骨头]战士灵庙")

        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        section = changelog.split("==v2.5.3==", 1)[1].split(
            "==v2.5.2==", 1
        )[0]
        messages = [
            line
            for line in section.splitlines()
            if line and not line.startswith("==") and not line.startswith("**")
        ]
        self.assertEqual(
            messages,
            [
                "现在可以准确的匹配挖矿任务是否是全改.",
                "现在挖矿中弹出网络波动的重试可以正确点击继续.",
                "修改了战士灵庙的文本.",
            ],
        )
        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message in messages:
                localized = translations.gettext(message)
                if language == "zh_CN":
                    self.assertEqual(localized, message)
                elif message.startswith(("Fixed ", "Added ")) and language == "en_US":
                    self.assertEqual(localized, message)
                else:
                    self.assertNotEqual(localized, message)
                if language == "ko_KR":
                    self.assertFalse(contains_han(localized), message)

    def test_upstream_254_changelog_and_quest_names_are_localized(self):
        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        section = changelog.split("==v2.5.4==", 1)[1].split(
            "**已知问题**", 1
        )[0]
        messages = [
            line
            for line in section.splitlines()
            if line and not line.startswith("==") and not line.startswith("**")
        ]
        self.assertEqual(
            messages,
            [
                "修复了战斗中next无法点击的问题.",
                "修复了偶发的无法识别到镐子数量不足的问题.",
                "Fixed an issue where the script failed to launch due to an incorrect English quest name.",
                "Added English descriptions for the mining quest. Enjoy!",
            ],
        )

        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message in messages:
                localized = translations.gettext(message)
                if language == "zh_CN":
                    self.assertEqual(localized, message)
                elif message.startswith(("Fixed ", "Added ")) and language == "en_US":
                    self.assertEqual(localized, message)
                else:
                    self.assertNotEqual(localized, message)
                if language == "ko_KR":
                    self.assertFalse(contains_han(localized), message)

        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        self.assertEqual(quests["FFXI-2F"]["questName_en_US"], "[Chest] FFXI 2F Chest")
        self.assertEqual(
            quests["FFXI-5F-2Elite-mid"]["questName_en_US"],
            "[Elite+Chest] FFXI 5F 2Elite Mid",
        )
        self.assertEqual(
            quests["FFXI-5F-2Elite-bottom"]["questName_en_US"],
            "[Elite+Chest] FFXI 5F 2Elite Bottom",
        )
        skill_source = (SRC / "script.py").read_text(encoding="utf-8")
        skill_start = skill_source.index("def SkillLvlSelectAndDoubleCheck(")
        skill_end = skill_source.index("# 资源不足", skill_start)
        skill_block = skill_source[skill_start:skill_end]
        self.assertIn('CheckIf(scn, "next", [[1,291,898,600]])', skill_block)
        self.assertIn("next_pos[1] + 40", skill_block)

    def test_upstream_252_character_names_are_localized(self):
        expected_translations = {
            "en_US": {
                "F 普修利": "F Prishe",
                "F 赛德": "F Zeid",
                "G 巴克什": "G Bakesh",
            },
            "ko_KR": {
                "F 普修利": "F 프리쉬",
                "F 赛德": "F 자이드",
                "G 巴克什": "G 바케쉬",
            },
            "zh_CN": {
                "F 普修利": "F 普修利",
                "F 赛德": "F 赛德",
                "G 巴克什": "G 巴克什",
            },
        }

        for language, expected in expected_translations.items():
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for source, localized in expected.items():
                self.assertEqual(translations.gettext(source), localized)

        korean_runtime_messages = {
            "游戏未启动!": "게임이 실행 중이 아닙니다!",
            "你开启了应用保活, 请关闭.": (
                "앱 실행 유지 기능이 켜져 있습니다. 비활성화해 주세요."
            ),
            "无法识别的截屏数据，头部内容: {a}": (
                "인식할 수 없는 스크린샷 데이터입니다. 헤더: {a}"
            ),
            "截图数据异常，无法修复": "스크린샷 데이터를 복구할 수 없습니다.",
            "遇到了一些状况之外的情况. 已保存在{a}中.": (
                "예상하지 못한 광석 보상입니다. 스크린샷을 {a}에 저장했습니다."
            ),
        }
        korean_catalog_path = (
            ROOT / "locale" / "ko_KR" / "LC_MESSAGES" / "messages.mo"
        )
        with korean_catalog_path.open("rb") as stream:
            korean_translations = gettext.GNUTranslations(stream)
        for source, localized in korean_runtime_messages.items():
            self.assertEqual(korean_translations.gettext(source), localized)
            self.assertFalse(contains_han(localized))

    def test_upstream_252_runtime_guards_and_cleanup_are_present(self):
        source = (SRC / "script.py").read_text(encoding="utf-8")
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )

        self.assertEqual(assigned_string(SRC / "main.py", "__version__"), "2.6.2-momo.1")
        self.assertIn('DeviceShell("dumpsys window | grep mCurrentFocus")', source)
        self.assertIn('else "screencap 2>/dev/null"', source)
        self.assertIn("Multiple displays were found", source)
        self.assertIn("raise TaskStoppedException()", source)

        self.assertNotIn("retard_tapjoy", quests)
        self.assertNotIn('case "retard_tapjoy"', source)
        for image_name in (
            "nothanks.png",
            "nothanks_s.png",
            "nothanks_y.png",
            "play.png",
            "smallgame_empty.png",
            "yes.png",
        ):
            self.assertFalse(
                (ROOT / "resources" / "images" / "smallgame" / image_name).exists()
            )

    def test_upstream_252_changelog_does_not_fall_back_to_chinese_in_korean(self):
        changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")
        new_section = changelog.split("==v2.5.2==", 1)[1].split(
            "==v2.4.15==", 1
        )[0]
        messages = [
            line
            for line in new_section.splitlines()
            if line and not line.startswith("==") and not line.startswith("**")
        ]
        self.assertEqual(len(messages), 16)

        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = (
                ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            )
            with catalog_path.open("rb") as stream:
                translations = gettext.GNUTranslations(stream)
            for message in messages:
                localized = translations.gettext(message)
                if language == "zh_CN":
                    self.assertEqual(localized, message)
                else:
                    self.assertNotEqual(localized, message)
                if language == "ko_KR":
                    self.assertFalse(
                        contains_han(localized),
                        f"Korean changelog is not localized: {message}",
                    )

    def test_quest_display_names_are_unique(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )
        names = [quest["questName"] for quest in quests.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_legacy_ffxi_code_resolves_to_new_bottom_definition(self):
        from script import LoadQuest, QUEST_DATA

        quest = LoadQuest("FFXI-5F-2Elite")
        self.assertEqual(
            QUEST_DATA["FFXI-5F-2Elite-bottom"]["questName"],
            "[恶名]FFXI 5F 底部2精英",
        )
        self.assertEqual(quest._TARGETINFOLIST[0].roi, [80, 1130])


if __name__ == "__main__":
    unittest.main()
