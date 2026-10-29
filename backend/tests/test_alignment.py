import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app.alignment import measure_sheet  # noqa: E402


def _sheet(corners):
    frame = np.full((2592, 4608, 3), 12, np.uint8)  # velvet
    cv2.fillPoly(frame, [np.array(corners, np.int32)], (225, 230, 228))
    return frame


def test_level_sheet_at_45_cm() -> None:
    # Short bond at 45 cm under the published 66 x 41 degree field of view: about 2203 x 1663 px.
    result = measure_sheet(_sheet([(1203, 465), (3406, 465), (3406, 2128), (1203, 2128)]))
    assert result["level"] and result["height_ok"]
    assert result["front_back_ratio"] == pytest.approx(1.0, abs=0.005)
    assert abs(result["front_back_tilt_deg"]) < 0.5 and abs(result["side_tilt_deg"]) < 0.5
    assert result["height_cm"] == pytest.approx(45, abs=0.5)


def test_tilted_camera_like_the_rig_on_27_october() -> None:
    # The rig photo: top edge 1995 px, bottom 2302 px, left 1641 px, right 1579 px.
    result = measure_sheet(_sheet([(1100, 650), (3095, 650), (3250, 2229), (948, 2291)]))
    assert not result["level"]
    assert result["front_back_ratio"] == pytest.approx(1.154, abs=0.01)
    assert result["front_back_tilt_deg"] == pytest.approx(17.9, abs=1.0)  # lens leans towards the top of the view
    assert result["side_tilt_deg"] < -2  # the left of the view is nearer
    assert len(result["corners"]) == 4


@pytest.mark.parametrize(
    "corners",
    [
        None,  # empty table
        [(0, 400), (2400, 400), (2400, 2200), (0, 2200)],  # cut off by the left edge
    ],
)
def test_no_whole_sheet_gives_no_reading(corners) -> None:
    frame = np.full((2592, 4608, 3), 12, np.uint8) if corners is None else _sheet(corners)
    assert measure_sheet(frame) is None
