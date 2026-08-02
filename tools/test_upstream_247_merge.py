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


class Upstream248MergeTests(unittest.TestCase):
    def test_quest_catalog_excludes_1f_and_preserves_upstream_entries(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )

        ffxi_quests = (
            "FFXI-2F",
            "FFXI-2F-elite",
            "FFXI-5F-4Elite",
            "FFXI-5F-2Elite",
            "FFXI-5F-Elite",
        )
        self.assertNotIn("ff-collabo-dungeon1f", quests)
        for quest_key in ffxi_quests:
            self.assertIn(quest_key, quests)

        self.assertEqual(quests["FFXI-5F-4Elite"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-2Elite"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-Elite"]["_EOT"][1][1], "FFXI/zone5")
        for quest_key in ffxi_quests:
            self.assertEqual(
                quests[quest_key]["_RTT"][0][2][0],
                "FFXI/City_VNH",
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

        for template_name in ("FFXI/zone5", "FFXI/City_VNH"):
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

        namespace = {"LoadRawConfigFromFile": lambda: {"GENERAL": {}}}
        exec(compile(isolated_module, str(utils_path), "exec"), namespace)
        getter = namespace["GetOneVarInGeneralConfig"]

        self.assertEqual(getter("LANGUAGE", "zh_CN"), "zh_CN")
        namespace["LoadRawConfigFromFile"] = lambda: {}
        self.assertEqual(getter("LANGUAGE", "zh_CN"), "zh_CN")

    def test_fork_version_keeps_upstream_update_comparison(self):
        version = assigned_string(SRC / "main.py", "__version__")
        self.assertEqual(version, "2.4.8-momo.1")

        from auto_updater import AutoUpdater

        updater = AutoUpdater(queue.Queue(), "owner", "repo", version)
        self.assertFalse(updater._is_newer_version("2.4.8"))
        self.assertTrue(updater._is_newer_version("2.4.9"))

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


if __name__ == "__main__":
    unittest.main()
