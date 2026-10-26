import asyncio
import json
import os
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.frames import save_frame  # noqa: E402
from app.leds import LedController, LedState  # noqa: E402
from app.model_inference import Stage1Prediction, Stage2Prediction  # noqa: E402
from app.pipeline import OVERLAY_CHECKING, OVERLAY_GRADE, OVERLAY_PROBLEM, OVERLAY_READY, PresencePipeline, PreviewOverlay, distance_check, draw_overlay, focus_distance_cm  # noqa: E402
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

    def __init__(self, label: str, width_px: float, image_width: int = 4608, confidence: float = 0.97, stage2_confidence: float = 0.93) -> None:
        self.label, self.width_px, self.image_width, self.confidence = label, width_px, image_width, confidence
        self.stage2_confidence = stage2_confidence
        self.stage1_inputs = []
        self.stage2_calls = 0

    def classify(self, image):
        self.stage1_inputs.append(image)
        return Stage1Prediction(self.label, self.confidence, 12.0)

    def detect(self, image):
        self.stage2_calls += 1
        return Stage2Prediction(True, (100.0, 50.0, 100.0 + self.width_px, 900.0), self.width_px, self.stage2_confidence, 30.0, self.image_width, 2592)


def _run(label: str, width_px: float, tmp_path: Path, image_width: int = 4608, confidence: float = 0.97):
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    session = storage.ensure_active_session()
    inference = FakeInference(label, width_px, image_width, confidence)
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
    # Stage 1 receives the raw (unmasked) frame, downscaled to 1152 px wide, as the model was trained.
    stage1_input = inference.stage1_inputs[0]
    assert stage1_input.shape == (648, 1152, 3)
    assert stage1_input[0, 0].tolist() == [5, 5, 5]


def test_stage1_mask_is_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BANAGRADE_STAGE1_MASK", "1")
    _, _, inference, _, _ = _run("Healthy", 2800.0, tmp_path)
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


def test_captured_frame_is_archived_for_disputes(tmp_path) -> None:
    scan, pipeline, *_ = _run("Healthy", 2800.0, tmp_path)
    frame = tmp_path / "frames" / f"{scan['scan_id']}.jpg"
    assert json.loads(scan["image_refs"]) == [str(frame)]
    assert frame.is_file()

    dispute = pipeline.storage.dispute_scan(scan["scan_id"], "Hand is small", "Class B", tmp_path / "retrain")
    assert dispute["original_grade"] == "Class A"
    assert [Path(p).name for p in dispute["archived_frames"]] == [f"{scan['scan_id']}_{frame.name}"]


def test_low_confidence_failure_keeps_stage1_result_and_frame(tmp_path) -> None:
    scan, *_ = _run("Unhealthy", 2800.0, tmp_path, confidence=0.62)
    assert scan["processing_status"] == "failed"
    assert scan["rejection_reason"] == "LOW_CONFIDENCE"
    assert scan["final_grade"] is None
    assert (scan["stage1_status"], scan["stage1_confidence"]) == ("Unhealthy", 0.62)
    assert (tmp_path / "frames" / f"{scan['scan_id']}.jpg").is_file()


def test_frame_archive_can_be_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BANAGRADE_FRAME_KEEP", "0")
    scan, *_ = _run("Healthy", 2800.0, tmp_path)
    assert scan["image_refs"] is None
    assert not (tmp_path / "frames").exists()


def test_frame_archive_prunes_oldest(tmp_path) -> None:
    image = np.zeros((8, 8, 3), np.uint8)
    for index in range(4):
        path = save_frame(tmp_path, f"s{index}", image, keep=2)
        os.utime(path, (index, index))
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["s2.jpg", "s3.jpg"]


class SequenceDetector(FakeInference):
    """Returns queued presence detections, one per detect_presence call."""

    def __init__(self, detections) -> None:
        super().__init__("Healthy", 2800.0)
        self.detections = list(detections)

    def detect_presence(self, image, confidence_threshold=0.80):
        return self.detections.pop(0)


