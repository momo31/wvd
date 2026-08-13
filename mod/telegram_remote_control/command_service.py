"""Long-polling Telegram command and outbound-message service."""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from .bot_api import (
    TelegramApiError,
    TelegramAuthError,
    TelegramBotClient,
    TelegramRateLimitError,
    TelegramTransientError,
    TelegramWebhookConflictError,
)
from .config import TelegramConfigError, validate_telegram_settings
from .constants import (
    MAX_PENDING_MESSAGES,
    POLL_TIMEOUT_SECONDS,
    SEND_BACKOFF_SECONDS,
    SENT_KEY_CACHE_SIZE,
    SERVICE_THREAD_JOIN_TIMEOUT_SECONDS,
    GUI_CONNECTION_TEST_TIMEOUT_SECONDS,
)
from .models import (
    ConnectionTestRequest,
    ConnectionTestResult,
    NotificationPriority,
    OutboundMessage,
    RemoteCommand,
    ServiceStatus,
    ServiceStatusPayload,
    TelegramCommandPayload,
    TelegramSettings,
)


COMMAND_ALIASES = {
    "/start": RemoteCommand.START,
    "/stop": RemoteCommand.STOP,
    "/status": RemoteCommand.STATUS,
    "동작": RemoteCommand.START,
    "정지": RemoteCommand.STOP,
    "상태": RemoteCommand.STATUS,
}


