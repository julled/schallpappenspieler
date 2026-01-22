import argparse
import time

import cv2

from .camera import open_camera
from .config import load_config
from .gui_debug import DebugGUI
from .mixxx_ui import MixxxConfig, MixxxController
from .qr_detector import QRDetector
from .state_tracker import StateTracker


def _pick_detection(detections):
    if not detections:
        return None
    return max(detections, key=lambda d: d.area)


def main() -> int:
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
        stable_seconds=timing_cfg.get("stable_seconds", 2.0),
        dropout_seconds=timing_cfg.get("dropout_seconds", 0.5),
        forget_seconds=timing_cfg.get("forget_seconds", 2.0),
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
    gui = DebugGUI() if show_gui else None

    last_action = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Failed to read camera frame.")
                break

            detections = detector.detect(frame)
            height, width = frame.shape[:2]
            split_x = int(width * split_cfg.get("ratio", 0.5))

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

            if gui:
                keep_running = gui.render(
                    frame,
                    detections,
                    split_x,
                    tracker.left,
                    tracker.right,
                    last_action,
                    now,
                )
                if not keep_running:
                    break
    finally:
        cap.release()
        if gui:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
