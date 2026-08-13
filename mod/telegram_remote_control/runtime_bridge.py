"""Thread-safe bridge between the legacy Farm and the remote feature."""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, TYPE_CHECKING

from .constants import HANDOFF_TARGET_7000G, REMOTE_STOP_TIMEOUT_SECONDS
from .models import (
    BoundedOperationTimeout,
    CheckpointKind,
    ControlState,
    RemoteProgressPayload,
    RemoteRecoverySuppressed,
    RemoteStopSignal,
    StartReason,
    TaskExitReason,
    TaskFinishedPayload,
)

if TYPE_CHECKING:
    from .adapters import GameAutomationAdapter


class RemoteRuntime:
    def __init__(
        self,
        run_id: str,
        start_reason: StartReason,
        farm_target_text: str,
        event_queue: queue.Queue,
        worker_force_stop_event: threading.Event,
        adb_executable: str | None,
        adb_address: str,
        started_at: datetime | None = None,
        started_monotonic: float | None = None,
        notification_chat_id: str | None = None,
    ):
        if not hasattr(worker_force_stop_event, "set") or not hasattr(worker_force_stop_event, "is_set"):
            raise TypeError("worker_force_stop_event must be Event-compatible")
        self.run_id = str(run_id)
        self.start_reason = StartReason(start_reason)
        self.farm_target_text = str(farm_target_text or "")
        self.event_queue = event_queue
        self.worker_force_stop_event = worker_force_stop_event
        self.adb_executable = adb_executable
        self.adb_address = str(adb_address or "")
        self.started_at = started_at or datetime.now(timezone.utc)
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        self.started_monotonic = time.monotonic() if started_monotonic is None else float(started_monotonic)
        self.notification_chat_id = str(notification_chat_id) if notification_chat_id is not None else None

        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self.stop_requested_at: datetime | None = None
        self.stop_deadline_monotonic: float | None = None
        self.exit_reason: TaskExitReason | None = None
        self.detail = ""
        self.failure_phase: str | None = None
        self.adapter: GameAutomationAdapter | None = None
        self.timeout_fallback_started = threading.Event()
        self.fallback_dispatch_started = threading.Event()
        self.fallback_done = threading.Event()
        self.fallback_succeeded: bool | None = None
        self.handoff_target: str | None = None

    def request_stop(self, now: datetime | None, monotonic_now: float, chat_id: str | None) -> bool:
        with self._lock:
            if self.stop_event.is_set():
                return False
            self.stop_event.set()
            self.stop_requested_at = now or datetime.now(timezone.utc)
            if self.stop_requested_at.tzinfo is None:
                self.stop_requested_at = self.stop_requested_at.replace(tzinfo=timezone.utc)
            self.stop_deadline_monotonic = float(monotonic_now) + REMOTE_STOP_TIMEOUT_SECONDS
            if chat_id is not None:
                self.notification_chat_id = str(chat_id)
            return True

    def is_stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def report_progress(self, new_state: ControlState, detail: str = "") -> None:
        payload = RemoteProgressPayload(self.run_id, ControlState(new_state), str(detail or ""))
        self.event_queue.put(("remote_progress", payload))

    def register_adapter(self, adapter: "GameAutomationAdapter", handoff_target: str | None = None) -> None:
        with self._lock:
            if self.adapter is None:
                if handoff_target is not None:
                    raise RuntimeError("first adapter cannot register as handoff")
                self.adapter = adapter
                return
            if (
                handoff_target
                and self.handoff_target == handoff_target
                and self.exit_reason is None
            ):
                self.adapter = adapter
                self.handoff_target = None
                return
            raise RuntimeError("adapter already registered")

    def mark_exit(
        self,
        reason: TaskExitReason,
        detail: str = "",
        failure_phase: str | None = None,
    ) -> bool:
        with self._lock:
            if self.exit_reason is not None:
                return False
            self.exit_reason = TaskExitReason(reason)
            self.detail = _public_detail(detail)
            self.failure_phase = _sanitize_phase(failure_phase) if failure_phase else None
            return True

    def request_handoff(self, target: str) -> bool:
        with self._lock:
            if self.exit_reason is not None or self.stop_event.is_set() or self.handoff_target is not None:
                return False
            self.handoff_target = str(target)
            return True

    def is_handoff_requested(self, target: str | None = None) -> bool:
        with self._lock:
            return self.handoff_target is not None and (target is None or self.handoff_target == target)

    def clear_handoff(self, target: str) -> bool:
        with self._lock:
            if self.handoff_target != target:
                return False
            self.handoff_target = None
            return True

    def update_farm_target(self, text: str) -> None:
        with self._lock:
            self.farm_target_text = str(text or "")

    def begin_timeout_fallback(self) -> bool:
        with self._lock:
            if self.worker_force_stop_event.is_set() and not self.timeout_fallback_started.is_set():
                return False
            if self.timeout_fallback_started.is_set():
                return False
            self.timeout_fallback_started.set()
            return True

    def is_timeout_fallback_started(self) -> bool:
        return self.timeout_fallback_started.is_set()

    def begin_fallback_dispatch(self) -> bool:
        with self._lock:
            if self.fallback_dispatch_started.is_set():
                return False
            self.fallback_dispatch_started.set()
            return True

    def finish_fallback(self, succeeded: bool, detail: str, failure_phase: str | None) -> None:
        with self._lock:
            self.fallback_succeeded = bool(succeeded)
            if failure_phase is not None:
                self.failure_phase = _sanitize_phase(failure_phase)
            if detail:
                self.detail = _public_detail(detail)
            self.fallback_done.set()

    def wait_for_fallback(self, timeout: float | None) -> bool | None:
        if not self.fallback_done.wait(timeout):
            return None
        with self._lock:
            return self.fallback_succeeded

    def build_finished_payload(
        self,
        finished_at: datetime | None = None,
        finished_monotonic: float | None = None,
    ) -> TaskFinishedPayload:
        with self._lock:
            if self.exit_reason is None:
                raise RuntimeError("task exit reason is not set")
            finished_at = finished_at or datetime.now(timezone.utc)
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=timezone.utc)
            finished_monotonic = time.monotonic() if finished_monotonic is None else float(finished_monotonic)
            elapsed = max(0.0, finished_monotonic - self.started_monotonic)
            return TaskFinishedPayload(
                run_id=self.run_id,
                reason=self.exit_reason,
                detail=self.detail,
                farm_target_text=self.farm_target_text,
                started_at=self.started_at,
                stop_requested_at=self.stop_requested_at,
                finished_at=finished_at,
                elapsed_seconds=elapsed,
                failure_phase=self.failure_phase,
                notification_chat_id=self.notification_chat_id,
            )


