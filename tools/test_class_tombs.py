"""Shared routes and distinct entrances for the added tombs."""
import unittest
from unittest.mock import patch

import script
import utils


class ClassTombTests(unittest.TestCase):
    def test_class_tombs_have_chest_then_exit_routes_distinct_entrances_and_localized_names(self):
        for code, entrance, korean, english, chinese in [
            ('LMG-FT', 'FTB1F', '전사', 'Fighter', '战士'),
            ('LMG-PR', 'PRB1F', '승려', 'Priest', '僧侣'),
            ('LMG-MG', 'MGB1F', '마법사', 'Mage', '法师'),
            ('LMG-KN', 'KNB1F', '기사', 'Knight', '骑士'),
            ('LMG-RA', 'RAB1F', 'Rarities', 'Rarities', '稀有'),
        ]:
            with self.subTest(code=code):
                quest = script.LoadQuest(code)
                self.assertIsNotNone(quest)
                self.assertEqual(quest._TYPE, 'dungeon')
                self.assertEqual([(point.target, point.roi, point.swipeDir)
                                  for point in quest._TARGETINFOLIST],
                                 [('position', [555, 1235], [[700, 1200, 100, 250]]),
                                  ('position', [178, 1240], [[700, 1200, 100, 250]])])
                actions = {entry[0]: entry[1] for entry in quest._EOT}
                self.assertEqual(actions['worldmap'], 'LMG/LMG')
                self.assertEqual(actions['L1'], 'LMG/' + entrance)
                self.assertEqual(actions['L2'], 'LMG/' + entrance)
                self.assertEqual(utils.ValidateQuestResources(code, 'en_US'), [])
                for language, label in [
                    ('ko_KR', '[뼈] ' + korean + ' 영묘'),
                    ('en_US', '[Bone] Mausoleum ' + english),
                    ('zh_CN', '[骨头]' + chinese + '灵庙'),
                ]:
                    with patch.object(utils, 'LANGUAGE', language):
                        catalog = utils.BuildQuestReflection()
                        names = [name for targets in catalog.values()
                                 for name, target in targets.items() if target == code]
                    self.assertEqual(names, [label])


if __name__ == '__main__':
    unittest.main()
