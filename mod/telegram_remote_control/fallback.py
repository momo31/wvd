"""Single-owner game force-stop fallback."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from .constants import (
    FALLBACK_SUBPROCESS_TIMEOUT_SECONDS,
    FALLBACK_VERIFY_TIMEOUT_SECONDS,
    FALLBACK_WAIT_TIMEOUT_SECONDS,
    GAME_PACKAGE,
)
from .models import ForceStopResult, TransitionOutcome, TransitionStatus
from .runtime_bridge import RemoteRuntime


def force_stop_game_once(
    adapter: Any,
    runtime: RemoteRuntime,
    *,
    failure_phase: str,
) -> TransitionOutcome:
    owner = runtime.begin_timeout_fallback()
    if not owner:
        if runtime.worker_force_stop_event.is_set() and not runtime.is_timeout_fallback_started():
            return TransitionOutcome(TransitionStatus.LOCAL_ABORT, "로컬 중지가 먼저 처리되었습니다.", failure_phase)
        if runtime.fallback_done.is_set() and runtime.fallback_succeeded is False:
            return TransitionOutcome(TransitionStatus.ERROR, "게임 종료 확인에 실패했습니다.", failure_phase)
        result = runtime.wait_for_fallback(FALLBACK_WAIT_TIMEOUT_SECONDS)
        if result is True:
            return TransitionOutcome(TransitionStatus.FALLBACK_COMPLETE, "게임을 종료했습니다.", failure_phase)
        return TransitionOutcome(TransitionStatus.ERROR, "게임 종료 확인에 실패했습니다.", failure_phase)

    stopped = False
    detail = "게임 종료 확인에 실패했습니다."
    try:
        transports = _select_transports(adapter, runtime)
        if not transports:
            runtime.mark_exit("error", detail, failure_phase)
            runtime.finish_fallback(False, detail, failure_phase)
            return TransitionOutcome(TransitionStatus.ERROR, detail, failure_phase)
        for transport in transports:
            try:
                running = _is_running(transport)
                if running is False:
                    stopped = True
                elif running is True:
                    _force_stop(transport)
                    stopped = _wait_stopped(transport)
                    if not stopped:
                        _force_stop(transport)
                        stopped = _wait_stopped(transport)
                if stopped:
                    break
            except Exception:
                # An adapter-bound shell can be stale while the external ADB
                # executable remains usable; try the next transport.
                continue
        if stopped:
            detail = "게임을 강제 종료했습니다."
            runtime.mark_exit("remote_stop_fallback", detail, failure_phase)
            runtime.finish_fallback(True, detail, failure_phase)
            outcome = TransitionOutcome(TransitionStatus.FALLBACK_COMPLETE, detail, failure_phase)
        else:
            runtime.mark_exit("error", detail, failure_phase)
            runtime.finish_fallback(False, detail, failure_phase)
            outcome = TransitionOutcome(TransitionStatus.ERROR, detail, failure_phase)
    except Exception:
        runtime.mark_exit("error", detail, failure_phase)
        runtime.finish_fallback(False, detail, failure_phase)
        outcome = TransitionOutcome(TransitionStatus.ERROR, detail, failure_phase)
    finally:
        runtime.worker_force_stop_event.set()
        try:
            runtime.event_queue.put(
                (
                    "remote_force_stop_result",
                    ForceStopResult(runtime.run_id, stopped, detail),
                )
            )
        except Exception:
            pass
    return outcome


class _AdapterTransport:
    def __init__(self, adapter):
        self.adapter = adapter

    def run(self, argv):
        return self.adapter.control_shell(list(argv))


class _AdbTransport:
    def __init__(self, executable: str, address: str):
        self.executable = executable
        self.address = address

    def run(self, argv):
        command = [self.executable, "-s", self.address, "shell", *argv]
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=FALLBACK_SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError("ADB command failed")
        return result.stdout or ""


def _select_transports(adapter, runtime):
    transports = []
    if adapter is not None:
        transports.append(_AdapterTransport(adapter))
    if runtime.adb_executable:
        transports.append(_AdbTransport(runtime.adb_executable, runtime.adb_address))
    return transports


def _select_transport(adapter, runtime):
    """Backward-compatible single transport helper for callers/tests."""
    transports = _select_transports(adapter, runtime)
    return transports[0] if transports else None


def _is_running(transport) -> bool | None:
    try:
        output = str(transport.run(["pidof", GAME_PACKAGE]) or "").strip()
    except Exception:
        try:
            output = str(transport.run(["dumpsys", "activity", "processes"]) or "")
        except Exception:
            return None
        return GAME_PACKAGE in output
    if not output:
        return False
    if re.search(r"(?:not found|unknown command|no such file)", output, re.I):
        try:
            output = str(transport.run(["dumpsys", "activity", "processes"]) or "")
        except Exception:
            return None
        return GAME_PACKAGE in output
    return bool(re.search(r"\b\d+\b", output))


def _force_stop(transport) -> None:
    transport.run(["am", "force-stop", GAME_PACKAGE])


def _wait_stopped(transport) -> bool:
    deadline = time.monotonic() + FALLBACK_VERIFY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = _is_running(transport)
        if state is False:
            return True
        time.sleep(0.5)
    return False
