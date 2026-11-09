import asyncio
import json
import os
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.frames import save_frame  # noqa: E402
from app.leds import LedController, LedState  # noqa: E402
from app.model_inference import ObjectCheck, Stage1Prediction, Stage2Prediction, judge_objects  # noqa: E402
from app.pipeline import OVERLAY_CHECKING, OVERLAY_GRADE, OVERLAY_PROBLEM, OVERLAY_READY, PipelineState, PresencePipeline, PreviewOverlay, draw_overlay  # noqa: E402
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

    objects = ObjectCheck(0.0, None)
    distance = 0.05  # Stage 1's distance from the box to the trained bunches; real bunches score <= 0.28
    distance_calls = 0

    def check_objects(self, image, trigger_box):
        return self.objects

    def bunch_distance(self, image, box):
        self.distance_calls += 1
        return self.distance

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
    scan, *_ = _run("Healthy", 2800.0, tmp_path, confidence=0.62)
    assert scan["processing_status"] == "failed"
    assert scan["rejection_reason"] == "LOW_CONFIDENCE"
    assert scan["final_grade"] is None
    assert (scan["stage1_status"], scan["stage1_confidence"]) == ("Healthy", 0.62)
    assert (tmp_path / "frames" / f"{scan['scan_id']}.jpg").is_file()


def test_an_unsure_unhealthy_result_is_still_rejected(tmp_path) -> None:
    # On the rig, bruised market fruit came back Unhealthy at 0.55-0.79 and the operator rejected every one.
    scan, pipeline, inference, *_ = _run("Unhealthy", 2800.0, tmp_path, confidence=0.55)
    assert (scan["final_grade"], scan["rejection_reason"]) == ("Rejected", "SURFACE_UNHEALTHY")
    assert scan["processing_status"] == "completed"
    assert inference.stage2_calls == 0
    assert pipeline.leds.state is LedState.REJECTED


def test_an_unsure_scan_is_check_by_hand_not_a_system_fault(tmp_path) -> None:
    scan, pipeline, _, events, _ = _run("Healthy", 2800.0, tmp_path, confidence=0.65)
    assert pipeline.leds.state is LedState.CHECK
    assert pipeline._held_label == "Unsure: Healthy 65% (needs 80%) · check by hand"
    assert pipeline.last_error is None
    assert not [event for event in events if event["event_type"] == "pipeline_error"]
    assert scan["error_details"] == "Stage 1 confidence 0.65 is below 0.80"


def test_a_real_fault_during_a_scan_is_still_an_error(tmp_path) -> None:
    class BrokenInference(FakeInference):
        def classify(self, image):
            raise RuntimeError("Stage 1 crashed")

    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    pipeline = PresencePipeline(storage, BrokenInference("Healthy", 2800.0), LedController(outputs=None))
    pipeline._camera = FakeCamera()
    asyncio.run(pipeline._process_scan())
    scan = storage.get_scan(pipeline.last_scan_id)
    assert scan["rejection_reason"] == "PIPELINE_ERROR"
    assert pipeline.leds.state is LedState.ERROR and pipeline.last_error == "Stage 1 crashed"
    assert pipeline._held_label == "Scan error · see System Status"


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


def _placed(seed: int = 1, left: int = 160, right: int = 480):
    frame = _velvet(seed)
    frame[90:270, left:right] = (40, 200, 220)
    return frame


@pytest.mark.parametrize(
    ("box", "ready", "label", "color"),
    [
        ((101.0, 101.0, 301.0, 251.0), True, "Bunch 0.91 (Stage 2) · scanning", OVERLAY_READY),
        ((0.0, 100.0, 200.0, 250.0), False, "Checking 0.91 (Stage 2) · touching the left edge, move it right", OVERLAY_PROBLEM),
        ((120.0, 100.0, 640.0, 250.0), False, "Checking 0.91 (Stage 2) · touching the right edge, move it left", OVERLAY_PROBLEM),
    ],
)
def test_capture_check_labels_the_preview_box(tmp_path, box, ready, label, color) -> None:
    pipeline = _pipeline(tmp_path, FakeInference("Healthy", 2800.0))
    assert asyncio.run(pipeline._ready_to_capture(_placed(), box, 0.91, "Stage 2")) is ready
    assert (pipeline._overlay.label, pipeline._overlay.color) == (label, color)
    assert pipeline._capture_box == (box if ready else None)


