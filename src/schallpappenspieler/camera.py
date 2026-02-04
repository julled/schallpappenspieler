"""Camera capture configuration and initialization."""

import cv2


def open_camera(
    index: int, preferred_width: int, preferred_height: int
) -> cv2.VideoCapture:
    """
    Open and configure a camera device for high-speed capture.

    Args:
        index: Camera device index (0 for default webcam)
        preferred_width: Desired frame width (0 = auto-select max)
        preferred_height: Desired frame height (0 = auto-select max)

    Returns:
        Configured VideoCapture object ready for threaded reading

    Note:
        - Uses MJPG compression to achieve 30 FPS on USB 2.0 webcams
        - Buffer size is minimized (1 frame) to reduce latency
        - Uncompressed YUYV format typically caps at 1-2 FPS at 1080p
    """
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera index {index}")

    # Use MJPG format — uncompressed YUYV at high resolution often caps at 1-2 FPS
    # on USB 2.0 webcams. MJPG unlocks 30 FPS at 1080p.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    if preferred_width and preferred_height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, preferred_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, preferred_height)
    else:
        # Ask for a very large size so the driver picks the highest available.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 10000)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 10000)

    cap.set(cv2.CAP_PROP_FPS, 30)
    # Minimize internal buffer to reduce latency in threaded capture
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap
