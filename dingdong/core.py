"""Hardware-independent wire protocol and gesture/action policy."""
import binascii
import math
import struct
from dataclasses import dataclass

PING, CONTROL, MODE, STOP = 0x01, 0x10, 0x11, 0x12
GAMEPAD_REQUEST, ACCEPT_REQUEST = 0x13, 0x14
GESTURE_ACTIONS = {
    3: "Victory: turn then nod",
    5: "Palm: shake then reverse",
    12: "ThumbLeft: turn left then move forward",
    13: "ThumbRight: turn right then move forward",
}


def encode(command, sequence, payload=b""):
    body = bytes((7 + len(payload), command, sequence)) + payload
    if len(body) + 4 > 32:
        raise ValueError("Frame exceeds 32 bytes")
    return b"\xaa\x55" + body + struct.pack("<H", binascii.crc_hqx(body, 0xFFFF))


class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        packets = []
        while self.buffer:
            if self.buffer[0] != 0xAA or (len(self.buffer) >= 2 and self.buffer[1] != 0x55):
                del self.buffer[0]
                continue
            if len(self.buffer) < 3:
                break
            length = self.buffer[2]
            if not 7 <= length <= 32:
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                break
            frame = self.buffer[:length]
            crc = struct.unpack("<H", frame[-2:])[0]
            if binascii.crc_hqx(frame[2:-2], 0xFFFF) != crc:
                del self.buffer[0]
                continue
            packets.append((frame[3], frame[4], bytes(frame[5:-2])))
            del self.buffer[:length]
        return packets


@dataclass(frozen=True)
class Pose:
    left: int = 0
    right: int = 0
    pitch: int = 0
    yaw: int = 0
    # Mask only arms channels. Once armed, the firmware keeps them enabled.
    mask: int = 3

    def pack(self):
        if not (-240 <= self.left <= 240 and -240 <= self.right <= 240
                and -30 <= self.pitch <= 30 and -60 <= self.yaw <= 60
                and 0 <= self.mask <= 3):
            raise ValueError("Motion outside firmware limits")
        return struct.pack("<hhbbB", self.left, self.right, self.pitch, self.yaw, self.mask)


class GestureGate:
    """One action per held gesture; requires steady, distinct, fresh frames."""
    def __init__(self, stable=0.5, release=0.8, cooldown=1.5, max_gap=0.3):
        self.stable, self.release = stable, release
        self.cooldown, self.max_gap = cooldown, max_gap
        self.reset()

    def reset(self):
        self.candidate = None
        self.since = self.last_seen = self.last_frame_time = None
        self.latched = None
        self.last_fire = -math.inf
        self.frame_id = None

    def observe(self, gesture, now, frame_id):
        if frame_id == self.frame_id:
            return None
        self.frame_id = frame_id
        if self.last_frame_time is not None and now - self.last_frame_time > self.max_gap:
            self.candidate = None
        self.last_frame_time = now
        if gesture not in GESTURE_ACTIONS:
            if self.last_seen is not None and now - self.last_seen >= self.release:
                self.latched = None
            self.candidate = None
            return None
        self.last_seen = now
        if gesture != self.candidate:
            self.candidate, self.since = gesture, now
        if (gesture != self.latched and now - self.since >= self.stable
                and now - self.last_fire >= self.cooldown):
            self.latched, self.last_fire = gesture, now
            return gesture
        return None


