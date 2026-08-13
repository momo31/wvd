"""Adapters that isolate the feature from the legacy automation code."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

try:  # OpenCV is a normal WvDAS dependency, but keep imports test-friendly.
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - only exercised in minimal environments
    cv2 = None
    np = None

from .constants import TITLE_TEMPLATE_THRESHOLD


class ModResourceError(RuntimeError):
    pass


def module_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "mod" / "telegram_remote_control"
    return Path(__file__).resolve().parent


def image_root() -> Path:
    root = module_root()
    candidates = [
        root / "resources" / "images",
        root.parent.parent / "resources" / "images",
    ]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys._MEIPASS) / "resources" / "images")
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.png")):
            return candidate
    # Keep a deterministic path in error messages when the packaged resource
    # tree is incomplete.
    return candidates[0]


@dataclass(frozen=True)
class GameAutomationAdapter:
    screenshot: Callable[[], Any]
    match_base: Callable[[Any, str, Sequence[Sequence[int]] | None, float], list[int] | None]
    is_black_frame: Callable[[Any], bool]
    press: Callable[[list[int]], bool]
    press_back: Callable[[], None]
    sleep: Callable[[float], None]
    try_press_retry: Callable[[Any], bool]
    device_shell: Callable[[str], str]
    control_shell: Callable[[list[str]], str]
    return_via_quest_rtt: Callable[[], bool]
    finish_combat_or_chest: Callable[[str], bool]
    local_stop_requested: Callable[[], bool]
    local_stop_exception_type: type[BaseException]
    failure_dir: Path

    def match_mod(
        self,
        screen: Any,
        name: str,
        roi: Sequence[Sequence[int]] | None = None,
        threshold: float = TITLE_TEMPLATE_THRESHOLD,
    ) -> list[int] | None:
        if cv2 is None or np is None:
            raise ModResourceError("OpenCV를 불러오지 못했습니다.")
        path = image_root() / name
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        if not path.is_file():
            raise ModResourceError(f"모듈 이미지가 없습니다: {path.name}")
        template = _load_template(path)
        if screen is None or not hasattr(screen, "shape"):
            return None
        image = np.asarray(screen)
        search = image
        offset_x = offset_y = 0
        if roi:
            x, y, w, h = [int(v) for v in roi[0]]
            if w <= 0 or h <= 0:
                return None
            offset_x, offset_y = x, y
            search = image[y : y + h, x : x + w]
        if template.shape[0] > search.shape[0] or template.shape[1] > search.shape[1]:
            return None
        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        if max_value < float(threshold):
            return None
        return [
            int(offset_x + max_location[0] + template.shape[1] // 2),
            int(offset_y + max_location[1] + template.shape[0] // 2),
        ]

    def save_failure_frame(self, screen: Any, phase: str) -> str | None:
        if cv2 is None or screen is None:
            return None
        safe_phase = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(phase))[:80]
        safe_phase = safe_phase or "unknown"
        self.failure_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.failure_dir / f"remote_{safe_phase}_{timestamp}.png"
        try:
            if cv2.imwrite(os.fspath(path), np.asarray(screen)):
                return str(path)
        except Exception:
            return None
        return None


def _load_template(path: Path):
    key = os.fspath(path)
    cache = getattr(_load_template, "_cache", None)
    if cache is None:
        cache = _load_template._cache = {}
    if key in cache:
        return cache[key]
    data = np.fromfile(key, dtype=np.uint8)
    template = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if template is None:
        raise ModResourceError(f"모듈 이미지를 해석하지 못했습니다: {path.name}")
    cache[key] = template
    return template


@dataclass(frozen=True)
class ControllerPorts:
    load_raw_config: Callable[[str | None], dict | None]
    load_latest_setting: Callable[[], Any]
    start_task: Callable[[Any, Any, str, Any], bool]
    task_is_alive: Callable[[], bool]
    sync_ui_state: Callable[[Any], None]
    schedule_after: Callable[[int, Callable[[], None]], None]
    show_test_result: Callable[[Any], None] | None = None
