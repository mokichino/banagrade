import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.preprocessing import banana_share, frame_health, hsv_mask, stage1_input  # noqa: E402


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


def test_banana_share_counts_banana_hues_inside_the_box_only() -> None:
    frame = np.full((2592, 4608, 3), 5, np.uint8)  # velvet
    assert banana_share(frame) == 0.0
    frame[500:2000, 1000:3000] = (40, 200, 220)  # yellow-green skin (BGR)
    assert banana_share(frame, (1000, 500, 3000, 2000)) == pytest.approx(1.0, abs=0.01)
    frame[500:2000, 1000:3000] = (240, 215, 200)  # paper under a blue cast: saturated, but blue
    assert banana_share(frame, (1000, 500, 3000, 2000)) == 0.0
    frame[100:400, 3800:4300] = (20, 110, 240)  # an orange phone case beside the sheet
    assert banana_share(frame, (1000, 500, 3000, 2000)) == 0.0
    assert banana_share(frame) > 0.0
