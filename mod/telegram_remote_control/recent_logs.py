"""Bounded, secret-free excerpts from the active WvDAS text log."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


DEFAULT_WINDOW_SECONDS = 60
MAX_LOG_READ_BYTES = 512 * 1024
TELEGRAM_SAFE_MESSAGE_CHARS = 3900

_LOG_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+-\s+")
_LOG_RECORD = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+-\s+"
    r"(?P<level>[A-Z]+)\s+-\s+\[[^\]]*\]\s+-\s+(?P<message>.*)$"
)
_BOT_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])\d{6,}:[A-Za-z0-9_-]{20,}")
_UI_LEVELS = frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class RecentLogExcerpt:
    file_name: str | None
    text: str
    latest_timestamp: datetime | None
    read_truncated: bool = False


def read_recent_log(
    log_directory: str | Path,
    *,
    now: datetime | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    max_read_bytes: int = MAX_LOG_READ_BYTES,
) -> RecentLogExcerpt:
    """Read timestamped entries from the latest log within the requested window.

    Continuation lines (for example tracebacks) inherit the timestamp of their
    preceding formatted log record. Reading is bounded at the end of the file so
    a Telegram status request cannot stall the Tk event loop on a large log.
    """

    directory = Path(log_directory)
    path = _newest_log_file(directory)
    if path is None:
        return RecentLogExcerpt(None, "", None)

    now_local = _as_local_naive(now or datetime.now()).replace(microsecond=0)
    cutoff = now_local - timedelta(seconds=max(1, int(window_seconds)))
    raw_text, read_truncated = _read_utf8_tail(path, max(1024, int(max_read_bytes)))

    selected: list[str] = []
    current_timestamp: datetime | None = None
    current_ui_message = False
    latest_timestamp: datetime | None = None
    for line in raw_text.splitlines():
        record = _LOG_RECORD.match(line)
        match = record or _LOG_TIMESTAMP.match(line)
        if match:
            try:
                timestamp_text = record.group("timestamp") if record else match.group(1)
                current_timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                current_timestamp = None
            current_ui_message = bool(record is None or record.group("level") in _UI_LEVELS)
            if current_timestamp is not None and (
                latest_timestamp is None or current_timestamp > latest_timestamp
            ):
                latest_timestamp = current_timestamp
        if current_timestamp is not None and current_timestamp >= cutoff and current_ui_message:
            selected.append(record.group("message") if record else line)

    return RecentLogExcerpt(
        file_name=path.name,
        text="\n".join(selected),
        latest_timestamp=latest_timestamp,
        read_truncated=read_truncated,
    )


def redact_log_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove configured secrets and token-shaped values from outbound logs."""

    redacted = _BOT_TOKEN.sub("<redacted-token>", str(text or ""))
    for secret in secrets:
        value = str(secret or "")
        if len(value) >= 6:
            redacted = redacted.replace(value, "<redacted>")
    return redacted


def fit_tail_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep the newest complete log lines inside a Telegram-safe character cap."""

    value = str(text or "")
    limit = max(0, int(max_chars))
    if len(value) <= limit:
        return value, False
    marker = "… 메시지 길이 제한으로 앞부분 생략 …\n"
    if limit <= len(marker):
        return marker[:limit], True
    tail = value[-(limit - len(marker)) :]
    first_newline = tail.find("\n")
    if first_newline >= 0:
        tail = tail[first_newline + 1 :]
    return marker + tail, True


def _newest_log_file(directory: Path) -> Path | None:
    candidates: list[tuple[int, str, Path]] = []
    try:
        paths = directory.glob("log_*.txt")
        for path in paths:
            try:
                candidates.append((path.stat().st_mtime_ns, path.name, path))
            except OSError:
                continue
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates)[2]


def _read_utf8_tail(path: Path, max_bytes: int) -> tuple[str, bool]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read(max_bytes)
    except OSError:
        return "", False
    if start:
        newline = data.find(b"\n")
        data = data[newline + 1 :] if newline >= 0 else b""
    return data.decode("utf-8", errors="replace"), bool(start)


def _as_local_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value
