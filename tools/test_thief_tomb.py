"""Thief Tomb visits the third-point chest before the fourth-point exit."""
import copy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import script
import utils


class ThiefTombTests(unittest.TestCase):
    def test_thief_loads_chest_then_exit_route_without_mutating_fighter(self):
        thief = script.LoadQuest('LMG-TH')
        self.assertIsNotNone(thief)
        self.assertEqual(thief._TYPE, 'dungeon')
        self.assertEqual([(point.target, point.roi, point.swipeDir)
                          for point in thief._TARGETINFOLIST],
                         [('position', [555, 1235], [[700, 1200, 100, 250]]),
                          ('position', [178, 1240], [[700, 1200, 100, 250]])])
        fighter = script.LoadQuest('LMG-FT')
        self.addCleanup(lambda: thief._TARGETINFOLIST[0].roi.__setitem__(0, 555))
        thief._TARGETINFOLIST[0].roi[0] = 999
        self.assertEqual(fighter._TARGETINFOLIST[0].roi, [555, 1235])

    def test_exit_is_visited_only_after_chest_handling_returns_to_map(self):
        from tools.test_upstream_321_merge import runtime_functions
        states = SimpleNamespace(Chest='chest', Map='map', Quit='quit', Dungeon='dungeon', Combat='combat')

        def search(point):
            events.append(tuple(point.roi))
            return (states.Chest if len(events) == 1 else states.Quit), 'DONE'

        def chest():
            state = next(chest_states)
            events.append('opening' if state == states.Chest else 'opened')
            return state

        namespace = dict(
            copy=copy, logger=Mock(), _=lambda text: text,
            runtimeContext=SimpleNamespace(CURRENT_STRATEGY={}),
            setting=SimpleNamespace(_FORCESTOPING=threading.Event(), TASK_POINT_STRATEGY={}),
            RecoveryPlan=script.RecoveryPlan, CheckpointKind=script.CheckpointKind,
            remote_stop_checkpoint=lambda *args: None,
            State=SimpleNamespace(Inn='inn', Dungeon='dungeon'), DungeonState=states,
            TargetInfo=script.TargetInfo,
            IdentifyState=lambda: ('dungeon', states.Map, None),
            Sleep=lambda *args: None, Press=lambda *args: None,
            StateMapSearch=search, StateChest=chest,
        )
        runtime_functions(['StateDungeon'], namespace)
        for code in ('LMG-TH', 'LMG-FT', 'LMG-PR', 'LMG-MG', 'LMG-KN', 'LMG-RA'):
            with self.subTest(quest=code):
                events = []
                chest_states = iter([states.Chest, states.Map])
                namespace['runtimeContext'] = SimpleNamespace(CURRENT_STRATEGY={})
                namespace['StateDungeon'](script.LoadQuest(code)._TARGETINFOLIST)
                self.assertEqual(events, [(555, 1235), 'opening', 'opened', (178, 1240)])

    def test_thief_selects_its_own_entrance_and_validates_missing_image(self):
        quest = script.LoadQuest('LMG-TH')
        self.assertIsNotNone(quest)
        actions = {entry[0]: entry[1] for entry in quest._EOT}
        self.assertEqual(actions['worldmap'], 'LMG/LMG')
        self.assertEqual(actions['L1'], 'LMG/THB1F')
        self.assertEqual(actions['L2'], 'LMG/THB1F')
        with patch.object(utils, '_missing_templates', side_effect=lambda names, language:
                          sorted(set(names) & {'LMG/THB1F'})):
            self.assertEqual(utils.ValidateQuestResources('LMG-TH', 'en_US'), ['LMG/THB1F'])
        with patch.object(utils, '_missing_templates', return_value=[]):
            self.assertEqual(utils.ValidateQuestResources('LMG-TH', 'en_US'), [])

    def test_thief_is_selectable_in_every_ui_language(self):
        for language, expected in [('ko_KR', '[뼈] 도적 영묘'),
                                   ('en_US', '[Bone] Mausoleum Thief'),
                                   ('zh_CN', '[骨头]盗贼灵庙')]:
            with self.subTest(language=language), patch.object(utils, 'LANGUAGE', language):
                catalog = utils.BuildQuestReflection()
                matches = [(name, code) for targets in catalog.values()
                           for name, code in targets.items() if code == 'LMG-TH']
                self.assertEqual(matches, [(expected, 'LMG-TH')])


if __name__ == '__main__':
    unittest.main()
