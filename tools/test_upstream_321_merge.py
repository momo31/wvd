"""Behavioral contracts for the 3.2.1 integration; no device or network access."""
import ast
import copy
import json
import os
import threading
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
import utils


class ResourceMigrationTests(unittest.TestCase):
    def test_global_recovery_assets_are_checked_before_a_quest_can_start(self):
        missing = utils.ValidateQuestResources('fishing', 'zh_CN')
        self.assertIn('settrap', missing)
        self.assertIn('guildDecline', missing)
        self.assertIn('startupDisclaimer', missing)

    def test_legacy_target_alias_is_validated_as_its_canonical_target(self):
        self.assertEqual(utils.ValidateQuestResources('FFXI-5F-2Elite', 'en_US'), [])

    def test_floor_alternatives_are_validated_individually(self):
        with patch.object(utils, 'QUEST_DATA', {'demo': {'_FloorCheck': ['first', 'second']}}), patch.object(utils, '_missing_templates', side_effect=lambda names, language: sorted(names)):
            missing = utils.ValidateQuestResources('demo', 'en_US')
        self.assertIn('first', missing)
        self.assertIn('second', missing)

    def test_language_cache_and_required_remote_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for language, value in [('en_US', 10), ('zh_CN', 20), ('common', 30)]:
                folder = root / 'resources/images' / language
                folder.mkdir(parents=True)
                cv2.imwrite(str(folder / 'fixture.png'), np.full((4, 4, 3), value, dtype=np.uint8))
            mod = root / 'mod/images'
            mod.mkdir(parents=True)
            cv2.imwrite(str(mod / 'custom.png'), np.full((4, 4, 3), 40, dtype=np.uint8))
            utils._TEMPLATE_CACHE.clear()
            self.addCleanup(utils._TEMPLATE_CACHE.clear)
            with patch.object(utils, 'ResourcePath', side_effect=lambda path: str(root / path)), patch.object(
                utils, 'GetModPath', side_effect=lambda path: str(root / 'mod' / path), create=True,
            ):
                english = utils.LoadTemplateImage('fixture', 'en_US')
                self.assertEqual(int(english[0, 0, 0]), 10)
                self.assertEqual(int(utils.LoadTemplateImage('fixture', 'zh_CN')[0, 0, 0]), 20)
                self.assertIs(utils.LoadTemplateImage('fixture', 'en_US'), english)
                self.assertEqual(int(utils.LoadTemplateImage('custom', 'zh_CN')[0, 0, 0]), 40)
                with patch.object(utils, 'QUEST_DATA', {'demo': {'_TYPE': 'dungeon', '_FloorCheck': 'missing-floor'}}):
                    self.assertIn('missing-floor', utils.ValidateQuestResources('demo', 'en_US'))

    def test_unavailable_language_does_not_use_english_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'resources/images/en_US'
            folder.mkdir(parents=True)
            cv2.imwrite(str(folder / 'only-english.png'), np.full((4, 4, 3), 10, dtype=np.uint8))
            with patch.object(utils, 'ResourcePath', side_effect=lambda path: str(root / path)):
                with self.assertRaises(FileNotFoundError):
                    utils.LoadTemplateImage('only-english', 'zh_CN')

    def test_catalog_retains_korean_and_rejects_removed_targets(self):
        self.assertIn('fishing', utils.QUEST_DATA)
        self.assertIn('shiphold-fairy', utils.QUEST_DATA)
        self.assertEqual(utils.QUEST_DATA['sandman']['questName_ko_KR'], '[인연] 샌드맨')
        for target in ('DOE', 'jier', 'missing-target'):
            self.assertEqual(utils.ValidateQuestResources(target, 'en_US'), ['quest:' + target])
        self.assertEqual(utils.ValidateQuestResources('7000G', 'en_US'), [])

    def test_required_remote_templates_resolve_and_missing_language_is_reported(self):
        for name in ('closeAppPrompt', 'startupDisclaimer', 'titlelogo', 'tabtostart'):
            self.assertIsNotNone(utils.LoadTemplateImage(name, 'en_US'))
        self.assertIn('startupDisclaimer', utils.ValidateRemoteResources('zh_CN'))
        self.assertEqual(utils.ValidateRemoteResources('en_US'), [])


