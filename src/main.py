"""Application controller and Telegram remote-control integration."""

from __future__ import annotations

import argparse
import heapq
import itertools
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ``python src/main.py`` puts only ``src`` on sys.path.  The optional remote
# module lives at the repository root, so make the project root importable
# before gui.py imports script.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform.startswith("win"):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

def parse_args():
    parser = argparse.ArgumentParser(description="WvDAS controller")
    parser.add_argument("-headless", "--headless", action="store_true")
    parser.add_argument("-config", "--config", type=str, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    startup_args = parse_args()
    if startup_args.config:
        # GUI and script modules copy LANGUAGE at import time.
        import utils
        utils.LANGUAGE = utils.GetOneVarInGeneralConfig("LANGUAGE_SCRIPT", utils.GetOneVarInGeneralConfig("LANGUAGE", "ko_KR", startup_args.config), startup_args.config)
        utils.LANGUAGE_SCRIPT = utils.LANGUAGE
        utils.LANGUAGE_GAME = utils.GetOneVarInGeneralConfig('LANGUAGE_GAME', 'en_US', startup_args.config)
        utils.trans = utils.gettext.translation("messages", utils.localedir, languages=[utils.LANGUAGE], fallback=True)
        utils.trans.install()

from script import *
from utils import *
from config_model import *
from auto_updater import AutoUpdater


def ConfigPanelApp(*args):
    from gui import ConfigPanelApp as WebPanel
    return WebPanel(*args)

from mod.telegram_remote_control.adapters import ControllerPorts
from mod.telegram_remote_control.config import (
    load_latest_farm_setting,
    load_farm_setting_for_target,
    resolve_adb_executable,
)
from mod.telegram_remote_control.constants import (
    CONTROLLER_TICK_MILLISECONDS,
    HANDOFF_TARGET_7000G,
    MAX_EVENTS_PER_TICK,
    WORKER_EXIT_TIMEOUT_SECONDS,
    SERVICE_THREAD_JOIN_TIMEOUT_SECONDS,
)
from mod.telegram_remote_control.feature import TelegramRemoteFeature
from mod.telegram_remote_control.models import (
    ConnectionTestResult,
    QuestTarget,
    StartReason,
    TaskExitReason,
    TaskFinishedPayload,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime
from mod.telegram_remote_control.worker import TaskCompletionLatch, run_farm_worker, make_worker_completion_callback


__version__ = '3.2.1-momo.1'
OWNER = "momo31"
REPO = "wvd"


class AppController:
    """Serialize all app mutations on one owner thread; WebView owns the main thread."""

    def __init__(self, headless: bool, config_path: str | None):
        self.headless = bool(headless)
        self.config_path = config_path
        self.msg_queue = queue.Queue()
        self.main_window = None
        self.quest_threading = None
        self.quest_setting = None
        self._active_runtime = None
        self._active_latch = None
        self._completion_enqueued = set()
        self._handoff_waiting = set()
        self._ui_finished = set()
        self._closing = False
        self._clock = time.monotonic
        self._force_exit = os._exit
        self._owner_ident = None
        self._scheduled = []
        self._schedule_lock = threading.Lock()
        self._schedule_sequence = itertools.count()
        self._wake = threading.Event()
        self._shutdown_done = threading.Event()
        self._shutdown_started = None
        self._service_stop_thread = None
        self._log_stop_thread = None
        self._logging_started = False
        self._aux_stop_event = threading.Event()
        self._download_thread = None
        self._update_check_thread = None
        self._restart_script = None
        self.exit_code = 0
        ports = ControllerPorts(
            load_raw_config=lambda path: LoadRawConfigFromFile(path),
            load_latest_setting=self._load_latest_setting,
            start_task=self._start_task,
            task_is_alive=self._task_is_alive,
            sync_ui_state=self._sync_remote_ui,
            schedule_after=self.schedule_after,
            show_test_result=self._show_connection_test_result,
            reboot_emulator=self._reboot_emulator,
            list_quest_targets=self._list_quest_targets,
            select_quest_target=self._select_quest_target,
        )
        self.remote_feature = TelegramRemoteFeature(self.msg_queue, config_path, ports, logger, LANGUAGE)
        self.is_checking_for_update = False
        self.update_downloading = False
        self.updater = AutoUpdater(msg_queue=self.msg_queue, github_user=OWNER, github_repo=REPO, current_version=__version__)
        self.updater.protected_paths = [self.config_path or CONFIG_FILE]

    def run_in_thread(self, target_func, *args):
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()
        return thread

    def schedule_after(self, delay_ms, callback):
        with self._schedule_lock:
            if self._closing:
                return
            heapq.heappush(self._scheduled, (self._clock() + max(0, delay_ms) / 1000, next(self._schedule_sequence), callback))
        self._wake.set()

    def _push_event(self, event):
        if self.main_window is not None:
            self.main_window.push_event(event)

    def schedule_periodic_update_check(self):
        if self._closing:
            return
        if not self.is_checking_for_update:
            self.is_checking_for_update = True

            def check():
                try:
                    self.updater.check_for_updates()
                finally:
                    self.is_checking_for_update = False

            self._update_check_thread = self.run_in_thread(check)
        self.schedule_after(3600000, self.schedule_periodic_update_check)


    def _load_latest_setting(self):
        return load_latest_farm_setting(
            self.config_path,
            lambda path: LoadRawConfigFromFile(path),
            LoadSettingFromDict,
        )

    def _list_quest_targets(self):
        return [
            QuestTarget(str(code), trans_cat(category), trans_tgt(name))
            for category, targets in DUNGEON_TARGETS.items()
            for name, code in targets.items()
        ]

    def _select_quest_target(self, quest_code: str) -> bool:
        selected = next(
            (
                (category, name)
                for category, targets in DUNGEON_TARGETS.items()
                for name, code in targets.items()
                if str(code) == str(quest_code)
            ),
            None,
        )
        if selected is None:
            return False
        category, name = selected
        category_display = trans_cat(category)
        target_display = trans_tgt(name)
        stored_name = (
            REVERSE_TARGET_MAP.get(target_display, target_display)
            if LANGUAGE == "ko_KR"
            else target_display
        )
        config_path = self.config_path or CONFIG_FILE
        raw = LoadRawConfigFromFile(config_path) or {}
        general = raw.get("GENERAL")
        if not isinstance(general, dict):
            return False
        general.update(
            {
                "FARM_TARGET": str(quest_code),
                "FARM_TARGET_TEXT": stored_name,
                "TASK_SPECIFIC_CONFIG": False,
            }
        )
        if not SaveConfigToFile(raw, config_path):
            return False
        if self.main_window is not None:
            return bool(
                self.main_window.select_farm_target_from_remote(
                    category_display,
                    target_display,
                )
            )
        return True

    def _task_is_alive(self) -> bool:
        return bool(self.quest_threading is not None and self.quest_threading.is_alive())

    def _new_local_runtime(self, setting):
        run_id = uuid.uuid4().hex
        worker_event = threading.Event()
        target = str(getattr(setting, "FARM_TARGET_TEXT", None) or getattr(setting, "FARM_TARGET", ""))
        return RemoteRuntime(
            run_id=run_id,
            start_reason=StartReason.LOCAL,
            farm_target_text=target,
            event_queue=self.msg_queue,
            worker_force_stop_event=worker_event,
            adb_executable=resolve_adb_executable(getattr(setting, "EMU_PATH", None)),
            adb_address=str(getattr(setting, "ADB_ADRESS", "")),
            started_at=datetime.now(timezone.utc),
            started_monotonic=time.monotonic(),
        )

    def _start_task(self, setting, start_reason, run_id, runtime) -> bool:
        if self._closing or self._task_is_alive() or getattr(
            getattr(self, "remote_feature", None),
            "emulator_reboot_in_progress",
            False,
        ):
            return False
        saved_target = str(getattr(setting, 'FARM_TARGET', ''))
        target = QUEST_CODE_ALIASES.get(saved_target, saved_target)
        language = getattr(setting, 'LANGUAGE_GAME', 'en_US')
        missing = ValidateQuestResources(target, language)
        if getattr(setting, 'TELEGRAM_ENABLED', False) or StartReason(start_reason) is StartReason.TELEGRAM:
            missing += ValidateRemoteResources(language)
        if missing:
            logger.error('Task cannot start; unavailable target/resources: %s', ', '.join(missing))
            self._push_event({'type': 'start_rejected', 'missing': missing})
            if runtime is not None:
                runtime.mark_exit(TaskExitReason.ERROR, '작업에 필요한 리소스가 없습니다.', 'task_resources')
            return False
        setting.FARM_TARGET = target
        # A headless/custom-config start has the same image-language contract as the GUI.
        import utils, script
        utils.LANGUAGE_GAME = script.LANGUAGE_GAME = language
        utils.DIALOG_OPTION_IMAGE_LIST = utils.reflectImage('dialogueChoices', language)
        script.DIALOG_OPTION_IMAGE_LIST = utils.DIALOG_OPTION_IMAGE_LIST
        if runtime is None:
            runtime = self._new_local_runtime(setting)
            run_id = runtime.run_id
        handoff = (
            self._active_runtime is runtime
            and runtime.is_handoff_requested()
        )
        if runtime is not self._active_runtime:
            self._active_runtime = runtime
            self._active_latch = TaskCompletionLatch(self.msg_queue, run_id)
            self._completion_enqueued.discard(run_id)

        setting._MSGQUEUE = self.msg_queue
        setting._FORCESTOPING = runtime.worker_force_stop_event
        setting._REMOTE_RUNTIME = runtime
        setting._START_REASON = StartReason(start_reason)
        setting._TASK_RUN_ID = runtime.run_id
        setting._REMOTE_HANDOFF_TARGET = runtime.handoff_target if handoff else None
        generation = runtime.begin_worker()
        setting._WORKER_GENERATION = generation

        callback = getattr(setting, "_FINISHINGCALLBACK", None)
        latch = self._active_latch
        guarded_complete = make_worker_completion_callback(runtime, latch, generation)

        def completion_callback():
            if not guarded_complete():
                return False
            if callback is not None:
                try:
                    callback()
                except Exception:
                    logger.exception("legacy completion callback failed")
            return True

        setting._FINISHINGCALLBACK = completion_callback
        farm = Factory()
        self.quest_setting = setting
        self.quest_threading = threading.Thread(
            target=run_farm_worker,
            args=(farm, setting, runtime, latch, logger),
            daemon=True,
            name=f"farm-worker-{runtime.run_id[:8]}-{generation}",
        )
        try:
            self.quest_threading.start()
        except Exception as exc:
            runtime.mark_exit(TaskExitReason.ERROR, "작업 스레드를 시작하지 못했습니다.", "thread_start")
            latch.callback()
            logger.exception("farm worker thread failed to start")
            return False
        if not handoff:
            self.remote_feature.on_task_started(runtime)
        runtime.update_farm_target(getattr(setting, 'FARM_TARGET_TEXT', '') or target)
        self._push_event({'type': 'task_started', 'target': target, 'run_id': runtime.run_id})
        return True

    def _request_local_stop(self):
        if self._active_runtime is not None:
            self._active_runtime.worker_force_stop_event.set()
        if self.quest_setting is not None:
            event = getattr(self.quest_setting, "_FORCESTOPING", None)
            if event is not None:
                event.set()

    def _reboot_emulator(self) -> bool:
        if self._aux_stop_event.is_set():
            return False
        worker = self.quest_threading
        if worker is not None and worker.is_alive():
            self._request_local_stop()
        runtime = getattr(self, "_active_runtime", None)
        if runtime is not None and runtime.clear_handoff():
            runtime.mark_exit(TaskExitReason.LOCAL_STOP, "에뮬레이터 재부팅으로 작업이 중지되었습니다.")
            latch = getattr(self, "_active_latch", None)
            if latch is not None:
                latch.callback()
        if worker is not None and worker.is_alive():
            worker.join(10)
            if worker.is_alive():
                return False
        if self._aux_stop_event.is_set():
            return False
        setting = self._load_latest_setting()
        setting._FORCESTOPING = self._aux_stop_event
        if self._aux_stop_event.is_set():
            return False
        setting._ADBDEVICE = CheckAndRecoverDevice(
            setting,
            RuntimeContext(),
            FORCE_RESTART_EMU=True,
        )
        return setting._ADBDEVICE is not None

    def _handle_task_completion_requested(self, run_id: str):
        run_id = str(run_id)
        runtime = self._active_runtime
        if runtime is None or runtime.run_id != run_id:
            return
        if self._task_is_alive():
            self.schedule_after(50, lambda: self._handle_task_completion_requested(run_id))
            return
        if run_id in self._completion_enqueued:
            return
        self._completion_enqueued.add(run_id)
        if runtime.exit_reason is None:
            runtime.mark_exit(TaskExitReason.COMPLETED, "작업이 완료되었습니다.")
        self.msg_queue.put(("task_finished", runtime.build_finished_payload()))

    def _handle_handoff(self, value):
        runtime = self._active_runtime
        if self._closing or runtime is None or not isinstance(value, dict):
            return
        run_id = value.get('run_id')
        generation = value.get('worker_generation')
        target = value.get('target')
        if (runtime.run_id != run_id or runtime.worker_generation != generation
                or not runtime.is_handoff_requested(target)):
            return
        key = (run_id, generation)
        if key in self._handoff_waiting:
            return
        self._handoff_waiting.add(key)
        deadline = self._clock() + WORKER_EXIT_TIMEOUT_SECONDS

        def wait_for_worker():
            if (self._closing or self._active_runtime is not runtime
                    or runtime.worker_generation != generation):
                self._handoff_waiting.discard(key)
                return
            if self._task_is_alive():
                if self._clock() >= deadline:
                    self._handoff_waiting.discard(key)
                    runtime.worker_force_stop_event.set()
                    runtime.clear_handoff()
                    runtime.mark_exit(TaskExitReason.ERROR, '이전 작업이 종료되지 않았습니다.', 'handoff_worker_timeout')
                    self._active_latch.callback()
                    return
                self.schedule_after(50, wait_for_worker)
                return
            self._handoff_waiting.discard(key)
            if not runtime.is_handoff_requested(target):
                return
            runtime.finish_round()
            if runtime.worker_force_stop_event.is_set() or runtime.exit_reason is not None:
                runtime.clear_handoff()
                runtime.mark_exit(TaskExitReason.LOCAL_STOP, '작업이 중지되었습니다.')
                self._active_latch.callback()
                return
            if runtime.is_stop_requested():
                runtime.clear_handoff()
                self._finish_handoff_stop(runtime)
                return
            try:
                setting = load_farm_setting_for_target(
                    self.config_path, target,
                    lambda path: LoadRawConfigFromFile(path, migrate_recovery=False),
                    LoadSettingFromDict,
                )
                setting.FARM_TARGET_TEXT = next((q.display_name for q in self._list_quest_targets() if q.code == target), target)
                if self._start_task(setting, runtime.start_reason, run_id, runtime):
                    return
                phase = 'handoff_start_rejected'
            except Exception:
                logger.exception('handoff setting load failed')
                phase = 'handoff_setting'
            runtime.clear_handoff()
            runtime.mark_exit(TaskExitReason.ERROR, '후속 작업을 시작하지 못했습니다.', phase)
            self._active_latch.callback()

        self.schedule_after(0, wait_for_worker)

    def _finish_handoff_stop(self, runtime):
        """Finish remote return when the previous Farm exited just before /stop."""
        from mod.telegram_remote_control.models import CheckpointKind, RemoteStopSignal
        from mod.telegram_remote_control.stop_orchestrator import execute_remote_stop
        complete = make_worker_completion_callback(runtime, self._active_latch, runtime.worker_generation)

        def finish():
            try:
                if runtime.adapter is None:
                    runtime.mark_exit(TaskExitReason.ERROR, '정지 전환에 필요한 장치가 없습니다.', 'stop_adapter_missing')
                else:
                    execute_remote_stop(runtime.adapter, runtime, RemoteStopSignal(CheckpointKind.BETWEEN_OPERATIONS))
            except Exception:
                runtime.mark_exit(TaskExitReason.ERROR, '정지 전환에 실패했습니다.', 'handoff_stop')
                logger.exception('handoff stop failed')
            finally:
                complete()

        self.quest_threading = threading.Thread(target=finish, name='handoff-stop', daemon=True)
        self.quest_threading.start()

    def _sync_remote_ui(self, state):
        if self.main_window is None:
            return
        callback = getattr(self.main_window, "apply_remote_control_state", None)
        if callback is not None:
            callback(state)

    def _show_connection_test_result(self, result):
        if self.main_window is not None:
            self.main_window.show_connection_test_result(result)

    def _dispatch(self, command, value):
        if command == 'ui_request':
            name, data, reply, cancelled = value
            if cancelled.is_set():
                return
            try:
                result = self._dispatch(name, data)
            except Exception:
                logger.exception('UI request failed: %s', name)
                result = {'ok': False, 'error': 'request_failed'}
            reply.put(result if isinstance(result, dict) else {'ok': True})
            return
        if command == 'close_window':
            self._begin_shutdown()
            return {'ok': True}
        if self._closing and command not in ('download_finished', 'task_completion_requested', 'task_finished'):
            return {'ok': False, 'error': 'closing'}
        if command == 'task_finished':
            runtime = self._active_runtime
            if runtime is None or value.run_id != runtime.run_id or value.run_id in self._ui_finished:
                return
            self._ui_finished.add(value.run_id)
            self._push_event({'type': 'task_finished', 'reason': value.reason.value, 'detail': value.detail})
        if self.remote_feature.handle_event(command, value):
            return {'ok': True}
        if command == 'task_completion_requested':
            self._handle_task_completion_requested(value)
        elif command == 'start_quest':
            try:
                setting = value if value is not None else self._load_latest_setting()
                started = self._start_task(setting, StartReason.LOCAL, '', None)
            except Exception:
                logger.exception('task settings are unavailable')
                started = False
            if not started:
                self._push_event({'type': 'start_rejected'})
                if self.headless and self._active_runtime is None:
                    self.exit_code = 1
                    self._begin_shutdown()
            return {'ok': started}
        elif command == 'stop_quest':
            self._request_local_stop()
            self._push_event({'type': 'local_stopping'})
        elif command == 'set_stop_after':
            runtime = self._active_runtime
            if runtime is None or runtime.exit_reason is not None:
                return {'ok': False, 'error': 'not_running'}
            (runtime.stop_after_run_event.set if value else runtime.stop_after_run_event.clear)()
            self._push_event({'type': 'stop_after', 'enabled': bool(value)})
        elif command in ('switch_quest', 'turn_to_7000G'):
            self._handle_handoff(value)
        elif command == 'update_available':
            self._show_update(value)
        elif command == 'update_manual':
            self._push_event({'type': 'update_manual', 'url': 'https://github.com/momo31/wvd/releases'})
        elif command == 'download_update':
            return {'ok': self._start_update_download()}
        elif command == 'cancel_update':
            self.updater.cancel_event.set()
        elif command in ('download_started', 'progress'):
            if not self.updater.cancel_event.is_set():
                self._push_event({'type': command, 'value': value})
        elif command == 'download_finished':
            self.update_downloading = False
            self._push_event({'type': 'download_finished'})
        elif command == 'error':
            if not self.updater.cancel_event.is_set():
                self._push_event({'type': 'error', 'message': str(value)})
        elif command == 'restart_ready':
            if (self.update_downloading and not self.updater.cancel_event.is_set()
                    and getattr(sys, 'frozen', False) and value == self.updater.restart_script
                    and isinstance(value, str) and os.path.isfile(value)):
                self._restart_script = value
                self._begin_shutdown()
        elif command in ('web_action', 'save_settings', 'save_telegram', 'set_language', 'test_connection', 'select_target'):
            if self.main_window is None:
                return {'ok': False, 'error': 'no_window'}
            return self.main_window.handle_request(command, value)
        return {'ok': True}

    def _show_update(self, update_data):
        self._push_event({'type': 'update_available', 'data': update_data})

    def _start_update_download(self):
        if self._closing or self.update_downloading:
            return False
        if not self.updater.can_download():
            self._push_event({'type': 'update_manual', 'url': 'https://github.com/momo31/wvd/releases'})
            return False
        self.update_downloading = True
        self.updater.cancel_event.clear()
        self._download_thread = self.run_in_thread(self.updater.download)
        self._push_event({'type': 'download_pending'})
        return True

    def check_queue(self):
        self.process_once()


    def call_on_owner(self, command, value=None, timeout=5):
        if threading.get_ident() == self._owner_ident:
            return self._dispatch(command, value)
        if self._closing:
            return {'ok': False, 'error': 'closing'}
        reply = queue.Queue(maxsize=1)
        cancelled = threading.Event()
        self.msg_queue.put(('ui_request', (command, value, reply, cancelled)))
        self._wake.set()
        try:
            return reply.get(timeout=timeout)
        except queue.Empty:
            cancelled.set()
            return {'ok': False, 'error': 'controller_timeout'}

    def process_once(self):
        for _ in range(MAX_EVENTS_PER_TICK):
            try:
                command, value = self.msg_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch(command, value)
            except Exception:
                logger.exception('controller event failed: %s', command)
                self._push_event({'type': 'error', 'message': _('The request could not be completed.')})
        if self._closing:
            self._poll_shutdown()
            return
        while True:
            with self._schedule_lock:
                if not self._scheduled or self._scheduled[0][0] > self._clock():
                    break
                _, _, callback = heapq.heappop(self._scheduled)
            try:
                callback()
            except Exception:
                logger.exception('scheduled controller callback failed')
            if self._closing:
                return
        self.remote_feature.tick()

    def request_shutdown(self):
        self.msg_queue.put(('close_window', None))
        self._wake.set()

    def _begin_shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._shutdown_started = self._clock()
        with self._schedule_lock:
            self._scheduled.clear()
        self._request_local_stop()
        self._aux_stop_event.set()
        self.updater.cancel_event.set()
        self._push_event({'type': 'closing'})
        self._service_stop_thread = self.run_in_thread(self.remote_feature.stop)

    def _poll_shutdown(self):
        if self._shutdown_done.is_set() or self._shutdown_started is None:
            return
        elapsed = self._clock() - self._shutdown_started
        alive = lambda thread: thread is not None and thread.is_alive()
        worker_alive = alive(self.quest_threading)
        service_alive = alive(self._service_stop_thread)
        download_alive = alive(self._download_thread) or alive(self._update_check_thread)
        log_alive = alive(self._log_stop_thread)
        expired = ((worker_alive and elapsed >= WORKER_EXIT_TIMEOUT_SECONDS)
                   or (service_alive and elapsed >= SERVICE_THREAD_JOIN_TIMEOUT_SECONDS)
                   or elapsed >= 45)
        if expired and (worker_alive or service_alive or download_alive or log_alive):
            logger.error('Shutdown deadline exceeded (worker=%s, service=%s, update=%s, log=%s)', worker_alive, service_alive, download_alive, log_alive)
            self.exit_code = 1
            self._shutdown_done.set()
            self._force_exit(1)
            return
        if worker_alive or service_alive or download_alive:
            return
        # Flush after every producer exits. Disk I/O must not block the owner
        # or bypass its overall 45-second shutdown deadline.
        if self._logging_started and self._log_stop_thread is None:
            self._log_stop_thread = self.run_in_thread(LOG_LISTENER_MGR.stop)
        if alive(self._log_stop_thread):
            return
        self._shutdown_done.set()
        if self._restart_script is not None:
            script, self._restart_script = self._restart_script, None
            try:
                subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive',
                                  '-ExecutionPolicy', 'Bypass', '-File', script],
                                 cwd=os.path.dirname(script), creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError:
                self.exit_code = 1
                logger.exception('Could not start update helper; manual update is required')
        if self.main_window is not None:
            self.main_window.destroy()

    def _owner_loop(self):
        self._owner_ident = threading.get_ident()
        try:
            if self.headless:
                RegisterConsoleHandler()
            RegisterQueueHandler()
            LOG_LISTENER_MGR.start()
            self._logging_started = True
            self.remote_feature.start()
            if self.headless and not HeadlessActive(self.config_path, self.msg_queue):
                self.exit_code = 1
                self._begin_shutdown()
            self.schedule_periodic_update_check()
            while not self._shutdown_done.is_set():
                self._wake.clear()
                self.process_once()
                self._wake.wait(CONTROLLER_TICK_MILLISECONDS / 1000)
        except BaseException:
            logger.exception('controller loop failed')
            self.exit_code = 1
            self._begin_shutdown()
            while not self._shutdown_done.is_set():
                self._poll_shutdown()
                self._wake.wait(.1)

    def run(self):
        if self.headless:
            self._owner_loop()
            return
        self.main_window = ConfigPanelApp(self, __version__, self.msg_queue)
        owner = threading.Thread(target=self._owner_loop, name='app-controller', daemon=True)
        owner.start()
        try:
            self.main_window.run()
        finally:
            self.request_shutdown()
            owner.join(46)
            if owner.is_alive():
                self._force_exit(1)


def _load_headless_setting(config_path):
    return load_latest_farm_setting(
        config_path,
        lambda path: LoadRawConfigFromFile(path),
        LoadSettingFromDict,
    )


def HeadlessActive(config_path, msg_queue):
    try:
        setting = _load_headless_setting(config_path)
    except Exception as exc:
        logger.error("headless macro settings are unavailable: %s", type(exc).__name__)
        return False
    msg_queue.put(("start_quest", setting))
    logger.info("WvDAS headless mode started: v%s", __version__)
    return True


def main(args=None):
    if args is None:
        args = parse_args()
    controller = AppController(args.headless, args.config)
    try:
        controller.run()
    finally:
        LOG_LISTENER_MGR.stop()
    return controller.exit_code


if __name__ == "__main__":
    raise SystemExit(main(startup_args))
