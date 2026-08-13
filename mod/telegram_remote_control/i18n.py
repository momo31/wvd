"""Module-local gettext loader."""

from __future__ import annotations

import gettext
import sys
from pathlib import Path


SUPPORTED_LANGUAGES = {"ko_KR", "en_US", "zh_CN"}


def locale_path() -> Path:
    if getattr(sys, "frozen", False):
        candidates = (
            Path(sys._MEIPASS) / "mod" / "telegram_remote_control" / "locale",
            Path(sys._MEIPASS) / "telegram_remote_control" / "locale",
        )
    else:
        candidates = (Path(__file__).resolve().parent / "locale",)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def get_translator(language: str | None = None):
    language = language if language in SUPPORTED_LANGUAGES else "ko_KR"
    return gettext.translation(
        "telegram_remote_control",
        localedir=str(locale_path()),
        languages=[language],
        fallback=True,
    ).gettext
