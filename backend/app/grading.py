from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FinalGrade(StrEnum):
    CLASS_A = "Class A"
    CLASS_B = "Class B"
    REJECTED = "Rejected"


class RejectionReason(StrEnum):
    SURFACE_UNHEALTHY = "SURFACE_UNHEALTHY"
    UNDERSIZED = "UNDERSIZED"
    DETECTION_FAILED = "DETECTION_FAILED"
    CALIBRATION_INVALID = "CALIBRATION_INVALID"
    CAMERA_ERROR = "CAMERA_ERROR"
    ILLUMINATION_ERROR = "ILLUMINATION_ERROR"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class Stage1Result(StrEnum):
    HEALTHY = "Healthy"
    UNHEALTHY = "Unhealthy"


@dataclass(frozen=True, slots=True)
class GradeThresholds:
    class_a_min_cm: float = 12.0
    class_b_min_cm: float = 8.0

    def validate(self) -> None:
        if self.class_b_min_cm <= 0:
            raise ValueError("Class B minimum must be positive")
        if self.class_a_min_cm <= self.class_b_min_cm:
            raise ValueError("Class A minimum must be greater than Class B minimum")


@dataclass(frozen=True, slots=True)
class GradeDecision:
    grade: FinalGrade | None
    rejection_reason: RejectionReason | None = None
    is_technical_failure: bool = False


def decide_grade(
    stage1: Stage1Result,
    length_cm: float | None,
    thresholds: GradeThresholds,
    *,
    stage2_detected: bool = True,
    calibration_valid: bool = True,
) -> GradeDecision:
    thresholds.validate()

    if stage1 is Stage1Result.UNHEALTHY:
        return GradeDecision(FinalGrade.REJECTED, RejectionReason.SURFACE_UNHEALTHY)
    if not calibration_valid:
        return GradeDecision(None, RejectionReason.CALIBRATION_INVALID, True)
    if not stage2_detected:
        return GradeDecision(None, RejectionReason.DETECTION_FAILED, True)
    if length_cm is None or length_cm < 0:
        return GradeDecision(None, RejectionReason.PIPELINE_ERROR, True)
    if length_cm >= thresholds.class_a_min_cm:
        return GradeDecision(FinalGrade.CLASS_A)
    if length_cm >= thresholds.class_b_min_cm:
        return GradeDecision(FinalGrade.CLASS_B)
    return GradeDecision(FinalGrade.REJECTED, RejectionReason.UNDERSIZED)