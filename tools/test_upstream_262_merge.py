"""Regression checks for the upstream 2.6.2 integration."""

from __future__ import annotations

import gettext
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class Upstream262MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (SRC / "main.py").read_text(encoding="utf-8")
        cls.script = (SRC / "script.py").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGES_LOG.md").read_text(encoding="utf-8")

    def test_release_and_narrow_random_target_fallback_are_integrated(self):
        self.assertIn("__version__ = '2.6.2-momo.1'", self.main)
        self.assertIn("==v2.6.2-momo.1==", self.changelog)

        start = self.script.index("# Upstream 2.4.14 fallback:")
        end = self.script.index("resource_shortage = False", start)
        fallback = self.script[start:end]
        for line in (
            "x0, y0 = 0, 560",
            "cols = 8",
            "rows = 3",
            "cell_w = 110",
            "cell_h = 110",
            "for random_pass in range(2):",
        ):
            self.assertIn(line, fallback)
        self.assertNotIn("width, height = 827, 600", fallback)
        self.assertIn("target_probe_points(next_pos)", self.script)

    def test_new_changelog_messages_are_compiled_for_every_locale(self):
        messages = {
            "Integrated upstream 2.6.2's narrower random single-target fallback area.": {
                "en_US": "Integrated upstream 2.6.2's narrower random single-target fallback area.",
                "ko_KR": "업스트림 2.6.2의 축소된 무작위 단일 대상 선택 예비 영역을 통합했습니다.",
                "zh_CN": "集成了上游2.6.2缩小后的随机单体目标备用选择区域。",
            },
            'Use per-combat strategy reset only after understanding the in-game "Repeat Previous Action" behavior.': {
                "en_US": 'Use per-combat strategy reset only after understanding the in-game "Repeat Previous Action" behavior.',
                "ko_KR": '게임 내 "이전 행동 반복" 동작을 이해한 경우에만 매 전투 전략 초기화를 사용하세요.',
                "zh_CN": "仅在了解游戏内“重复上一次”功能后使用每场战斗前策略重置。",
            },
        }

        for language in ("en_US", "ko_KR", "zh_CN"):
            catalog_path = ROOT / "locale" / language / "LC_MESSAGES" / "messages.mo"
            with catalog_path.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            for message_id, translations in messages.items():
                with self.subTest(language=language, message_id=message_id):
                    localized = catalog.gettext(message_id)
                    self.assertEqual(localized, translations[language])
                    if language == "ko_KR":
                        self.assertIsNone(HAN_PATTERN.search(localized))


if __name__ == "__main__":
    unittest.main()
