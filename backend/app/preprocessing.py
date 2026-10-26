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


def colour_share(bgr: Any, min_saturation: int = 30, min_value: int = 40) -> float:
    """Share of the frame that is clearly coloured (HSV saturation >= 30 and not velvet-dark), on a 1152 px wide copy.

    Banana skin, green, yellow or brown, is saturated; paper, the velvet and grey objects are not. All 344
    dataset photos (Class A, B and Rejected) scored at least 0.19; the white paper graded as Class B on
    2026-10-26 scored 0.012-0.014. A hand scores about 0.87, so this does not replace the Stage 2 minimum.
    """
    import cv2

    height, width = bgr.shape[:2]
    if width > 1152:
        bgr = cv2.resize(bgr, (1152, round(height * 1152 / width)), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 1] >= min_saturation) & (hsv[..., 2] >= min_value)).mean())


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
