"""Camera colour and brightness calibrated to match the training photos, saved and reapplied at every start.

The dataset was shot on the same camera (Raspberry Pi imx708, rpicam-apps, 4608x2592) in daylight with automatic
exposure and white balance. Measured on 2026-10-27, the rig under the ring light came out brighter and drifted in
colour: bunch brightness 171-174 against the dataset's 149 (HSV value, 0-255), velvet 51-53 against 11, and a blue
cast that turned the white sheet light blue within minutes. Two calibrations bring it back:

- White balance from a white sheet: fixed colour gains that make the sheet neutral, as the dataset's backdrop is.
- Brightness from a bunch: an exposure compensation (EV) that makes the bunch as bright as the dataset's median.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .alignment import _corners

# Median brightness (HSV value) of the bunch pixels in the 269 dataset Class A and B photos.
DATASET_BUNCH_BRIGHTNESS = 149.0
BRIGHTNESS_TOLERANCE = 5.0
NEUTRAL_TOLERANCE = 0.02  # sheet red/green and blue/green within 2% counts as neutral
EV_LIMITS = (-3.0, 3.0)
GAIN_LIMITS = (0.5, 8.0)


def sheet_colour(bgr: Any) -> tuple[float, float, float] | None:
    """Median (blue, green, red) of the middle of a white sheet in view, or None when no whole sheet is found."""
    import cv2
    import numpy as np

    corners = _corners(bgr)
    if corners is None:
        return None
    centre = corners.mean(axis=0)
    inner = centre + (corners - centre) * 0.6  # stay clear of the edges and their shadows
    height, width = bgr.shape[:2]
    scale = 1152 / width if width > 1152 else 1.0
    small = cv2.resize(bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    mask = np.zeros(small.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.round(inner * scale).astype(np.int32)], 255)
    pixels = small[mask > 0]
    bright = pixels[pixels.sum(axis=1) >= np.percentile(pixels.sum(axis=1), 30)]  # drop a pen mark on the sheet
    return tuple(float(np.median(bright[:, channel])) for channel in range(3))  # type: ignore[return-value]


def neutral_gains(sheet_bgr: tuple[float, float, float], gains: tuple[float, float]) -> tuple[float, float]:
    """Colour gains (red, blue) that would make the sheet grey, from the gains it was captured with."""
    blue, green, red = sheet_bgr
    clamp = lambda value: min(GAIN_LIMITS[1], max(GAIN_LIMITS[0], value))  # noqa: E731
    return round(clamp(gains[0] * green / max(red, 1.0)), 4), round(clamp(gains[1] * green / max(blue, 1.0)), 4)


def colour_cast(sheet_bgr: tuple[float, float, float]) -> float:
    blue, green, red = sheet_bgr
    return max(abs(red / green - 1), abs(blue / green - 1))


def bunch_brightness(bgr: Any) -> float | None:
    """Mean brightness (HSV value) of the banana-coloured pixels on a 640 px wide copy, as measured on the dataset."""
    import cv2

    height, width = bgr.shape[:2]
    small = cv2.resize(bgr, (640, round(height * 640 / width)), interpolation=cv2.INTER_AREA) if width > 640 else bgr
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    banana = (hue >= 5) & (hue <= 55) & (saturation >= 25) & (value >= 40)
    if banana.mean() < 0.02:
        return None
    return float(value[banana].mean())


def next_exposure_value(current_ev: float, brightness: float, target: float = DATASET_BUNCH_BRIGHTNESS) -> float:
    """EV step that would move ``brightness`` to ``target``, treating the image as gamma 2.2."""
    step = math.log2((target / 255) ** 2.2 / (max(brightness, 1.0) / 255) ** 2.2)
    return round(min(EV_LIMITS[1], max(EV_LIMITS[0], current_ev + step)), 2)


def load_settings(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2))
    temporary.replace(path)


def controls_for(settings: dict[str, Any]) -> dict[str, Any]:
    """Picamera2 controls for saved settings; automatic white balance and EV 0 when none are saved."""
    controls: dict[str, Any] = {"ExposureValue": float(settings.get("exposure_value", 0.0))}
    gains = settings.get("colour_gains")
    if gains:
        controls.update({"AwbEnable": False, "ColourGains": (float(gains[0]), float(gains[1]))})
    else:
        controls["AwbEnable"] = True
    return controls
