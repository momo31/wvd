import subprocess
import unittest
from types import SimpleNamespace

from src.adb_recovery import (
    AdbBootState,
    adb_device_is_online,
    probe_adb_boot_state,
)


class AdbBootProbeTests(unittest.TestCase):
    @staticmethod
    def _runner(*, stdout="", stderr="", returncode=0):
        def run(command, **kwargs):
            return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

        return run

    def test_reports_ready_only_for_completed_boot(self):
        result = probe_adb_boot_state(
            "adb.exe",
            "127.0.0.1:16384",
            runner=self._runner(stdout="1\r\n"),
        )
        self.assertEqual(result.state, AdbBootState.READY)

    def test_empty_success_means_android_is_still_booting(self):
        result = probe_adb_boot_state(
            "adb.exe",
            "127.0.0.1:16384",
            runner=self._runner(stdout=""),
        )
        self.assertEqual(result.state, AdbBootState.NOT_READY)

    def test_error_closed_requires_transport_reconnect(self):
        result = probe_adb_boot_state(
            "adb.exe",
            "127.0.0.1:16384",
            runner=self._runner(stderr="error: closed", returncode=1),
        )
        self.assertEqual(result.state, AdbBootState.TRANSPORT_ERROR)
        self.assertIn("error: closed", result.detail)

    def test_timeout_requires_transport_reconnect(self):
        def timeout_runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        result = probe_adb_boot_state(
            "adb.exe",
            "127.0.0.1:16384",
            runner=timeout_runner,
        )
        self.assertEqual(result.state, AdbBootState.TRANSPORT_ERROR)
        self.assertIn("timed out", result.detail)

    def test_device_list_requires_exact_online_serial(self):
        output = "List of devices attached\n127.0.0.1:16384\toffline\nemulator-5554\tdevice\n"
        self.assertFalse(adb_device_is_online(output, "127.0.0.1:16384"))
        self.assertTrue(adb_device_is_online(output, "emulator-5554"))


if __name__ == "__main__":
    unittest.main()
