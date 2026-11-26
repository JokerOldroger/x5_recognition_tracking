import unittest
from unittest.mock import patch

from wait_clock import ClockReady, main


class ClockTests(unittest.TestCase):
    def test_late_clock_correction_starts_without_service_restart(self):
        with patch("wait_clock.time.monotonic", side_effect=[0, 180, 181, 186]), \
                patch("wait_clock.time.time", side_effect=[946684800, 1792910970,
                                                          1792910971, 1792910976]), \
                patch("wait_clock.time.sleep") as sleep, patch("builtins.print") as output:
            main()
        self.assertEqual(sleep.call_count, 3)
        self.assertIn("System clock ready", output.call_args.args[0])

    def test_year_2000_never_starts_camera(self):
        clock = ClockReady()
        for elapsed in range(20):
            self.assertFalse(clock.observe(946684800 + elapsed, elapsed))

    def test_valid_offline_clock_does_not_require_ntp(self):
        clock = ClockReady()
        self.assertFalse(clock.observe(1792910970, 0))
        self.assertTrue(clock.observe(1792910975, 5))

    def test_forward_and_backward_steps_restart_stability_wait(self):
        for change in (100, -100):
            clock = ClockReady()
            self.assertFalse(clock.observe(1792910970, 0))
            self.assertFalse(clock.observe(1792910974, 4))
            self.assertFalse(clock.observe(1792910975 + change, 5))
            self.assertFalse(clock.observe(1792910976 + change, 6))
            self.assertFalse(clock.observe(1792910980 + change, 10))
            self.assertTrue(clock.observe(1792910981 + change, 11))


if __name__ == "__main__":
    unittest.main()