def runtime_functions(names, namespace):
    class ExposeFactoryFunctions(ast.NodeTransformer):
        depth = 0

        def visit_FunctionDef(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1
            return node

        def visit_Nonlocal(self, node):
            return ast.copy_location(ast.Global(names=node.names), node) if self.depth == 1 else node
    source = (Path(__file__).resolve().parents[1] / 'src/script.py').read_text(encoding='utf-8')
    nodes = [copy.deepcopy(node) for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.FunctionDef) and node.name in names]
    missing = set(names) - {node.name for node in nodes}
    if missing:
        raise AssertionError('Runtime functions missing: ' + ', '.join(sorted(missing)))
    module = ExposeFactoryFunctions().visit(ast.Module(nodes, type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), '<runtime-integration>', 'exec'), namespace)
    return namespace


class RuntimeIntegrationTests(unittest.TestCase):
    def test_fishing_preserves_cast_gesture_and_releases_touch_on_stop(self):
        class Stopped(Exception): pass
        for interrupt_at in (None, 1, 4):
            commands = []
            release = Mock()
            ticks = [0]
            def sleep(seconds):
                ticks[0] += 1
                if ticks[0] == interrupt_at: raise Stopped()
            ns = runtime_functions({'CastFishingLine'}, dict(DeviceShell=commands.append, Sleep=sleep,
                setting=SimpleNamespace(_ADBDEVICE=SimpleNamespace(shell=release)), logger=Mock()))
            if interrupt_at is None:
                ns['CastFishingLine']()
                self.assertEqual(len(commands), 181)
            else:
                with self.assertRaises(Stopped): ns['CastFishingLine']()
            self.assertEqual(commands[0], 'input motionevent DOWN 243 1200')
            release.assert_called_once_with('input motionevent UP 243 1200', timeout=2)

    def test_gold_quest_summary_reports_gold_earned(self):
        from script import RuntimeContext
        class Completed(Exception): pass
        context = RuntimeContext()
        logger = Mock()
        ns = runtime_functions({'QuestFarm'}, dict(runtimeContext=context,
            setting=SimpleNamespace(FARM_TARGET='7000G', _FORCESTOPING=threading.Event()),
            RestartableSequenceExecution=lambda *steps: None, Sleep=lambda seconds: None,
            time=SimpleNamespace(time=Mock(side_effect=[100, 102])), logger=logger, _=lambda text: text,
            RoundCompleted=Mock(side_effect=Completed)))
        with self.assertRaises(Completed): ns['QuestFarm']()
        data = logger.info.call_args.kwargs['extra']['summary_data']
        self.assertEqual(data['complete_times'], 1)
        self.assertEqual(data['col_2_counter'], 7000)
        self.assertEqual(data['total_time'], 2)

    def test_arrow_probe_without_next_marker_is_bounded(self):
        presses = []
        detector = Mock(return_value=([(100, 200, .9, 'red')] * 4, None))
        ns = runtime_functions({'ProbeEnemyArrows'}, dict(StateCombat_DetectArrow=detector,
            CutRoI=lambda screen, roi: screen, Press=presses.append, Sleep=lambda seconds: None))
        self.assertTrue(ns['ProbeEnemyArrows']('frame'))
        self.assertEqual(presses, [[100, 361]] * 3)
        presses.clear(); detector.return_value = ([], None)
        self.assertFalse(ns['ProbeEnemyArrows']('frame'))
        self.assertEqual(presses, [])

    def test_blank_matching_frames_never_report_a_template_hit(self):
        ns = runtime_functions({'_check'}, dict(np=np, cv2=cv2, logger=Mock(), _=lambda text: text,
            CutRoI=lambda screen, roi: screen))
        for screen in (None, np.zeros((0, 0, 3), np.uint8), np.zeros((20, 20, 3), np.uint8)):
            self.assertEqual(ns['_check'](screen, np.zeros((5, 5, 3), np.uint8)), (None, 0.0))

    def test_quick_exit_target_uses_visible_dungeon_button(self):
        DungeonState = SimpleNamespace(Quit='quit', Dungeon='dungeon')
        presses = []
        ns = runtime_functions({'startAuto'}, dict(targetInfoList=[SimpleNamespace(target='leaveDung')],
            ScreenShot=lambda: 'screen', CheckIf=lambda screen, name, *args: [800, 300] if name == 'leaveDung' else None,
            Press=lambda point: presses.append(point) or bool(point), Sleep=lambda seconds: None,
            StateMoving_CheckStop=lambda: DungeonState.Quit, DungeonState=DungeonState, logger=Mock(), _=lambda text: text))
        self.assertEqual(ns['startAuto'](), DungeonState.Quit)
        self.assertEqual(presses[0], [800, 300])

    def test_resume_has_a_bound_and_stops_before_twenty_first_tap(self):
        from script import RuntimeContext
        class Restart(Exception): pass
        context = RuntimeContext(); context._RESUMEAVAILABLE = True
        presses = []
        ns = runtime_functions({'TryResume'}, dict(runtimeContext=context, ScreenShot=lambda: None,
            CheckIf=lambda *args: [10, 20], Press=presses.append, logger=Mock(), _=lambda text: text,
            restartGame=Mock(side_effect=Restart)))
        for _ in range(20): self.assertTrue(ns['TryResume']())
        with self.assertRaises(Restart): ns['TryResume']()
        self.assertEqual(len(presses), 20)

    def test_summary_contains_current_counts_and_isolated_event_snapshot(self):
        from script import RuntimeContext
        first, second = RuntimeContext(), RuntimeContext()
        first._TOTALTIME = 21.239
        first._COUNTERDUNG = 2
        first._COUNTERCHEST = 4
        first._COUNTERCOMBAT = 3
        first.record_special_event('retry')
        summary = first.summary_extra()
        first.record_special_event('retry')
        self.assertEqual(summary['summary_data']['total_time'], 21.24)
        self.assertEqual(summary['summary_data']['complete_times'], 2)
        self.assertEqual(summary['summary_data']['col_2_counter'], 4)
        self.assertEqual(summary['summary_data']['col_3_counter'], 3)
        self.assertEqual(summary['summary_events'], {'retry': 1})
        self.assertEqual(second.summary_extra()['summary_events'], {})
        self.assertEqual(second.summary_extra()['summary_data']['complete_times'], 0)

    def test_retry_event_is_counted_only_after_retry_is_pressed(self):
        from script import RuntimeContext
        context = RuntimeContext()
        ns = runtime_functions({'TryPressRetry'}, dict(
            runtimeContext=context, CheckIf=lambda screen, name: [1, 2] if screen == name else None,
            Press=lambda point: bool(point), logger=Mock(), _=lambda text: text))
        self.assertFalse(ns['TryPressRetry']('clear'))
        self.assertEqual(context._EVENT_COUNTERS, {})
        self.assertTrue(ns['TryPressRetry']('retry'))
        self.assertEqual(sum(context._EVENT_COUNTERS.values()), 1)

    def test_eot_uses_upstream_levels_with_existing_retry_boundary(self):
        screens = iter(['town', 'level1', 'level1', 'level1', 'level2', 'level2', 'level2', 'dungeon'])
        positions = {'EdgeOfTown': [10, 10], 'TradeWaterway': [20, 20], 'Dist': [30, 30], 'GotoDung': [40, 40]}
        presses = []

        def check(screen, name, *args):
            flags = {'town': 'Inn', 'level1': 'openworldmap', 'level2': 'EoTreturn', 'dungeon': 'dungFlag'}
            if name == flags.get(screen):
                return [1, 1]
            return positions.get(name)

        ns = runtime_functions({'StateEoT'}, dict(
            quest=SimpleNamespace(_EOT=[['town', 'EOT'], ['L1', 'TradeWaterway'], ['L2', 'Dist']]),
            setting=SimpleNamespace(_FORCESTOPING=threading.Event()), runtimeContext=SimpleNamespace(),
            ScreenShot=lambda: next(screens), CheckIf=check,
            FindCoordsOrElseExecuteFallbackAndWait=lambda names, *args: positions.get(names) if isinstance(names, str) else None,
            RestartableSequenceExecution=lambda *steps: [step() for step in steps],
            Press=lambda pos: presses.append(pos), Sleep=lambda *args: None,
            logger=Mock(), _=lambda value: value,
        ))
        ns['StateEoT']()
        self.assertEqual(presses, [[10, 10], [20, 20], [40, 40], [30, 30], [40, 40]])

    def test_adb_shell_closes_its_connection_after_read(self):
        sent = []
        closed = []
        connection = SimpleNamespace(send=sent.append, read_all=lambda: b'command-output', close=lambda: closed.append(True))
        device = SimpleNamespace(create_connection=lambda **kwargs: connection)
        ns = runtime_functions({'DeviceShell'}, dict(
            setting=SimpleNamespace(_FORCESTOPING=threading.Event(), _ADBDEVICE=device),
            Event=threading.Event, Thread=threading.Thread, cv2=cv2, logger=Mock(), _=lambda value: value,
        ))
        self.assertEqual(ns['DeviceShell']('echo probe'), 'command-output')
        self.assertEqual(sent, ['shell:echo probe'])
        self.assertEqual(closed, [True])

    def test_floor_name_compares_pixels_and_skips_loading_frames(self):
        tile = ((np.indices((50, 600)).sum(axis=0) // 12) % 2 * 255).astype(np.uint8)
        template = np.repeat(tile[:, :, None], 3, axis=2)
        screen = np.zeros((1600, 900, 3), dtype=np.uint8)
        screen[65:115, 150:750] = template
        ns = runtime_functions({'CheckFloorName', 'CutRoI'}, dict(
            cv2=cv2, np=np, logger=Mock(), _=lambda value: value,
            LoadTemplateImage=lambda name: template, SaveImage=Mock(),
        ))
        self.assertTrue(ns['CheckFloorName'](screen, 'fixture-floor'))
        screen[65:115, 150:750] = 255 - template
        self.assertFalse(ns['CheckFloorName'](screen, 'fixture-floor'))
        self.assertTrue(ns['CheckFloorName'](None, 'fixture-floor'))
        self.assertTrue(ns['CheckFloorName'](np.zeros_like(screen), 'fixture-floor'))

    def test_wrong_floor_exits_once_and_loading_does_not_restart_loop(self):
        presses = []
        ns = runtime_functions({'StateMapSearch'}, dict(
            os=os, quest=SimpleNamespace(_FloorCheck='fixture-floor'), logger=Mock(),
            _=lambda value: value, ScreenShot=lambda: 'map',
            CheckIf=lambda screen, name, *args: name == 'mapFlag',
            CheckFloorName=lambda *args: False,
            StateMap_FindSwipeClick=lambda target: [123, 456],
            Press=lambda value: presses.append(value), DungeonState=SimpleNamespace(Map='map'),
        ))
        self.assertEqual(ns['StateMapSearch'](SimpleNamespace(target='stair_other')), (None, 'WRONGFLOOR'))
        self.assertEqual(ns['StateMapSearch'](SimpleNamespace(target='dungFlag')), (None, 'DONE'))
        self.assertEqual(presses, [[123, 456]])
        ns['CheckIf'] = lambda *args: False
        self.assertEqual(ns['StateMapSearch'](SimpleNamespace(target='stair_other')), (None, 'FAIL'))
        self.assertEqual(presses, [[123, 456]])

    def test_arrow_detection_preserves_bounded_fallback(self):
        from combat_strategy import target_probe_points
        screen = np.zeros((240, 300, 3), dtype=np.uint8)
        candidates, annotated = utils.StateCombat_DetectArrow(screen)
        self.assertEqual(candidates, [])
        self.assertEqual(annotated.shape, screen.shape)
        points = target_probe_points((200, 300))
        self.assertGreater(len(points), 0)
        self.assertLess(len(points), 20)
        self.assertEqual(points, target_probe_points((200, 300)))

    def test_fishing_detector_does_not_invent_a_bobber_on_blank_frame(self):
        candidates, annotated = utils.Fishing_DetectBobber(np.zeros((240, 300, 3), dtype=np.uint8))
        self.assertEqual(candidates, [])
        self.assertEqual(annotated.shape, (240, 300))
