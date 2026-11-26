"""Acknowledged UART transactions. Missing ACK never causes implicit rearming."""
import os
import struct
import time
from dataclasses import dataclass
from .core import Decoder, encode, PING, MODE, CONTROL, STOP, GAMEPAD_REQUEST, ACCEPT_REQUEST


@dataclass
class Reply:
    status: int
    mode: int
    left: int
    right: int


class LinkError(RuntimeError):
    pass


@dataclass
class GamepadRequest:
    status: int
    mode: int
    token: int
    pending: bool


class SerialLink:
    def __init__(self, port, baud=115200):
        import fcntl
        import serial
        # Linux advisory lock prevents the supplied CLI and bridge competing.
        name = os.path.basename(os.path.realpath(port))
        self.lock = open("/tmp/dingdong-" + name + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.serial = serial.Serial(port=None, baudrate=baud, timeout=0.01,
                                        write_timeout=0.1, exclusive=True)
            self.serial.dtr = False
            self.serial.rts = False
            self.serial.port = port
            self.serial.open()
        except Exception:
            self.lock.close()
            raise
        self.decoder = Decoder()
        self.sequence = 0
        self.serial.reset_input_buffer()

    def request(self, command, payload=b""):
        self.sequence = (self.sequence + 1) & 255
        try:
            self.serial.write(encode(command, self.sequence, payload))
            deadline = time.monotonic() + 0.15
            while time.monotonic() < deadline:
                for cmd, seq, data in self.decoder.feed(self.serial.read(64)):
                    if cmd == (command | 0x80) and seq == self.sequence and len(data) == 6:
                        return Reply(*struct.unpack("<BBhh", data))
        except Exception as exc:
            # pyserial SerialException is not consistently an OSError subclass.
            raise LinkError(str(exc)) from exc
        raise LinkError("MCU ACK timeout; check H60 communication USB port and firmware")

    def ping(self):
        return self.request(PING)

    def arm(self):
        return self.request(MODE, b"\x01")

    def gamepad_request(self):
        reply = self.request(GAMEPAD_REQUEST)
        return GamepadRequest(reply.status, reply.mode, reply.left & 0xFFFF, reply.right == 1)

    def accept_request(self, token):
        return self.request(ACCEPT_REQUEST, struct.pack("<H", token))

    def control(self, pose):
        return self.request(CONTROL, pose.pack())

    def stop(self):
        return self.request(STOP)

    def exit_diagnostics(self):
        replies = [self.request(command) for command in (0x15, 0x16, 0x17)]
        if any(reply.status != 0 for reply in replies):
            raise LinkError("MCU does not support exit diagnostics")
        reason, buttons = replies[0].left & 0xFFFF, replies[0].right & 0xFFFF
        axes = struct.unpack("<bbbb", struct.pack("<HH",
            replies[1].left & 0xFFFF, replies[1].right & 0xFFFF))
        triggers = struct.unpack("<BB", struct.pack("<H", replies[2].left & 0xFFFF))
        names = {0: "未记录或主控复位", 1: "手柄输入", 2: "START再次按下",
                 3: "手柄接收器连接状态重置", 4: "控制指令超过500毫秒未更新",
                 5: "串口接收错误", 6: "收到STOP指令", 7: "收到遥控模式指令",
                 8: "START申请超过两秒"}
        return (f"退出原因={names.get(reason, '未知')}({reason}); "
                f"K1=0x{buttons & 255:02X}, K2=0x{buttons >> 8:02X}, "
                f"LX={axes[0]}, LY={axes[1]}, RX={axes[2]}, RY={axes[3]}, "
                f"LT={triggers[0]}, RT={triggers[1]}")

    def close(self):
        self.serial.close()
        self.lock.close()
