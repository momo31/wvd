"""Tk-thread-owned orchestration for Telegram remote control."""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .command_service import COMMAND_MENU_TEXT, TelegramCommandService
from .config import (
    TelegramConfigError,
    clear_telegram_secrets,
    read_telegram_settings,
    resolve_adb_executable,
)
from .constants import (
    CONTROLLER_TICK_MILLISECONDS,
    FALLBACK_WAIT_TIMEOUT_SECONDS,
    HANDOFF_TARGET_7000G,
)
from .fallback import force_stop_game_once
from .i18n import get_translator
from .models import (
    ConnectionTestRequest,
    ControlState,
    EmulatorRebootResult,
    ForceStopResult,
    NotificationPriority,
    OutboundMessage,
    QuestTarget,
    RemoteCommand,
    RemoteProgressPayload,
    ServiceStatus,
    ServiceStatusPayload,
    StartReason,
    StatusSnapshot,
    TaskExitReason,
    TaskFinishedPayload,
    TelegramCallbackPayload,
    TelegramCommandPayload,
    TelegramSettings,
)
from .runtime_bridge import RemoteRuntime
from .recent_logs import (
    TELEGRAM_SAFE_MESSAGE_CHARS,
    fit_tail_text,
    read_recent_log,
    redact_log_text,
)


ALLOWED_TRANSITIONS = {
    ControlState.IDLE: {ControlState.STARTING, ControlState.RUNNING, ControlState.ERROR},
    ControlState.STARTING: {
        ControlState.RUNNING,
        ControlState.STOP_REQUESTED,
        ControlState.ERROR,
        ControlState.IDLE,
    },
    ControlState.RUNNING: {ControlState.STOP_REQUESTED, ControlState.IDLE, ControlState.ERROR},
    ControlState.STOP_REQUESTED: {
        ControlState.RETURNING_TO_TOWN,
        ControlState.RETURNING_TO_TITLE,
        ControlState.AT_TITLE,
        ControlState.GAME_STOPPED_FALLBACK,
        ControlState.ERROR,
        ControlState.IDLE,
    },
    ControlState.RETURNING_TO_TOWN: {
        ControlState.RETURNING_TO_TITLE,
        ControlState.AT_TITLE,
        ControlState.GAME_STOPPED_FALLBACK,
        ControlState.ERROR,
        ControlState.IDLE,
    },
    ControlState.RETURNING_TO_TITLE: {
        ControlState.AT_TITLE,
        ControlState.GAME_STOPPED_FALLBACK,
        ControlState.ERROR,
        ControlState.IDLE,
    },
    # Telegram starts pass through STARTING while a local button start is
    # already running by the time on_task_started() is notified.  Both paths
    # must be legal after any terminal state; otherwise the worker starts but
    # the UI is synchronized from the stale terminal state and keeps showing
    # the Start label.
    ControlState.AT_TITLE: {
        ControlState.STARTING,
        ControlState.RUNNING,
        ControlState.IDLE,
    },
    ControlState.GAME_STOPPED_FALLBACK: {
        ControlState.STARTING,
        ControlState.RUNNING,
        ControlState.IDLE,
    },
    ControlState.ERROR: {
        ControlState.STARTING,
        ControlState.RUNNING,
        ControlState.IDLE,
    },
}

QUEST_SELECTION_STATES = {
    ControlState.IDLE,
    ControlState.AT_TITLE,
    ControlState.GAME_STOPPED_FALLBACK,
    ControlState.ERROR,
}
QUEST_CALLBACK_ROOT = "quest:root"
QUEST_CALLBACK_CATEGORY = "quest:category:"
QUEST_CALLBACK_TARGET = "quest:target:"
PERIODIC_SUMMARY_SECONDS = 3 * 60 * 60


