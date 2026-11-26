import binascii
import struct
import unittest
from dingdong.core import (Action, DEFAULT_CONFIG, Decoder, GestureGate, Pose,
                           encode, validate_config)


class ProtocolTests(unittest.TestCase):
    def test_start_token_round_trip_preserves_unsigned_wrap(self):
        from unittest.mock import Mock
        from dingdong.transport import SerialLink, Reply
        from dingdong.core import GAMEPAD_REQUEST, ACCEPT_REQUEST
        link = SerialLink.__new__(SerialLink)
        link.request = Mock(return_value=Reply(0, 0, -1, 1))
        pending = link.gamepad_request()
        self.assertEqual(pending.token, 65535)
        self.assertTrue(pending.pending)
        link.request.assert_called_with(GAMEPAD_REQUEST)
        link.accept_request(pending.token)
        link.request.assert_called_with(ACCEPT_REQUEST, b"\xff\xff")
    def test_crc_reference_and_wire_layout(self):
        self.assertEqual(binascii.crc_hqx(b"123456789", 0xFFFF), 0x29B1)
        packet = encode(0x10, 42, Pose(-50, 70, -12, 18).pack())
        self.assertEqual(packet[:5], bytes([0xAA, 0x55, 14, 0x10, 42]))
        self.assertEqual(struct.unpack("<hhbbB", packet[5:-2]), (-50, 70, -12, 18, 3))

    def test_all_fragment_boundaries_and_coalesced_frames(self):
        frame = encode(0x81, 254, struct.pack("<BBhh", 0, 1, -240, 240))
        for split in range(len(frame)+1):
            decoder = Decoder()
            packets = decoder.feed(frame[:split]) + decoder.feed(frame[split:] + frame)
            self.assertEqual(len(packets), 2)
            self.assertEqual(packets[0], (0x81, 254, struct.pack("<BBhh", 0, 1, -240, 240)))

    def test_corrupt_crc_bad_length_and_noise_recover(self):
        good = encode(1, 7)
        for index in range(2, len(good)):
            bad = bytearray(good)
            bad[index] ^= 0x80
            decoder = Decoder()
            result = decoder.feed(b"noise\xaa\xaa\x55\x00" + bad + good)
            self.assertIn((1, 7, b""), result)

    def test_motion_limits(self):
        for pose in (Pose(left=241), Pose(right=-241), Pose(pitch=31), Pose(yaw=-61), Pose(mask=4)):
            with self.assertRaises(ValueError):
                pose.pack()


class GestureTests(unittest.TestCase):
    def test_short_flash_never_triggers(self):
        gate = GestureGate()
        self.assertIsNone(gate.observe(3, 0, 0))
        self.assertIsNone(gate.observe(3, .2, 1))
        self.assertIsNone(gate.observe(None, .3, 2))

    def test_held_gesture_fires_once_and_release_rearms(self):
        gate = GestureGate()
        fired = [gate.observe(3, i / 10, i) for i in range(40)]
        self.assertEqual([x for x in fired if x], [3])
        for i in range(40, 51):
            gate.observe(None, i / 10, i)
        fired = [gate.observe(3, i / 10, i) for i in range(51, 61)]
        self.assertEqual([x for x in fired if x], [3])

    def test_duplicate_and_widely_spaced_frames_cannot_confirm(self):
        gate = GestureGate()
        for i in range(10):
            self.assertIsNone(gate.observe(3, i, "same"))
        gate.reset()
        for i in range(10):
            self.assertIsNone(gate.observe(3, i, i))

    def test_different_gesture_can_replace_after_stability(self):
        gate = GestureGate()
        fired = [gate.observe(3 if i < 20 else 5, i / 10, i) for i in range(40)]
        self.assertEqual([x for x in fired if x], [3, 5])


