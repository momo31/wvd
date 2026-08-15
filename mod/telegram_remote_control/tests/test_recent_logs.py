from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mod.telegram_remote_control.recent_logs import (
    fit_tail_text,
    read_recent_log,
    redact_log_text,
)


class RecentLogTests(unittest.TestCase):
    def test_reads_only_last_minute_from_newest_log_with_continuations(self):
        now = datetime(2026, 8, 14, 12, 0, 0)
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            old_file = log_dir / "log_260814-110000.txt"
            old_file.write_text(
                "2026-08-14 11:59:55 - INFO - [old:line:1] - wrong file\n",
                encoding="utf-8",
            )
            current_file = log_dir / "log_260814-115900.txt"
            current_file.write_text(
                "2026-08-14 11:58:00 - INFO - [macro:run:1] - too old\n"
                "2026-08-14 11:59:10 - DEBUG - [macro:run:1] - debug not shown in UI\n"
                "2026-08-14 11:59:20 - INFO - [macro:run:2] - recent A\n"
                "continued detail\n"
                "2026-08-14 11:59:59 - ERROR - [macro:run:3] - recent B\n",
                encoding="utf-8",
            )
            os.utime(old_file, (1, 1))
            os.utime(current_file, (2, 2))

            result = read_recent_log(log_dir, now=now)

        self.assertEqual(result.file_name, current_file.name)
        self.assertNotIn("too old", result.text)
        self.assertNotIn("wrong file", result.text)
        self.assertNotIn("debug not shown in UI", result.text)
        self.assertEqual(
            result.text,
            "recent A\ncontinued detail\nrecent B",
        )
        self.assertIn("continued detail", result.text)
        self.assertIn("recent B", result.text)
        self.assertEqual(result.latest_timestamp, datetime(2026, 8, 14, 11, 59, 59))

    def test_redacts_configured_and_token_shaped_secrets(self):
        token = "8700047422:" + "A" * 35
        text = f"token={token} chat=123456789 and 777777:{'b' * 24}"
        result = redact_log_text(text, (token, "123456789"))
        self.assertNotIn(token, result)
        self.assertNotIn("123456789", result)
        self.assertNotIn("777777:", result)
        self.assertIn("<redacted-token>", result)

    def test_fit_tail_text_preserves_character_limit(self):
        result, truncated = fit_tail_text("old line\n" + "x" * 100 + "\nnew line", 60)
        self.assertTrue(truncated)
        self.assertLessEqual(len(result), 60)
        self.assertIn("new line", result)
        self.assertNotIn("old line", result)


if __name__ == "__main__":
    unittest.main()
