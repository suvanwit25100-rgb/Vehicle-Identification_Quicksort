"""A still image can be analysed like a one-frame clip."""
import cv2
import numpy as np

from app import main
from app.vision.pipeline import _video_info
from app.vision.video import is_image, sample_frames


def write(path):
    cv2.imwrite(str(path), np.full((90, 160, 3), 120, np.uint8))
    return path


def test_an_image_is_one_frame_and_described_as_an_image(tmp_path):
    for name in ("a.jpg", "b.png", "c.bmp"):
        p = write(tmp_path / name)
        assert is_image(p)
        frames = sample_frames(p)
        assert len(frames) == 1 and frames[0].image.shape[:2] == (90, 160)
        info = _video_info(p)
        assert info.kind == "image" and info.fps == 0 and info.frames_total == 1 and (info.width, info.height) == (160, 90)


def test_a_video_is_still_described_as_a_video(tmp_path):
    p = tmp_path / "v.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for _ in range(5):
        w.write(np.zeros((48, 64, 3), np.uint8))
    w.release()
    assert not is_image(p) and _video_info(p).kind == "video"


def test_image_types_are_accepted_by_the_upload_endpoint():
    assert {".jpg", ".jpeg", ".png", ".webp", ".bmp"} <= main.ALLOWED_EXT and ".mp4" in main.ALLOWED_EXT
