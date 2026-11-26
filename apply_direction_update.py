"""Apply the requested speed/direction update, preserving deployed settings."""
import json
from pathlib import Path
import shutil
import time

from dingdong.core import DEFAULT_CONFIG, validate_config


def update_config(cfg):
    result = dict(cfg)
    result.update(turn_speed_mm_s=120, reverse_speed_mm_s=120)
    result.setdefault("direction_turn_speed_mm_s", 120)
    result.setdefault("direction_turn_seconds", 0.6)
    merged = dict(DEFAULT_CONFIG)
    merged.update(result)
    validate_config(merged)
    return result


def main():
    path = Path(__file__).resolve().parent / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    updated = update_config(cfg)
    backup = path.with_name("config.before_direction_" + str(time.time_ns()) + ".json")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print("Updated:", path)
    print("Backup:", backup)
    print("Wheel action speeds: 120 mm/s; new direction turn duration:", updated["direction_turn_seconds"])
    print("Preserved serial_port, enable_motion, existing durations and servo settings.")


if __name__ == "__main__":
    main()
