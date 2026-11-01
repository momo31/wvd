"""Replay the map that caused repeated Resume/restart loops, without ADB."""
import ast
from enum import Enum
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2

from tools import test_guild_startup_recovery as startup
from tools.test_server_maintenance import _ExtractFunctions


class MapMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        startup.GuildStartupRecoveryTests.setUpClass()
        tree = ast.parse((startup.ROOT / 'src/script.py').read_text(encoding='utf-8'))
        names = {'StateMapSearch', 'StateMoving_CheckStop', 'IdentifyState', 'State', 'DungeonState'}
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
        cls.code = compile(ast.fix_missing_locations(_ExtractFunctions().visit(
            ast.Module(body=nodes, type_ignores=[]))), '<map-replay>', 'exec')

    def harness(self):
        ns, _, _, _ = startup.GuildStartupRecoveryTests().harness()
        frame = cv2.imread(str(startup.ROOT / 'tools/fixtures/tomb_map_automove.png'))
        self.assertIsNotNone(frame)
        ns.update(Enum=Enum, os=os, TargetInfo=SimpleNamespace,
                  quest=SimpleNamespace(_FloorCheck=None),
                  ScreenShot=Mock(return_value=frame),
                  StateMap_FindSwipeClick=Mock(return_value=[555, 1235]),
                  StateCombatCheck=Mock(return_value=None))
        ns['runtimeContext']._STATE_RESET_REQUIRED = False
        ns['runtimeContext'].mark_stable = Mock()
        ns['Press'].side_effect = lambda position: bool(position)
        exec(self.code, ns)
        return ns, frame

    def test_map_with_dungeon_icon_is_identified_as_map(self):
        ns, frame = self.harness()
        self.assertIsNotNone(ns['CheckIf'](frame, 'dungFlag'))
        self.assertIsNotNone(ns['CheckIf'](frame, 'mapFlag'))
        state, substate, _ = ns['IdentifyState']()
        self.assertEqual((state, substate), (ns['State'].Dungeon, ns['DungeonState'].Map))
        self.assertFalse(any(c.args[0] for c in ns['Press'].call_args_list))

    def test_selected_destination_uses_visible_automove_button(self):
        ns, _ = self.harness()
        ns['StateMoving_CheckStop'] = Mock(return_value=ns['DungeonState'].Dungeon)
        ns['StateMapSearch'](SimpleNamespace(target='position'))
        taps = [call.args[0] for call in ns['Press'].call_args_list]
        self.assertEqual(taps[0], [555, 1235])
        self.assertEqual(len(taps), 2)
        self.assertTrue(430 <= taps[1][0] <= 680 and 1100 <= taps[1][1] <= 1155, taps)

    def test_chest_marker_still_wins_over_map_and_dungeon_icons(self):
        for name in ('chestFlag', 'whowillopenit', 'chestOpening'):
            with self.subTest(name=name):
                ns, frame = self.harness()
                tile = ns['LoadTemplateImage'](name)
                height, width = tile.shape[:2]
                frame[800:800+height, 100:100+width] = tile
                state, substate, _ = ns['IdentifyState']()
                self.assertEqual((state, substate), (ns['State'].Dungeon, ns['DungeonState'].Chest))
                self.assertFalse(any(c.args[0] for c in ns['Press'].call_args_list))

    def test_exit_on_bright_map_presses_its_visible_automove_button(self):
        ns, _ = self.harness()
        frame = cv2.imread(str(startup.ROOT / 'tools/fixtures/tomb_map_exit_automove.png'))
        ns['ScreenShot'] = Mock(return_value=frame)
        ns['StateMap_FindSwipeClick'] = Mock(return_value=[178, 1240])
        ns['StateMoving_CheckStop'] = Mock(return_value=ns['DungeonState'].Dungeon)
        self.assertEqual(ns['StateMapSearch'](SimpleNamespace(target='position')),
                         (ns['DungeonState'].Dungeon, 'FAIL'))
        taps = [call.args[0] for call in ns['Press'].call_args_list]
        self.assertEqual(taps[0], [178, 1240])
        self.assertEqual(len(taps), 2)
        self.assertTrue(60 <= taps[1][0] <= 300 and 1100 <= taps[1][1] <= 1155, taps)

    def test_missing_automove_button_does_not_tap_old_toolbar_coordinate(self):
        ns, _ = self.harness()
        check = ns['CheckIf']
        ns['CheckIf'] = lambda image, name, *args, **kwargs: None if name in ('AutoMove', 'AutoMove_light') else check(image, name, *args, **kwargs)
        ns['StateMoving_CheckStop'] = Mock()
        self.assertEqual(ns['StateMapSearch'](SimpleNamespace(target='position')),
                         (ns['DungeonState'].Map, 'FAIL'))
        self.assertEqual([c.args[0] for c in ns['Press'].call_args_list], [[555, 1235]])
        ns['StateMoving_CheckStop'].assert_not_called()

    def test_failed_movement_returns_to_map_without_toolbar_fallback_taps(self):
        ns, frame = self.harness()
        ns['IdentifyState'] = lambda: (ns['State'].Dungeon, ns['DungeonState'].Map, frame)
        ns['FindCoordsOrElseExecuteFallbackAndWait'] = Mock()
        self.assertEqual(ns['StateMoving_CheckStop'](), ns['DungeonState'].Map)
        ns['FindCoordsOrElseExecuteFallbackAndWait'].assert_not_called()
        ns['Press'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
