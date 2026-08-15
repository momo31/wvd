"""Bounded ADB boot-state probes used by emulator recovery."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class AdbBootState(Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True)
class AdbBootProbe:
    state: AdbBootState
    detail: str = ""


_TRANSPORT_ERROR_MARKERS = (
    "error: closed",
    "device offline",
    "offline",
    "device not found",
    "no devices/emulators found",
    "cannot connect",
    "connection refused",
    "protocol fault",
)


def adb_device_is_online(devices_output: str, serial: str) -> bool:
    """Return True only when ``adb devices`` reports this serial as ready."""

    expected = str(serial).strip()
    for line in str(devices_output or "").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == expected and fields[1] == "device":
            return True
    return False


def probe_adb_boot_state(
    adb_path: str,
    serial: str,
    *,
    timeout_seconds: float = 5.0,
    runner: Callable = subprocess.run,
) -> AdbBootProbe:
    """Return Android boot state without allowing an ADB shell to hang.

    ``pure-python-adb`` shell calls do not expose a reliable command timeout.
    A short-lived adb subprocess gives recovery code a hard upper bound and
    lets it distinguish a booting Android guest from a broken transport.
    """

    command = [
        str(adb_path),
        "-s",
        str(serial),
        "shell",
        "getprop",
        "sys.boot_completed",
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, float(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return AdbBootProbe(AdbBootState.TRANSPORT_ERROR, "boot probe timed out")
    except OSError as exc:
        return AdbBootProbe(AdbBootState.TRANSPORT_ERROR, str(exc))

    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    combined = "\n".join(part for part in (stdout, stderr) if part).lower()

    if result.returncode == 0 and stdout == "1":
        return AdbBootProbe(AdbBootState.READY)
    if result.returncode != 0 or any(marker in combined for marker in _TRANSPORT_ERROR_MARKERS):
        return AdbBootProbe(
            AdbBootState.TRANSPORT_ERROR,
            combined or f"adb exited with code {result.returncode}",
        )
    return AdbBootProbe(AdbBootState.NOT_READY, stdout)