def remote_stop_checkpoint(runtime: RemoteRuntime | None, kind: CheckpointKind) -> None:
    if runtime is None or not runtime.is_stop_requested():
        return
    kind = CheckpointKind(kind)
    if kind in (CheckpointKind.DUNGEON_STABLE, CheckpointKind.TOWN_STABLE):
        raise RemoteStopSignal(kind)
    adapter = runtime.adapter
    if adapter is None:
        return
    screen = adapter.screenshot()
    patterns = ("dungFlag", "mapFlag", "Inn", "worldmapflag", "openworldmap", "returntotown")
    for pattern in patterns:
        try:
            if adapter.match_base(screen, pattern, None, 0.80):
                raise RemoteStopSignal(kind)
        except RemoteStopSignal:
            raise
        except Exception:
            continue


def request_task_handoff(
    runtime: RemoteRuntime | None,
    event_queue: queue.Queue,
    *,
    target: str,
    event_name: str,
) -> bool:
    remote_stop_checkpoint(runtime, CheckpointKind.BETWEEN_OPERATIONS)
    if runtime is None:
        event_queue.put((event_name, ""))
        return True
    if not runtime.request_handoff(target):
        return False
    try:
        event_queue.put((event_name, runtime.run_id))
    except Exception:
        runtime.clear_handoff(target)
        raise
    return True


def raise_if_remote_recovery_disallowed(runtime: RemoteRuntime | None, operation: str) -> None:
    if runtime is not None and runtime.adapter is not None and runtime.is_stop_requested():
        raise RemoteRecoverySuppressed(operation)


def run_bounded_operation(
    operation: Callable[[], Any],
    *,
    runtime: RemoteRuntime,
    deadline_monotonic: float,
) -> Any:
    result: list[Any] = []
    error: list[BaseException] = []
    completed = threading.Event()

    def invoke() -> None:
        try:
            result.append(operation())
        except BaseException as exc:  # pass legacy exceptions back to caller
            error.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=invoke, name="remote-bounded-operation", daemon=True)
    thread.start()
    while not completed.wait(0.1):
        if runtime.worker_force_stop_event.is_set():
            adapter = runtime.adapter
            exception_type = adapter.local_stop_exception_type if adapter else RuntimeError
            raise exception_type()
        if runtime.is_timeout_fallback_started():
            raise RemoteRecoverySuppressed("bounded_operation")
        if time.monotonic() >= deadline_monotonic:
            raise BoundedOperationTimeout("bounded_operation")
    if error:
        raise error[0]
    return result[0] if result else None


def _public_detail(value: str | None) -> str:
    return str(value or "")[:240]


def _sanitize_phase(value: str) -> str:
    result = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value))
    return result[:80] or "unknown"

