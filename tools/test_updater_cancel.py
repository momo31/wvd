"""No real HTTP, Tk windows, restart scripts or subprocesses are used."""

import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import auto_updater
import main
from tools.test_updater_channel import controller, updater as make_updater


class UpdaterCancelTests(unittest.TestCase):
    def make_updater(self):
        return controller().updater

    def test_cancel_sets_shared_event_without_closing_app(self):
        c = controller()
        c._dispatch('cancel_update', None)
        c._dispatch('progress', 10)
        self.assertTrue(c.updater.cancel_event.is_set())
        self.assertFalse(c._closing)
        c.main_window.destroy.assert_not_called()
        c.main_window.push_event.assert_not_called()

    def test_cancel_during_read_discards_chunk_and_never_retries(self):
        updater = self.make_updater()
        response = Mock()
        response.headers = {"Content-Length": "100"}
        response.read.side_effect = lambda _: (updater.cancel_event.set() or b"late bytes")
        with tempfile.TemporaryDirectory() as directory, patch.object(auto_updater, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            path = Path(directory) / "update.zip"
            with self.assertRaises(auto_updater.CancelException):
                updater._download_bar_and_retry("https://example.invalid", path)
            self.assertEqual(path.read_bytes(), b"")
            open_url.assert_called_once_with("https://example.invalid", timeout=15)
        self.assertFalse(any(kind == "download_complete" for kind, _ in updater.msg_queue.queue))

    def test_network_timeout_has_finite_retries(self):
        updater = self.make_updater()
        with patch.object(auto_updater, "urlopen", side_effect=TimeoutError()) as open_url, patch.object(updater.cancel_event, "wait"):
            with self.assertRaises(TimeoutError):
                updater._download_bar_and_retry("https://example.invalid", "unused")
        self.assertEqual(open_url.call_count, 4)
        self.assertTrue(all(call.kwargs["timeout"] == 15 for call in open_url.call_args_list))

    def test_cancellation_during_retry_wait_stops_next_request(self):
        updater = self.make_updater()
        with patch.object(auto_updater, "urlopen", side_effect=TimeoutError()) as open_url, patch.object(
            updater.cancel_event, "wait", side_effect=lambda _: updater.cancel_event.set(),
        ):
            with self.assertRaises(auto_updater.CancelException):
                updater._download_bar_and_retry("https://example.invalid", "unused")
        self.assertEqual(open_url.call_count, 1)

    def test_every_download_phase_checks_cancel_before_restart_ready(self):
        phases = ("before_start", "_download_bar_and_retry", "_verify_md5", "_extract_archive", "_create_restart_script")
        for phase in phases:
            with self.subTest(phase=phase), patch.object(auto_updater.os, "makedirs"), patch.object(auto_updater.sys, 'frozen', True, create=True):
                updater = self.make_updater()
                for method in phases[1:]:
                    setattr(updater, method, Mock(return_value=True))
                if phase == "before_start":
                    updater.cancel_event.set()
                else:
                    getattr(updater, phase).side_effect = lambda *_: (updater.cancel_event.set() or True)
                updater.download()
                self.assertEqual(list(updater.msg_queue.queue), [("download_finished", None)])
                if phase != "_create_restart_script":
                    updater._create_restart_script.assert_not_called()

    def test_successful_download_still_emits_ready_then_finished(self):
        updater = self.make_updater()
        with patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(auto_updater.os, "makedirs"), patch.object(updater, "_download_bar_and_retry"), patch.object(
            updater, "_verify_md5", return_value=True,
        ), patch.object(updater, "_extract_archive"), patch.object(updater, "_create_restart_script", return_value="fake.bat"):
            updater.download()
        self.assertEqual(list(updater.msg_queue.queue), [("restart_ready", "fake.bat"), ("download_finished", None)])

    def test_cancellation_between_archive_members_stops_extraction(self):
        updater = self.make_updater()
        archive = Mock()
        first, second = SimpleNamespace(filename='first'), SimpleNamespace(filename='second')
        archive.infolist.return_value = [first, second]
        archive.extract.side_effect = lambda *_: updater.cancel_event.set()
        with patch("zipfile.ZipFile") as zip_file:
            zip_file.return_value.__enter__.return_value = archive
            with self.assertRaises(auto_updater.CancelException):
                updater._extract_archive("unused.zip", "unused")
        archive.extract.assert_called_once_with(first, "unused")

    def test_cancel_while_restart_message_is_open_prevents_subprocess(self):
        c = controller(); c.update_downloading = True
        c._dispatch('cancel_update', None)
        with patch.object(main.subprocess, "Popen") as restart:
            c._dispatch("restart_ready", "unused.ps1")
        restart.assert_not_called()
        c.main_window.destroy.assert_not_called()

    def test_ui_waits_for_worker_finish_before_allowing_a_new_download(self):
        c = controller(); c.run_in_thread = Mock()
        with patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(main.subprocess, "Popen") as restart:
            c._start_update_download()
            c.updater.cancel_event.set()
            c._start_update_download()
            self.assertTrue(c.updater.cancel_event.is_set())
            c.run_in_thread.assert_called_once()
            for kind, value in (("download_started", 100), ("progress", 50), ("restart_ready", "fake.bat")):
                c._dispatch(kind, value)
            restart.assert_not_called()
            self.assertEqual([call.args[0]['type'] for call in c.main_window.push_event.call_args_list], ['download_pending'])
            c._dispatch("download_finished", None)
            c._start_update_download()
            self.assertFalse(c.updater.cancel_event.is_set())
            self.assertEqual(c.run_in_thread.call_count, 2)


if __name__ == "__main__":
    unittest.main()
