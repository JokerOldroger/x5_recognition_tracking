"""Bench check: ping, stop, or request control and execute one bounded pose."""
import argparse
import time
from .core import Pose
from .transport import SerialLink


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("command", choices=["ping", "stop", "hold", "nod"])
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--left", type=int, default=0)
    parser.add_argument("--right", type=int, default=0)
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--yaw", type=int, default=0)
    args = parser.parse_args()
    if not 0.1 <= args.seconds <= 10:
        parser.error("seconds must be 0.1..10")
    pose = Pose(args.left, args.right, args.pitch, args.yaw)
    pose.pack()
    link = SerialLink(args.port)
    owned = False
    try:
        if args.command in ("ping", "stop"):
            print(link.ping() if args.command == "ping" else link.stop())
            return
        ack = link.arm()
        print("ARM", ack)
        if ack.status != 0 or ack.mode != 1:
            raise RuntimeError("MCU refused host control")
        owned = True
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            cycle = time.monotonic()
            if args.command == "nod":
                import math
                pose = Pose(pitch=round(10 * math.sin(4 * math.pi * (cycle-start) / args.seconds)))
            ack = link.control(pose)
            if ack.status != 0 or ack.mode != 1:
                owned = False
                raise RuntimeError("Manual takeover or MCU timeout; action cancelled")
            time.sleep(max(0, 0.05 - (time.monotonic() - cycle)))
    finally:
        if owned:
            try:
                link.stop()
            except Exception:
                pass
        link.close()


if __name__ == "__main__":
    main()