@pytest.mark.parametrize("box", [(100.0, 0.0, 300.0, 250.0), (100.0, 110.0, 300.0, 360.0)])
def test_a_big_bunch_may_run_off_the_top_or_bottom(tmp_path, box) -> None:
    # Its whole width is still in view, and big bunches do this in 34 of the 336 dataset photos.
    pipeline = _pipeline(tmp_path, FakeInference("Healthy", 2800.0))
    assert asyncio.run(pipeline._ready_to_capture(_placed(), box, 0.96, "presence")) is True
    assert pipeline._overlay.label == "Bunch 0.96 (presence) · scanning"


def test_capture_waits_until_the_scene_has_been_still_for_the_window(tmp_path, monkeypatch) -> None:
    detector = FakeInference("Healthy", 2800.0)
    pipeline = _pipeline(tmp_path, detector)
    pipeline.STABILITY_WINDOW_S = 0.4
    clock = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: clock[0])
    box = (160.0, 90.0, 480.0, 270.0)
    checks = []
    detector.check_objects = lambda image, trigger_box: checks.append(1) or ObjectCheck(0.0, None)

    def ready(frame):
        pipeline._last_signature = None
        return asyncio.run(pipeline._ready_to_capture(frame, box, 0.95, "presence"))

    assert ready(_placed(1)) is False  # first sight
    clock[0] += 0.2
    assert ready(_placed(2)) is False and pipeline._overlay.label == "Checking 0.95 (presence) · hold still"
    clock[0] += 0.1
    assert ready(_placed(3, left=200, right=520)) is False  # slid sideways: the window starts again
    clock[0] += 0.3
    assert ready(_placed(4, left=200, right=520)) is False
    clock[0] += 0.15
    assert ready(_placed(5, left=200, right=520)) is True  # 0.45 s without a change, sensor noise aside
    assert checks == [1]  # the COCO check ran once, only when the scene was still


def test_held_result_shows_the_grade_on_the_box(tmp_path) -> None:
    scan, pipeline, *_ = _run("Healthy", 2800.0, tmp_path)
    assert (pipeline._held_label, pipeline._held_color) == ("Class A", OVERLAY_GRADE["Class A"])
    failed, failed_pipeline, *_ = _run("Healthy", 2800.0, tmp_path / "f", confidence=0.5)
    assert failed_pipeline._held_label == "Unsure: Healthy 50% (needs 80%) · check by hand"


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
    assert preview.shape == (540, 960, 3)  # sent smaller than the camera's 1280x720 so a hotspot keeps up
    assert preview[262, 150, 1] > 150  # green left edge (x 100 * 1.5) survives JPEG

    monkeypatch.setattr(pipeline, "OVERLAY_TTL_S", -1)
    asyncio.run(pipeline._capture_lores())
    stale = cv2.imdecode(np.frombuffer(pipeline.latest_jpeg(), np.uint8), cv2.IMREAD_COLOR)
    assert stale[262, 150].max() < 30


def test_preview_frames_come_from_the_camera_callback_not_the_trigger_loop(tmp_path) -> None:
    cv2 = pytest.importorskip("cv2")
    pipeline = _pipeline(tmp_path, FakeInference("Healthy", 2800.0))

    class Request:
        def __init__(self, value):
            self.value = value

        def make_array(self, stream):
            assert stream == "lores"
            return np.full((720, 1280, 3), self.value, np.uint8)

    pipeline._viewer_at = 1e12  # someone is watching
    pipeline._preview_thread = __import__("threading").Thread(target=pipeline._preview_worker, daemon=True)
    pipeline._preview_thread.start()
    try:
        for value in (10, 90):
            before = pipeline._jpeg_seq
            pipeline._on_frame(Request(value))
            seq, jpeg = asyncio.run(pipeline.next_jpeg(before, timeout=2.0))
            assert seq > before
            assert abs(float(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).mean()) - value) < 3
        assert asyncio.run(pipeline._capture_lores()).shape == (360, 640, 3)  # the trigger reads the same frames
    finally:
        pipeline._close_camera()
    assert pipeline._preview_thread is None


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

    # Unchanged frame: the same answer, so the box does not wobble on a bunch that lies still.
    asyncio.run(pipeline._presence_check(placed))
    assert detector.runs == 2
    moved = _velvet(2)
    moved[60:240, 100:420] = (60, 180, 200)
    asyncio.run(pipeline._presence_check(moved))
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
    assert pipeline.leds.state is LedState.CHECK
    assert pipeline._held_label == "Not measured: outline 75% (needs 90%) · check by hand"



