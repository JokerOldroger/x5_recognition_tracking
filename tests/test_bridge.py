"""Exercise failure paths without requiring ROS or a connected robot."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

# Minimal ROS import substitutes. No production safety policy is replaced.
for name in ("rclpy", "rclpy.node", "rclpy.qos", "rclpy.executors", "ai_msgs", "ai_msgs.msg",
             "std_srvs", "std_srvs.srv"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rclpy.node"].Node = object
sys.modules["rclpy.qos"].qos_profile_sensor_data = object()
sys.modules["rclpy.executors"].ExternalShutdownException = type("ExternalShutdownException", (Exception,), {})
sys.modules["ai_msgs.msg"].PerceptionTargets = object
sys.modules["std_srvs.srv"].SetBool = object

from dingdong.bridge import Bridge
from dingdong.core import Action, DEFAULT_CONFIG, GestureGate
from dingdong.transport import Reply, GamepadRequest


def bridge():
    node = Bridge.__new__(Bridge)
    node.cfg = dict(DEFAULT_CONFIG)
    node.link = Mock()
    node.link.control.return_value = Reply(0, 1, 0, 0)
    node.enabled = True
    node.action = Action(3, 100, node.cfg)
    node.gate = GestureGate()
    node.last_vision = 100
    node.last_stamp = None
    node.vision_stale = False
    node.next_request_poll = 0
    node.request_blocked_until_clear = False
    node.request_failed_id = None
    node.request_protocol_warned = False
    node.last_link_error_log = -float("inf")
    node.link.gamepad_request.return_value = GamepadRequest(0, 0, 0, False)
    node.get_logger = Mock(return_value=Mock())
    node.get_clock = Mock(return_value=types.SimpleNamespace(
        now=lambda: types.SimpleNamespace(nanoseconds=int(100e9))))
    return node


class BridgeSafetyTests(unittest.TestCase):
    def test_start_request_requires_conditional_accept_not_unconditional_arm(self):
        node = bridge()
        node.enabled = False
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 7, True)
        node.link.accept_request.return_value = Reply(0, 1, 0, 0)
        with patch("dingdong.bridge.time.monotonic", return_value=100.1):
            node.tick()
        self.assertTrue(node.enabled)
        node.link.accept_request.assert_called_once_with(7)
        node.link.arm.assert_not_called()
        self.assertIsNone(node.action)

    def test_manual_input_between_poll_and_accept_does_not_rearm(self):
        node = bridge()
        node.enabled = False
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 7, True)
        node.link.accept_request.return_value = Reply(2, 0, 0, 0)
        node.poll_gamepad_request(100)
        node.poll_gamepad_request(100.3)
        self.assertFalse(node.enabled)
        node.link.accept_request.assert_called_once_with(7)
        node.link.arm.assert_not_called()

    def test_no_start_request_never_acquires_control(self):
        node = bridge()
        node.enabled = False
        node.poll_gamepad_request(100)
        node.poll_gamepad_request(100.3)
        node.link.accept_request.assert_not_called()
        node.link.arm.assert_not_called()

    def test_busy_request_retries_only_conditional_token(self):
        node = bridge()
        node.enabled = False
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 12, True)
        node.link.accept_request.side_effect = [Reply(3, 0, 0, 0), Reply(0, 1, 0, 0)]
        node.poll_gamepad_request(100)
        self.assertFalse(node.enabled)
        node.poll_gamepad_request(100.6)
        self.assertTrue(node.enabled)
        self.assertEqual(node.link.accept_request.call_count, 2)
        node.link.arm.assert_not_called()

    def test_reconnected_pending_token_is_ignored_until_clear_then_new_press(self):
        node = bridge()
        node.enabled = False
        node.request_blocked_until_clear = True
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 3, True)
        node.poll_gamepad_request(100)
        node.link.accept_request.assert_not_called()
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 3, False)
        node.poll_gamepad_request(100.3)
        node.link.gamepad_request.return_value = GamepadRequest(0, 0, 4, True)
        node.link.accept_request.return_value = Reply(0, 1, 0, 0)
        node.poll_gamepad_request(100.6)
        node.link.accept_request.assert_called_once_with(4)

    def test_old_firmware_does_not_fall_back_to_unconditional_arm(self):
        node = bridge()
        node.enabled = False
        node.link.gamepad_request.return_value = GamepadRequest(1, 0, 0, False)
        node.poll_gamepad_request(100)
        node.link.arm.assert_not_called()
        node.link.accept_request.assert_not_called()

    def publish_gesture(self, node, value=3, confidence=0):
        for i in range(10):
            now = 100 + i * .1
            sec = int(now)
            msg = types.SimpleNamespace(
                header=types.SimpleNamespace(stamp=types.SimpleNamespace(
                    sec=sec, nanosec=round((now-sec)*1e9)), frame_id=str(i)),
                targets=[types.SimpleNamespace(rois=[types.SimpleNamespace(type="hand")],
                    attributes=[types.SimpleNamespace(type="gesture", value=value, confidence=confidence)])])
            node.get_clock.return_value = types.SimpleNamespace(
                now=lambda: types.SimpleNamespace(nanoseconds=int(now*1e9)))
            with patch("dingdong.bridge.time.monotonic", return_value=now):
                node.on_gesture(msg)

    def test_official_unset_confidence_triggers_victory(self):
        node = bridge()
        node.action = None
        self.publish_gesture(node, 3, 0)
        self.assertIsNotNone(node.action)
        self.assertEqual(node.action.gesture, 3)

    def test_official_unset_confidence_triggers_palm(self):
        node = bridge()
        node.action = None
        self.publish_gesture(node, 5, 0)
        self.assertEqual(node.action.gesture, 5)

    def test_official_direction_gestures_trigger_correct_wheel_direction(self):
        for value, expected in ((12, (-120, 120)), (13, (120, -120))):
            with self.subTest(gesture=value):
                node = bridge()
                node.action = None
                self.publish_gesture(node, value, 0)
                self.assertIsNotNone(node.action)
                self.assertEqual(node.action.gesture, value)
                pose = node.action.sample(node.action.start + .1)
                self.assertEqual((pose.left, pose.right), expected)

    def test_direction_hold_fires_once_and_no_motion_when_disabled(self):
        for value in (12, 13):
            node = bridge()
            node.action = None
            self.publish_gesture(node, value, 0)
            logs = [str(call) for call in node.get_logger.return_value.info.call_args_list]
            self.assertEqual(sum("Thumb" in line for line in logs), 1)
            node = bridge()
            node.action = None
            node.enabled = False
            self.publish_gesture(node, value, 0)
            self.assertIsNone(node.action)

    def test_explicit_scored_producer_still_filters_low_confidence(self):
        node = bridge()
        node.action = None
        node.cfg["gesture_confidence_available"] = True
        self.publish_gesture(node, 3, .2)
        self.assertIsNone(node.action)

    def test_recognition_only_never_creates_action(self):
        node = bridge()
        node.enabled = False
        node.action = None
        self.publish_gesture(node, 3, 0)
        self.assertIsNone(node.action)

    def test_manual_takeover_cancels_without_stop_or_rearm(self):
        node = bridge()
        node.link.control.return_value = Reply(2, 0, 50, 50)
        with patch("dingdong.bridge.time.monotonic", return_value=100.1):
            node.tick()
            node.tick()
        self.assertFalse(node.enabled)
        self.assertIsNone(node.action)
        node.link.control.assert_called_once()
        node.link.arm.assert_not_called()
        node.link.stop.assert_not_called()

    def test_diagnostic_failure_does_not_interrupt_manual_or_rearm(self):
        node = bridge()
        node.link.control.return_value = Reply(2, 0, 0, 0)
        node.link.exit_diagnostics.side_effect = RuntimeError("old firmware")
        with patch("dingdong.bridge.time.monotonic", return_value=100.1):
            node.tick()
        self.assertFalse(node.enabled)
        self.assertIsNone(node.action)
        node.link.stop.assert_not_called()
        node.link.arm.assert_not_called()
        node.link.close.assert_not_called()
        self.assertTrue(any("Exit diagnostics unavailable" in str(c)
                            for c in node.get_logger().warn.call_args_list))

    def test_ack_failure_latches_disabled(self):
        node = bridge()
        previous_link = node.link
        node.link.control.side_effect = RuntimeError("cable unplugged")
        with patch("dingdong.bridge.time.monotonic", return_value=100.1), \
                patch("dingdong.bridge.SerialLink", side_effect=RuntimeError("USB absent")):
            node.tick()
            node.tick()
        self.assertFalse(node.enabled)
        previous_link.stop.assert_called_once()
        previous_link.arm.assert_not_called()
        self.assertIsNone(node.link)
        self.assertTrue(node.request_blocked_until_clear)

    def test_vision_loss_cancels_moving_action(self):
        node = bridge()
        with patch("dingdong.bridge.time.monotonic", return_value=101.1):
            node.tick()
        pose = node.link.control.call_args.args[0]
        self.assertEqual((pose.left, pose.right, pose.pitch, pose.yaw), (0, 0, 0, 0))
        self.assertIsNone(node.action)

    def test_vision_loss_cancels_forward_stage_of_both_direction_actions(self):
        for gesture in (12, 13):
            node = bridge()
            node.action = Action(gesture, 100, node.cfg)
            with patch("dingdong.bridge.time.monotonic", return_value=101.1):
                node.tick()
            pose = node.link.control.call_args.args[0]
            self.assertEqual((pose.left, pose.right), (0, 0))
            self.assertIsNone(node.action)

    def test_manual_takeover_during_forward_stage_cannot_resume_motion(self):
        node = bridge()
        node.action = Action(12, 100, node.cfg)
        node.link.control.return_value = Reply(2, 0, 50, 50)
        with patch("dingdong.bridge.time.monotonic", return_value=100.9):
            node.tick()
        pose = node.link.control.call_args.args[0]
        self.assertEqual((pose.left, pose.right), (120, 120))
        self.assertFalse(node.enabled)
        self.assertIsNone(node.action)
        with patch("dingdong.bridge.time.monotonic", return_value=101):
            node.tick()
        node.link.control.assert_called_once()
        node.link.arm.assert_not_called()

    def test_stale_ros_frame_does_not_refresh_vision(self):
        node = bridge()
        message = types.SimpleNamespace(header=types.SimpleNamespace(
            stamp=types.SimpleNamespace(sec=90, nanosec=0), frame_id="1"), targets=[])
        node.on_gesture(message)
        self.assertEqual(node.last_vision, 100)
        self.assertIsNone(node.last_stamp)

    def test_explicit_enable_resets_old_action(self):
        node = bridge()
        node.link.arm.return_value = Reply(0, 1, 0, 0)
        self.assertTrue(node.enable())
        self.assertIsNone(node.action)
        node.link.arm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
