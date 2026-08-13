from __future__ import annotations

import queue
import threading
import unittest
from datetime import datetime, timezone

from mod.telegram_remote_control.models import (
    CheckpointKind,
    RemoteStopSignal,
    StartReason,
    TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import (
    RemoteRuntime,
    remote_stop_checkpoint,
)
from mod.telegram_remote_control.worker import TaskCompletionLatch, run_farm_worker


class _Setting:
    def __init__(self):
        self._FORCESTOPING = threading.Event()


class RuntimeWorkerTests(unittest.TestCase):
    def make_runtime(self):
        return RemoteRuntime(
            "run-1",
            StartReason.TELEGRAM,
            "target",
            queue.Queue(),
            threading.Event(),
            None,
            "127.0.0.1:16384",
            datetime.now(timezone.utc),
            0.0,
            "1",
        )

    def test_checkpoint_raises_only_after_remote_stop(self):
        runtime = self.make_runtime()
        remote_stop_checkpoint(runtime, CheckpointKind.DUNGEON_STABLE)
        runtime.request_stop(datetime.now(timezone.utc), 1.0, "1")
        with self.assertRaises(RemoteStopSignal):
            remote_stop_checkpoint(runtime, CheckpointKind.DUNGEON_STABLE)

    def test_worker_completion_callback_is_exactly_once(self):
        runtime = self.make_runtime()
        events = queue.Queue()
        latch = TaskCompletionLatch(events, runtime.run_id)
        setting = _Setting()
        run_farm_worker(lambda _setting: None, setting, runtime, latch, None)
        self.assertEqual(events.get_nowait(), ("task_completion_requested", "run-1"))
        self.assertEqual(runtime.exit_reason, TaskExitReason.COMPLETED)
        self.assertFalse(latch.callback())
        with self.assertRaises(queue.Empty):
            events.get_nowait()

    def test_remote_handoff_does_not_complete_original_worker(self):
        runtime = self.make_runtime()
        runtime.request_handoff("7000G")
        events = queue.Queue()
        latch = TaskCompletionLatch(events, runtime.run_id)
        run_farm_worker(lambda _setting: (_ for _ in ()).throw(SystemExit()), _Setting(), runtime, latch, None)
        self.assertTrue(events.empty())
        self.assertIsNone(runtime.exit_reason)


if __name__ == "__main__":
    unittest.main()
