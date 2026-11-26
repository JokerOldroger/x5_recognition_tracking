"""Enable START-based control requests and boot in manual mode."""
import json
from pathlib import Path
import shutil
import time
from dingdong.core import DEFAULT_CONFIG, validate_config


def update_config(config):
    updated = dict(config)
    updated["enable_motion"] = False
    updated["gamepad_host_request"] = True
    merged = dict(DEFAULT_CONFIG)
    merged.update(updated)
    validate_config(merged)
    return updated


def main():
    path = Path(__file__).resolve().parent / "config.json"
    config = update_config(json.loads(path.read_text(encoding="utf-8")))
    backup = path.with_name("config.before_start_" + str(time.time_ns()) + ".json")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print("Boot mode: manual; START alone requests gesture control.")
    print("Serial port, speeds and action calibration preserved. Backup:", backup)


if __name__ == "__main__":
    main()