def test_object_unlike_the_trained_bunches_is_not_graded(tmp_path) -> None:
    # The bond sheets of 2026-11-08 scored 0.49 and 0.63 from the trained bunches, and Stage 1 called them Unhealthy.
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    storage.ensure_active_session()
    inference = FakeInference("Unhealthy", 2400.0)
    inference.distance = 0.63
    pipeline = PresencePipeline(storage, inference, LedController(outputs=None))
    pipeline._camera = FakeCamera()
    pipeline._capture_box = (150.0, 60.0, 450.0, 300.0)
    asyncio.run(pipeline._process_scan())
    scan = storage.get_scan(pipeline.last_scan_id)
    assert (scan["final_grade"], scan["rejection_reason"]) == (None, "NOT_A_BUNCH")
    assert scan["error_details"] == "Unlike the bunches Stage 1 was trained on: distance 0.63 (limit 0.34)"
    assert inference.stage1_inputs == [] and inference.stage2_calls == 0
    assert pipeline.leds.state is LedState.CHECK
    assert pipeline._held_label == "Not a bunch · unlike the trained bunches"


def test_a_graded_bunch_records_its_distance_from_the_trained_bunches(tmp_path) -> None:
    scan, _ = _run_on(FakeCamera(), tmp_path)
    values = json.loads(scan["threshold_values"])
    assert (values["bunch_distance"], values["max_bunch_distance"]) == (0.05, 0.34)


class FocusCamera:
    def __init__(self) -> None:
        self.controls = []

    def set_controls(self, values) -> None:
        self.controls.append(values)

    def autofocus_cycle(self) -> None:
        pass

    def capture_metadata(self):
        return {"LensPosition": 1.31}


@pytest.fixture()
def fake_libcamera(monkeypatch):
    import enum
    import sys
    import types

    controls = types.SimpleNamespace(AfModeEnum=enum.Enum("AfModeEnum", "Manual Auto"))
    monkeypatch.setitem(sys.modules, "libcamera", types.SimpleNamespace(controls=controls))
    return controls


@pytest.mark.parametrize(("setting", "mode", "position"), [(None, "fixed", 0.99), ("1.2", "fixed", 1.2), ("auto", "autofocus", 1.31)])
def test_lens_is_held_at_the_calibrated_position_unless_set_to_auto(tmp_path, monkeypatch, fake_libcamera, setting, mode, position) -> None:
    if setting is None:
        monkeypatch.delenv("BANAGRADE_LENS_POSITION", raising=False)
    else:
        monkeypatch.setenv("BANAGRADE_LENS_POSITION", setting)
    pipeline = PresencePipeline(Storage(tmp_path / "p.db"), FakeInference("Healthy", 2400.0), LedController(outputs=None))
    pipeline._camera = FocusCamera()
    pipeline._lock_focus()
    assert (pipeline.focus_mode, pipeline.lens_position) == (mode, position)
    assert pipeline._camera.controls[-1] == {"AfMode": fake_libcamera.AfModeEnum.Manual, "LensPosition": position}
    camera = asyncio.run(pipeline.status())["camera"]
    assert (camera["focus"], camera["lens_position_dioptres"], camera["expected_distance_cm"]) == (mode, position, 45)


def test_trigger_box_on_paper_is_labelled_and_never_captured(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    pipeline.presence_interval_s = 0
    pipeline.release_s = 1.5
    clock = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: clock[0])
    paper = _velvet(1)
    paper[60:300, 150:450] = (232, 236, 238)
    frames = [_velvet(2)] * 8 + [paper] * 8  # 2 s of empty table clears the startup hold, then the sheet

    detector.distance = 0.49

    async def capture():
        if not frames:
            raise asyncio.CancelledError
        clock[0] += 0.25
        frame = frames.pop(0)
        pipeline._last_lores = frame
        detector.bunch = ((150.0, 60.0, 450.0, 300.0), 0.96, "presence") if frame is paper else None
        return frame

    async def no_scan():
        raise AssertionError("paper must not be captured")

    monkeypatch.setattr(pipeline, "_capture_lores", capture)
    monkeypatch.setattr(pipeline, "_process_scan", no_scan)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._run())
    assert pipeline._overlay.label == "Not a bunch · unlike the trained bunches (0.49)"
    assert pipeline.state is PipelineState.IDLE and pipeline.leds.state is LedState.READY
    assert detector.runs <= 3  # the unchanged sheet is not re-checked every frame
    assert detector.distance_calls <= detector.runs  # and Stage 1 looks at it once per detector answer


