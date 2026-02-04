"""
Schallpappenspieler - QR code-based DJ deck controller for Mixxx.

Main application orchestrating:
- Threaded camera capture (30 FPS)
- Threaded QR detection
- State tracking with stability-based triggering
- Mixxx automation via xdotool
- Real-time debug visualization

Architecture:
    Capture Thread → Detection Thread → Main Thread
         ↓                ↓                 ↓
    Latest Frame    Latest Detections   GUI + Mixxx
"""

import argparse
import threading
import time

import cv2

from .camera import open_camera
from .config import load_config
from .gui_debug import DebugGUI
from .mixxx_ui import MixxxConfig, MixxxController
from .qr_detector import QRDetector
from .state_tracker import StateTracker


class _FPSCounter:
    """Simple FPS counter that updates every second."""

    def __init__(self):
        self._count = 0
        self._last_time = time.monotonic()
        self.fps = 0.0

    def tick(self):
        self._count += 1
        now = time.monotonic()
        elapsed = now - self._last_time
        if elapsed >= 1.0:
            self.fps = self._count / elapsed
            self._count = 0
            self._last_time = now


class _PerfStats:
    """Thread-safe container for performance metrics across pipeline stages."""

    def __init__(self):
        self._lock = threading.Lock()
        self.capture_fps = 0.0
        self.detect_fps = 0.0
        self.detect_latency_ms = 0.0
        self.gui_fps = 0.0

    def update_capture(self, fps):
        with self._lock:
            self.capture_fps = fps

    def update_detect(self, fps, latency_ms):
        with self._lock:
            self.detect_fps = fps
            self.detect_latency_ms = latency_ms

    def update_gui(self, fps):
        with self._lock:
            self.gui_fps = fps

    def snapshot(self):
        with self._lock:
            return (
                self.capture_fps,
                self.detect_fps,
                self.detect_latency_ms,
                self.gui_fps,
            )


class _LatestROI:
    """Thread-safe storage for GUI-selected region of interest (ROI)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._roi = None

    def update(self, roi) -> None:
        with self._lock:
            self._roi = roi

    def snapshot(self):
        with self._lock:
            return self._roi


class _LatestFrame:
    """Thread-safe storage for latest captured frame with version tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame = None
        self._version = 0

    def update(self, frame) -> None:
        with self._lock:
            self._frame = frame
            self._version += 1

    def snapshot(self):
        with self._lock:
            return self._frame, self._version


class _LatestDetections:
    """Thread-safe storage for latest QR detections with version tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detections = []
        self._version = 0

    def update(self, detections, version: int) -> None:
        with self._lock:
            self._detections = detections
            self._version = version

    def snapshot(self):
        with self._lock:
            return self._detections, self._version


def _start_capture_thread(
    cap,
    latest: _LatestFrame,
    stats: _PerfStats,
    stop: threading.Event,
    *,
    mirror: bool = True,
) -> threading.Thread:
    """
    Start camera capture thread that continuously reads frames.

    The mirror parameter horizontally flips frames so left in image = left in reality.
    Runs at full camera speed (typically 30 FPS with MJPG format).
    """

    def run() -> None:
        fps = _FPSCounter()
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            if mirror:
                frame = cv2.flip(frame, 1)
            latest.update(frame)
            fps.tick()
            stats.update_capture(fps.fps)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _start_detection_thread(
    detector,
    latest: _LatestFrame,
    out: _LatestDetections,
    roi: _LatestROI,
    stats: _PerfStats,
    stop: threading.Event,
) -> threading.Thread:
    """
    Start QR detection thread that processes latest frames.

    Polls for new frame versions, applies optional ROI cropping, runs detection,
    and adjusts coordinates back to full-frame space. Measures per-frame latency.
    """

    def run() -> None:
        last_seen = -1
        fps = _FPSCounter()
        while not stop.is_set():
            frame, version = latest.snapshot()
            if frame is None or version == last_seen:
                time.sleep(0.005)
                continue
            last_seen = version
            roi_rect = roi.snapshot()
            t0 = time.monotonic()
            if roi_rect:
                x1, y1, x2, y2 = roi_rect
                h, w = frame.shape[:2]
                x1 = max(0, min(x1, w - 1))
                x2 = max(0, min(x2, w - 1))
                y1 = max(0, min(y1, h - 1))
                y2 = max(0, min(y2, h - 1))
                if x2 > x1 and y2 > y1:
                    crop = frame[y1:y2, x1:x2].copy()
                    detections = detector.detect(crop)
                    for det in detections:
                        det.points = [(x + x1, y + y1) for x, y in det.points]
                        det.center = (det.center[0] + x1, det.center[1] + y1)
                else:
                    detections = detector.detect(frame)
            else:
                detections = detector.detect(frame)
            latency_ms = (time.monotonic() - t0) * 1000.0
            fps.tick()
            stats.update_detect(fps.fps, latency_ms)
            out.update(detections, version)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _pick_detection(detections):
    """Select largest QR code by area (handles overlapping codes)."""
    if not detections:
        return None
    return max(detections, key=lambda d: d.area)


def main() -> int:
    """Main application entry point."""
    parser = argparse.ArgumentParser(description="Schallpappenspieler live QR loader")
    parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    parser.add_argument("--no-gui", action="store_true", help="Disable debug GUI")
    args = parser.parse_args()

    config = load_config(args.config)

    cam_cfg = config.get("camera", {})
    split_cfg = config.get("split", {})
    qr_cfg = config.get("qr", {})
    timing_cfg = config.get("timing", {})
    mixxx_cfg = config.get("mixxx", {})
    ui_cfg = config.get("ui", {})

    cap = open_camera(
        cam_cfg.get("index", 0),
        cam_cfg.get("preferred_width", 0),
        cam_cfg.get("preferred_height", 0),
    )

    tracker = StateTracker(
        stable_seconds=timing_cfg.get("stable_seconds", 1.0),
        dropout_seconds=timing_cfg.get("dropout_seconds", 1.0),
        forget_seconds=timing_cfg.get("forget_seconds", 5.0),
    )

    detector = QRDetector(backend=qr_cfg.get("backend", "opencv"))

    mixxx = MixxxController(
        MixxxConfig(
            window_class_hint=mixxx_cfg.get("window_class_hint", "mixxx"),
            step_delay_seconds=mixxx_cfg.get("step_delay_seconds", 0.5),
            search_hotkey=mixxx_cfg.get("search_hotkey", "ctrl+f"),
            result_tab_count=mixxx_cfg.get("result_tab_count", 3),
            left_deck_key=mixxx_cfg.get("left_deck_key", "Shift+Left"),
            right_deck_key=mixxx_cfg.get("right_deck_key", "Shift+Right"),
        )
    )

    show_gui = ui_cfg.get("show_debug", True) and not args.no_gui
    latest_roi = _LatestROI()
    gui = DebugGUI(roi_sink=latest_roi) if show_gui else None

    latest_frame = _LatestFrame()
    latest_detections = _LatestDetections()
    stop_event = threading.Event()
    perf_stats = _PerfStats()

    mirror = cam_cfg.get("mirror", True)
    cap_thread = _start_capture_thread(
        cap, latest_frame, perf_stats, stop_event, mirror=mirror
    )
    det_thread = _start_detection_thread(
        detector, latest_frame, latest_detections, latest_roi, perf_stats, stop_event
    )

    last_action = None
    last_detection_version = -1
    last_frame_version = -1
    gui_fps = _FPSCounter()
    split_ratio = split_cfg.get("ratio", 0.5)
    try:
        while True:
            frame, frame_version = latest_frame.snapshot()
            if frame is None:
                time.sleep(0.01)
                continue

            # No new frame — just keep GUI responsive without re-rendering
            if frame_version == last_frame_version:
                if gui:
                    if not gui.process_events():
                        break
                else:
                    time.sleep(0.005)
                continue
            last_frame_version = frame_version

            detections, det_version = latest_detections.snapshot()
            new_detections = det_version != last_detection_version
            if new_detections:
                last_detection_version = det_version

            height, width = frame.shape[:2]
            split_x = int(width * split_ratio)

            left_detections = [d for d in detections if d.center[0] < split_x]
            right_detections = [d for d in detections if d.center[0] >= split_x]

            left_det = _pick_detection(left_detections)
            right_det = _pick_detection(right_detections)

            now = time.monotonic()
            left_event = tracker.update(
                "left", left_det.text if left_det else None, now
            )
            right_event = tracker.update(
                "right", right_det.text if right_det else None, now
            )

            if left_event:
                print(f"Trigger left: {left_event.text}")
                if mixxx.load_track(left_event.text, "left"):
                    last_action = f"Loaded left: {left_event.text}"

            if right_event:
                print(f"Trigger right: {right_event.text}")
                if mixxx.load_track(right_event.text, "right"):
                    last_action = f"Loaded right: {right_event.text}"

            gui_fps.tick()
            perf_stats.update_gui(gui_fps.fps)

            if gui:
                display = frame.copy()
                keep_running = gui.render(
                    display,
                    detections,
                    split_x,
                    tracker.left,
                    tracker.right,
                    last_action,
                    now,
                    perf_stats=perf_stats,
                )
                if not keep_running:
                    break
            else:
                time.sleep(0.005)
    finally:
        stop_event.set()
        cap_thread.join(timeout=1.0)
        det_thread.join(timeout=1.0)
        cap.release()
        if gui:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
