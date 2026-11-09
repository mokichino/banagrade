"""Scan photos for the dashboard: a light preview of the saved full-resolution frame."""

from __future__ import annotations

from pathlib import Path

# The preview is the frame at exactly a quarter of its size (1152 x 648 for the 4608 x 2592 camera), so the dashboard
# maps the full-frame Stage 2 box onto it by dividing by this. libjpeg decodes straight to 1/4 scale, which is far
# faster on the Pi than decoding the full frame and resizing, and the ~0.9 MB frame becomes ~100 KB for a phone.
PREVIEW_SCALE = 4


def preview_jpeg(path: Path) -> bytes:
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4)
    if image is None:
        raise FileNotFoundError(path)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise RuntimeError(f"Could not encode a preview of {path}")
    return encoded.tobytes()
