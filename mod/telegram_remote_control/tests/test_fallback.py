from __future__ import annotations

import queue
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mod.telegram_remote_control.fallback import force_stop_game_once
from mod.telegram_remote_control.models import StartReason, TaskExitReason, TransitionStatus
from mod.telegram_remote_control.runtime_bridge import RemoteRuntime


class _Adapter:
    local_stop_exception_type = RuntimeError

    def __init__(self):
        self.commands = []

    def control_shell(self, argv):
        self.commands.append(list(argv))
        if argv[0] == "pidof":
            return "1234" if ["am", "force-stop", "jp.co.drecom.wizardry.daphne"] not in self.commands else ""
        return ""


class FallbackTests(unittest.TestCase):
    def test_fallback_has_single_owner_and_reports_result(self):
        events = queue.Queue()
        runtime = RemoteRuntime(
            "run-fallback", StartReason.TELEGRAM, "target", events, threading.Event(), None, "", datetime.now(timezone.utc), 0.0, "1"
        )
        adapter = _Adapter()
        result = force_stop_game_once(adapter, runtime, failure_phase="test")
        self.assertEqual(result.status, TransitionStatus.FALLBACK_COMPLETE)
        self.assertEqual(runtime.exit_reason, TaskExitReason.REMOTE_STOP_FALLBACK)
        self.assertEqual(events.get_nowait()[0], "remote_force_stop_result")
        self.assertTrue(any(command[:2] == ["am", "force-stop"] for command in adapter.commands))


if __name__ == "__main__":
    unittest.main()