def normalize_command(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value:
        return None
    if value.startswith("/"):
        token = value.split(None, 1)[0].lower()
        if "@" in token:
            token = token.split("@", 1)[0]
        return token
    return value


def parse_command(text: str) -> RemoteCommand | None:
    return COMMAND_ALIASES.get(normalize_command(text))


def parse_update_command(
    update: dict[str, Any],
    settings: TelegramSettings,
    generation: int,
    *,
    received_at: datetime | None = None,
) -> tuple[TelegramCommandPayload | None, bool]:
    """Return (payload, authorized_unknown_text)."""

    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return None, False
    chat = message.get("chat")
    sender = message.get("from")
    text = message.get("text")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None, False
    if str(chat.get("id")) != settings.allowed_chat_id:
        return None, False
    if not isinstance(sender, dict) or sender.get("is_bot") is not False:
        return None, False
    if not isinstance(text, str):
        return None, False
    command = parse_command(text)
    if command is None:
        return None, True
    try:
        update_id = int(update["update_id"])
    except (KeyError, TypeError, ValueError):
        return None, False
    when = received_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (
        TelegramCommandPayload(
            command=command,
            update_id=update_id,
            chat_id=settings.allowed_chat_id,
            received_at=when,
            service_generation=int(generation),
        ),
        False,
    )


class TelegramCommandService:
    def __init__(
        self,
        event_queue,
        logger: logging.Logger | Any,
        client_factory: Callable[..., TelegramBotClient] = TelegramBotClient,
    ):
        self._events = event_queue
        self._logger = logger
        self._client_factory = client_factory
        self._condition = threading.Condition(threading.RLock())
        self._settings = TelegramSettings(False, "", "")
        self._generation = 0
        self._final_stop = False
        self._poll_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._pending: dict[str, OutboundMessage] = {}
        self._retry_counts: dict[str, int] = {}
        self._outbound: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
        self._sequence = 0
        self._sent_set: set[str] = set()
        self._sent_order: deque[str] = deque()
        self._last_update_id: int | None = None

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    @property
    def settings(self) -> TelegramSettings:
        with self._condition:
            return self._settings

    def start(self, settings: TelegramSettings) -> None:
        self._apply_settings(settings, initial=True)

    def reconfigure(self, settings: TelegramSettings) -> None:
        self._apply_settings(settings, initial=False)

    def stop(self) -> None:
        with self._condition:
            if self._final_stop:
                return
            self._final_stop = True
            self._condition.notify_all()
        def cleanup() -> None:
            for thread in (self._poll_thread, self._send_thread):
                if thread and thread.is_alive():
                    thread.join(SERVICE_THREAD_JOIN_TIMEOUT_SECONDS)
        threading.Thread(target=cleanup, name="telegram-service-cleanup", daemon=True).start()

    def enqueue(self, message: OutboundMessage) -> bool:
        if not isinstance(message, OutboundMessage):
            raise TypeError("message must be OutboundMessage")
        with self._condition:
            if message.key in self._sent_set or message.key in self._pending:
                return False
            if len(self._pending) >= MAX_PENDING_MESSAGES:
                self._evict_non_terminal_locked()
            if len(self._pending) >= MAX_PENDING_MESSAGES:
                self._put_status_locked(ServiceStatus.ERROR, "Telegram 알림 큐가 가득 찼습니다.")
                return False
            self._pending[message.key] = message
            self._sequence += 1
            self._outbound.put((int(message.priority), self._sequence, message.key))
            self._condition.notify_all()
            return True

    def start_connection_test(self, request: ConnectionTestRequest) -> None:
        result_sent = threading.Event()

        def emit(result: ConnectionTestResult) -> None:
            if result_sent.is_set():
                return
            result_sent.set()
            self._events.put(("telegram_test_result", result))

        timeout_timer = threading.Timer(
            GUI_CONNECTION_TEST_TIMEOUT_SECONDS,
            lambda: emit(ConnectionTestResult(request.request_id, False, "Telegram 연결 테스트 시간이 초과되었습니다.")),
        )
        timeout_timer.daemon = True
        timeout_timer.start()

        def run() -> None:
            try:
                settings = validate_telegram_settings(request.settings)
                client = self._client_factory(settings.bot_token, self._logger)
                client.get_me()
                client.send_message(settings.allowed_chat_id, "WvDAS 연결 테스트가 완료되었습니다.")
                result = ConnectionTestResult(request.request_id, True, "연결됨")
            except TelegramApiError as exc:
                result = ConnectionTestResult(request.request_id, False, exc.public_message)
            except TelegramConfigError as exc:
                result = ConnectionTestResult(request.request_id, False, str(exc))
            except Exception:
                result = ConnectionTestResult(request.request_id, False, "Telegram 연결 테스트에 실패했습니다.")
            timeout_timer.cancel()
            emit(result)
        threading.Thread(target=run, name="telegram-connection-test", daemon=True).start()

    def _apply_settings(self, settings: TelegramSettings, *, initial: bool) -> None:
        settings = validate_telegram_settings(settings)
        with self._condition:
            old = self._settings
            self._generation += 1
            self._settings = settings
            self._last_update_id = None
            if not settings.enabled or old.allowed_chat_id != settings.allowed_chat_id:
                self._pending.clear()
                self._retry_counts.clear()
                self._outbound = queue.PriorityQueue()
                self._sent_set.clear()
                self._sent_order.clear()
            elif not initial:
                self._retain_terminal_messages_locked()
            self._put_status_locked(
                ServiceStatus.CONNECTING if settings.enabled else ServiceStatus.DISABLED,
                "" if settings.enabled else "Telegram 원격 제어가 비활성화되어 있습니다.",
            )
            if settings.enabled and not self._final_stop:
                if self._poll_thread is None or not self._poll_thread.is_alive():
                    self._poll_thread = threading.Thread(target=self._poll_loop, name="telegram-poll", daemon=True)
                    self._poll_thread.start()
                if self._send_thread is None or not self._send_thread.is_alive():
                    self._send_thread = threading.Thread(target=self._send_loop, name="telegram-send", daemon=True)
                    self._send_thread.start()
            self._condition.notify_all()

    def _poll_loop(self) -> None:
        offset: int | None = None
        while True:
            snapshot = self._wait_for_enabled()
            if snapshot is None:
                return
            generation, settings = snapshot
            try:
                client = self._client_factory(settings.bot_token, self._logger)
                client.get_me()
                discarded = client.get_updates(-1, timeout=0)
                offset = None
                if discarded:
                    offset = max(int(item["update_id"]) for item in discarded if "update_id" in item) + 1
                self._put_status(ServiceStatus.CONNECTED, "", generation)
                while self._is_generation_active(generation, settings):
                    updates = client.get_updates(offset, timeout=POLL_TIMEOUT_SECONDS)
                    if not updates:
                        continue
                    max_id = None
                    for update in sorted(updates, key=lambda item: int(item.get("update_id", -1))):
                        try:
                            update_id = int(update["update_id"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if self._last_update_id is not None and update_id <= self._last_update_id:
                            continue
                        max_id = update_id if max_id is None else max(max_id, update_id)
                        payload, unknown = parse_update_command(update, settings, generation)
                        if payload is not None:
                            self._events.put(("telegram_command", payload))
                        elif unknown:
                            self.enqueue(
                                OutboundMessage(
                                    key=f"usage:{update_id}",
                                    chat_id=settings.allowed_chat_id,
                                    text="사용법: /start, /stop, /status",
                                    priority=NotificationPriority.ACKNOWLEDGEMENT,
                                )
                            )
                    if max_id is not None:
                        self._last_update_id = max_id
                        offset = max_id + 1
            except (TelegramAuthError, TelegramWebhookConflictError) as exc:
                self._put_status(ServiceStatus.ERROR, exc.public_message, generation)
                self._wait_for_change(generation, 5.0)
            except TelegramRateLimitError as exc:
                self._put_status(ServiceStatus.RETRYING, exc.public_message, generation)
                self._wait_for_change(generation, exc.retry_after or 5.0)
            except (TelegramTransientError, OSError, TimeoutError) as exc:
                self._put_status(ServiceStatus.RETRYING, "Telegram 연결을 재시도합니다.", generation)
                self._wait_for_change(generation, SEND_BACKOFF_SECONDS[0])
            except TelegramApiError as exc:
                self._put_status(ServiceStatus.ERROR, exc.public_message, generation)
                self._wait_for_change(generation, 5.0)
            except Exception:
                self._put_status(ServiceStatus.RETRYING, "Telegram 수신기를 재시작합니다.", generation)
                self._wait_for_change(generation, SEND_BACKOFF_SECONDS[0])

    def _send_loop(self) -> None:
        while True:
            with self._condition:
                while not self._final_stop and (not self._settings.enabled or not self._pending):
                    self._condition.wait()
                if self._final_stop:
                    return
                generation = self._generation
                settings = self._settings
            try:
                _, _, key = self._outbound.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._condition:
                message = self._pending.get(key)
                if message is None:
                    continue
                if generation != self._generation or not settings.enabled or message.chat_id != settings.allowed_chat_id:
                    self._pending.pop(key, None)
                    continue
            try:
                client = self._client_factory(settings.bot_token, self._logger)
                client.send_message(message.chat_id, message.text)
            except TelegramRateLimitError as exc:
                self._retry_message(message, exc.retry_after or SEND_BACKOFF_SECONDS[0])
            except TelegramTransientError:
                self._retry_message(message, SEND_BACKOFF_SECONDS[0])
            except TelegramApiError as exc:
                self._put_status(ServiceStatus.ERROR, exc.public_message, generation)
                with self._condition:
                    self._pending.pop(key, None)
                    self._retry_counts.pop(key, None)
            except Exception:
                self._retry_message(message, SEND_BACKOFF_SECONDS[0])
            else:
                with self._condition:
                    self._pending.pop(key, None)
                    self._retry_counts.pop(key, None)
                    self._remember_sent_locked(key)

    def _retry_message(self, message: OutboundMessage, delay: float) -> None:
        with self._condition:
            if message.key not in self._pending or self._final_stop:
                return
            generation = self._generation
            attempt = self._retry_counts.get(message.key, 0)
            self._retry_counts[message.key] = attempt + 1
            if attempt < len(SEND_BACKOFF_SECONDS):
                delay = max(float(delay), float(SEND_BACKOFF_SECONDS[attempt]))
            else:
                delay = max(float(delay), float(SEND_BACKOFF_SECONDS[-1]))
        self._wait_for_change(generation, max(0.0, float(delay)))
        with self._condition:
            if self._final_stop or message.key not in self._pending:
                return
            self._sequence += 1
            self._outbound.put((int(message.priority), self._sequence, message.key))
            self._condition.notify_all()

    def _drop_message(self, key: str) -> None:
        with self._condition:
            self._pending.pop(key, None)
            self._retry_counts.pop(key, None)

    def _wait_for_enabled(self):
        with self._condition:
            while not self._final_stop and not self._settings.enabled:
                self._condition.wait()
            if self._final_stop:
                return None
            return self._generation, self._settings

    def _wait_for_change(self, generation: int, seconds: float) -> None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._final_stop or self._generation != generation or not self._settings.enabled,
                timeout=max(0.0, seconds),
            )

    def _is_generation_active(self, generation: int, settings: TelegramSettings) -> bool:
        with self._condition:
            return (
                not self._final_stop
                and self._generation == generation
                and self._settings == settings
                and settings.enabled
            )

    def _put_status(self, status: ServiceStatus, message: str, generation: int | None = None) -> None:
        with self._condition:
            self._put_status_locked(status, message, generation)

    def _put_status_locked(self, status: ServiceStatus, message: str, generation: int | None = None) -> None:
        self._events.put(
            (
                "telegram_service_status",
                ServiceStatusPayload(
                    self._generation if generation is None else generation,
                    ServiceStatus(status),
                    str(message or "")[:240],
                ),
            )
        )

    def _remember_sent_locked(self, key: str) -> None:
        if key in self._sent_set:
            return
        self._sent_set.add(key)
        self._sent_order.append(key)
        while len(self._sent_order) > SENT_KEY_CACHE_SIZE:
            self._sent_set.discard(self._sent_order.popleft())

    def _evict_non_terminal_locked(self) -> None:
        removable = [
            key
            for key, message in self._pending.items()
            if message.priority != NotificationPriority.TERMINAL
        ]
        for key in removable:
            if len(self._pending) < MAX_PENDING_MESSAGES:
                break
            self._pending.pop(key, None)
            self._retry_counts.pop(key, None)

    def _retain_terminal_messages_locked(self) -> None:
        keep = {
            key: message
            for key, message in self._pending.items()
            if message.priority == NotificationPriority.TERMINAL
        }
        self._pending = keep
        self._retry_counts = {key: value for key, value in self._retry_counts.items() if key in keep}
        self._outbound = queue.PriorityQueue()
        for message in keep.values():
            self._sequence += 1
            self._outbound.put((int(message.priority), self._sequence, message.key))