def _pipeline(tmp_path: Path, inference) -> PresencePipeline:
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    pipeline = PresencePipeline(storage, inference, LedController(outputs=None))
    pipeline._camera = FakeCamera()
    pipeline.STABILITY_WINDOW_S = 0
    return pipeline


def test_draw_overlay_scales_the_box_and_leaves_the_model_frame_untouched() -> None:
    frame = np.zeros((720, 1280, 3), np.uint8)
    overlay = PreviewOverlay((100.0, 100.0, 300.0, 250.0), "Bunch 0.93 · scanning", OVERLAY_READY, 0.0)
    drawn = draw_overlay(frame, overlay, 1280 / 640)
    assert not frame.any()  # detection and grading frames are never annotated
    assert drawn[350, 200].tolist() == list(OVERLAY_READY)  # left edge: x 100 * 2, between y 200 and 500
    assert drawn[350, 400].tolist() == [0, 0, 0]  # inside the box stays clear


@pytest.mark.parametrize(
    ("second", "stable", "label", "color"),
    [
        (((101.0, 101.0, 301.0, 251.0), 0.91, "Stage 2"), True, "Bunch 0.91 (Stage 2) · scanning", OVERLAY_READY),
        (((180.0, 100.0, 380.0, 250.0), 0.91, "Stage 2"), False, "Bunch 0.91 (Stage 2) · moving, hold still", OVERLAY_CHECKING),
        (((0.0, 100.0, 200.0, 250.0), 0.91, "backup"), False, "Bunch 0.91 (backup) · touching the edge, move it in", OVERLAY_PROBLEM),
        (None, False, None, None),
    ],
)
def test_stability_check_labels_the_preview_box(tmp_path, second, stable, label, color) -> None:
    pipeline = _pipeline(tmp_path, SequenceDetector([second]))
    assert asyncio.run(pipeline._stable_and_in_frame(None, (100.0, 100.0, 300.0, 250.0))) is stable
    if label is None:
        assert pipeline._overlay is None
    else:
        assert (pipeline._overlay.label, pipeline._overlay.color) == (label, color)


def test_held_result_shows_the_grade_on_the_box(tmp_path) -> None:
    scan, pipeline, *_ = _run("Healthy", 2800.0, tmp_path)
    assert (pipeline._held_label, pipeline._held_color) == ("Class A", OVERLAY_GRADE["Class A"])
    failed, failed_pipeline, *_ = _run("Healthy", 2800.0, tmp_path / "f", confidence=0.5)
    assert failed_pipeline._held_label == "Technical failure"


def test_preview_draws_a_fresh_box_and_drops_a_stale_one(tmp_path, monkeypatch) -> None:
    cv2 = pytest.importorskip("cv2")

    class PreviewCamera:
        def capture_array(self, stream):
            return np.zeros((720, 1280, 3), np.uint8)

    pipeline = _pipeline(tmp_path, FakeInference("Healthy", 2800.0))
    pipeline._camera = PreviewCamera()
    pipeline.PREVIEW_INTERVAL_S = 0
    pipeline._show((100.0, 100.0, 300.0, 250.0), "Bunch 0.93 · hold still", OVERLAY_READY)

    detection_frame = asyncio.run(pipeline._capture_lores())
    assert not detection_frame.any()
    preview = cv2.imdecode(np.frombuffer(pipeline.latest_jpeg(), np.uint8), cv2.IMREAD_COLOR)
    assert preview[350, 200, 1] > 150  # green left edge survives JPEG

    monkeypatch.setattr(pipeline, "OVERLAY_TTL_S", -1)
    asyncio.run(pipeline._capture_lores())
    stale = cv2.imdecode(np.frombuffer(pipeline.latest_jpeg(), np.uint8), cv2.IMREAD_COLOR)
    assert stale[350, 200].max() < 30


class CountingDetector(FakeInference):
    """Counts detector runs; reports a bunch while ``bunch`` is set."""

    def __init__(self) -> None:
        super().__init__("Healthy", 2800.0)
        self.runs = 0
        self.bunch = None

    def detect_presence(self, image, confidence_threshold=0.80):
        self.runs += 1
        return self.bunch


