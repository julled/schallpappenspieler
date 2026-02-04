"""
OpenCV-based debug visualization for Schallpappenspieler.

Shows live camera feed with overlays:
- QR detection polylines (green)
- Split line dividing left/right decks (green)
- Status per deck with stability timers
- Performance stats (CAP/DET/GUI FPS)
- Interactive ROI selection (red rectangle)

Controls:
- Click ROI button or press 'r' to enter selection mode
- Click-drag to draw ROI rectangle
- Press 'c' or right-click to clear ROI
- Press 'q' to quit
"""

import time
from typing import Iterable, Optional

import cv2
import numpy as np

from .qr_detector import QRCodeDetection
from .state_tracker import SideState


class DebugGUI:
    """Interactive debug visualization with ROI selection and performance overlay."""

    def __init__(self, roi_sink=None):
        self.neon = (57, 255, 20)
        self.red = (0, 0, 255)
        self.window_name = "Schallpappenspieler"
        self._roi_sink = roi_sink
        self._roi_mode = False
        self._roi = None
        self._dragging = False
        self._drag_start = None
        self._drag_current = None
        self._button_rect = None
        self._frame_size = (1, 1)  # (w, h) of last rendered frame
        self._window_size = (1, 1)  # (w, h) of display window
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self._on_mouse)

    def _on_mouse(self, event, x, y, flags, param=None):
        if event == cv2.EVENT_RBUTTONDOWN:
            self._roi = None
            self._dragging = False
            self._drag_start = None
            self._drag_current = None
            self._roi_mode = False
            if self._roi_sink:
                self._roi_sink.update(None)
            return

        if self._button_rect and event == cv2.EVENT_LBUTTONDOWN:
            bx1, by1, bx2, by2 = self._button_rect
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                self._roi_mode = True
                self._dragging = False
                self._drag_start = None
                self._drag_current = None
                return

        if not self._roi_mode:
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            self._dragging = True
            self._drag_start = (x, y)
            self._drag_current = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self._dragging:
            self._drag_current = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self._dragging:
            self._dragging = False
            self._drag_current = (x, y)
            if self._drag_start and self._drag_current:
                x1, y1 = self._drag_start
                x2, y2 = self._drag_current
                x1, x2 = sorted([x1, x2])
                y1, y2 = sorted([y1, y2])
                if (x2 - x1) >= 5 and (y2 - y1) >= 5:
                    self._roi = (x1, y1, x2, y2)
                    if self._roi_sink:
                        self._roi_sink.update(self._roi)
            self._roi_mode = False

    def render(
        self,
        frame,
        detections: Iterable[QRCodeDetection],
        split_x: int,
        left_state: SideState,
        right_state: SideState,
        last_action: Optional[str],
        now: Optional[float] = None,
        perf_stats=None,
    ) -> bool:
        """
        Render frame with overlays and display in window.

        Args:
            frame: Camera frame to draw on (will be modified)
            detections: List of detected QR codes
            split_x: X coordinate of deck split line
            left_state: Current state for left deck
            right_state: Current state for right deck
            last_action: Most recent Mixxx action
            now: Current timestamp (for timer calculations)
            perf_stats: Performance metrics object

        Returns:
            True to continue, False if user quit
        """
        if now is None:
            now = time.monotonic()
        height, width = frame.shape[:2]
        self._frame_size = (width, height)
        cv2.line(frame, (split_x, 0), (split_x, height), self.neon, 8)
        # ROI button
        button_w, button_h = 80, 28
        bx1 = width - button_w - 10
        by1 = 10
        bx2 = bx1 + button_w
        by2 = by1 + button_h
        self._button_rect = (bx1, by1, bx2, by2)
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), self.red, 8)
        label = "ROI SET" if self._roi else "ROI"
        if self._roi_mode:
            label = "ROI..."
        cv2.putText(
            frame,
            label,
            (bx1 + 6, by1 + 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            self.red,
            4,
            cv2.LINE_AA,
        )

        # Draw ROI rectangle
        if self._roi:
            x1, y1, x2, y2 = self._roi
            cv2.rectangle(frame, (x1, y1), (x2, y2), self.red, 8)
        if self._dragging and self._drag_start and self._drag_current:
            x1, y1 = self._drag_start
            x2, y2 = self._drag_current
            cv2.rectangle(frame, (x1, y1), (x2, y2), self.red, 4)

        for det in detections:
            pts = [(int(x), int(y)) for x, y in det.points]
            cv2.polylines(frame, [np.array(pts, dtype="int32")], True, self.neon, 8)
            side_state = left_state if det.center[0] < split_x else right_state
            stable = (now - side_state.first_seen) if side_state.first_seen else 0.0
            dropout = (now - side_state.last_seen) if side_state.last_seen else 0.0
            label = f"{det.text} {stable:.1f}s/{dropout:.1f}s"
            cv2.putText(
                frame,
                label,
                (int(det.center[0]), int(det.center[1])),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                self.neon,
                4,
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
                1.2,
                self.neon,
                8,
                cv2.LINE_AA,
            )
            y += 48

        if perf_stats is not None:
            cap_fps, det_fps, det_ms, gui_fps = perf_stats.snapshot()
            perf_line = (
                f"CAP {cap_fps:.0f}fps | "
                f"DET {det_fps:.0f}fps {det_ms:.0f}ms | "
                f"GUI {gui_fps:.0f}fps"
            )
            cv2.putText(
                frame,
                perf_line,
                (10, height - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                self.neon,
                8,
                cv2.LINE_AA,
            )

        try:
            visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
            if visible < 0:
                return False
            render_ok = True
            try:
                _, _, w, h = cv2.getWindowImageRect(self.window_name)
                if w > 0 and h > 0:
                    self._window_size = (w, h)
                else:
                    render_ok = False
            except cv2.error:
                render_ok = False
            if render_ok:
                cv2.imshow(self.window_name, frame)
            return self._handle_key()
        except cv2.error:
            return True

    def process_events(self) -> bool:
        """
        Poll keyboard/mouse events without rendering a frame.

        Use this in main loop when no new frame is available to keep
        the GUI responsive without redundant redraws.

        Returns:
            True to continue, False if user quit
        """
        try:
            return self._handle_key()
        except cv2.error:
            return True

    def _handle_key(self) -> bool:
        """Handle keyboard input. Returns False if user pressed 'q' to quit."""
        key = cv2.waitKey(1) & 0xFF
        if key == ord("r"):
            self._roi_mode = True
            self._dragging = False
            self._drag_start = None
            self._drag_current = None
        if key == ord("c"):
            self._roi = None
            self._roi_mode = False
            if self._roi_sink:
                self._roi_sink.update(None)
        return key != ord("q")