def _quest_callback_token(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


class TelegramRemoteFeature:
    def __init__(self, event_queue, config_path, ports, logger, language):
        self.event_queue = event_queue
        self.config_path = config_path
        self.ports = ports
        self.logger = logger
        self.translate = get_translator(language)
        self.service = TelegramCommandService(event_queue, logger)
        self.state = ControlState.IDLE
        self.current_runtime: RemoteRuntime | None = None
        self.current_settings = TelegramSettings(False, "", "")
        self.last_error: str | None = None
        self.progress_detail = ""
        self.service_status = ServiceStatus.DISABLED
        self._progress_sent: set[tuple[str, ControlState]] = set()
        self._force_results: dict[str, ForceStopResult] = {}
        self._finished_waiting_for_force: dict[str, TaskFinishedPayload] = {}
        self._last_test_request_id: str | None = None
        self._started = False
        self.emulator_reboot_in_progress = False
        self._latest_dungeon_summary = ""
        self._next_summary_at: float | None = None
        self._summary_sequence = 0
        self.log_directory = Path.cwd() / "logs"

    def start(self) -> None:
        try:
            self.current_settings = read_telegram_settings(self.config_path, self.ports.load_raw_config)
            self.service.start(self.current_settings)
            self.service_status = ServiceStatus.CONNECTING if self.current_settings.enabled else ServiceStatus.DISABLED
        except TelegramConfigError as exc:
            self.current_settings = TelegramSettings(False, "", "")
            self.service_status = ServiceStatus.ERROR
            self.last_error = str(exc)
            self._emit_service_error(str(exc))
        self._started = True

    def stop(self) -> None:
        self.service.stop()

    def handle_event(self, command, value) -> bool:
        handlers = {
            "telegram_command": self._handle_telegram_command,
            "telegram_callback": self._handle_telegram_callback,
            "telegram_reconfigure": self._handle_reconfigure,
            "telegram_test_connection": self._handle_test_connection,
            "telegram_test_result": self._handle_test_result,
            "telegram_service_status": self._handle_service_status,
            "remote_progress": self._handle_progress,
            "dungeon_summary": self._handle_dungeon_summary,
            "task_finished": self._handle_task_finished,
            "remote_force_stop_result": self._handle_force_result,
            "emulator_reboot_finished": self._handle_emulator_reboot_finished,
        }
        handler = handlers.get(command)
        if handler is None:
            return False
        handler(value)
        return True

    def on_task_started(self, runtime: RemoteRuntime) -> None:
        self.current_runtime = runtime
        self.last_error = None
        self.progress_detail = ""
        self._latest_dungeon_summary = ""
        self._next_summary_at = runtime.started_monotonic + PERIODIC_SUMMARY_SECONDS
        self._summary_sequence = 0
        target = ControlState.STARTING if runtime.start_reason is StartReason.TELEGRAM else ControlState.RUNNING
        self._transition(target)
        if target is ControlState.RUNNING and runtime.start_reason is StartReason.LOCAL:
            self._send_progress(runtime.run_id, target, "매크로가 실행 중입니다.")
        self._sync_ui()

    def on_task_finished(self, payload: TaskFinishedPayload) -> None:
        if self.current_runtime is not None and payload.run_id != self.current_runtime.run_id:
            return
        force_result = self._force_results.get(payload.run_id)
        if payload.reason is TaskExitReason.REMOTE_STOP_FALLBACK and force_result is None:
            self._finished_waiting_for_force[payload.run_id] = payload
            return
        self._finalize_payload(payload, force_result)

    def tick(self, monotonic_now: float | None = None) -> None:
        now = time.monotonic() if monotonic_now is None else float(monotonic_now)
        self._send_periodic_summary(now)
        runtime = self.current_runtime
        if runtime is None or runtime.stop_deadline_monotonic is None or runtime.exit_reason is not None:
            return
        if now < runtime.stop_deadline_monotonic:
            return
        if not runtime.begin_fallback_dispatch():
            return
        threading.Thread(
            target=force_stop_game_once,
            kwargs={"adapter": runtime.adapter, "runtime": runtime, "failure_phase": "stop_watchdog"},
            name="remote-stop-watchdog",
            daemon=True,
        ).start()

    def _handle_dungeon_summary(self, value) -> None:
        if not isinstance(value, tuple) or len(value) != 2 or self.current_runtime is None:
            return
        run_id, text = value
        if str(run_id) == self.current_runtime.run_id and text:
            self._latest_dungeon_summary = str(text)

    def _send_periodic_summary(self, now: float) -> None:
        runtime = self.current_runtime
        if (
            runtime is None
            or runtime.exit_reason is not None
            or self._next_summary_at is None
            or now < self._next_summary_at
            or not self._latest_dungeon_summary
            or not self.current_settings.enabled
            or not self.current_settings.allowed_chat_id
        ):
            return
        self.service.enqueue(
            OutboundMessage(
                f"periodic-summary:{runtime.run_id}:{self._summary_sequence}",
                self.current_settings.allowed_chat_id,
                self._latest_dungeon_summary,
                NotificationPriority.PROGRESS,
            )
        )
        self._summary_sequence += 1
        self._next_summary_at = now + PERIODIC_SUMMARY_SECONDS

    def status_snapshot(self) -> StatusSnapshot:
        runtime = self.current_runtime
        return StatusSnapshot(
            state=self.state,
            run_id=runtime.run_id if runtime else None,
            farm_target_text=runtime.farm_target_text if runtime else None,
            started_at=runtime.started_at if runtime else None,
            stop_requested_at=runtime.stop_requested_at if runtime else None,
            last_error=self.last_error,
        )

    def _handle_telegram_command(self, payload: TelegramCommandPayload) -> None:
        if not isinstance(payload, TelegramCommandPayload):
            return
        if payload.service_generation != self.service.generation:
            return
        if payload.chat_id != self.current_settings.allowed_chat_id:
            return
        if payload.command is RemoteCommand.START:
            self._handle_start(payload)
        elif payload.command is RemoteCommand.STOP:
            self._handle_stop(payload)
        elif payload.command is RemoteCommand.REBOOT:
            self._handle_reboot(payload)
        elif payload.command is RemoteCommand.QUEST:
            self._handle_quest_command(payload)
        elif payload.command is RemoteCommand.STATUS:
            self._handle_status(payload)
        elif payload.command is RemoteCommand.STAT:
            self._handle_stat(payload)
        elif payload.command is RemoteCommand.MENU:
            self._handle_menu(payload)

    def _handle_start(self, payload: TelegramCommandPayload) -> None:
        if self.emulator_reboot_in_progress:
            self._send_ack(payload.chat_id, self.translate("에뮬레이터 재부팅이 이미 진행 중입니다."), payload.update_id)
            return
        if self.state not in {ControlState.IDLE, ControlState.AT_TITLE, ControlState.GAME_STOPPED_FALLBACK, ControlState.ERROR} or self.ports.task_is_alive():
            self._send_ack(payload.chat_id, "이미 실행 중이거나 정지 처리 중입니다.", payload.update_id)
            return
        try:
            setting = self.ports.load_latest_setting()
        except Exception:
            self._send_ack(payload.chat_id, "최신 매크로 설정을 불러오지 못했습니다.", payload.update_id)
            return
        run_id = uuid.uuid4().hex
        worker_event = threading.Event()
        target = str(getattr(setting, "FARM_TARGET_TEXT", None) or getattr(setting, "FARM_TARGET", ""))
        runtime = RemoteRuntime(
            run_id=run_id,
            start_reason=StartReason.TELEGRAM,
            farm_target_text=target,
            event_queue=self.event_queue,
            worker_force_stop_event=worker_event,
            adb_executable=resolve_adb_executable(getattr(setting, "EMU_PATH", None)),
            adb_address=str(getattr(setting, "ADB_ADRESS", "")),
            started_at=datetime.now(timezone.utc),
            started_monotonic=time.monotonic(),
            notification_chat_id=payload.chat_id,
        )
        clear_telegram_secrets(setting)
        if not self.ports.start_task(setting, StartReason.TELEGRAM, run_id, runtime):
            self._send_ack(payload.chat_id, "작업을 시작할 수 없습니다.", payload.update_id)
            return
        if self.current_runtime is not runtime or self.state is not ControlState.STARTING:
            runtime.mark_exit(TaskExitReason.ERROR, "작업 시작 상태를 확인하지 못했습니다.", "start_task_contract")
            self.last_error = "작업 시작 상태를 확인하지 못했습니다."
            self._send_ack(payload.chat_id, self.last_error, payload.update_id)
            self._sync_ui()
            return
        self._send_ack(payload.chat_id, "동작 요청을 접수했습니다.", payload.update_id)

    def _handle_stop(self, payload: TelegramCommandPayload) -> None:
        runtime = self.current_runtime
        if runtime is None or self.state not in {ControlState.STARTING, ControlState.RUNNING}:
            self._send_ack(payload.chat_id, "현재 실행 중인 작업이 없습니다.", payload.update_id)
            return
        accepted = runtime.request_stop(datetime.now(timezone.utc), time.monotonic(), payload.chat_id)
        self._transition(ControlState.STOP_REQUESTED)
        text = "안전 정지 요청을 접수했습니다." if accepted else "안전 정지가 이미 진행 중입니다."
        self._send_ack(payload.chat_id, text, payload.update_id)

    def _handle_reboot(self, payload: TelegramCommandPayload) -> None:
        if self.emulator_reboot_in_progress:
            self._send_ack(payload.chat_id, self.translate("에뮬레이터 재부팅이 이미 진행 중입니다."), payload.update_id)
            return
        reboot_emulator = getattr(self.ports, "reboot_emulator", None)
        if reboot_emulator is None:
            self._send_ack(payload.chat_id, self.translate("에뮬레이터 재부팅에 실패했습니다. stat 명령으로 로그를 확인하세요."), payload.update_id)
            return

        self.emulator_reboot_in_progress = True
        self._send_ack(
            payload.chat_id,
            self.translate("에뮬레이터 재부팅을 시작했습니다. 실행 중인 매크로는 먼저 중지됩니다."),
            payload.update_id,
        )

        def reboot() -> None:
            try:
                succeeded = bool(reboot_emulator())
            except Exception:
                succeeded = False
                if self.logger is not None:
                    self.logger.exception("Telegram emulator reboot failed")
            self.event_queue.put(
                (
                    "emulator_reboot_finished",
                    EmulatorRebootResult(
                        payload.update_id,
                        payload.chat_id,
                        payload.service_generation,
                        succeeded,
                    ),
                )
            )

        threading.Thread(target=reboot, name="telegram-emulator-reboot", daemon=True).start()

    def _handle_quest_command(self, payload: TelegramCommandPayload) -> None:
        if not self._quest_selection_allowed():
            self._send_quest_busy(payload.chat_id, payload.update_id)
            return
        targets = self._load_quest_targets()
        if not targets:
            self._send_ack(
                payload.chat_id,
                self.translate("선택할 수 있는 퀘스트 목표가 없습니다."),
                payload.update_id,
            )
            return
        self._send_quest_categories(payload.chat_id, payload.update_id, targets)

    def _handle_telegram_callback(self, payload: TelegramCallbackPayload) -> None:
        if not isinstance(payload, TelegramCallbackPayload):
            return
        if payload.service_generation != self.service.generation:
            return
        if payload.chat_id != self.current_settings.allowed_chat_id:
            return
        if not self._quest_selection_allowed():
            self._send_quest_busy(payload.chat_id, payload.update_id)
            return

        targets = self._load_quest_targets()
        if not targets:
            self._send_ack(
                payload.chat_id,
                self.translate("선택할 수 있는 퀘스트 목표가 없습니다."),
                payload.update_id,
            )
            return
        if payload.data == QUEST_CALLBACK_ROOT:
            self._send_quest_categories(payload.chat_id, payload.update_id, targets)
            return
        if payload.data.startswith(QUEST_CALLBACK_CATEGORY):
            token = payload.data[len(QUEST_CALLBACK_CATEGORY) :]
            categories = self._group_quest_targets(targets)
            category = next(
                (name for name in categories if _quest_callback_token(name) == token),
                None,
            )
            if category is not None:
                self._send_quest_targets(
                    payload.chat_id,
                    payload.update_id,
                    category,
                    categories[category],
                )
                return
        elif payload.data.startswith(QUEST_CALLBACK_TARGET):
            token = payload.data[len(QUEST_CALLBACK_TARGET) :]
            target = next(
                (item for item in targets if _quest_callback_token(item.code) == token),
                None,
            )
            if target is not None:
                select_target = getattr(self.ports, "select_quest_target", None)
                try:
                    selected = bool(select_target and select_target(target.code))
                except Exception:
                    selected = False
                    try:
                        self.logger.exception("Telegram quest target selection failed")
                    except Exception:
                        pass
                text = (
                    self.translate("퀘스트 목표를 '%s'(으)로 변경했습니다.\n/start 명령으로 실행하세요.")
                    % target.display_name
                    if selected
                    else self.translate("퀘스트 목표 저장에 실패했습니다. stat 명령으로 로그를 확인하세요.")
                )
                self._send_ack(payload.chat_id, text, payload.update_id)
                return

        self._send_ack(
            payload.chat_id,
            self.translate("퀘스트 목록이 변경되었습니다. /quest 명령으로 다시 여세요."),
            payload.update_id,
        )

    def _quest_selection_allowed(self) -> bool:
        return (
            self.state in QUEST_SELECTION_STATES
            and not self.ports.task_is_alive()
            and not self.emulator_reboot_in_progress
        )

    def _load_quest_targets(self) -> list[QuestTarget]:
        list_targets = getattr(self.ports, "list_quest_targets", None)
        if list_targets is None:
            return []
        try:
            values = list_targets() or ()
        except Exception:
            try:
                self.logger.exception("Telegram quest target listing failed")
            except Exception:
                pass
            return []

        targets = []
        seen_codes = set()
        for value in values:
            if not isinstance(value, QuestTarget):
                continue
            code = str(value.code).strip()
            category = str(value.category).strip()
            display_name = str(value.display_name).strip()
            if not code or not category or not display_name or code in seen_codes:
                continue
            seen_codes.add(code)
            targets.append(QuestTarget(code, category, display_name))
        return targets

    @staticmethod
    def _group_quest_targets(targets: list[QuestTarget]) -> dict[str, list[QuestTarget]]:
        categories: dict[str, list[QuestTarget]] = {}
        for target in targets:
            categories.setdefault(target.category, []).append(target)
        return categories

    def _send_quest_categories(
        self,
        chat_id: str,
        update_id: int,
        targets: list[QuestTarget],
    ) -> None:
        keyboard = [
            [
                {
                    "text": category,
                    "callback_data": QUEST_CALLBACK_CATEGORY + _quest_callback_token(category),
                }
            ]
            for category in self._group_quest_targets(targets)
        ]
        self._send_quest_menu(
            f"quest-categories:{update_id}",
            chat_id,
            self.translate("퀘스트 분류를 선택하세요."),
            keyboard,
        )

    def _send_quest_targets(
        self,
        chat_id: str,
        update_id: int,
        category: str,
        targets: list[QuestTarget],
    ) -> None:
        keyboard = [
            [
                {
                    "text": target.display_name,
                    "callback_data": QUEST_CALLBACK_TARGET + _quest_callback_token(target.code),
                }
            ]
            for target in targets
        ]
        keyboard.append(
            [
                {
                    "text": self.translate("분류로 돌아가기"),
                    "callback_data": QUEST_CALLBACK_ROOT,
                }
            ]
        )
        self._send_quest_menu(
            f"quest-targets:{update_id}",
            chat_id,
            self.translate("퀘스트 목표를 선택하세요: %s") % category,
            keyboard,
        )

    def _send_quest_menu(self, key: str, chat_id: str, text: str, keyboard: list) -> None:
        self.service.enqueue(
            OutboundMessage(
                key,
                chat_id,
                text,
                NotificationPriority.ACKNOWLEDGEMENT,
                {"inline_keyboard": keyboard},
            )
        )

    def _send_quest_busy(self, chat_id: str, update_id: int) -> None:
        self._send_ack(
            chat_id,
            self.translate("퀘스트 목표는 매크로가 완전히 정지된 상태에서만 변경할 수 있습니다."),
            update_id,
        )

    def _handle_status(self, payload: TelegramCommandPayload) -> None:
        self._handle_recent_ui_messages(payload, f"status:{payload.update_id}")

    def _handle_stat(self, payload: TelegramCommandPayload) -> None:
        self._handle_recent_ui_messages(payload, f"stat:{payload.update_id}")

    def _handle_recent_ui_messages(self, payload: TelegramCommandPayload, key: str) -> None:
        excerpt = read_recent_log(self.log_directory)
        header = "📋 WvDAS UI 메시지 (최근 60초)"
        if excerpt.text:
            body = excerpt.text
            if excerpt.read_truncated:
                body = "메시지가 많아 최신 구간만 표시합니다.\n" + body
        elif excerpt.file_name is None:
            body = "현재 UI 메시지가 없습니다."
        else:
            body = "최근 60초 내 UI 메시지가 없습니다."

        secrets = (self.current_settings.bot_token, self.current_settings.allowed_chat_id)
        header = redact_log_text(header, secrets)
        body = redact_log_text(body, secrets)
        body, _ = fit_tail_text(
            body,
            TELEGRAM_SAFE_MESSAGE_CHARS - len(header) - 2,
        )
        text = f"{header}\n\n{body}"
        self.service.enqueue(
            OutboundMessage(
                key,
                payload.chat_id,
                text,
                NotificationPriority.ACKNOWLEDGEMENT,
            )
        )

    def _handle_menu(self, payload: TelegramCommandPayload) -> None:
        self._send_ack(payload.chat_id, COMMAND_MENU_TEXT, payload.update_id)

    def _handle_reconfigure(self, _value) -> None:
        try:
            settings = read_telegram_settings(self.config_path, self.ports.load_raw_config)
            self.current_settings = settings
            self.service.reconfigure(settings)
            self.service_status = ServiceStatus.CONNECTING if settings.enabled else ServiceStatus.DISABLED
            self.last_error = None
        except TelegramConfigError as exc:
            self.service_status = ServiceStatus.ERROR
            self.last_error = str(exc)
            self._emit_service_error(str(exc))

    def _handle_test_connection(self, request: ConnectionTestRequest) -> None:
        if not isinstance(request, ConnectionTestRequest):
            return
        self._last_test_request_id = request.request_id
        self.service.start_connection_test(request)

    def _handle_test_result(self, result) -> None:
        if not hasattr(result, "request_id") or result.request_id != self._last_test_request_id:
            return
        self._last_test_request_id = None
        callback = getattr(self.ports, "show_test_result", None)
        if callback is not None:
            try:
                callback(result)
            except Exception:
                pass

    def _handle_task_finished(self, payload) -> None:
        if not isinstance(payload, TaskFinishedPayload):
            return
        self.on_task_finished(payload)

    def _handle_service_status(self, payload: ServiceStatusPayload) -> None:
        if not isinstance(payload, ServiceStatusPayload) or payload.service_generation != self.service.generation:
            return
        self.service_status = payload.status
        if payload.status is ServiceStatus.ERROR:
            self.last_error = payload.public_message
        self._sync_ui()

    def _handle_progress(self, payload: RemoteProgressPayload) -> None:
        if self.current_runtime is None or payload.run_id != self.current_runtime.run_id:
            return
        if not self._transition(payload.state):
            return
        self.progress_detail = payload.detail
        self._send_progress(payload.run_id, payload.state, payload.detail)
        self._sync_ui()

    def _handle_force_result(self, result: ForceStopResult) -> None:
        if not isinstance(result, ForceStopResult):
            return
        self._force_results[result.run_id] = result
        payload = self._finished_waiting_for_force.pop(result.run_id, None)
        if payload is not None:
            self._finalize_payload(payload, result)

    def _handle_emulator_reboot_finished(self, result: EmulatorRebootResult) -> None:
        if not isinstance(result, EmulatorRebootResult):
            return
        self.emulator_reboot_in_progress = False
        if (
            result.service_generation != self.service.generation
            or result.chat_id != self.current_settings.allowed_chat_id
        ):
            return
        text = self.translate(
            "에뮬레이터 재부팅이 완료되었습니다."
            if result.succeeded
            else "에뮬레이터 재부팅에 실패했습니다. stat 명령으로 로그를 확인하세요."
        )
        self.service.enqueue(
            OutboundMessage(
                f"reboot-complete:{result.update_id}",
                result.chat_id,
                text,
                NotificationPriority.TERMINAL,
            )
        )

    def _finalize_payload(self, payload: TaskFinishedPayload, force_result: ForceStopResult | None) -> None:
        if payload.reason is TaskExitReason.REMOTE_STOP:
            self._transition(ControlState.AT_TITLE)
            self._send_terminal(payload, "종료 작업 완료")
        elif payload.reason is TaskExitReason.REMOTE_STOP_FALLBACK:
            if force_result is None or not force_result.game_stopped:
                self._transition(ControlState.ERROR)
                self.last_error = "게임 종료 확인에 실패했습니다."
                self._send_abnormal_exit(payload, detail=self.last_error)
            else:
                self._transition(ControlState.GAME_STOPPED_FALLBACK)
                self._send_terminal(payload, "종료 작업 비정상 완료")
        elif payload.reason is TaskExitReason.ERROR:
            self._transition(ControlState.ERROR)
            self.last_error = payload.detail
            self._send_abnormal_exit(payload)
        else:
            self._transition(ControlState.IDLE)
        if self.current_runtime is not None and self.current_runtime.run_id == payload.run_id:
            self.current_runtime = None
        self._sync_ui()

    def _transition(self, state: ControlState) -> bool:
        state = ControlState(state)
        if state is self.state:
            return True
        if state not in ALLOWED_TRANSITIONS.get(self.state, set()):
            try:
                self.logger.warning("ignored remote state transition %s -> %s", self.state.value, state.value)
            except Exception:
                pass
            return False
        self.state = state
        return True

    def _send_ack(self, chat_id: str, text: str, update_id: int) -> None:
        self.service.enqueue(OutboundMessage(f"command:{update_id}", chat_id, text, NotificationPriority.ACKNOWLEDGEMENT))

    def _send_progress(self, run_id: str, state: ControlState, detail: str) -> None:
        key = (run_id, state)
        if key in self._progress_sent or not self.current_settings.enabled:
            return
        self._progress_sent.add(key)
        if not self.current_runtime or not self.current_runtime.notification_chat_id:
            return
        self.service.enqueue(OutboundMessage(f"progress:{run_id}:{state.value}", self.current_runtime.notification_chat_id, detail or state.value, NotificationPriority.PROGRESS))
        if state is ControlState.RUNNING and self.current_runtime.start_reason is StartReason.TELEGRAM:
            self.service.enqueue(OutboundMessage(f"start-complete:{run_id}", self.current_runtime.notification_chat_id, f"▶️ 동작 시작 완료\n매크로: {self.current_runtime.farm_target_text}\n상태: 실행 중", NotificationPriority.TERMINAL))

    def _send_terminal(self, payload: TaskFinishedPayload, title: str) -> None:
        if payload.notification_chat_id != self.current_settings.allowed_chat_id or not self.current_settings.enabled:
            return
        if payload.reason is TaskExitReason.REMOTE_STOP:
            key = f"remote-stop-complete:{payload.run_id}"
        elif payload.reason is TaskExitReason.REMOTE_STOP_FALLBACK:
            key = f"remote-stop-fallback:{payload.run_id}"
        else:
            key = f"error:{payload.run_id}"
        self.service.enqueue(
            OutboundMessage(
                key,
                payload.notification_chat_id,
                f"{title}\n매크로: {payload.farm_target_text}\n경과 시간: {self._format_elapsed(payload.elapsed_seconds)}",
                NotificationPriority.TERMINAL,
            )
        )

    def _send_abnormal_exit(
        self,
        payload: TaskFinishedPayload,
        *,
        detail: str | None = None,
    ) -> None:
        if not self.current_settings.enabled or not self.current_settings.allowed_chat_id:
            return
        detail = detail or payload.detail or "알 수 없는 오류"
        phase = payload.failure_phase or "알 수 없음"
        self.service.enqueue(
            OutboundMessage(
                f"abnormal-exit:{payload.run_id}",
                self.current_settings.allowed_chat_id,
                (
                    "⚠️ 매크로 비정상 종료\n"
                    f"매크로: {payload.farm_target_text or '없음'}\n"
                    f"오류: {detail}\n"
                    f"실패 단계: {phase}\n"
                    f"경과 시간: {self._format_elapsed(payload.elapsed_seconds)}\n"
                    "최근 실행 내용은 stat 명령으로 확인할 수 있습니다."
                ),
                NotificationPriority.TERMINAL,
            )
        )

    def _emit_service_error(self, message: str) -> None:
        self.event_queue.put(("telegram_service_status", ServiceStatusPayload(self.service.generation, ServiceStatus.ERROR, message)))

    def _sync_ui(self) -> None:
        try:
            self.ports.sync_ui_state(self.state)
        except Exception:
            pass

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        seconds = int(max(0, seconds))
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
