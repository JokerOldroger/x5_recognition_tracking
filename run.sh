#!/usr/bin/env bash
# Runs both processes in one systemd service; no background orphan algorithm.
set -eo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$APP_DIR/wait_clock.py"
source /opt/tros/humble/setup.bash
export CAM_TYPE=usb
export PYTHONUNBUFFERED=1
CAMERA="${DINGDONG_CAMERA:-/dev/video0}"
for ((attempt=0; attempt<60; attempt++)); do
    [[ -e "$CAMERA" ]] && break
    sleep 1
done
[[ -e "$CAMERA" ]] || { echo "Camera not found: $CAMERA" >&2; exit 1; }

mkdir -p "$APP_DIR/runtime"
cd "$APP_DIR/runtime"
for package in mono2d_body_detection hand_lmk_detection hand_gesture_detection; do
    # Config/model files remain in the user directory, never chmod /opt/tros.
    cp -rn "/opt/tros/humble/lib/$package/config" .
done
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
ALGORITHM_PID=""
BRIDGE_PID=""
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$BRIDGE_PID" ]] || kill -INT "$BRIDGE_PID" 2>/dev/null || true
    [[ -z "$ALGORITHM_PID" ]] || kill -INT "$ALGORITHM_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" "$ALGORITHM_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
ros2 launch hand_gesture_detection hand_gesture_detection.launch.py \
    usb_video_device:="$CAMERA" &
ALGORITHM_PID=$!
python3 -m dingdong.bridge --config "$APP_DIR/config.json" &
BRIDGE_PID=$!
wait -n "$ALGORITHM_PID" "$BRIDGE_PID"
