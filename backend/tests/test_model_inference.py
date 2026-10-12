import pytest

from app.model_inference import pixel_length_from_bbox


def test_pixel_length_uses_explicit_axis() -> None:
    bbox = (10, 20, 110, 80)
    assert pixel_length_from_bbox(bbox, "width") == 100
    assert pixel_length_from_bbox(bbox, "height") == 60


def test_pixel_length_rejects_unknown_axis() -> None:
    with pytest.raises(ValueError):
        pixel_length_from_bbox((0, 0, 10, 10), "diagonal")