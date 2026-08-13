"""Farm worker and exactly-once completion callback."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .models import TaskExitReason
from .runtime_bridge import RemoteRuntime


class TaskCompletionLatch:
    def __init__(self, event_queue, run_id: str):
        self._event_queue = event_queue
        self._run_id = str(run_id)
        self._lock = threading.Lock()
        self._called = False

    def callback(self) -> bool:
        with self._lock:
            if self._called:
                return False
            self._called = True
        self._event_queue.put(("task_completion_requested", self._run_id))
        return True

    @property
    def called(self) -> bool:
        with self._lock:
            return self._called


def run_farm_worker(
    farm_callable: Callable[[Any], Any],
    setting: Any,
    runtime: RemoteRuntime,
    latch: TaskCompletionLatch,
    logger: logging.Logger | Any,
) -> None:
    handed_off = False
    try:
        farm_callable(setting)
    except SystemExit:
        if runtime.is_handoff_requested("7000G"):
            handed_off = True
        else:
            runtime.mark_exit(
                TaskExitReason.ERROR,
                "작업 스레드가 예기치 않게 종료되었습니다.",
                "farm_worker_system_exit",
            )
    except Exception:
        runtime.mark_exit(
            TaskExitReason.ERROR,
            "작업 스레드에서 예기치 않은 오류가 발생했습니다.",
            "farm_worker",
        )
        try:
            logger.exception("farm worker failed")
        except Exception:
            pass
    finally:
        # A 7000G handoff intentionally leaves completion ownership with the
        # replacement worker.  Avoid returning from ``finally`` so the
        # callback remains exactly-once for every other terminal path.
        if not handed_off:
            if runtime.exit_reason is None:
                force_event = getattr(setting, "_FORCESTOPING", None)
                reason = TaskExitReason.LOCAL_STOP if force_event is not None and force_event.is_set() else TaskExitReason.COMPLETED
                runtime.mark_exit(reason)
            latch.callback()
