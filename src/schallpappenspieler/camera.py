import cv2


def open_camera(
    index: int, preferred_width: int, preferred_height: int
) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera index {index}")

    if preferred_width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, preferred_width)
    if preferred_height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, preferred_height)

    return cap
