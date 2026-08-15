"""Application controller and Telegram remote-control integration."""

from __future__ import annotations

import argparse
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

from gui import *  # noqa: F401,F403 - legacy GUI exports are part of this entrypoint

from mod.telegram_remote_control.adapters import ControllerPorts
from mod.telegram_remote_control.config import (
    load_latest_farm_setting,
    resolve_adb_executable,
)
from mod.telegram_remote_control.constants import (
    CONTROLLER_TICK_MILLISECONDS,
    HANDOFF_TARGET_7000G,
    MAX_EVENTS_PER_TICK,
)
from mod.telegram_remote_control.feature import TelegramRemoteFeature
from mod.telegram_remote_control.models import (
    ConnectionTestResult,
    StartReason,
    TaskExitReason,
    TaskFinishedPayload,
)
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime
from mod.telegram_remote_control.worker import TaskCompletionLatch, run_farm_worker


__version__ = '2.5.4-momo.6'
OWNER = "arnold2957"
REPO = "wvd"


class AppController(tk.Tk):
    """Own the Tk event loop, legacy worker, and remote feature boundary."""

    def __init__(self, headless: bool, config_path: str | None):
        super().__init__()
        self.withdraw()
        self.headless = bool(headless)
        self.config_path = config_path
        self.msg_queue = queue.Queue()
        self.main_window = None
        self.quest_threading = None
        self.quest_setting = None
        self._active_runtime: RemoteRuntime | None = None
        self._active_latch: TaskCompletionLatch | None = None
        self._completion_enqueued: set[str] = set()
        self._handoff_waiting: set[str] = set()

        if not self.headless:
            self.main_window = ConfigPanelApp(self, __version__, self.msg_queue)

        ports = ControllerPorts(
            load_raw_config=lambda path: LoadRawConfigFromFile(path),
            load_latest_setting=self._load_latest_setting,
            start_task=self._start_task,
            task_is_alive=self._task_is_alive,
            sync_ui_state=self._sync_remote_ui,
            schedule_after=lambda delay, callback: self.after(delay, callback),
            show_test_result=self._show_connection_test_result,
        )
        self.remote_feature = TelegramRemoteFeature(
            self.msg_queue,
            config_path,
            ports,
            logger,
            LANGUAGE,
        )
        self.remote_feature.start()

        if self.headless:
            HeadlessActive(config_path, self.msg_queue)

        self.is_checking_for_update = False
        self.updater = AutoUpdater(
            msg_queue=self.msg_queue,
            github_user=OWNER,
            github_repo=REPO,
            current_version=__version__,
        )
        self.schedule_periodic_update_check()
        self.after(CONTROLLER_TICK_MILLISECONDS, self._remote_tick)
        self.check_queue()

    def run_in_thread(self, target_func, *args):
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()
        return thread

    def schedule_periodic_update_check(self):
        if not self.is_checking_for_update:
            self.is_checking_for_update = True

            def check():
                try:
                    self.updater.check_for_updates()
                finally:
                    self.is_checking_for_update = False

            self.run_in_thread(check)
        self.after(3600000, self.schedule_periodic_update_check)

    def _remote_tick(self):
        try:
            self.remote_feature.tick()
        finally:
            self.after(CONTROLLER_TICK_MILLISECONDS, self._remote_tick)

    def _load_latest_setting(self):
        return load_latest_farm_setting(
            self.config_path,
            lambda path: LoadRawConfigFromFile(path),
            LoadSettingFromDict,
        )

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
        if self._task_is_alive():
            return False
        if runtime is None:
            runtime = self._new_local_runtime(setting)
            run_id = runtime.run_id
        handoff = (
            self._active_runtime is runtime
            and runtime.is_handoff_requested(HANDOFF_TARGET_7000G)
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

        callback = getattr(setting, "_FINISHINGCALLBACK", None)
        latch = self._active_latch

        def completion_callback():
            if callback is not None:
                try:
                    callback()
                except Exception:
                    logger.exception("legacy completion callback failed")
            if latch is not None:
                latch.callback()

        setting._FINISHINGCALLBACK = completion_callback
        farm = Factory()
        self.quest_setting = setting
        self.quest_threading = threading.Thread(
            target=run_farm_worker,
            args=(farm, setting, runtime, latch, logger),
            daemon=True,
            name=f"farm-worker-{runtime.run_id[:8]}",
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
        return True

    def _request_local_stop(self):
        if self.quest_setting is not None:
            event = getattr(self.quest_setting, "_FORCESTOPING", None)
            if event is not None:
                event.set()

    def _handle_task_completion_requested(self, run_id: str):
        run_id = str(run_id)
        runtime = self._active_runtime
        if runtime is None or runtime.run_id != run_id:
            return
        if self._task_is_alive():
            self.after(50, lambda: self._handle_task_completion_requested(run_id))
            return
        if run_id in self._completion_enqueued:
            return
        self._completion_enqueued.add(run_id)
        if runtime.exit_reason is None:
            runtime.mark_exit(TaskExitReason.COMPLETED, "작업이 완료되었습니다.")
        self.msg_queue.put(("task_finished", runtime.build_finished_payload()))

    def _handle_handoff(self, value):
        runtime = self._active_runtime
        run_id = str(value or (runtime.run_id if runtime else ""))
        if runtime is None or runtime.run_id != run_id:
            return
        if not runtime.is_handoff_requested(HANDOFF_TARGET_7000G):
            return
        if run_id in self._handoff_waiting:
            return
        self._handoff_waiting.add(run_id)

        def wait_for_worker():
            if self._task_is_alive():
                self.after(50, wait_for_worker)
                return
            self._handoff_waiting.discard(run_id)
            if self._active_runtime is not runtime or not runtime.is_handoff_requested(HANDOFF_TARGET_7000G):
                return
            setting = self.quest_setting
            if setting is None:
                runtime.mark_exit(TaskExitReason.ERROR, "인계할 작업 설정이 없습니다.", "handoff_setting_missing")
                self._handle_task_completion_requested(run_id)
                return
            setting.FARM_TARGET = HANDOFF_TARGET_7000G
            setting.FARM_TARGET_TEXT = HANDOFF_TARGET_7000G
            setting._COUNTERDUNG = 0
            self._start_task(setting, runtime.start_reason, run_id, runtime)
            if self.main_window:
                self.main_window.turn_to_7000G()

        self.after(0, wait_for_worker)

    def _sync_remote_ui(self, state):
        if self.main_window is None:
            return
        callback = getattr(self.main_window, "apply_remote_control_state", None)
        if callback is not None:
            callback(state)

    def _show_connection_test_result(self, result: ConnectionTestResult):
        if self.main_window is None:
            return
        if result.succeeded:
            messagebox.showinfo("Telegram", result.public_message, parent=self.main_window)
        else:
            messagebox.showerror("Telegram", result.public_message, parent=self.main_window)

    def _dispatch(self, command, value):
        if self.remote_feature.handle_event(command, value):
            return
        if command == "task_completion_requested":
            self._handle_task_completion_requested(value)
            return
        if command == "start_quest":
            self._start_task(value, StartReason.LOCAL, "", None)
            return
        if command == "stop_quest":
            self._request_local_stop()
            return
        if command == "quest_finished":
            if self.main_window:
                self.main_window.real_finishingcallback()
            return
        if command == "turn_to_7000G":
            self._handle_handoff(value)
            return
        if command == "update_available":
            self._show_update(value)
            return
        if command == "download_started":
            if not hasattr(self, "progress_window") or not self.progress_window.winfo_exists():
                self.progress_window = Progressbar(self.main_window, title="다운로드 중...", max_size=value)
            return
        if command == "progress":
            if hasattr(self, "progress_window") and self.progress_window.winfo_exists():
                self.progress_window.update_progress(value)
            return
        if command == "download_complete":
            if hasattr(self, "progress_window") and self.progress_window.winfo_exists():
                self.progress_window.destroy()
            return
        if command == "error":
            if hasattr(self, "progress_window") and self.progress_window.winfo_exists():
                self.progress_window.destroy()
            messagebox.showerror("오류", value, parent=self.main_window)
            return
        if command == "restart_ready":
            script_path = value
            messagebox.showinfo("재시작", "업데이트가 준비되었습니다.", parent=self.main_window)
            if sys.platform == "win32":
                subprocess.Popen([script_path], shell=True)
            else:
                os.system(script_path)
            self.destroy()
            return

    def _show_update(self, update_data):
        if not self.main_window:
            return
        version = update_data["version"]
        for widget in (
            self.main_window.find_update,
            self.main_window.update_text,
            self.main_window.button_auto_download,
            self.main_window.button_manual_download,
            self.main_window.update_sep,
        ):
            widget.grid()
        self.main_window.LATEST_VERSION.set(version)
        self.main_window.button_auto_download.config(command=lambda: self.run_in_thread(self.updater.download))

    def check_queue(self):
        try:
            for _ in range(MAX_EVENTS_PER_TICK):
                command, value = self.msg_queue.get_nowait()
                self._dispatch(command, value)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.check_queue)


def parse_args():
    parser = argparse.ArgumentParser(description="WvDAS controller")
    parser.add_argument("-headless", "--headless", action="store_true")
    parser.add_argument("-config", "--config", type=str, default=None)
    return parser.parse_args()


def _load_headless_setting(config_path):
    return load_latest_farm_setting(
        config_path,
        lambda path: LoadRawConfigFromFile(path),
        LoadSettingFromDict,
    )


def HeadlessActive(config_path, msg_queue):
    RegisterConsoleHandler()
    RegisterQueueHandler()
    LOG_LISTENER_MGR.start()
    try:
        setting = _load_headless_setting(config_path)
    except Exception as exc:
        logger.error("headless macro settings are unavailable: %s", type(exc).__name__)
        return
    msg_queue.put(("start_quest", setting))
    logger.info("WvDAS headless mode started: v%s", __version__)


def main():
    args = parse_args()
    controller = AppController(args.headless, args.config)
    try:
        controller.mainloop()
    finally:
        controller.remote_feature.stop()
        LOG_LISTENER_MGR.stop()


if __name__ == "__main__":
    main()
