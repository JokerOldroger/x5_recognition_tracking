"""ROS 2 gesture subscriber, action scheduler and H60 control ownership."""
import argparse
import json
import math
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.executors import ExternalShutdownException
from ai_msgs.msg import PerceptionTargets
from std_srvs.srv import SetBool

from .core import DEFAULT_CONFIG, validate_config, GestureGate, Action, Pose, GESTURE_ACTIONS
from .transport import SerialLink


class Bridge(Node):
    def __init__(self, cfg):
        super().__init__("dingdong_gesture_bridge")
        self.cfg = cfg
        self.link = None
        self.enabled = False
        self.action = None
        self.last_vision = None
        self.last_stamp = None
        self.last_rejection_log = -math.inf
        self.next_request_poll = 0.0
        self.request_blocked_until_clear = False
        self.request_failed_id = None
        self.request_protocol_warned = False
        self.last_link_error_log = -math.inf
        self.vision_stale = False
        self.gate = GestureGate(cfg["stable_seconds"], cfg["release_seconds"], cfg["cooldown_seconds"])
        self.subscription = self.create_subscription(
            PerceptionTargets, cfg["gesture_topic"], self.on_gesture, qos_profile_sensor_data)
        self.arm_service = self.create_service(SetBool, "/dingdong/enable_host", self.on_enable)
        self.timer = self.create_timer(0.05, self.tick)
        if cfg["enable_motion"]:
            # Allow cold-boot USB enumeration once. Missing MCU must not stop
            # the camera/recognition process or cause later automatic rearming.
            for _ in range(100):
                if os.path.exists(cfg["serial_port"]):
                    break
                time.sleep(0.1)
            self.enable()
        else:
            self.get_logger().info("Manual mode. Press START alone or call /dingdong/enable_host to request control.")

    def enable(self, request_token=None):
        self.action = None
        self.enabled = False
        self.gate.reset()
        try:
            if self.link is None:
                self.link = SerialLink(self.cfg["serial_port"], self.cfg["baudrate"])
            ack = self.link.arm() if request_token is None else self.link.accept_request(request_token)
            if ack.status != 0 or ack.mode != 1:
                # Busy is retried only while this explicit button request is
                # still pending. Rejected/cancelled tokens are not replayed.
                if request_token is not None and ack.status != 3:
                    self.request_failed_id = request_token
                self.get_logger().warn(f"Host request refused, status={ack.status}, mode={ack.mode}")
                return False
            self.enabled = True
            self.request_blocked_until_clear = False
            self.request_failed_id = request_token
            self.get_logger().info("MCU granted host control. Waiting for a stable fresh gesture.")
            return True
        except Exception as exc:
            self.get_logger().error("Cannot acquire MCU control: " + str(exc))
            self.drop_link()
            return False

    def drop_link(self):
        # Reconnection may read status, but never replay an uncertain request.
        self.request_blocked_until_clear = True
        if self.link is not None:
            try:
                self.link.close()
            except Exception:
                pass
            self.link = None

    def poll_gamepad_request(self, now):
        if not self.cfg.get("gamepad_host_request", True) or now < self.next_request_poll:
            return
        self.next_request_poll = now + 0.2
        try:
            if self.link is None:
                self.link = SerialLink(self.cfg["serial_port"], self.cfg["baudrate"])
            request = self.link.gamepad_request()
            if request.status != 0:
                if not self.request_protocol_warned:
                    self.get_logger().warn("MCU lacks START request support; flash the matching firmware.")
                    self.request_protocol_warned = True
                return
            if not request.pending:
                self.request_blocked_until_clear = False
                self.request_failed_id = None
                return
            if self.request_blocked_until_clear or request.token == self.request_failed_id:
                return
            self.get_logger().info("START request received; validating with MCU.")
            self.enable(request_token=request.token)
        except Exception as exc:
            self.drop_link()
            self.next_request_poll = now + 1.0
            if now - self.last_link_error_log >= 5:
                self.last_link_error_log = now
                self.get_logger().warn("Waiting for H60 communication: " + str(exc))

    def disable(self, stop=True):
        was_enabled = self.enabled
        self.enabled = False
        self.action = None
        self.gate.reset()
        if stop and was_enabled and self.link:
            try:
                self.link.stop()
            except Exception:
                pass  # STM32 independently stops at 500 ms.

    def on_enable(self, request, response):
        if request.data:
            response.success = self.enable()
            response.message = "host enabled" if response.success else "request refused; check USB and gamepad"
        else:
            self.disable()
            response.success, response.message = True, "manual mode"
        return response

    def on_gesture(self, message):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        if age > self.cfg["max_frame_age_seconds"] or age < -0.5:
            now = time.monotonic()
            if now - getattr(self, "last_rejection_log", -math.inf) >= 5:
                self.last_rejection_log = now
                self.get_logger().warn(f"Discard stale/future gesture frame: age={age:.2f}s")
            return
        if self.last_stamp is not None and stamp <= self.last_stamp:
            return
        self.last_stamp = stamp
        now = time.monotonic()
        if self.last_vision is None or self.vision_stale:
            self.get_logger().info("Fresh gesture messages received.")
        self.last_vision, self.vision_stale = now, False
        values = set()
        for target in message.targets:
            if not any(roi.type == "hand" for roi in target.rois):
                continue
            for attribute in target.attributes:
                # D-Robotics HandGestureDetNode::Publish sets type/value only.
                # Its confidence=0 is an unset field, not a rejected prediction.
                # The producer already applies its own classifier threshold.
                if attribute.type != "gesture" or attribute.value not in GESTURE_ACTIONS:
                    continue
                if self.cfg.get("gesture_confidence_available", False):
                    if (not math.isfinite(attribute.confidence) or
                            attribute.confidence < self.cfg["confidence"]):
                        continue
                values.add(int(attribute.value))
        # Conflicting hands do not choose an arbitrary action.
        gesture = next(iter(values)) if len(values) == 1 else None
        event = self.gate.observe(gesture, now, (message.header.frame_id, stamp))
        if event is not None:
            label = GESTURE_ACTIONS[event]
            self.get_logger().info(label + ("" if self.enabled else " (recognition only, no motion)"))
            if self.enabled:
                self.action = Action(event, now, self.cfg)

    def tick(self):
        now = time.monotonic()
        if not self.enabled:
            self.poll_gamepad_request(now)
            return
        fresh = self.last_vision is not None and now - self.last_vision <= self.cfg["vision_timeout_seconds"]
        if not fresh:
            self.action = None
            if not self.vision_stale:
                self.gate.reset()
                self.vision_stale = True
                self.get_logger().warn("No fresh vision; cancel action and hold wheels stopped.")
        pose = self.action.sample(now) if self.action is not None else None
        if pose is None:
            self.action = None
            pose = Pose(mask=0)
        try:
            ack = self.link.control(pose)
            if ack.status != 0 or ack.mode != 1:
                # A manual takeover must not be stopped or automatically undone.
                self.disable(stop=False)
                self.get_logger().warn(f"MCU revoked host control ({ack.status}). Explicit enable required.")
                try:
                    self.get_logger().warn(self.link.exit_diagnostics())
                except Exception as diagnostic_error:
                    # Reading diagnostics must never STOP manual control or rearm.
                    self.get_logger().warn("Exit diagnostics unavailable: " + str(diagnostic_error))
        except Exception as exc:
            self.disable()
            self.drop_link()
            self.get_logger().error("Communication failed; explicit enable required: " + str(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = dict(DEFAULT_CONFIG)
    with open(args.config, encoding="utf-8") as stream:
        cfg.update(json.load(stream))
    validate_config(cfg)
    rclpy.init()
    node = None
    try:
        node = Bridge(cfg)
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.disable()
            if node.link:
                node.link.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
