import asyncio
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.leds import LedController, LedState  # noqa: E402
from app.model_inference import Stage1Prediction, Stage2Prediction  # noqa: E402
from app.pipeline import PresencePipeline  # noqa: E402
from app.storage import Storage  # noqa: E402


class FakeCamera:
    def capture_array(self, stream: str):
        height, width = (2592, 4608) if stream == "main" else (360, 640)
        frame = np.full((height, width, 3), 5, np.uint8)
        frame[height // 4: 3 * height // 4, width // 4: 3 * width // 4] = (40, 200, 220)
        return frame


class FakeInference:
    length_axis = "width"
    stage1_path = Path("stage1_best.pt")
    stage2_path = Path("stage2_best.pt")
    available = True

    def __init__(self, label: str, width_px: float, image_width: int = 4608) -> None:
        self.label, self.width_px, self.image_width = label, width_px, image_width
        self.stage1_inputs = []
        self.stage2_calls = 0

    def classify(self, image):
        self.stage1_inputs.append(image)
        return Stage1Prediction(self.label, 0.97, 12.0)

    def detect(self, image):
        self.stage2_calls += 1
        return Stage2Prediction(True, (100.0, 50.0, 100.0 + self.width_px, 900.0), self.width_px, 0.93, 30.0, self.image_width, 2592)


def _run(label: str, width_px: float, tmp_path: Path, image_width: int = 4608):
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    session = storage.ensure_active_session()
    inference = FakeInference(label, width_px, image_width)
    pipeline = PresencePipeline(storage, inference, LedController(outputs=None))
    pipeline._camera = FakeCamera()
    events = []

    async def publish(event):
        events.append(event)

    pipeline._publish = publish
    asyncio.run(pipeline._process_scan())
    scan = storage.get_scan(pipeline.last_scan_id)
    return scan, pipeline, inference, events, session


@pytest.mark.parametrize(("width", "grade", "led"), [(2800.0, "Class A", LedState.CLASS_A), (2730.07, "Class A", LedState.CLASS_A), (2400.0, "Class B", LedState.CLASS_B)])
def test_healthy_bunch_is_graded_by_width_threshold(tmp_path, width, grade, led) -> None:
    scan, pipeline, inference, events, session = _run("Healthy", width, tmp_path)
    assert scan["final_grade"] == grade
    assert scan["session_id"] == session["id"]
    assert scan["stage2_confidence"] == 0.93
    assert scan["pixel_length"] == pytest.approx(width)
    assert '"width_threshold_px":2730.07' in scan["threshold_values"]
    assert pipeline.leds.state is led
    assert [e["event_type"] for e in events][-2:] == ["scan_completed", "fsm_state_changed"]
    # Stage 1 receives the masked image: background pixels are black.
    assert inference.stage1_inputs[0][0, 0].tolist() == [0, 0, 0]


def test_unhealthy_bunch_is_rejected_without_running_stage2(tmp_path) -> None:
    scan, pipeline, inference, _, _ = _run("Unhealthy", 3000.0, tmp_path)
    assert scan["final_grade"] == "Rejected"
    assert scan["rejection_reason"] == "SURFACE_UNHEALTHY"
    assert inference.stage2_calls == 0
    assert pipeline.leds.state is LedState.REJECTED


def test_width_from_smaller_frame_is_projected_to_reference(tmp_path) -> None:
    scan, *_ = _run("Healthy", 1200.0, tmp_path, image_width=1920)  # 1200 * 4608/1920 = 2880 px
    assert scan["final_grade"] == "Class A"
    assert scan["pixel_length"] == pytest.approx(2880.0)
