"""Run lifetime, cancellation and target reload at the real controller boundary."""
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
import script
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime, request_task_handoff
from mod.telegram_remote_control import worker


def make_runtime(events=None):
    return RemoteRuntime('chain', main.StartReason.LOCAL, 'target', events or queue.Queue(),
                         threading.Event(), None, '')


def make_controller():
    c = object.__new__(main.AppController)
    c.msg_queue = queue.Queue()
    c.headless = True
    c.config_path = 'fixture.json'
    c.main_window = None
    c.quest_threading = None
    c.quest_setting = None
    c._active_runtime = None
    c._active_latch = None
    c._completion_enqueued = set()
    c._ui_finished = set()
    c._handoff_waiting = set()
    c._closing = False
    c.remote_feature = Mock(emulator_reboot_in_progress=False)
    c.remote_feature.handle_event.return_value = False
    c.pending = []
    c.schedule_after = lambda delay, callback: c.pending.append(callback)
    c.after = c.schedule_after
    c._clock = time.monotonic
    c._push_event = Mock()
    return c


def pump(c):
    for _ in range(100):
        callbacks, c.pending = c.pending, []
        for callback in callbacks:
            callback()
        while not c.msg_queue.empty():
            name, value = c.msg_queue.get_nowait()
            c._dispatch(name, value)
        if not c.pending and not c._task_is_alive():
            return
        time.sleep(.005)
    raise AssertionError('controller did not settle')


