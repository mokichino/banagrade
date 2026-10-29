from pathlib import Path

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


class StubBoxes:
    def __init__(self, boxes):
        import torch

        self.xyxy = torch.tensor([b for b, _, _ in boxes], dtype=torch.float32).reshape(-1, 4)
        self.conf = torch.tensor([c for _, c, _ in boxes], dtype=torch.float32)
        self.cls = torch.tensor([k for _, _, k in boxes], dtype=torch.float32)

    def __len__(self):
        return len(self.conf)


class StubDetector:
    """Boxes are (xyxy, confidence) for class 0, or (xyxy, confidence, class)."""

    def __init__(self, boxes, task="detect", names=None):
        self.boxes = [b if len(b) == 3 else (*b, 0) for b in boxes]
        self.task, self.names = task, names or {0: "banana_bunch"}
        self.calls = []

    def predict(self, source, conf, imgsz, classes=None, verbose=False):
        self.calls.append({"conf": conf, "imgsz": imgsz, "classes": classes})
        kept = [b for b in self.boxes if b[1] >= conf and (classes is None or b[2] in classes)]
        return [type("Result", (), {"boxes": StubBoxes(kept)})()]


def _inference(stage2, presence=None):
    from app.model_inference import UltralyticsInference

    inference = UltralyticsInference("s1.pt", "s2.pt")
    inference._stage2, inference._presence = stage2, presence
    inference._presence_classes, inference._person_classes = ([46], [0]) if presence else ([], [])
    return inference


def test_trigger_uses_stage2_first_at_640_px() -> None:
    pytest.importorskip("torch")
    stage2 = StubDetector([((10, 20, 300, 200), 0.93)])
    presence = StubDetector([((0, 0, 50, 50), 0.99)])
    box, confidence, source = _inference(stage2, presence).detect_presence(None, 0.80)
    assert box == (10, 20, 300, 200) and confidence == pytest.approx(0.93) and source == "Stage 2"
    assert stage2.calls == [{"conf": 0.80, "imgsz": 640, "classes": None}]
    assert presence.calls == []  # the backup only runs when Stage 2 sees nothing


def test_trigger_falls_back_to_coco_banana_for_bunches_stage2_misses() -> None:
    pytest.importorskip("torch")
    stage2 = StubDetector([((10, 20, 300, 200), 0.40)])  # below the 0.80 trigger gate, e.g. a diseased bunch
    presence = StubDetector([((12, 22, 298, 205), 0.88, 46)])
    box, confidence, source = _inference(stage2, presence).detect_presence(None, 0.80)
    assert box == (12, 22, 298, 205) and confidence == pytest.approx(0.88) and source == "backup"
    assert presence.calls == [{"conf": 0.25, "imgsz": 640, "classes": [46, 0]}]


def test_backup_ignores_a_banana_that_a_hand_covers() -> None:
    pytest.importorskip("torch")
    stage2 = StubDetector([])
    # Live camera: an open palm, fingers together, scored 0.62 "banana" inside a 0.65 "person" box.
    hand = StubDetector([((100, 40, 220, 200), 0.62, 46), ((80, 20, 260, 360), 0.65, 0)])
    assert _inference(stage2, hand).detect_presence(None, 0.80) is None


def test_backup_keeps_a_bunch_next_to_a_stray_person_box() -> None:
    pytest.importorskip("torch")
    # Held-out photos sometimes show a faint "person" elsewhere in the frame; it must not hide the bunch.
    scene = StubDetector([((150, 80, 450, 300), 0.615, 46), ((560, 0, 640, 120), 0.61, 0), ((0, 0, 60, 60), 0.20, 0)])
    hit = _inference(StubDetector([]), scene).detect_presence(None, 0.80)
    assert hit is not None and hit.confidence == pytest.approx(0.615) and hit.source == "backup"


def test_backup_ignores_bananas_below_its_threshold() -> None:
    pytest.importorskip("torch")
    weak = StubDetector([((150, 80, 450, 300), 0.40, 46)])  # returned because predict runs at the person gate
    assert _inference(StubDetector([]), weak).detect_presence(None, 0.80) is None


def test_trigger_without_backup_model_is_stage2_only() -> None:
    pytest.importorskip("torch")
    assert _inference(StubDetector([((10, 20, 300, 200), 0.40)])).detect_presence(None, 0.80) is None


def test_invalid_or_missing_presence_model_is_reported_without_stopping_grading(tmp_path) -> None:
    from app.model_inference import UltralyticsInference

    missing = UltralyticsInference("s1.pt", "s2.pt", presence_path=tmp_path / "nope.pt")
    missing._load_presence(lambda path: None)
    assert missing._presence is None and "presence" in missing._model_errors

    wrong = tmp_path / "wrong.pt"
    wrong.write_bytes(b"x")
    inference = UltralyticsInference("s1.pt", "s2.pt", presence_path=wrong)
    inference._load_presence(lambda path: StubDetector([], names={0: "person"}))
    assert inference._presence is None
    assert "banana class" in inference._model_errors["presence"]
    assert next(m for m in inference.status()["models"] if m["key"] == "presence")["state"] == "error"

    inference._load_presence(lambda path: StubDetector([], names={0: "person", 46: "banana"}))
    assert (inference._presence_classes, inference._person_classes) == ([46], [0])



def test_trained_presence_model_is_the_whole_trigger() -> None:
    pytest.importorskip("torch")
    from app.model_inference import UltralyticsInference

    stage2 = StubDetector([((10, 20, 300, 200), 0.95)])
    presence = StubDetector([((12, 22, 298, 205), 0.93)], names={0: "banana_bunch"})
    inference = UltralyticsInference("s1.pt", "s2.pt", presence_path="best.pt")
    inference._stage2 = stage2
    inference._load_presence(lambda path: presence)  # file check is skipped below
    assert inference._presence_mode is None  # best.pt does not exist in the test directory

    inference.presence_path = Path(__file__)  # any existing file
    inference._load_presence(lambda path: presence)
    assert inference._presence_mode == "trained"
    hit = inference.detect_presence(None, 0.80)
    assert hit.source == "presence" and hit.confidence == pytest.approx(0.93)
    assert presence.calls == [{"conf": 0.80, "imgsz": 640, "classes": None}]
    assert stage2.calls == []  # one model per check
    status = inference.status()
    assert status["trigger"] == "YOLO11n-presence detector"
    assert next(m for m in status["models"] if m["key"] == "presence")["architecture"].startswith("YOLO11n-presence")


def test_trained_presence_model_below_the_trigger_gate_does_not_fire() -> None:
    pytest.importorskip("torch")
    from app.model_inference import UltralyticsInference

    inference = UltralyticsInference("s1.pt", "s2.pt", presence_path=Path(__file__))
    inference._stage2 = StubDetector([((10, 20, 300, 200), 0.95)])
    inference._load_presence(lambda path: StubDetector([((12, 22, 298, 205), 0.74)], names={0: "banana_bunch"}))
    assert inference.detect_presence(None, 0.80) is None  # Stage 2 is not consulted in trained mode
