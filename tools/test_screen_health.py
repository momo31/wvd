import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from screen_health import ScreenHealth, classify_screen


class ScreenHealthTests(unittest.TestCase):
    def test_black_portrait_frame_is_not_actionable(self):
        image = np.zeros((1600, 900, 3), dtype=np.uint8)

        self.assertIs(classify_screen(image), ScreenHealth.BLACK)

    def test_dark_scene_with_ui_highlight_is_normal(self):
        image = np.zeros((1600, 900, 3), dtype=np.uint8)
        image[100:300, 100:400] = 255

        self.assertIs(classify_screen(image), ScreenHealth.NORMAL)

    def test_landscape_frame_is_reported_separately(self):
        image = np.zeros((900, 1600, 3), dtype=np.uint8)

        self.assertIs(classify_screen(image), ScreenHealth.LANDSCAPE)

    def test_invalid_shape_is_rejected(self):
        image = np.zeros((800, 600, 3), dtype=np.uint8)

        self.assertIs(classify_screen(image), ScreenHealth.INVALID)


if __name__ == "__main__":
    unittest.main()
