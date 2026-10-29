"""Camera alignment check from a short bond sheet (27.94 x 21.59 cm) lying flat on the velvet.

Looking straight down, the sheet's opposite edges are the same length. If the camera leans, the edge nearer
the lens looks longer, and the ratio gives the tilt. A tilted camera makes the same bunch look wider in one
part of the view than another, which moves grades across the 2730.07 px threshold.

The tilt comes from the sheet alone. The height uses the published Camera Module 3 field of view (66 x 41
degrees), so it is approximate: on 2026-10-26 it read 42-43 cm where the tape said 45.
"""

from __future__ import annotations

import math
from typing import Any

SHEET_CM = (27.94, 21.59)  # short bond (8.5 x 11 in)
FOV_DEG = (66.0, 41.0)
LEVEL_RATIO = 0.02  # opposite edges within 2% (about 2.5 degrees) counts as level
HEIGHT_TOLERANCE_CM = 3.0


def _corners(bgr: Any) -> Any | None:
    """Corners (top-left, top-right, bottom-right, bottom-left) of the largest bright quadrilateral, in full-frame px."""
    import cv2
    import numpy as np

    height, width = bgr.shape[:2]
    scale = 1152 / width if width > 1152 else 1.0
    small = cv2.resize(bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if not 0.05 <= cv2.contourArea(contour) / mask.size <= 0.85:
        return None
    quad = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True).reshape(-1, 2).astype(float)
    if len(quad) != 4 or not cv2.isContourConvex(quad.astype(np.int32)):
        return None
    total, diff = quad.sum(1), np.diff(quad, axis=1).ravel()
    ordered = np.array([quad[total.argmin()], quad[diff.argmin()], quad[total.argmax()], quad[diff.argmax()]])
    margin = 3
    if (ordered[:, 0] <= margin).any() or (ordered[:, 1] <= margin).any() or (ordered[:, 0] >= small.shape[1] - margin).any() or (ordered[:, 1] >= small.shape[0] - margin).any():
        return None  # cut off by the frame edge
    return ordered / scale


def _tilt_deg(near_over_far: float, centre_cm: float, span_cm: float) -> float:
    """Tilt along one axis from the length ratio of two opposite edges ``span_cm`` apart."""
    offset = centre_cm * (near_over_far - 1) / (near_over_far + 1)  # half the depth difference
    return math.degrees(math.asin(max(-1.0, min(1.0, 2 * offset / span_cm))))


def measure_sheet(bgr: Any) -> dict[str, Any] | None:
    """Tilt and height from a sheet in view, or None when no whole sheet is found."""
    import numpy as np

    corners = _corners(bgr)
    if corners is None:
        return None
    height, width = bgr.shape[:2]
    tl, tr, br, bl = corners
    top, bottom = float(np.linalg.norm(tr - tl)), float(np.linalg.norm(br - bl))
    left, right = float(np.linalg.norm(bl - tl)), float(np.linalg.norm(br - tr))
    landscape = top + bottom >= left + right
    across_cm, down_cm = SHEET_CM if landscape else SHEET_CM[::-1]
    # Height at the sheet centre from its mean width and height against the field of view.
    from_width = across_cm / ((top + bottom) / 2 / width) / (2 * math.tan(math.radians(FOV_DEG[0] / 2)))
    from_height = down_cm / ((left + right) / 2 / height) / (2 * math.tan(math.radians(FOV_DEG[1] / 2)))
    centre_cm = (from_width + from_height) / 2
    front_back = bottom / top  # > 1: the bottom of the view is nearer the lens
    side = right / left  # > 1: the right of the view is nearer the lens
    level = abs(front_back - 1) <= LEVEL_RATIO and abs(side - 1) <= LEVEL_RATIO
    return {
        "corners": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
        "edges_px": {"top": round(top), "bottom": round(bottom), "left": round(left), "right": round(right)},
        "front_back_ratio": round(front_back, 3),
        "side_ratio": round(side, 3),
        # Positive: the lens leans towards the top (front-back) or the left (side) of the view.
        "front_back_tilt_deg": round(_tilt_deg(front_back, centre_cm, down_cm), 1),
        "side_tilt_deg": round(_tilt_deg(side, centre_cm, across_cm), 1),
        "height_cm": round(centre_cm, 1),
        "level": level,
        "height_ok": abs(centre_cm - 45) <= HEIGHT_TOLERANCE_CM,
    }
