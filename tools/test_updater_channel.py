"""Fork update checks use fake HTTP and temporary files only."""
import io
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import zipfile

import auto_updater
import main


def metadata(version='3.2.1-momo.2', url=None):
    return {'version': version, 'download_url': url or
            f'https://github.com/momo31/wvd/releases/download/{version}/wvd.zip', 'md5': 'a' * 32}


def updater():
    return auto_updater.AutoUpdater(queue.Queue(), 'momo31', 'wvd', '3.2.1-momo.1')


def controller():
    with patch.object(main, 'TelegramRemoteFeature') as feature:
        feature.return_value.handle_event.return_value = False
        c = main.AppController(False, None)
    c.updater = updater()
    c.updater.update_data = metadata()
    c.main_window = Mock()
    c._force_exit = Mock()
    return c


class UpdaterChannelTests(unittest.TestCase):
    def test_each_download_uses_a_fresh_staging_directory(self):
        u = updater(); u.update_data = metadata()
        with patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(auto_updater.os, 'makedirs'), patch.object(u, '_download_bar_and_retry') as download, patch.object(u, '_verify_md5', return_value=True), patch.object(u, '_extract_archive'), patch.object(u, '_create_restart_script', return_value='unused.ps1'):
            u.download(); u.download()
        self.assertEqual(download.call_count, 2)
        self.assertNotEqual(download.call_args_list[0].args[1], download.call_args_list[1].args[1])

    def test_fork_revision_comparison(self):
        u = updater()
        for value in ('3.2.1-momo.2', '3.2.1-momo.10', '3.3.0-momo.1', '4.0.0-momo.0'):
            self.assertTrue(u._is_newer_version(value), value)
        for value in ('3.2.1-momo.1', '3.2.1-momo.0', '3.1.9-momo.99', '3.2.2', 'invalid', None, 'v3.2.1-momo.2', '3.2.1-momo.2\n'):
            self.assertFalse(u._is_newer_version(value), value)

    def test_foreign_or_malformed_release_never_downloads(self):
        for data in (metadata(url='https://github.com/arnold2957/wvd/releases/download/3.2.1/wvd.zip'),
                     metadata(url='https://github.com/momo31/other/releases/download/x/wvd.zip'),
                     metadata(url='https://github.com.evil.test/momo31/wvd/releases/download/x/wvd.zip'),
                     metadata(url='https://github.com/momo31/wvd/releases/download/../x/wvd.zip'),
                     metadata('3.2.2'), {'version': '3.2.1-momo.2'}, []):
            with self.subTest(data=data), patch.object(auto_updater.sys, 'frozen', True, create=True):
                u = updater(); u.update_data = data
                self.assertFalse(u._is_allowed_update(data))
                with patch.object(u, '_download_bar_and_retry') as download, patch.object(u, '_create_restart_script') as restart:
                    u.download()
                download.assert_not_called(); restart.assert_not_called()
                self.assertIn('update_manual', [kind for kind, _ in u.msg_queue.queue])
                self.assertEqual(list(u.msg_queue.queue)[-1], ('download_finished', None))

    def test_absent_or_invalid_metadata_offers_manual_fork_release(self):
        for payload in (b'not-json', b'[]', b'{}', json.dumps(metadata('3.2.2')).encode()):
            with self.subTest(payload=payload), patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(auto_updater, 'urlopen', return_value=io.BytesIO(payload)):
                u = updater(); u.check_for_updates()
                self.assertEqual(list(u.msg_queue.queue)[0][0], 'update_manual')
        with patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(auto_updater, 'urlopen', side_effect=HTTPError('fake', 404, 'missing', {}, None)):
            u = updater(); u.check_for_updates()
            self.assertEqual(list(u.msg_queue.queue)[0][1]['url'], 'https://github.com/momo31/wvd/releases')

    def test_source_run_never_downloads_or_checks_network(self):
        with patch.object(auto_updater.sys, 'frozen', False, create=True), patch.object(auto_updater, 'urlopen') as request:
            u = updater(); u.update_data = metadata(); u.check_for_updates(); u.download()
        request.assert_not_called()
        self.assertNotIn('restart_ready', [kind for kind, _ in u.msg_queue.queue])

    def test_restart_waits_for_cleanup_and_runs_once(self):
        c = controller()
        with tempfile.TemporaryDirectory() as directory, patch.object(auto_updater.sys, 'frozen', True, create=True), patch.object(main.subprocess, 'Popen') as restart:
            script = Path(directory) / '_update_restart.ps1'; script.write_text('# test only')
            c.update_downloading = True
            c.updater.restart_script = str(script)
            c.quest_threading = Mock(is_alive=Mock(return_value=True))
            c._dispatch('restart_ready', str(script))
            c._poll_shutdown(); restart.assert_not_called()
            c.quest_threading.is_alive.return_value = False
            c._service_stop_thread.join(1)
            c._poll_shutdown(); c._poll_shutdown()
            restart.assert_called_once()
            c.main_window.destroy.assert_called_once()
            c._force_exit.assert_not_called()

    def test_cancel_and_late_restart_never_restart(self):
        c = controller(); c.update_downloading = True
        c.updater.cancel_event.set()
        with patch.object(main.subprocess, 'Popen') as restart:
            c._dispatch('restart_ready', 'unused.ps1')
        restart.assert_not_called(); self.assertFalse(c._closing)

    def test_archive_cannot_escape_staging_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'update.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../escape.txt', 'bad')
            with self.assertRaises(ValueError):
                updater()._extract_archive(str(archive), str(root / 'stage'))
            self.assertFalse((root / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
