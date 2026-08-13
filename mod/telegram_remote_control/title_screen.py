"""Shared recognition helpers for the startup disclaimer and title screen."""

from __future__ import annotations

from typing import Any

from .adapters import ModResourceError
from .constants import (
    STARTUP_DISCLAIMER_ROI,
    STARTUP_DISCLAIMER_TEMPLATE,
    TITLE_LOGO_ROI,
    TITLE_LOGO_TEMPLATE,
    TITLE_TAP_ROI,
    TITLE_TAP_TEMPLATE,
    TITLE_TEMPLATE_THRESHOLD,
)


def match_startup_disclaimer(adapter: Any, screen: Any) -> list[int] | None:
    return _match_mod(
        adapter,
        screen,
        STARTUP_DISCLAIMER_TEMPLATE,
        STARTUP_DISCLAIMER_ROI,
    )


def match_title_logo(adapter: Any, screen: Any) -> list[int] | None:
    """Return the stable title-logo position.

    The animated background and blinking ``Tap to Start`` text are deliberately
    excluded from the title-screen decision. Callers that start the game may
    use :func:`match_title_tap` as an optional tap-position hint.
    """

    return _match_mod(adapter, screen, TITLE_LOGO_TEMPLATE, TITLE_LOGO_ROI)


def match_title_tap(adapter: Any, screen: Any) -> list[int] | None:
    return _match_mod(adapter, screen, TITLE_TAP_TEMPLATE, TITLE_TAP_ROI)


def title_visible(adapter: Any, screen: Any) -> bool:
    return bool(match_title_logo(adapter, screen))


def _match_mod(
    adapter: Any,
    screen: Any,
    name: str,
    roi: tuple[tuple[int, int, int, int], ...],
) -> list[int] | None:
    try:
        return adapter.match_mod(
            screen,
            name,
            roi,
            TITLE_TEMPLATE_THRESHOLD,
        )
    except ModResourceError:
        raise
    except Exception:
        return None
