import cv2
import numpy as np


def render_plate(text: str, width: int = 380) -> np.ndarray:
    img = np.full((90, width, 3), 255, np.uint8)
    cv2.rectangle(img, (2, 2), (width - 3, 87), (0, 0, 0), 3)
    cv2.putText(img, text, (16, 62), cv2.FONT_HERSHEY_DUPLEX, 1.7, (0, 0, 0), 3, cv2.LINE_AA)
    return img


def solid(bgr: tuple[int, int, int], size: int = 200) -> np.ndarray:
    return np.full((size, size, 3), bgr, np.uint8)


def render_two_row_plate(top: str, bottom: str, width: int = 300) -> np.ndarray:
    """The two-row layout used on most Indian two-wheelers: e.g. DL14S over Z8550."""
    height = int(width / 1.9)
    img = np.full((height, width, 3), 255, np.uint8)
    cv2.rectangle(img, (2, 2), (width - 3, height - 3), (0, 0, 0), 3)
    for i, text in enumerate((top, bottom)):
        scale = 2.1
        while True:
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 4)
            if tw <= width - 40:
                break
            scale -= 0.05
        y = int(height * (0.31 if i == 0 else 0.79)) + th // 2
        cv2.putText(img, text, ((width - tw) // 2, y), cv2.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    return img
