import pytest

from app.grading import (
    FinalGrade,
    GradeThresholds,
    RejectionReason,
    Stage1Result,
    decide_grade,
)


def test_grade_boundaries() -> None:
    thresholds = GradeThresholds()
    assert decide_grade(Stage1Result.HEALTHY, 12, thresholds).grade is FinalGrade.CLASS_A
    assert decide_grade(Stage1Result.HEALTHY, 8, thresholds).grade is FinalGrade.CLASS_B
    assert decide_grade(Stage1Result.HEALTHY, 7.99, thresholds).rejection_reason is RejectionReason.UNDERSIZED


def test_unhealthy_is_commercial_rejection() -> None:
    decision = decide_grade(Stage1Result.UNHEALTHY, None, GradeThresholds())
    assert decision.grade is FinalGrade.REJECTED
    assert decision.rejection_reason is RejectionReason.SURFACE_UNHEALTHY
    assert decision.is_technical_failure is False


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"stage2_detected": False}, RejectionReason.DETECTION_FAILED),
        ({"calibration_valid": False}, RejectionReason.CALIBRATION_INVALID),
        ({"length_cm": None}, RejectionReason.PIPELINE_ERROR),
    ],
)
def test_technical_failures_do_not_receive_a_commercial_grade(kwargs, reason) -> None:
    length_cm = kwargs.pop("length_cm", 10)
    decision = decide_grade(Stage1Result.HEALTHY, length_cm, GradeThresholds(), **kwargs)
    assert decision.grade is None
    assert decision.rejection_reason is reason
    assert decision.is_technical_failure is True


def test_thresholds_must_be_ordered_and_positive() -> None:
    with pytest.raises(ValueError):
        GradeThresholds(class_a_min_cm=8, class_b_min_cm=8).validate()
    with pytest.raises(ValueError):
        GradeThresholds(class_a_min_cm=12, class_b_min_cm=0).validate()