import pytest

from app.grading import (
    DEFAULT_WIDTH_THRESHOLD_PX,
    FinalGrade,
    RejectionReason,
    Stage1Result,
    decide_grade,
    scale_width_to_reference,
)


def test_width_threshold_boundary_matches_thesis_rule() -> None:
    # Thesis 4.4.3 / models/grading_config.txt: width >= 2730.07 px -> Class A, else Class B.
    assert decide_grade(Stage1Result.HEALTHY, 2730.07).grade is FinalGrade.CLASS_A
    assert decide_grade(Stage1Result.HEALTHY, 3100.0).grade is FinalGrade.CLASS_A
    assert decide_grade(Stage1Result.HEALTHY, 2730.06).grade is FinalGrade.CLASS_B
    assert decide_grade(Stage1Result.HEALTHY, 900.0).grade is FinalGrade.CLASS_B
    assert DEFAULT_WIDTH_THRESHOLD_PX == 2730.07


def test_unhealthy_is_rejected_regardless_of_width() -> None:
    decision = decide_grade(Stage1Result.UNHEALTHY, 4000.0)
    assert decision.grade is FinalGrade.REJECTED
    assert decision.rejection_reason is RejectionReason.SURFACE_UNHEALTHY
    assert decision.is_technical_failure is False


def test_healthy_bunch_is_never_size_rejected() -> None:
    # Pixel-only rule: no centimetre-based undersize rejection.
    assert decide_grade(Stage1Result.HEALTHY, 1.0).grade is FinalGrade.CLASS_B


@pytest.mark.parametrize(
    ("width", "detected", "reason"),
    [(None, False, RejectionReason.DETECTION_FAILED), (None, True, RejectionReason.PIPELINE_ERROR), (-1.0, True, RejectionReason.PIPELINE_ERROR)],
)
def test_technical_failures_receive_no_commercial_grade(width, detected, reason) -> None:
    decision = decide_grade(Stage1Result.HEALTHY, width, stage2_detected=detected)
    assert decision.grade is None
    assert decision.rejection_reason is reason
    assert decision.is_technical_failure is True


def test_width_is_projected_onto_reference_frame() -> None:
    assert scale_width_to_reference(1137.53, 1920) == pytest.approx(2730.07, abs=0.01)
    assert scale_width_to_reference(2730.07, 4608) == pytest.approx(2730.07)
    with pytest.raises(ValueError):
        scale_width_to_reference(10, 0)


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        decide_grade(Stage1Result.HEALTHY, 10, 0)
