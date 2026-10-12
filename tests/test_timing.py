import unittest

from timing import SustainTimer


class SustainTimerTests(unittest.TestCase):
    def test_requires_min_duration_before_sustained(self):
        timer = SustainTimer(min_duration_seconds=1.5)
        self.assertFalse(timer.update(True, now=0.0))
        self.assertFalse(timer.update(True, now=1.0))
        self.assertTrue(timer.update(True, now=1.5))

    def test_blink_shorter_than_min_duration_never_sustains(self):
        # A blink (or any brief blip) that ends before the debounce window elapses
        # must never count as "looking down".
        timer = SustainTimer(min_duration_seconds=0.4)
        self.assertFalse(timer.update(True, now=0.0))
        self.assertFalse(timer.update(True, now=0.1))
        self.assertFalse(timer.update(False, now=0.15))  # eyes back up: blink over
        self.assertFalse(timer.update(True, now=0.2))  # condition true again, but timer restarted
        self.assertFalse(timer.update(False, now=0.25))

    def test_condition_becoming_false_resets_the_timer(self):
        timer = SustainTimer(min_duration_seconds=1.0)
        self.assertFalse(timer.update(True, now=0.0))
        self.assertFalse(timer.update(False, now=0.5))
        self.assertFalse(timer.update(True, now=0.6))  # restarted, not yet 1.0s since 0.6
        self.assertTrue(timer.update(True, now=1.6))

    def test_reset_clears_state(self):
        timer = SustainTimer(min_duration_seconds=1.0)
        timer.update(True, now=0.0)
        timer.reset()
        self.assertIsNone(timer.started_at)
        self.assertEqual(timer.elapsed(now=5.0), 0.0)


if __name__ == "__main__":
    unittest.main()
