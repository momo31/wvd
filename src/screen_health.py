"""Small, emulator-independent helpers for validating captured frames.

The automation state machine must not interpret a black or rotated frame as a
valid dungeon screen.  Keeping the pixel heuristics here makes them testable
without starting an emulator or importing the Tkinter application.
"""

from enum import Enum

import numpy as np


class ScreenHealth(Enum):
    """Classification of a raw emulator screenshot."""

    NORMAL = "normal"
    BLACK = "black"
    LANDSCAPE = "landscape"
    INVALID = "invalid"


def classify_screen(image, *, black_mean=4.0, black_pixel=8.0, black_fraction=0.02):
    """Classify a BGR screenshot using shape and conservative black-frame rules.

    ``(height, width) == (1600, 900)`` is the only supported portrait frame.
    A frame is considered black only when both its mean luminance and the
    fraction of pixels above ``black_pixel`` are low.  This avoids treating a
    dark dungeon scene with normal UI highlights as a blank capture.
    """

    if image is None or not hasattr(image, "shape"):
        return ScreenHealth.INVALID

    shape = tuple(image.shape[:2])
    if shape == (900, 1600):
        return ScreenHealth.LANDSCAPE
    if shape != (1600, 900) or len(image.shape) < 2:
        return ScreenHealth.INVALID

    pixels = np.asarray(image)
    if pixels.size == 0:
        return ScreenHealth.INVALID
    if pixels.ndim == 2:
        luminance = pixels.astype(np.float32)
    else:
        luminance = pixels[..., :3].astype(np.float32).mean(axis=2)

    bright_fraction = float(np.count_nonzero(luminance > black_pixel)) / luminance.size
    if float(luminance.mean()) <= black_mean and bright_fraction <= black_fraction:
        return ScreenHealth.BLACK
    return ScreenHealth.NORMAL


def is_black_screen(image):
    """Return whether ``image`` is a likely blank/black emulator capture."""

    return classify_screen(image) is ScreenHealth.BLACK
