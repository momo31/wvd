import ast
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


class Upstream247MergeTests(unittest.TestCase):
    def test_quest_catalog_preserves_local_and_upstream_entries(self):
        quests = load_json_rejecting_duplicate_keys(
            ROOT / "resources" / "quest" / "quest.json"
        )

        for quest_key in (
            "ff-collabo-dungeon1f",
            "FFXI-2F",
            "FFXI-2F-elite",
            "FFXI-5F-4Elite",
            "FFXI-5F-2Elite",
        ):
            self.assertIn(quest_key, quests)

        self.assertEqual(quests["FFXI-5F-4Elite"]["_EOT"][1][1], "FFXI/zone5")
        self.assertEqual(quests["FFXI-5F-2Elite"]["_EOT"][1][1], "FFXI/zone5")

    def test_zone5_template_exists_and_loads(self):
        image_path = ROOT / "resources" / "images" / "FFXI" / "zone5.png"
        self.assertTrue(image_path.is_file())

        from utils import LoadTemplateImage

        image = LoadTemplateImage("FFXI/zone5")
        self.assertIsNotNone(image)
        self.assertGreater(image.size, 0)

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
        self.assertEqual(version, "2.4.7-momo.1")

        from auto_updater import AutoUpdater

        updater = AutoUpdater(queue.Queue(), "owner", "repo", version)
        self.assertFalse(updater._is_newer_version("2.4.7"))
        self.assertTrue(updater._is_newer_version("2.4.8"))

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
