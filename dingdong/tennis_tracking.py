"""Track a yellow-green tennis ball with OpenCV and RDK Model Zoo ByteTrack."""

import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np


def detect_tennis_balls(frame, lower_hsv, upper_hsv, min_area, min_circularity):
    """Return an N×5 array of original-image XYXY boxes and shape scores."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    max_area = frame.shape[0] * frame.shape[1] * 0.2
    detections = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not min_area <= area <= max_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = min(1.0, 4 * math.pi * area / perimeter**2)
        x, y, width, height = cv2.boundingRect(contour)
        aspect = min(width, height) / max(width, height)
        if circularity >= min_circularity and aspect >= 0.65:
            detections.append((x, y, x + width, y + height, circularity * aspect))
    return np.asarray(detections, dtype=np.float32).reshape(-1, 5)


def create_tracker(model_zoo, fps, track_buffer, match_thresh):
    checkout = model_zoo.resolve()
    backend = checkout / "samples/vision/bytetrack/runtime/python/tracker_backend/byte_tracker.py"
    if not backend.is_file():
        raise ValueError(f"RDK Model Zoo ByteTrack backend not found: {backend}")
    sys.path.insert(0, str(checkout))
    from samples.vision.bytetrack.runtime.python.tracker_backend.byte_tracker import BYTETracker
    from samples.vision.bytetrack.runtime.python.tracking import TrackingConfig

    config = TrackingConfig(
        track_thresh=0.45,
        frame_rate=max(1, round(fps)),
        track_buffer=track_buffer,
        match_thresh=match_thresh,
    )
    return BYTETracker(config, frame_rate=config.frame_rate)


def snapshot_track(track):
    x1, y1, x2, y2 = (float(value) for value in track.tlbr)
    return {
        "track_id": int(track.track_id),
        "bbox_xyxy": [x1, y1, x2, y2],
        "center_xy": [(x1 + x2) / 2, (y1 + y2) / 2],
        "score": float(track.score),
    }


def draw_tracks(frame, tracks):
    for track in tracks:
        x1, y1, x2, y2 = (round(value) for value in track["bbox_xyxy"])
        center = tuple(round(value) for value in track["center_xy"])
        color = (60, 255, 60)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.circle(frame, center, 3, color, -1)
        cv2.putText(
            frame, f"Tennis ball #{track['track_id']}", (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )


def run(args):
    if args.input is not None and not args.input.is_file():
        raise ValueError(f"Input video not found: {args.input}")
    is_camera = args.camera is not None
    source = args.camera if is_camera else str(args.input)
    if is_camera and source.isdecimal():
        source = int(source)

    lower_hsv = np.array(args.hsv_low, dtype=np.uint8)
    upper_hsv = np.array(args.hsv_high, dtype=np.uint8)
    with ExitStack() as resources:
        backend = cv2.CAP_V4L2 if is_camera and sys.platform.startswith("linux") else cv2.CAP_ANY
        capture = cv2.VideoCapture(source, backend)
        resources.callback(capture.release)
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video source: {source}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0
        tracker = create_tracker(args.model_zoo, fps, args.track_buffer, args.match_thresh)
        records = resources.enter_context(args.records.open("w", encoding="utf-8")) if args.records else None
        writer = None
        if args.preview:
            cv2.namedWindow("Tennis ball tracking", cv2.WINDOW_NORMAL)
            resources.callback(cv2.destroyAllWindows)

        frame_count = 0
        tracked_frames = 0
        while args.max_frames == 0 or frame_count < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                if is_camera or frame_count == 0:
                    raise RuntimeError(f"Could not read a frame from {source} after {frame_count} frames")
                break
            frame_count += 1
            size = frame.shape[:2]
            detections = detect_tennis_balls(frame, lower_hsv, upper_hsv, args.min_area, args.min_circularity)
            # Advance ByteTrack once even on empty frames. Both sizes use original pixels.
            tracks = [snapshot_track(track) for track in tracker.update(detections, size, size)]
            tracked_frames += bool(tracks)
            if records is not None:
                records.write(json.dumps({
                    "frame": frame_count,
                    "candidates": len(detections),
                    "tracks": tracks,
                }) + "\n")
            if args.output and writer is None:
                height, width = size
                writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                resources.callback(writer.release)
                if not writer.isOpened():
                    raise RuntimeError(f"Could not create output video: {args.output}")
            if writer is not None or args.preview:
                draw_tracks(frame, tracks)
            if writer is not None:
                writer.write(frame)
            if args.preview:
                cv2.imshow("Tennis ball tracking", frame)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break
    print(f"Processed {frame_count} frames, {tracked_frames} with confirmed tracks.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-zoo", type=Path, required=True, help="RDK Model Zoo checkout")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Input video file")
    source.add_argument("--camera", help="Camera index or device path, e.g. /dev/video0")
    parser.add_argument("--output", type=Path, help="Write an annotated MP4")
    parser.add_argument("--records", type=Path, help="Write frame records as JSON Lines")
    parser.add_argument("--preview", action="store_true", help="Show a window (q or Esc to exit)")
    parser.add_argument("--max-frames", type=int, default=0, help="0 processes the entire input")
    parser.add_argument("--hsv-low", type=int, nargs=3, default=(24, 75, 65), metavar=("H", "S", "V"))
    parser.add_argument("--hsv-high", type=int, nargs=3, default=(85, 255, 255), metavar=("H", "S", "V"))
    parser.add_argument("--min-area", type=float, default=60, help="Minimum contour area in px²")
    parser.add_argument("--min-circularity", type=float, default=0.60)
    parser.add_argument("--track-buffer", type=int, default=15, help="Lost-track buffer in frames at 30 FPS")
    parser.add_argument("--match-thresh", type=float, default=0.8, help="ByteTrack first-pass match cost threshold")
    args = parser.parse_args()

    if any(not 0 <= lo <= hi <= limit for lo, hi, limit in zip(args.hsv_low, args.hsv_high, (179, 255, 255))):
        parser.error("HSV bounds must be ordered and within OpenCV ranges (179, 255, 255)")
    if not (math.isfinite(args.min_area) and args.min_area > 0 and 0 < args.min_circularity <= 1):
        parser.error("min-area must be positive and min-circularity must be in (0, 1]")
    if not (args.max_frames >= 0 and args.track_buffer >= 0 and 0 <= args.match_thresh <= 1):
        parser.error("frame counts must be nonnegative and match-thresh must be in [0, 1]")
    paths = [path.resolve() for path in (args.input, args.output, args.records) if path is not None]
    if len(set(paths)) != len(paths):
        parser.error("input, output and records paths must be distinct")
    if args.output is not None and args.output.suffix.lower() != ".mp4":
        parser.error("output video must have an .mp4 extension")

    try:
        run(args)
    except (OSError, ImportError, ValueError, RuntimeError, cv2.error) as exc:
        parser.exit(1, f"Tennis tracking failed: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Stopped tennis tracking.\n")


if __name__ == "__main__":
    main()
