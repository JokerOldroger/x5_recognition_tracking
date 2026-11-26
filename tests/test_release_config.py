import unittest

from prepare_config import prepare


class ReleaseConfigTests(unittest.TestCase):
    def test_preserves_live_port_and_calibration_and_adds_missing_fields(self):
        original = {"serial_port": "/dev/serial/by-id/custom", "turn_seconds": 2.4,
                    "direction_forward_seconds": 0.4, "nod_degrees": 9,
                    "enable_motion": True, "gamepad_host_request": False}
        config = prepare(original)
        self.assertEqual(config["serial_port"], original["serial_port"])
        self.assertEqual(config["turn_seconds"], 2.4)
        self.assertEqual(config["direction_forward_seconds"], 0.4)
        self.assertEqual(config["nod_degrees"], 9)
        self.assertIn("direction_pause_seconds", config)
        self.assertFalse(config["enable_motion"])
        self.assertTrue(config["gamepad_host_request"])
        self.assertTrue(original["enable_motion"])

    def test_clean_install_defaults_to_manual(self):
        config = prepare({})
        self.assertFalse(config["enable_motion"])
        self.assertEqual(config["turn_speed_mm_s"], 120)
        self.assertEqual(config["direction_forward_speed_mm_s"], 120)
