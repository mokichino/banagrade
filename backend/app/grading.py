"""Deterministic grading contract.

Thesis traceability:
- Section 3.5.4 Rule 1: an Unhealthy Stage 1 result terminates the pipeline as Rejected,
  whatever its confidence. Only a Healthy result below BANAGRADE_STAGE1_MIN_CONF is held
  for a hand check (pipeline.py).
- Sections 3.5.3 / 3.7.6 / 4.4.3: healthy bunches are graded by the horizontal
  whole-bunch bounding-box width measured in the original 4608 x 2592 image
  coordinate system. The frozen, validation-selected threshold is 2730.07 px:
  width >= threshold -> Class A, otherwise Class B.
- The threshold is an image-space decision boundary, not a centimetre measurement
  (Sections 1.6, 2.4, 3.4.2). The "Large hand >= 12 cm" / "Small hand 8-12 cm"
  wording is the commercial class description from Table 1 / Table 5 only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

REFERENCE_RESOLUTION: tuple[int, int] = (4608, 2592)
DEFAULT_WIDTH_THRESHOLD_PX = 2730.07


class FinalGrade(StrEnum):
    CLASS_A = "Class A"
    CLASS_B = "Class B"
    REJECTED = "Rejected"


class RejectionReason(StrEnum):
    SURFACE_UNHEALTHY = "SURFACE_UNHEALTHY"
    DETECTION_FAILED = "DETECTION_FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CAMERA_ERROR = "CAMERA_ERROR"
    ILLUMINATION_ERROR = "ILLUMINATION_ERROR"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    NOT_A_BUNCH = "NOT_A_BUNCH"
    # Retained so rows written by earlier cm-based builds still render.
    UNDERSIZED = "UNDERSIZED"
    CALIBRATION_INVALID = "CALIBRATION_INVALID"


class Stage1Result(StrEnum):
    HEALTHY = "Healthy"
    UNHEALTHY = "Unhealthy"


@dataclass(frozen=True, slots=True)
class GradeDecision:
    grade: FinalGrade | None
    rejection_reason: RejectionReason | None = None
    is_technical_failure: bool = False


def width_threshold_px() -> float:
    value = float(os.getenv("BANAGRADE_WIDTH_THRESHOLD_PX", DEFAULT_WIDTH_THRESHOLD_PX))
    if value <= 0:
        raise ValueError("BANAGRADE_WIDTH_THRESHOLD_PX must be positive")
    return value


def scale_width_to_reference(width_px: float, image_width: int) -> float:
    """Project a width measured on a frame of any size onto the 4608 px reference frame."""
    if image_width <= 0:
        raise ValueError("image_width must be positive")
    return width_px * (REFERENCE_RESOLUTION[0] / image_width)


def decide_grade(
    stage1: Stage1Result,
    width_px: float | None,
    threshold_px: float = DEFAULT_WIDTH_THRESHOLD_PX,
    *,
    stage2_detected: bool = True,
) -> GradeDecision:
    if threshold_px <= 0:
        raise ValueError("threshold_px must be positive")
    if stage1 is Stage1Result.UNHEALTHY:
        return GradeDecision(FinalGrade.REJECTED, RejectionReason.SURFACE_UNHEALTHY)
    if not stage2_detected:
        return GradeDecision(None, RejectionReason.DETECTION_FAILED, True)
    if width_px is None or width_px < 0:
        return GradeDecision(None, RejectionReason.PIPELINE_ERROR, True)
    if width_px >= threshold_px:
        return GradeDecision(FinalGrade.CLASS_A)
    return GradeDecision(FinalGrade.CLASS_B)
