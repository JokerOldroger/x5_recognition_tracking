"""Wait for a plausible, stable wall clock before camera startup."""
import time


class ClockReady:
    def __init__(self, stable_seconds=5.0):
        self.stable_seconds = stable_seconds
        self.previous = None
        self.stable_since = None

    def observe(self, wall, monotonic):
        # 2024-01-01 UTC. A cold boot clock in 2000 is not ready.
        plausible = wall >= 1704067200
        jumped = self.previous is not None and abs(
            (wall - self.previous[0]) - (monotonic - self.previous[1])) > 0.5
        self.previous = wall, monotonic
        if not plausible or jumped:
            self.stable_since = None
            return False
        if self.stable_since is None:
            self.stable_since = monotonic
        return monotonic - self.stable_since >= self.stable_seconds


def main():
    clock = ClockReady()
    next_report = 0.0
    # A late clock correction must not require a person to restart the service.
    # No MCU control is requested while waiting, and SIGINT still stops us.
    while True:
        now = time.monotonic()
        if clock.observe(time.time(), now):
            print("System clock ready; starting camera and gesture recognition.", flush=True)
            return
        if now >= next_report:
            print("Waiting for a valid stable system clock; camera has not started. "
                  "Will start automatically when ready.", flush=True)
            next_report = now + 30
        time.sleep(0.5)


if __name__ == "__main__":
    main()
