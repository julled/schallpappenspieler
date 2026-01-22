import time
from typing import Iterable, Optional

import cv2
import numpy as np

from .qr_detector import QRCodeDetection
from .state_tracker import SideState


class DebugGUI:
    def __init__(self):
        self.neon = (57, 255, 20)
        self.window_name = "Schallpappenspieler"
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

    def render(
        self,
        frame,
        detections: Iterable[QRCodeDetection],
        split_x: int,
        left_state: SideState,
        right_state: SideState,
        last_action: Optional[str],
        now: Optional[float] = None,
    ) -> bool:
        if now is None:
            now = time.monotonic()
        height, width = frame.shape[:2]
        cv2.line(frame, (split_x, 0), (split_x, height), self.neon, 2)

        for det in detections:
            pts = [(int(x), int(y)) for x, y in det.points]
            cv2.polylines(frame, [np.array(pts, dtype="int32")], True, self.neon, 2)
            side_state = left_state if det.center[0] < split_x else right_state
            stable = (now - side_state.first_seen) if side_state.first_seen else 0.0
            dropout = (now - side_state.last_seen) if side_state.last_seen else 0.0
            label = f"{det.text} {stable:.1f}s/{dropout:.1f}s"
            cv2.putText(
                frame,
                label,
                (int(det.center[0]), int(det.center[1])),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                self.neon,
                1,
                cv2.LINE_AA,
            )

        def _timers(state: SideState) -> str:
            if state.current_text is None:
                return "stable=0.0s dropout=0.0s"
            stable = (now - state.first_seen) if state.first_seen else 0.0
            dropout = (now - state.last_seen) if state.last_seen else 0.0
            return f"stable={stable:.1f}s dropout={dropout:.1f}s"

        status_lines = [
            f"Left: {left_state.current_text or '-'} ({_timers(left_state)})",
            f"Right: {right_state.current_text or '-'} ({_timers(right_state)})",
            f"Last action: {last_action or '-'}",
        ]
        y = 20
        for line in status_lines:
            cv2.putText(
                frame,
                line,
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                self.neon,
                2,
                cv2.LINE_AA,
            )
            y += 24

        try:
            visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
            if visible < 0:
                return False
            render_ok = True
            try:
                _, _, w, h = cv2.getWindowImageRect(self.window_name)
                if w == 0 or h == 0:
                    render_ok = False
            except cv2.error:
                render_ok = False
            if render_ok:
                cv2.imshow(self.window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            return key != ord("q")
        except cv2.error:
            return True
