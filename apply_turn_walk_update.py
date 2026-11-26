"""Add turn-then-forward settings without changing existing calibration/modes."""
import json
from pathlib import Path
import shutil
import time
from dingdong.core import DEFAULT_CONFIG, validate_config


def update_config(config):
    updated = dict(config)
    for key in ("direction_turn_speed_mm_s", "direction_turn_seconds", "direction_pause_seconds",
                "direction_forward_speed_mm_s", "direction_forward_seconds"):
        updated.setdefault(key, DEFAULT_CONFIG[key])
    merged = dict(DEFAULT_CONFIG)
    merged.update(updated)
    validate_config(merged)
    return updated


def main():
    path = Path(__file__).resolve().parent / "config.json"
    updated = update_config(json.loads(path.read_text(encoding="utf-8")))
    backup = path.with_name("config.before_turn_walk_" + str(time.time_ns()) + ".json")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print("Updated left/right gestures: turn, pause, move forward, stop.")
    print("Existing mode, port, speeds and calibration preserved. Backup:", backup)
    print("Turn seconds:", updated["direction_turn_seconds"],
          "Forward speed:", updated["direction_forward_speed_mm_s"],
          "Forward seconds:", updated["direction_forward_seconds"])


if __name__ == "__main__":
    main()
