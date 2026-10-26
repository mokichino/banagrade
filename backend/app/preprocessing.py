"""Image preprocessing (thesis Sections 3.3.7 and 3.6.4).

Colour order: Picamera2 frames configured as ``"RGB888"`` are laid out in memory
as B, G, R, which is the OpenCV/Ultralytics convention for numpy inputs. Every
function here therefore takes and returns BGR arrays, keeping camera frames
compatible with models trained on images loaded by OpenCV.

Stage 1 receives the HSV-masked RGB image (black background, uncropped).
Stage 2 receives the original raw image so the bounding-box width stays in the
same coordinate system as the frozen 2730.07 px threshold.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _bounds(name: str, default: str) -> tuple[int, int, int]:
    values = tuple(int(part) for part in os.getenv(name, default).split(","))
    if len(values) != 3:
        raise ValueError(f"{name} must contain three comma-separated integers")
    return values  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MaskSettings:
    """HSV range separating the banana bunch from the black velvet backdrop.

    Defaults keep any pixel that is not near-black; tune on site against the
    hand-masked reference images (Section 3.3.3).
    """

    lower: tuple[int, int, int] = (0, 0, 40)
    upper: tuple[int, int, int] = (179, 255, 255)
    kernel_size: int = 7

    @classmethod
    def from_environment(cls) -> "MaskSettings":
        return cls(
            _bounds("BANAGRADE_HSV_LOWER", "0,0,40"),
            _bounds("BANAGRADE_HSV_UPPER", "179,255,255"),
            int(os.getenv("BANAGRADE_MASK_KERNEL", "7")),
        )


def hsv_mask(bgr: Any, settings: MaskSettings | None = None) -> Any:
    """Return a uint8 binary mask (255 = banana) of the largest foreground region."""
    import cv2
    import numpy as np

    settings = settings or MaskSettings()
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(settings.lower, np.uint8), np.array(settings.upper, np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (settings.kernel_size, settings.kernel_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    clean = np.zeros_like(mask)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        cv2.drawContours(clean, [largest], -1, 255, thickness=cv2.FILLED)
    return clean


def apply_mask(bgr: Any, mask: Any) -> Any:
    """Black out the background without cropping, preserving original pixel values."""
    import cv2

    return cv2.bitwise_and(bgr, bgr, mask=mask)


def stage1_input(bgr: Any, settings: MaskSettings | None = None) -> Any:
    return apply_mask(bgr, hsv_mask(bgr, settings))


def banana_share(bgr: Any, box: tuple[float, float, float, float] | None = None) -> float:
    """Share of the box (or the whole frame) in banana colours: OpenCV hue 5-55 (brown, yellow, green), saturation >= 25.

    Measured inside the trigger's box, so things beside the bunch do not count, and by hue, so a colour cast
    does not: on 2026-10-27 auto white balance turned the paper light blue and a saturation-only check read it
    as 91% coloured. All 344 dataset bunches scored at least 0.276 (median 0.63); every paper frame, blue-tinted
    or not, scored 0.004 or less. Skin is in this hue range too (a hand scored 0.30), so hands are left to the
    COCO hand check.
    """
    import cv2

    if box is not None:
        height, width = bgr.shape[:2]
        x1, y1, x2, y2 = (int(round(value)) for value in box)
        bgr = bgr[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
        if bgr.size == 0:
            return 0.0
    height, width = bgr.shape[:2]
    if width > 640:
        bgr = cv2.resize(bgr, (640, max(1, round(height * 640 / width))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return float(((hue >= 5) & (hue <= 55) & (saturation >= 25) & (value >= 40)).mean())


@dataclass(frozen=True, slots=True)
class FrameHealth:
    status: str  # "ok" | "dark" | "obstructed"
    mean_value: float
    std_value: float

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def frame_health(bgr: Any) -> FrameHealth:
    """Conservative illumination / obstruction check for the fast-red error state (Section 3.6.5).

    The black velvet backdrop is intentionally dark, so the defaults only trip when
    the lens is covered or the ring light is off. Tune with
    BANAGRADE_MIN_BRIGHTNESS and BANAGRADE_MIN_CONTRAST on site.
    """
    import cv2

    value = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2]
    mean, std = float(value.mean()), float(value.std())
    min_brightness = float(os.getenv("BANAGRADE_MIN_BRIGHTNESS", "8"))
    min_contrast = float(os.getenv("BANAGRADE_MIN_CONTRAST", "1.5"))
    if mean < min_brightness:
        return FrameHealth("dark", mean, std)
    if std < min_contrast:
        return FrameHealth("obstructed", mean, std)
    return FrameHealth("ok", mean, std)
