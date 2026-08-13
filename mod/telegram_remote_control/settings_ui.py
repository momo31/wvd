"""Tk settings panel for the Telegram feature."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .config import TelegramConfigError, validate_telegram_settings
from .models import ConnectionTestRequest, TelegramSettings


@dataclass
class TelegramSettingsWidgets:
    section: Any
    enabled_check: Any
    token_entry: Any
    chat_id_entry: Any
    apply_button: Any
    test_button: Any
    status_label: Any
    active_test_request_id: str | None = None

    def set_test_state(self, enabled: bool) -> None:
        self.test_button.configure(state="normal" if enabled else "disabled")


def mount_telegram_settings(
    parent,
    *,
    enabled_var,
    token_var,
    chat_id_var,
    event_queue,
    save_config: Callable[[], Any],
    translator: Callable[[str], str] = lambda value: value,
) -> TelegramSettingsWidgets:
    import tkinter as tk
    from tkinter import ttk

    section = ttk.LabelFrame(parent, text=translator("텔레그램 원격 제어"))
    section.pack(fill="x", padx=5, pady=5)
    enabled_check = ttk.Checkbutton(section, text=translator("원격 제어 사용"), variable=enabled_var)
    enabled_check.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=3)
    ttk.Label(section, text=translator("Bot Token")).grid(row=1, column=0, sticky="w", padx=5, pady=3)
    token_entry = ttk.Entry(section, textvariable=token_var, show="*")
    token_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=3)
    ttk.Label(section, text=translator("허용 Chat ID")).grid(row=2, column=0, sticky="w", padx=5, pady=3)
    chat_id_entry = ttk.Entry(section, textvariable=chat_id_var)
    chat_id_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=3)
    section.columnconfigure(1, weight=1)
    status_label = ttk.Label(section, text="")
    status_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=3)
    widgets: TelegramSettingsWidgets

    def read_settings() -> TelegramSettings:
        return validate_telegram_settings(TelegramSettings(bool(enabled_var.get()), token_var.get(), chat_id_var.get()))

    def apply() -> None:
        try:
            read_settings()
        except TelegramConfigError as exc:
            status_label.configure(text=str(exc))
            return
        save_config()
        event_queue.put(("telegram_reconfigure", None))
        status_label.configure(text=translator("저장 및 적용 완료"))

    def test() -> None:
        try:
            settings = read_settings()
        except TelegramConfigError as exc:
            status_label.configure(text=str(exc))
            return
        request_id = uuid.uuid4().hex
        widgets.active_test_request_id = request_id
        widgets.set_test_state(False)
        status_label.configure(text=translator("연결 확인 중..."))
        event_queue.put(("telegram_test_connection", ConnectionTestRequest(request_id, settings)))

    apply_button = ttk.Button(section, text=translator("저장 및 적용"), command=apply)
    apply_button.grid(row=3, column=0, padx=5, pady=3, sticky="ew")
    test_button = ttk.Button(section, text=translator("연결 테스트"), command=test)
    test_button.grid(row=3, column=1, padx=5, pady=3, sticky="ew")
    widgets = TelegramSettingsWidgets(
        section,
        enabled_check,
        token_entry,
        chat_id_entry,
        apply_button,
        test_button,
        status_label,
    )
    return widgets