class ActionTests(unittest.TestCase):
    def test_victory_rotates_then_nods_and_finishes(self):
        action = Action(3, 0, DEFAULT_CONFIG)
        self.assertLess(action.sample(1).left, 0)
        self.assertGreater(action.sample(1).right, 0)
        pose = action.sample(3.2)
        self.assertEqual((pose.left, pose.right), (0, 0))
        self.assertNotEqual(pose.pitch, 0)
        self.assertIsNone(action.sample(4.7))

    def test_palm_shakes_before_bounded_reverse(self):
        action = Action(5, 0, DEFAULT_CONFIG)
        self.assertEqual(action.sample(.2).left, 0)
        self.assertNotEqual(action.sample(.2).yaw, 0)
        self.assertEqual(action.sample(1.7).left, -120)
        self.assertIsNone(action.sample(2.3))

    def test_direction_turns_then_pauses_then_walks_and_stops(self):
        for gesture, expected in ((12, (-120, 120)), (13, (120, -120))):
            with self.subTest(gesture=gesture):
                action = Action(gesture, 10, DEFAULT_CONFIG)
                pose = action.sample(10.2)
                self.assertEqual((pose.left, pose.right), expected)
                self.assertEqual((pose.pitch, pose.yaw, pose.mask), (0, 0, 0))
                pose.pack()
                pause = action.sample(10.7)
                self.assertEqual((pause.left, pause.right), (0, 0))
                forward = action.sample(10.9)
                self.assertEqual((forward.left, forward.right), (120, 120))
                self.assertEqual((forward.pitch, forward.yaw, forward.mask), (0, 0, 0))
                self.assertIsNone(action.sample(11.7))

    def test_turn_walk_uses_configured_stage_durations_and_speed(self):
        cfg = dict(DEFAULT_CONFIG, direction_turn_seconds=1.2, direction_pause_seconds=.3,
                   direction_forward_seconds=.4, direction_forward_speed_mm_s=100)
        for gesture in (12, 13):
            action = Action(gesture, 0, cfg)
            self.assertNotEqual(action.sample(1.1).left, action.sample(1.1).right)
            self.assertEqual((action.sample(1.3).left, action.sample(1.3).right), (0, 0))
            self.assertEqual((action.sample(1.6).left, action.sample(1.6).right), (100, 100))
            self.assertIsNone(action.sample(2))

    def test_turn_walk_migration_preserves_modes_and_existing_values(self):
        from apply_turn_walk_update import update_config
        cfg = dict(DEFAULT_CONFIG, enable_motion=False, gamepad_host_request=True,
                   serial_port="/dev/serial/by-id/H60", direction_turn_seconds=1.3)
        for key in ("direction_forward_seconds", "direction_forward_speed_mm_s", "direction_pause_seconds"):
            cfg.pop(key)
        updated = update_config(cfg)
        for key, value in cfg.items():
            self.assertEqual(updated[key], value)
        self.assertEqual(updated["direction_forward_seconds"], .8)
        self.assertEqual(updated["direction_forward_speed_mm_s"], 120)
        self.assertEqual(updated["direction_pause_seconds"], .2)

    def test_update_preserves_live_port_mode_and_calibration(self):
        from apply_direction_update import update_config
        old = dict(DEFAULT_CONFIG, serial_port="/dev/serial/by-id/my-H60", enable_motion=True,
                   turn_seconds=1.75, nod_degrees=8, turn_speed_mm_s=70, reverse_speed_mm_s=50)
        old.pop("direction_turn_seconds")
        old.pop("direction_turn_speed_mm_s")
        new = update_config(old)
        for key in ("serial_port", "enable_motion", "turn_seconds", "nod_degrees"):
            self.assertEqual(new[key], old[key])
        self.assertEqual(new["turn_speed_mm_s"], 120)
        self.assertEqual(new["reverse_speed_mm_s"], 120)
        self.assertEqual(new["direction_turn_seconds"], .6)

    def test_start_update_defaults_to_manual_and_preserves_actions(self):
        from apply_start_button_update import update_config
        old = dict(DEFAULT_CONFIG, enable_motion=True, serial_port="/dev/serial/by-id/H60",
                   direction_turn_seconds=1.2, turn_seconds=1.7)
        updated = update_config(old)
        self.assertFalse(updated["enable_motion"])
        self.assertTrue(updated["gamepad_host_request"])
        for key in ("serial_port", "turn_seconds", "direction_turn_seconds", "turn_speed_mm_s"):
            self.assertEqual(updated[key], old[key])

    def test_config_rejects_excess_reverse_and_nonfinite_duration(self):
        validate_config(DEFAULT_CONFIG)
        for key, value in (("reverse_seconds", 10), ("turn_seconds", float("nan")),
                           ("nod_degrees", 40), ("enable_motion", "false"),
                           ("direction_turn_seconds", 4), ("reverse_speed_mm_s", 121)):
            cfg = dict(DEFAULT_CONFIG, **{key: value})
            with self.assertRaises(ValueError):
                validate_config(cfg)

    def test_turn_walk_rejects_excess_or_invalid_motion(self):
        for key, value in (("direction_forward_seconds", 2.1),
                           ("direction_forward_seconds", float("nan")),
                           ("direction_forward_speed_mm_s", 121),
                           ("direction_pause_seconds", -.1),
                           ("direction_pause_seconds", 1.1)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    validate_config(dict(DEFAULT_CONFIG, **{key: value}))


if __name__ == "__main__":
    unittest.main()
