import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.preprocessing import colour_share, frame_health, hsv_mask, stage1_input  # noqa: E402


def _scene() -> "np.ndarray":
    frame = np.full((360, 640, 3), 5, np.uint8)  # black velvet
    frame[100:260, 200:440] = (40, 200, 220)  # yellow-green bunch (BGR)
    frame[10:14, 10:14] = (255, 255, 255)  # specular speck smaller than the opening kernel
    return frame


def test_mask_keeps_largest_bunch_and_drops_noise() -> None:
    mask = hsv_mask(_scene())
    assert mask[180, 320] == 255
    assert mask[12, 12] == 0
    assert mask[5, 600] == 0


def test_stage1_input_blacks_out_background_without_cropping() -> None:
    frame = _scene()
    masked = stage1_input(frame)
    assert masked.shape == frame.shape
    assert tuple(masked[180, 320]) == (40, 200, 220)
    assert tuple(masked[5, 600]) == (0, 0, 0)


def test_frame_health_flags_covered_lens_and_flat_frames() -> None:
    assert frame_health(_scene()).ok
    assert frame_health(np.zeros((360, 640, 3), np.uint8)).status == "dark"
    assert frame_health(np.full((360, 640, 3), 120, np.uint8)).status == "obstructed"


def test_colour_share_separates_banana_skin_from_paper_and_velvet() -> None:
    frame = np.full((2592, 4608, 3), 5, np.uint8)  # velvet
    assert colour_share(frame) == 0.0
    frame[:, :2304] = (40, 200, 220)  # yellow-green skin (BGR) over half the frame
    assert colour_share(frame) == pytest.approx(0.5, abs=0.01)
    frame[:, :2304] = (232, 236, 238)  # white paper
    assert colour_share(frame) == 0.0
