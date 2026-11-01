"""Validate development packaging inputs without building or running an exe."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gui
import utils

ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_source_and_bundle_html_are_the_same_bytes(self):
        expected_html = (ROOT / 'src/ui.html').read_bytes()
        self.assertEqual(Path(gui.ResolveUiPath()).read_bytes(), expected_html)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'ui.html').write_bytes(expected_html)
            with patch.object(sys, '_MEIPASS', directory, create=True), patch.object(sys, 'frozen', True, create=True):
                self.assertEqual(Path(gui.ResolveUiPath()).read_bytes(), expected_html)

    def test_packaging_contract_includes_webview_and_locales(self):
        ci = (ROOT / '.github/workflows/build-executable.yml').read_text(encoding='utf-8')
        self.assertTrue('needs: validate' in ci)
        self.assertLess(ci.index('Compile development catalogs'), ci.index('Run tools unit tests'))
        for value in ('--collect-all webview', '--add-data "src/ui.html;."', 'mod/telegram_remote_control/locale', "python-version: '3.14'"):
            self.assertTrue(value in ci, value)
        spec = (ROOT / 'tools/wvd.spec.template').read_text(encoding='utf-8')
        for value in ("collect_all('webview')", "('src/ui.html', '.')", "('locale', 'locale')", "('resources', 'resources')", 'mod/telegram_remote_control/locale'):
            self.assertTrue(value in spec, value)
        for language in ('ko_KR', 'en_US', 'zh_CN'):
            for base, domain in [('locale', 'messages'), ('mod/telegram_remote_control/locale', 'telegram_remote_control')]:
                self.assertGreater((ROOT / base / language / 'LC_MESSAGES' / (domain + '.mo')).stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()