def _held_run(tmp_path, monkeypatch, script):
    """Drive the trigger loop through ``script`` (one entry per 0.25 s check: True = bunch seen) and count scans."""
    pipeline = _pipeline(tmp_path, CountingDetector())
    pipeline.presence_interval_s = 0
    pipeline.release_s = 1.5
    clock = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: clock[0])
    steps = list(script)
    bunch = _velvet(1)
    bunch[90:270, 160:480] = (40, 200, 220)
    scans = []

    async def capture():
        if not steps:
            raise asyncio.CancelledError
        clock[0] += 0.25
        pipeline._seen = steps.pop(0)
        return bunch

    async def presence(frame):
        return ((80.0, 45.0, 240.0, 135.0), 0.95, "presence") if pipeline._seen else None

    async def ready(frame, box, confidence, source):
        return True

    async def scan():
        scans.append(clock[0])

    monkeypatch.setattr(pipeline, "_capture_lores", capture)
    monkeypatch.setattr(pipeline, "_presence_check", presence)
    monkeypatch.setattr(pipeline, "_ready_to_capture", ready)
    monkeypatch.setattr(pipeline, "_process_scan", scan)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._run())
    return scans, pipeline


def test_bunch_briefly_out_of_view_is_not_scanned_again(tmp_path, monkeypatch) -> None:
    # Graded, then a hand covers it (or it is lifted to turn it) for 1.25 s, then it is seen again.
    script = [False] * 7 + [True] * 3 + [False] * 5 + [True] * 4 + [False, True] * 3
    scans, pipeline = _held_run(tmp_path, monkeypatch, script)
    assert len(scans) == 1
    assert pipeline._hold


def test_removed_bunch_releases_the_hold_and_the_next_one_is_scanned(tmp_path, monkeypatch) -> None:
    script = [False] * 7 + [True] * 3 + [False] * 7 + [True] * 2  # 1.75 s of empty table between the two bunches
    scans, pipeline = _held_run(tmp_path, monkeypatch, script)
    assert len(scans) == 2
    assert pipeline._hold


def test_bunch_already_on_the_table_at_startup_is_not_scanned_until_removed(tmp_path, monkeypatch) -> None:
    # A restart while a graded bunch sits on the table, then the next bunch after it is taken away.
    scans, pipeline = _held_run(tmp_path, monkeypatch, [True] * 12 + [False] * 7 + [True] * 2)
    assert len(scans) == 1
    scans, pipeline = _held_run(tmp_path, monkeypatch, [True] * 12)
    assert scans == [] and pipeline._overlay.label == "On the table at startup · remove it to scan"


def test_object_check_finds_hands_and_other_objects_but_not_bananas() -> None:
    box = (100.0, 50.0, 400.0, 300.0)
    assert judge_objects([("banana", 0.93, [100, 50, 400, 300])], box) == ObjectCheck(0.0, None)
    assert judge_objects([("person", 0.43, [0, 0, 120, 200]), ("banana", 0.40, [110, 60, 390, 290])], box).hand == 0.43
    assert judge_objects([("cell phone", 0.71, [110, 60, 380, 290])], box).other == ("cell phone", 0.71)
    assert judge_objects([("oven", 0.30, [100, 50, 400, 300])], box).other is None  # the strongest dataset false hit
    assert judge_objects([("cup", 0.55, [100, 50, 400, 300]), ("banana", 0.80, [100, 50, 400, 300])], box).other is None
    assert judge_objects([("airplane", 0.93, [200, 120, 260, 170])], box).other is None  # off the box (the X drawn on the paper)


@pytest.mark.parametrize(
    ("objects", "label", "ignored"),
    [
        (ObjectCheck(0.43, None), "Hand in view (0.43) · let go to scan", None),
        (ObjectCheck(0.0, ("cell phone", 0.71)), "Not a bunch · looks like a cell phone (0.71)", "Not a bunch · looks like a cell phone (0.71)"),
    ],
)
def test_hand_or_other_object_stops_the_capture(tmp_path, objects, label, ignored) -> None:
    detector = FakeInference("Healthy", 2800.0)
    detector.objects = objects
    pipeline = _pipeline(tmp_path, detector)
    assert asyncio.run(pipeline._ready_to_capture(_placed(), (101.0, 101.0, 301.0, 251.0), 0.91, "presence")) is False
    assert pipeline._overlay.label == label
    assert pipeline._ignored_label == ignored


