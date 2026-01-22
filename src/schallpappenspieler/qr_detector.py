from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np


@dataclass
class QRCodeDetection:
    text: str
    points: List[Tuple[float, float]]
    center: Tuple[float, float]
    area: float


def _polygon_area(points: np.ndarray) -> float:
    if points.shape[0] < 3:
        return 0.0
    return float(cv2.contourArea(points.astype("float32")))


class QRDetector:
    def __init__(self, backend: str = "opencv"):
        self.backend = backend
        self._opencv = cv2.QRCodeDetector()
        self._pyzbar = None
        if backend == "pyzbar":
            try:
                from pyzbar import pyzbar  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "pyzbar is not installed; install it or use backend=opencv"
                ) from exc
            self._pyzbar = pyzbar

    def detect(self, frame) -> List[QRCodeDetection]:
        if self.backend == "pyzbar":
            return _detect_pyzbar(frame, self._pyzbar)
        return _detect_opencv(frame, self._opencv)


def _detect_opencv(frame, detector: cv2.QRCodeDetector) -> List[QRCodeDetection]:
    detections: List[QRCodeDetection] = []

    ok, decoded_info, points, _ = detector.detectAndDecodeMulti(frame)
    if ok and decoded_info and points is not None:
        for text, quad in zip(decoded_info, points):
            if not text:
                continue
            quad_points = [(float(x), float(y)) for x, y in quad]
            center_x = sum(p[0] for p in quad_points) / 4.0
            center_y = sum(p[1] for p in quad_points) / 4.0
            area = _polygon_area(np.array(quad_points))
            detections.append(
                QRCodeDetection(
                    text=text,
                    points=quad_points,
                    center=(center_x, center_y),
                    area=area,
                )
            )
        return detections
    try:
        result = detector.detectAndDecode(frame)
    except cv2.error:
        return detections
    if len(result) == 3:
        text, points, _ = result
    else:
        text, points = result
    if text and points is not None:
        quad_points = [(float(x), float(y)) for x, y in points[0]]
        center_x = sum(p[0] for p in quad_points) / 4.0
        center_y = sum(p[1] for p in quad_points) / 4.0
        area = _polygon_area(np.array(quad_points))
        detections.append(
            QRCodeDetection(
                text=text,
                points=quad_points,
                center=(center_x, center_y),
                area=area,
            )
        )

    return detections


def _detect_pyzbar(frame, pyzbar) -> List[QRCodeDetection]:
    detections: List[QRCodeDetection] = []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for obj in pyzbar.decode(gray):
        text = obj.data.decode("utf-8", errors="replace")
        points = obj.polygon or []
        if points:
            quad_points = [(float(p.x), float(p.y)) for p in points]
        else:
            rect = obj.rect
            quad_points = [
                (float(rect.left), float(rect.top)),
                (float(rect.left + rect.width), float(rect.top)),
                (float(rect.left + rect.width), float(rect.top + rect.height)),
                (float(rect.left), float(rect.top + rect.height)),
            ]
        center_x = sum(p[0] for p in quad_points) / len(quad_points)
        center_y = sum(p[1] for p in quad_points) / len(quad_points)
        area = _polygon_area(np.array(quad_points))
        detections.append(
            QRCodeDetection(
                text=text,
                points=quad_points,
                center=(center_x, center_y),
                area=area,
            )
        )
    return detections