def _velvet(seed: int, noise: float = 3.0):
    rng = np.random.default_rng(seed)
    return np.clip(8 + rng.normal(0, noise, (360, 640, 3)), 0, 255).astype(np.uint8)


def test_change_check_ignores_sensor_noise_but_catches_a_corner_intrusion() -> None:
    from app.pipeline import change_signature, frame_changed

    empty = change_signature(_velvet(1))
    assert not frame_changed(empty, change_signature(_velvet(2)))
    corner = _velvet(3)
    corner[:30, :50] = (60, 180, 200)  # a fingertip-sized patch entering the top-left corner
    assert frame_changed(empty, change_signature(corner))


def test_unchanged_empty_table_skips_the_detectors_until_the_forced_check(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    clock = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: clock[0])

    for step in range(5):  # 1 s of an empty table at 4 checks per second
        assert asyncio.run(pipeline._presence_check(_velvet(step))) is None
        clock[0] += 0.25
    assert detector.runs == 1
    assert pipeline.trigger_stats == {"model_checks": 1, "skipped_unchanged": 4}

    clock[0] += 1.0  # past FORCED_CHECK_S since the last model run
    asyncio.run(pipeline._presence_check(_velvet(9)))
    assert detector.runs == 2


def test_a_change_runs_the_detectors_and_an_unseen_bunch_is_rechecked(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: 100.0)
    asyncio.run(pipeline._presence_check(_velvet(0)))

    placed = _velvet(1)
    placed[90:270, 160:480] = (60, 180, 200)
    detector.bunch = ((80.0, 45.0, 240.0, 135.0), 0.95, "Stage 2")
    assert asyncio.run(pipeline._presence_check(placed)) == detector.bunch
    assert detector.runs == 2

    # Seen but not captured yet (e.g. still moving): never reused, always checked again.
    asyncio.run(pipeline._presence_check(placed))
    assert detector.runs == 3


def test_held_bunch_is_not_rechecked_until_the_frame_changes(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: 100.0)
    placed = _velvet(1)
    placed[90:270, 160:480] = (60, 180, 200)
    detector.bunch = ((80.0, 45.0, 240.0, 135.0), 0.95, "Stage 2")
    asyncio.run(pipeline._presence_check(placed))
    pipeline._hold = True  # result shown, waiting for removal

    assert asyncio.run(pipeline._presence_check(placed)) == detector.bunch
    assert detector.runs == 1

    detector.bunch = None  # bunch lifted off the table
    assert asyncio.run(pipeline._presence_check(_velvet(2))) is None
    assert detector.runs == 2


def test_weak_stage2_box_is_a_technical_failure_not_a_grade(tmp_path) -> None:
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    # The live hand scan: Stage 1 Healthy 0.807, Stage 2 box 0.75 over hand, laptop and desk, 3010 px wide.
    inference = FakeInference("Healthy", 3010.0, confidence=0.807, stage2_confidence=0.75)
    pipeline = PresencePipeline(storage, inference, LedController(outputs=None))
    pipeline._camera = FakeCamera()

    async def publish(event):
        pass

    pipeline._publish = publish
    asyncio.run(pipeline._process_scan())
    scan = storage.get_scan(pipeline.last_scan_id)
    assert scan["final_grade"] is None
    assert scan["rejection_reason"] == "DETECTION_FAILED"
    assert scan["error_details"] == "Stage 2 confidence 0.75 is below 0.90"
    assert pipeline.leds.state is LedState.ERROR
    assert pipeline._held_label == "Technical failure"


@pytest.mark.parametrize(
    ("lens_position", "distance", "check"),
    [(2.222, 45.0, "ok"), (0.818, 122.2, "too_far"), (3.5, 28.6, "too_close"), (0.0, None, None), (None, None, None)],
)
def test_focus_distance_flags_a_camera_off_the_rig_height(lens_position, distance, check) -> None:
    assert focus_distance_cm(lens_position) == distance
    assert distance_check(focus_distance_cm(lens_position)) == check
