import cv2
import numpy as np


def render_plate(text: str, width: int = 380) -> np.ndarray:
    img = np.full((90, width, 3), 255, np.uint8)
    cv2.rectangle(img, (2, 2), (width - 3, 87), (0, 0, 0), 3)
    cv2.putText(img, text, (16, 62), cv2.FONT_HERSHEY_DUPLEX, 1.7, (0, 0, 0), 3, cv2.LINE_AA)
    return img


def solid(bgr: tuple[int, int, int], size: int = 200) -> np.ndarray:
    return np.full((size, size, 3), bgr, np.uint8)