class QuestHandoffTests(unittest.TestCase):
    def test_zero_resource_priority_and_failed_handoff(self):
        setting = SimpleNamespace(ACTIVE_DIGGING=True, ACTIVE_BEG_MONEY=True, ACTIVE_FISHING=True)
        for option, expected in [('ACTIVE_DIGGING', 'FFXI-Org'), ('ACTIVE_BEG_MONEY', '7000G'), ('ACTIVE_FISHING', 'fishing')]:
            self.assertEqual(script.SelectResourceFallback(setting), expected)
            setattr(setting, option, False)
        self.assertIsNone(script.SelectResourceFallback(setting))
        r = make_runtime()
        r.worker_force_stop_event.set()
        self.assertFalse(request_task_handoff(r, r.event_queue, target='fishing', event_name='switch_quest'))
        self.assertTrue(r.event_queue.empty())

    def test_special_item_is_checked_before_any_result_tap(self):
        from tools.test_upstream_321_merge import runtime_functions
        from chest_guard import decide_chest_guard_action, ChestGuardAction
        from network_guard import NetworkStallTracker, NETWORK_STALL_SECONDS, NETWORK_PROBE_COOLDOWN_SECONDS
        from screen_health import classify_screen, ScreenHealth
        import numpy as np
        frame = np.full((1600, 900, 3), 60, dtype=np.uint8)
        namespace = dict(
            runtimeContext=SimpleNamespace(_TIME_CHEST=0),
            quest=SimpleNamespace(_SPECIALJUNK='item', _SPECIALJUNK_CALLBACK='shiphold-fairy'),
            setting=SimpleNamespace(QUICK_DISARM_CHEST=True),
            time=time, NetworkStallTracker=NetworkStallTracker,
            NETWORK_STALL_SECONDS=NETWORK_STALL_SECONDS, NETWORK_PROBE_COOLDOWN_SECONDS=NETWORK_PROBE_COOLDOWN_SECONDS,
            ScreenShot=lambda: frame, classify_screen=classify_screen, ScreenHealth=ScreenHealth,
            CheckIf=lambda screen, name: [100, 200] if name == 'item' else None,
            CheckIfAtThreshold=lambda *args, **kwargs: [800, 1500],
            decide_chest_guard_action=decide_chest_guard_action, ChestGuardAction=ChestGuardAction,
            StateCombatCheck=lambda screen: False, TryPressNetworkRetry=lambda *args: False,
            ChangeQuest=Mock(side_effect=SystemExit), Press=Mock(), logger=Mock(),
        )
        runtime_functions(['StateChest'], namespace)
        with self.assertRaises(SystemExit):
            namespace['StateChest']()
        namespace['ChangeQuest'].assert_called_once_with('shiphold-fairy')
        namespace['Press'].assert_not_called()

    def test_no_bait_supply_stops_instead_of_tapping_missing_item(self):
        from tools.test_upstream_321_merge import runtime_functions
        namespace = dict(
            Press=Mock(), Sleep=Mock(), ScreenShot=lambda: 'frame',
            CheckIf=lambda screen, name, *args: [1, 2] if name == 'fishing/nobaitinbag' else None,
            logger=Mock(), RestartableSequenceExecution=lambda *ops: [op() for op in ops],
            FindCoordsOrElseExecuteFallbackAndWait=lambda *args: [1, 2],
            StateDungeon=lambda *args: None, TargetInfo=script.TargetInfo,
            StopTaskWithError=Mock(side_effect=RuntimeError('no bait')), _=lambda s: s,
        )
        def stop_with_error(detail, phase, screen):
            raise RuntimeError('no bait')
        namespace['StopTaskWithError'] = Mock(side_effect=stop_with_error)
        runtime_functions(['refillBait'], namespace)
        with self.assertRaisesRegex(RuntimeError, 'no bait'):
            namespace['refillBait']()
        namespace['StopTaskWithError'].assert_called_once()
        self.assertNotIn(None, [call.args[0] for call in namespace['Press'].call_args_list])

    def test_stop_wins_over_handoff_and_stale_events(self):
        for stop in ('local', 'remote', 'round', 'stale-run', 'stale-generation'):
            with self.subTest(stop=stop):
                c = make_controller()
                r = make_runtime(c.msg_queue)
                c._active_runtime = r
                r.worker_generation = 3
                r.request_handoff('fishing')
                c._active_latch = worker.TaskCompletionLatch(c.msg_queue, r.run_id)
                payload = dict(run_id=r.run_id, worker_generation=3, target='fishing')
                if stop == 'local':
                    r.worker_force_stop_event.set()
                elif stop == 'remote':
                    r.request_stop(None, 0, None)
                elif stop == 'round':
                    r.stop_after_run_event.set()
                elif stop == 'stale-run':
                    payload['run_id'] = 'previous'
                else:
                    payload['worker_generation'] = 2
                with patch.object(c, '_start_task') as start_task:
                    c._handle_handoff(payload)
                    for callback in list(c.pending):
                        callback()
                    start_task.assert_not_called()

    def test_handoff_wait_is_bounded_and_never_overlaps_workers(self):
        c = make_controller()
        r = make_runtime(c.msg_queue)
        r.worker_generation = 1
        r.request_handoff('fishing')
        c._active_runtime = r
        c._active_latch = worker.TaskCompletionLatch(c.msg_queue, r.run_id)
        c.quest_threading = Mock(is_alive=Mock(return_value=True))
        now = [0.0]
        c._clock = lambda: now[0]
        with patch.object(c, '_start_task') as start_task:
            c._handle_handoff(dict(run_id=r.run_id, worker_generation=1, target='fishing'))
            c.pending.pop(0)()
            start_task.assert_not_called()
            now[0] = 15.1
            c.pending.pop(0)()
            start_task.assert_not_called()
        self.assertEqual(r.exit_reason, main.TaskExitReason.ERROR)
        self.assertEqual(r.failure_phase, 'handoff_worker_timeout')
        self.assertTrue(r.worker_force_stop_event.is_set())

    def test_handoff_chain_completes_once(self):
        c = make_controller()
        targets = ['7000G', 'fishing', 'FFXI-Org', 'shiphold-fairy']
        for target in targets:
            self.assertIn(target, main.QUEST_DATA)
        calls, old_callbacks = [], []

        def farm(setting):
            r = setting._REMOTE_RUNTIME
            calls.append((setting.FARM_TARGET, id(setting), r.run_id, r.worker_generation))
            # A real Farm replaces its adapter when entering the new task.
            r.register_adapter(object(), setting._REMOTE_HANDOFF_TARGET)
            old_callbacks.append(setting._FINISHINGCALLBACK)
            i = targets.index(setting.FARM_TARGET)
            if i < len(targets) - 1:
                request_task_handoff(r, c.msg_queue, target=targets[i + 1], event_name='switch_quest')
                setting._FINISHINGCALLBACK()  # must not consume the final latch
                raise SystemExit
            for callback in old_callbacks[:-1]:
                callback()  # stale same-run callbacks must not finish the UI

        def setting(target):
            return SimpleNamespace(FARM_TARGET=target, FARM_TARGET_TEXT=target,
                                   LANGUAGE_GAME='en_US', TELEGRAM_ENABLED=False)

        with patch.object(main, 'Factory', return_value=farm), patch.object(main, 'ValidateQuestResources', return_value=[]), patch.object(
            main, 'load_farm_setting_for_target', side_effect=lambda path, target, *_: setting(target)
        ):
            self.assertTrue(c._start_task(setting(targets[0]), main.StartReason.LOCAL, '', None))
            pump(c)
        self.assertEqual([call[0] for call in calls], targets)
        self.assertEqual(len({call[1] for call in calls}), 4)
        self.assertEqual(len({call[2] for call in calls}), 1)
        self.assertEqual([call[3] for call in calls], [1, 2, 3, 4])
        finished = [call for call in c.remote_feature.handle_event.call_args_list if call.args[0] == 'task_finished']
        self.assertEqual(len(finished), 1)
        self.assertFalse(c._task_is_alive())

    def test_stop_after_current_round_is_run_scoped(self):
        r = make_runtime()
        self.assertFalse(r.worker_force_stop_event.is_set())
        r.stop_after_run_event.set()
        r.stop_after_run_event.clear()
        self.assertFalse(r.finish_round())
        self.assertFalse(r.worker_force_stop_event.is_set())
        r.stop_after_run_event.set()
        self.assertTrue(r.finish_round())
        self.assertTrue(r.worker_force_stop_event.is_set())
        self.assertEqual(r.exit_reason, main.TaskExitReason.LOCAL_STOP)
        self.assertFalse(make_runtime().stop_after_run_event.is_set())

    def test_stale_completion_does_not_consume_latch(self):
        r = make_runtime()
        r.worker_generation = 2
        latch = worker.TaskCompletionLatch(r.event_queue, r.run_id)
        old = worker.make_worker_completion_callback(r, latch, 1)
        self.assertFalse(old())
        self.assertFalse(latch.called)
        r.request_handoff('fishing')
        self.assertFalse(worker.make_worker_completion_callback(r, latch, 2)())
        self.assertFalse(latch.called)

    def test_removed_or_missing_resource_target_is_rejected_before_factory(self):
        c = make_controller()
        with patch.object(main, 'Factory') as factory:
            for target in ('DOE', 'jier', 'not-a-quest'):
                self.assertFalse(c._start_task(SimpleNamespace(FARM_TARGET=target), main.StartReason.LOCAL, '', None))
            with patch.object(main, 'ValidateQuestResources', return_value=['missing-floor']):
                self.assertFalse(c._start_task(SimpleNamespace(FARM_TARGET='fishing'), main.StartReason.LOCAL, '', None))
            factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
