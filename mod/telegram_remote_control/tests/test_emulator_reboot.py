from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main  # noqa: E402


class _Worker:
    def __init__(self):
        self.joined = []

    def is_alive(self):
        return True

    def join(self, timeout):
        self.joined.append(timeout)


class EmulatorRebootTests(unittest.TestCase):
    def test_controller_reuses_forced_emulator_recovery(self):
        worker = _Worker()
        setting = SimpleNamespace()
        runtime = Mock()
        runtime.clear_handoff.return_value = True
        latch = Mock()
        controller = SimpleNamespace(
            quest_threading=worker,
            _request_local_stop=Mock(),
            _load_latest_setting=Mock(return_value=setting),
            _active_runtime=runtime,
            _active_latch=latch,
        )
        context = object()
        device = object()

        with patch.object(main, "RuntimeContext", return_value=context), patch.object(
            main,
            "CheckAndRecoverDevice",
            return_value=device,
        ) as recover:
            succeeded = main.AppController._reboot_emulator(controller)

        self.assertTrue(succeeded)
        controller._request_local_stop.assert_called_once_with()
        runtime.clear_handoff.assert_called_once_with(main.HANDOFF_TARGET_7000G)
        runtime.mark_exit.assert_called_once_with(
            main.TaskExitReason.LOCAL_STOP,
            "에뮬레이터 재부팅으로 작업이 중지되었습니다.",
        )
        latch.callback.assert_called_once_with()
        self.assertEqual(worker.joined, [10])
        self.assertFalse(setting._FORCESTOPING.is_set())
        self.assertIs(setting._ADBDEVICE, device)
        recover.assert_called_once_with(
            setting,
            context,
            FORCE_RESTART_EMU=True,
        )


if __name__ == "__main__":
    unittest.main()