def test_an_ignored_object_is_not_rechecked_until_the_table_changes(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: 100.0)
    phone = _velvet(1)
    phone[90:270, 160:480] = (40, 60, 200)
    detector.bunch = ((80.0, 45.0, 240.0, 135.0), 0.90, "presence")
    asyncio.run(pipeline._presence_check(phone))
    pipeline._ignored_label = "Not a bunch · looks like a cell phone (0.71)"
    asyncio.run(pipeline._presence_check(phone))
    assert detector.runs == 1 and pipeline._ignored_label is not None
    moved = _velvet(2)
    moved[60:240, 100:420] = (40, 60, 200)
    asyncio.run(pipeline._presence_check(moved))
    assert detector.runs == 2 and pipeline._ignored_label is None


def test_a_hand_in_view_is_labelled_and_never_captured(tmp_path, monkeypatch) -> None:
    detector = CountingDetector()
    detector.objects = ObjectCheck(0.62, None)  # the trigger boxes a hand opening and closing
    pipeline = _pipeline(tmp_path, detector)
    pipeline.presence_interval_s = 0
    pipeline.release_s = 0
    clock = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: clock[0])
    hand = _velvet(1)
    hand[60:300, 150:450] = (150, 180, 230)  # skin is coloured, so the colour check passes it
    frames = [_velvet(2)] * 2 + [hand] * 6

    async def capture():
        if not frames:
            raise asyncio.CancelledError
        clock[0] += 0.25
        frame = frames.pop(0)
        detector.bunch = ((150.0, 60.0, 450.0, 300.0), 0.93, "presence") if frame is hand else None
        return frame

    async def no_scan():
        raise AssertionError("a hand must not be captured")

    monkeypatch.setattr(pipeline, "_capture_lores", capture)
    monkeypatch.setattr(pipeline, "_process_scan", no_scan)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._run())
    assert pipeline._overlay.label == "Hand in view (0.62) · let go to scan"


def _run_on(camera, tmp_path, confidence=0.99):
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    inference = FakeInference("Healthy", 2800.0, confidence=confidence)
    pipeline = PresencePipeline(storage, inference, LedController(outputs=None))
    pipeline._camera = camera
    pipeline._capture_box = (20.0, 10.0, 400.0, 125.0)
    asyncio.run(pipeline._process_scan())
    return storage.get_scan(pipeline.last_scan_id), pipeline


def test_the_held_result_keeps_the_box_it_was_measured_on(tmp_path, monkeypatch) -> None:
    scan, pipeline = _run_on(FakeCamera(), tmp_path)
    measured = tuple(value * 640 / 4608 for value in (100.0, 50.0, 2900.0, 900.0))  # Stage 2's box on the preview
    assert pipeline._held_box == pytest.approx(measured)
    pipeline._hold = True
    pipeline.presence_interval_s = 0
    jittered = [(measured[0] + 6, measured[1] - 4, measured[2] - 9, measured[3] + 5), (300.0, 200.0, 600.0, 350.0)]
    frames = [_placed(1), _placed(2)]

    async def capture():
        if not frames:
            raise asyncio.CancelledError
        return frames.pop(0)

    shown = []

    async def presence(frame):
        if shown or pipeline._overlay is not None:
            shown.append(pipeline._overlay.box)
        return (jittered.pop(0), 0.97, "presence")

    monkeypatch.setattr(pipeline, "_capture_lores", capture)
    monkeypatch.setattr(pipeline, "_presence_check", presence)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._run())
    assert shown[0] == pytest.approx(measured)  # a wobbling box on the same bunch: the measured box stays
    assert pipeline._overlay.box == (300.0, 200.0, 600.0, 350.0)  # moved for real: the live box


def test_a_weak_trigger_box_is_shown_but_never_captured(tmp_path, monkeypatch) -> None:
    # Both hands scanned as Rejected scored 0.83-0.84 on the trigger; every dataset bunch scored 0.93 or more.
    detector = CountingDetector()
    pipeline = _pipeline(tmp_path, detector)
    pipeline.presence_interval_s = 0
    pipeline.release_s = 0
    frames = [_velvet(2)] * 2 + [_placed(1)] * 4

    async def capture():
        if not frames:
            raise asyncio.CancelledError
        frame = frames.pop(0)
        detector.bunch = ((160.0, 90.0, 480.0, 270.0), 0.84, "presence") if frame.max() > 100 else None
        return frame

    async def no_scan():
        raise AssertionError("a weak box must not be captured")

    monkeypatch.setattr(pipeline, "_process_scan", no_scan)
    monkeypatch.setattr(pipeline, "_capture_lores", capture)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._run())
    assert pipeline._overlay.label == "Unsure it is a bunch (0.84, needs 0.90)"
