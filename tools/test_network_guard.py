import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from network_guard import (  # noqa: E402
    NETWORK_PROBE_COOLDOWN_SECONDS,
    NETWORK_STALL_SECONDS,
    NetworkStallTracker,
)


class NetworkStallTrackerTests(unittest.TestCase):
    def test_does_not_probe_before_thirty_seconds(self):
        tracker = NetworkStallTracker()
        tracker.observe(("chest", "open_chest", "chestFlag"), 100.0)

        self.assertFalse(tracker.should_probe(100.0 + NETWORK_STALL_SECONDS - 0.01))
        self.assertTrue(tracker.should_probe(100.0 + NETWORK_STALL_SECONDS))

    def test_repeated_input_does_not_reset_stall_clock(self):
        tracker = NetworkStallTracker()
        tracker.observe(("chest", "open_chest", "chestFlag"), 100.0)
        tracker.observe(("chest", "open_chest", "chestFlag"), 125.0)

        self.assertTrue(tracker.should_probe(130.0))

    def test_probe_is_throttled_without_resetting_phase(self):
        tracker = NetworkStallTracker()
        tracker.observe(("chest", "open_chest", "chestFlag"), 100.0)
        tracker.mark_probe(130.0)

        self.assertFalse(
            tracker.should_probe(130.0 + NETWORK_PROBE_COOLDOWN_SECONDS - 0.01)
        )
        self.assertTrue(
            tracker.should_probe(130.0 + NETWORK_PROBE_COOLDOWN_SECONDS)
        )

    def test_phase_change_resets_stall_and_probe_state(self):
        tracker = NetworkStallTracker()
        tracker.observe(("chest", "open_chest", "chestFlag"), 100.0)
        tracker.mark_probe(130.0)

        self.assertTrue(tracker.observe(("chest", "choose", "whowillopenit"), 131.0))
        self.assertFalse(tracker.should_probe(131.0 + NETWORK_STALL_SECONDS - 0.01))
        self.assertIsNone(tracker.last_probe_at)


if __name__ == "__main__":
    unittest.main()
