import pytest

from app.model_inference import classify_with, pixel_length_from_bbox, stage1_transform


def test_pixel_length_uses_explicit_axis() -> None:
    bbox = (10, 20, 110, 80)
    assert pixel_length_from_bbox(bbox, "width") == 100
    assert pixel_length_from_bbox(bbox, "height") == 60


def test_pixel_length_rejects_unknown_axis() -> None:
    with pytest.raises(ValueError):
        pixel_length_from_bbox((0, 0, 10, 10), "diagonal")


class StubClassifier:
    """Mimics the Ultralytics Classify head in eval mode: returns (probabilities, logits)."""

    def __init__(self, probs: list[float]) -> None:
        self.probs = probs
        self.inputs = []

    def __call__(self, batch):
        import torch

        self.inputs.append(batch)
        p = torch.tensor([self.probs])
        return p, p.log()


def test_stage1_squashes_whole_frame_without_center_crop() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("torchvision")
    frame = np.zeros((2592, 4608, 3), np.uint8)
    frame[:, -200:] = (0, 0, 255)  # red strip along the right edge (BGR)
    net = StubClassifier([0.1, 0.9])

    label, confidence = classify_with(net, stage1_transform(), {0: "Healthy", 1: "Unhealthy"}, frame)

    batch = net.inputs[0]
    assert tuple(batch.shape) == (1, 3, 224, 224)
    assert 0.0 <= float(batch.min()) and float(batch.max()) <= 1.0
    # A center crop would cut the right edge off; the squash keeps it, and BGR became RGB.
    assert float(batch[0, 0, 112, -1]) == pytest.approx(1.0, abs=0.02)
    assert float(batch[0, 2, 112, -1]) == pytest.approx(0.0, abs=0.02)
    assert (label, confidence) == ("Unhealthy", pytest.approx(0.9))
