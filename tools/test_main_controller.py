from __future__ import annotations

import queue
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main  # noqa: E402


class _Runtime:
    def __init__(self):
        self.run_id = "local-run"
        self.worker_force_stop_event = object()
        self.handoff_target = None
        self.handoff_checks = 0

    def is_handoff_requested(self, _target):
        self.handoff_checks += 1
        return False

    def mark_exit(self, *_args):
        raise AssertionError("the fake thread must start successfully")


class _Setting:
    FARM_TARGET_TEXT = "test target"


class _Feature:
    def __init__(self):
        self.started = []

    def on_task_started(self, runtime):
        self.started.append(runtime)


class _Thread:
    def __init__(self, *, target, args, daemon, name):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


class _Controller:
    def __init__(self, runtime):
        self.runtime = runtime
        self.msg_queue = queue.Queue()
        self.quest_threading = None
        self.quest_setting = None
        self._active_runtime = None
        self._active_latch = None
        self._completion_enqueued = set()
        self.remote_feature = _Feature()

    def _task_is_alive(self):
        return False

    def _new_local_runtime(self, _setting):
        return self.runtime


class MainControllerTests(unittest.TestCase):
    def test_task_button_uses_one_localized_label_source(self):
        gui_source = (SRC / "gui.py").read_text(encoding="utf-8")

        self.assertIn(
            'return _("停止") if busy else _("脚本, 启动!")',
            gui_source,
        )
        self.assertNotIn('_("중지") if busy else _("시작")', gui_source)
        self.assertIn("text=task_button_text(False)", gui_source)
        self.assertIn("text=task_button_text(busy)", gui_source)

    def test_local_start_creates_runtime_before_handoff_check(self):
        runtime = _Runtime()
        controller = _Controller(runtime)
        setting = _Setting()

        with mock.patch.object(main, "Factory", return_value=object()), mock.patch.object(
            main.threading,
            "Thread",
            _Thread,
        ):
            started = main.AppController._start_task(
                controller,
                setting,
                main.StartReason.LOCAL,
                "",
                None,
            )

        self.assertTrue(started)
        self.assertIs(controller._active_runtime, runtime)
        self.assertIs(setting._REMOTE_RUNTIME, runtime)
        self.assertIs(setting._FORCESTOPING, runtime.worker_force_stop_event)
        self.assertIsNone(setting._REMOTE_HANDOFF_TARGET)
        self.assertEqual(runtime.handoff_checks, 0)
        self.assertEqual(controller.remote_feature.started, [runtime])
        self.assertTrue(controller.quest_threading.started)


if __name__ == "__main__":
    unittest.main()
