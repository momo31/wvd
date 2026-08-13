"""Configuration and secret-validation helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from .models import TelegramSettings


class TelegramConfigError(ValueError):
    """A user-facing configuration error with no secret data."""


TOKEN_RE = re.compile(r"^(\d+):([^\s]{20,})$")


def extend_config_var_list(base_list: list, tk_module: Any) -> list:
    """Return a copy of the app config list with Telegram GENERAL keys."""

    result = list(base_list)
    names = {item[1] for item in result if len(item) > 1}
    additions = (
        ("TELEGRAM_ENABLED", tk_module.BooleanVar, False),
        ("TELEGRAM_BOT_TOKEN", tk_module.StringVar, ""),
        ("TELEGRAM_ALLOWED_CHAT_ID", tk_module.StringVar, ""),
    )
    for name, var_type, default in additions:
        if name not in names:
            result.append(["GENERAL", name, var_type, default])
    return result


def mask_token(token: str | None) -> str:
    return "***" if str(token or "").strip() else "<empty>"


def validate_telegram_settings(settings: TelegramSettings) -> TelegramSettings:
    enabled = bool(settings.enabled)
    token = str(settings.bot_token or "").strip()
    chat_id = str(settings.allowed_chat_id or "").strip()
    if not enabled:
        return TelegramSettings(False, token, chat_id)
    match = TOKEN_RE.fullmatch(token)
    if not match:
        raise TelegramConfigError("Bot Token 형식이 올바르지 않습니다.")
    if not chat_id.isdecimal():
        raise TelegramConfigError("허용 Chat ID는 양의 정수여야 합니다.")
    try:
        numeric_chat_id = int(chat_id, 10)
    except ValueError as exc:  # pragma: no cover - isdecimal guards this
        raise TelegramConfigError("허용 Chat ID가 올바르지 않습니다.") from exc
    if not 1 <= numeric_chat_id <= 2**63 - 1:
        raise TelegramConfigError("허용 Chat ID 범위를 확인하십시오.")
    return TelegramSettings(True, token, chat_id)


def _load_raw(path: str | None, load_raw: Callable[[str | None], dict | None]) -> dict:
    try:
        data = load_raw(path)
    except TelegramConfigError:
        raise
    except Exception as exc:
        raise TelegramConfigError("설정 파일을 읽지 못했습니다.") from exc
    if data is None:
        raise TelegramConfigError("설정 파일을 읽지 못했습니다.")
    if not isinstance(data, dict):
        raise TelegramConfigError("설정 파일 형식이 올바르지 않습니다.")
    return data


def read_telegram_settings(
    config_path: str | os.PathLike[str] | None,
    load_raw: Callable[[str | None], dict | None],
) -> TelegramSettings:
    """Read only GENERAL Telegram keys; never merge task settings."""

    path = str(Path(config_path).resolve(strict=False)) if config_path else None
    raw = _load_raw(path, load_raw)
    general = raw.get("GENERAL") or {}
    if not isinstance(general, dict):
        raise TelegramConfigError("GENERAL 설정 형식이 올바르지 않습니다.")
    settings = TelegramSettings(
        bool(general.get("TELEGRAM_ENABLED", False)),
        str(general.get("TELEGRAM_BOT_TOKEN", "") or ""),
        str(general.get("TELEGRAM_ALLOWED_CHAT_ID", "") or ""),
    )
    return validate_telegram_settings(settings)


def load_latest_farm_setting(
    config_path: str | os.PathLike[str] | None,
    load_raw: Callable[[str | None], dict | None],
    build_setting: Callable[[dict], Any],
) -> Any:
    path = str(Path(config_path).resolve(strict=False)) if config_path else None
    raw = _load_raw(path, load_raw)
    general = dict(raw.get("GENERAL") or {})
    target = general.get("FARM_TARGET")
    if general.get("TASK_SPECIFIC_CONFIG") and target:
        task = dict(raw.get(str(target)) or {})
    else:
        task = dict(raw.get("DEFAULT") or {})
    merged = {**general, **task}
    setting = build_setting(merged)
    if not getattr(setting, "FARM_TARGET", None):
        raise TelegramConfigError("실행할 매크로가 설정되지 않았습니다.")
    return setting


def resolve_adb_executable(emu_path: str | os.PathLike[str] | None) -> str | None:
    if not emu_path:
        return None
    path = Path(emu_path)
    name = path.name.lower()
    if name == "hd-player.exe":
        candidate = path.with_name("HD-Adb.exe")
    elif name in {"mumuplayer.exe", "mumunxdevice.exe"}:
        candidate = path.with_name("adb.exe")
    else:
        candidate = path.with_name("adb.exe")
    return str(candidate) if candidate.is_file() else None


def clear_telegram_secrets(setting: Any) -> None:
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
        if hasattr(setting, name):
            setattr(setting, name, "")


def load_json_file(path: str | os.PathLike[str]) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise TelegramConfigError("설정 파일을 읽지 못했습니다.") from exc
    if not isinstance(value, dict):
        raise TelegramConfigError("설정 파일 형식이 올바르지 않습니다.")
    return value