class Action:
    def __init__(self, gesture, start, cfg):
        self.gesture, self.start, self.cfg = gesture, start, cfg

    def sample(self, now):
        t = now - self.start
        c = self.cfg
        if self.gesture == 3:
            # Time-based rotation, followed by two smooth nods.
            turn_time = c["turn_seconds"]
            if t < turn_time:
                return Pose(-c["turn_speed_mm_s"], c["turn_speed_mm_s"], mask=0)
            t -= turn_time
            if t < c["nod_seconds"]:
                pitch = round(c["nod_degrees"] * math.sin(4 * math.pi * t / c["nod_seconds"]))
                return Pose(pitch=pitch)
        elif self.gesture == 5:
            if t < c["shake_seconds"]:
                yaw = round(c["shake_degrees"] * math.sin(4 * math.pi * t / c["shake_seconds"]))
                return Pose(yaw=yaw)
            t -= c["shake_seconds"]
            if t < c["reverse_seconds"]:
                return Pose(-c["reverse_speed_mm_s"], -c["reverse_speed_mm_s"])
        elif self.gesture in (12, 13):
            if t < c["direction_turn_seconds"]:
                speed = c["direction_turn_speed_mm_s"]
                # Robot-relative direction: left wheel backwards means left turn.
                return Pose(-speed, speed, mask=0) if self.gesture == 12 else Pose(speed, -speed, mask=0)
            t -= c["direction_turn_seconds"]
            if t < c["direction_pause_seconds"]:
                return Pose(mask=0)
            t -= c["direction_pause_seconds"]
            if t < c["direction_forward_seconds"]:
                speed = c["direction_forward_speed_mm_s"]
                return Pose(speed, speed, mask=0)
        return None


DEFAULT_CONFIG = {
    "serial_port": "/dev/ttyACM0",
    "baudrate": 115200,
    "enable_motion": False,
    "gamepad_host_request": True,
    "gesture_topic": "/hobot_hand_gesture_detection",
    "confidence": 0.5,
    "gesture_confidence_available": False,
    "stable_seconds": 0.5,
    "release_seconds": 0.8,
    "cooldown_seconds": 1.5,
    "vision_timeout_seconds": 1.0,
    "max_frame_age_seconds": 1.5,
    "turn_speed_mm_s": 120,
    "turn_seconds": 3.0,
    "nod_degrees": 12,
    "nod_seconds": 1.6,
    "shake_degrees": 18,
    "shake_seconds": 1.6,
    "reverse_speed_mm_s": 120,
    "reverse_seconds": 0.6,
    "direction_turn_speed_mm_s": 120,
    "direction_turn_seconds": 0.6,
    "direction_pause_seconds": 0.2,
    "direction_forward_speed_mm_s": 120,
    "direction_forward_seconds": 0.8,
}


def validate_config(cfg):
    for key in DEFAULT_CONFIG:
        if key not in cfg:
            raise ValueError("Missing config: " + key)
    if type(cfg["enable_motion"]) is not bool:
        raise ValueError("enable_motion must be boolean")
    if type(cfg["gamepad_host_request"]) is not bool:
        raise ValueError("gamepad_host_request must be boolean")
    for key, limit in (("turn_speed_mm_s", 120), ("reverse_speed_mm_s", 120),
                       ("direction_turn_speed_mm_s", 120),
                       ("direction_forward_speed_mm_s", 120),
                       ("nod_degrees", 25), ("shake_degrees", 45)):
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= limit:
            raise ValueError("Invalid " + key)
    for key in ("stable_seconds", "release_seconds", "cooldown_seconds",
                "vision_timeout_seconds", "max_frame_age_seconds", "turn_seconds",
                "nod_seconds", "shake_seconds", "reverse_seconds", "direction_turn_seconds",
                "direction_forward_seconds"):
        if not isinstance(cfg[key], (int, float)) or not math.isfinite(cfg[key]) or not 0.1 <= cfg[key] <= 15:
            raise ValueError("Invalid " + key)
    if cfg["reverse_seconds"] > 2:
        raise ValueError("reverse_seconds exceeds 2 seconds")
    if cfg["direction_turn_seconds"] > 3:
        raise ValueError("direction_turn_seconds exceeds 3 seconds")
    if cfg["direction_forward_seconds"] > 2:
        raise ValueError("direction_forward_seconds exceeds 2 seconds")
    pause = cfg["direction_pause_seconds"]
    if not isinstance(pause, (int, float)) or not math.isfinite(pause) or not 0 <= pause <= 1:
        raise ValueError("direction_pause_seconds must be 0..1 seconds")
    if not 0 <= cfg["confidence"] <= 1 or cfg["baudrate"] != 115200:
        raise ValueError("Invalid confidence or baudrate")
