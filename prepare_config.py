"""Prepare the full release while preserving the device's motion calibration."""
import json
from pathlib import Path
import shutil
import time

from dingdong.core import DEFAULT_CONFIG, validate_config


def prepare(existing):
    config = dict(DEFAULT_CONFIG)
    config.update(existing)
    config["enable_motion"] = False
    config["gamepad_host_request"] = True
    validate_config(config)
    return config


def main():
    path = Path(__file__).resolve().parent / "config.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    config = prepare(existing)
    if path.exists():
        backup = path.with_name("config.before_latest_" + str(time.time_ns()) + ".json")
        shutil.copy2(path, backup)
        print("Previous configuration saved:", backup)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print("Configuration ready. Boot in manual mode; press START after recognition starts.")
    print("Port and existing motion calibration preserved:", config["serial_port"])


if __name__ == "__main__":
    main()
