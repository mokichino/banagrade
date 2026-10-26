import asyncio

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app import camera_tuning  # noqa: E402
from app.leds import LedController  # noqa: E402
from app.pipeline import PresencePipeline  # noqa: E402
from app.storage import Storage  # noqa: E402


class TuningCamera:
    """A white sheet with a pen mark and a green bunch, rendered with the current colour gains and EV."""

    def __init__(self, sheet=True, bunch=True) -> None:
        self.controls = {"AwbEnable": True, "ColourGains": (1.0, 1.0), "ExposureValue": 0.0}
        self.sheet, self.bunch = sheet, bunch

    def set_controls(self, values) -> None:
        self.controls.update(values)

    def capture_request(self):
        red_gain, blue_gain = self.controls["ColourGains"]
        light = 2 ** (self.controls["ExposureValue"] / 2.2)
        frame = np.full((2592, 4608, 3), 10, np.float32)
        if self.sheet:
            frame[600:2000, 1200:3400] = (215 * blue_gain, 190, 160 * red_gain)  # blue cast under unity gains
            cv2.line(frame, (2100, 1100), (2400, 1500), (40, 40, 40), 30)
        if self.bunch:
            frame[700:1900, 3500:4400] = (40 * light, 180 * light, 150 * light)  # green bunch, value 180 at EV 0
        camera = self

        class Request:
            def make_array(self, stream):
                return np.clip(frame, 0, 255).astype(np.uint8)

            def get_metadata(self):
                return {"ColourGains": camera.controls["ColourGains"]}

            def release(self):
                pass

        return Request()


def _pipeline(tmp_path, camera):
    storage = Storage(tmp_path / "p.db")
    storage.initialize()
    pipeline = PresencePipeline(storage, None, LedController(outputs=None))
    pipeline._camera = camera
    pipeline.state = "IDLE"
    return pipeline


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("app.pipeline.asyncio.sleep", instant)


def test_white_balance_is_locked_so_the_sheet_is_neutral_and_saved(tmp_path) -> None:
    camera = TuningCamera()
    pipeline = _pipeline(tmp_path, camera)
    result = asyncio.run(pipeline.calibrate_white_balance())
    assert result["neutral"] and result["cast"] <= 0.02
    assert camera.controls["AwbEnable"] is False
    assert result["colour_gains"][0] == pytest.approx(190 / 160, abs=0.02)  # red raised
    assert result["colour_gains"][1] == pytest.approx(190 / 215, abs=0.02)  # blue lowered
    assert pipeline._hold and pipeline._held_label == "Calibration · remove it to scan"

    restarted = _pipeline(tmp_path, TuningCamera())  # same data directory
    restarted._apply_camera_settings()
    assert restarted._camera.controls["AwbEnable"] is False
    assert restarted._camera.controls["ColourGains"] == pytest.approx(tuple(result["colour_gains"]))
    camera_status = asyncio.run(restarted.status())["camera"]
    assert camera_status["white_balance"]["mode"] == "locked"

    asyncio.run(restarted.reset_camera_setting("white_balance"))
    assert restarted._camera.controls["AwbEnable"] is True
    assert asyncio.run(restarted.status())["camera"]["white_balance"] == {"mode": "auto"}


def test_brightness_is_matched_to_the_dataset_bunches(tmp_path) -> None:
    camera = TuningCamera(sheet=False)
    pipeline = _pipeline(tmp_path, camera)
    result = asyncio.run(pipeline.calibrate_brightness())
    assert result["matched"]
    assert abs(result["bunch_brightness"] - 149) <= 5
    assert result["exposure_value"] < 0  # the rig bunch started brighter than the dataset's
    assert camera.controls["ExposureValue"] == result["exposure_value"]
    asyncio.run(pipeline.reset_camera_setting("brightness"))
    assert camera.controls["ExposureValue"] == 0.0


@pytest.mark.parametrize(("call", "message"), [("calibrate_white_balance", "No whole sheet"), ("calibrate_brightness", "No bunch in view")])
def test_calibration_needs_its_target_in_view(tmp_path, call, message) -> None:
    pipeline = _pipeline(tmp_path, TuningCamera(sheet=False, bunch=False))
    with pytest.raises(ValueError, match=message):
        asyncio.run(getattr(pipeline, call)())
    assert not pipeline._calibrating
    assert not pipeline._hold  # a failed calibration leaves whatever is on the table to be scanned


def test_calibration_is_refused_mid_scan(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, TuningCamera())
    pipeline.state = pipeline.SNAPSHOT_BUSY[0]
    with pytest.raises(RuntimeError):
        asyncio.run(pipeline.calibrate_white_balance())


def test_exposure_step_and_controls() -> None:
    assert camera_tuning.next_exposure_value(0.0, 174) < 0 < camera_tuning.next_exposure_value(0.0, 120)
    assert camera_tuning.next_exposure_value(0.0, 149) == 0.0
    assert camera_tuning.next_exposure_value(2.9, 20) == 3.0  # clamped
    assert camera_tuning.controls_for({}) == {"ExposureValue": 0.0, "AwbEnable": True}
    assert camera_tuning.controls_for({"colour_gains": [1.9, 1.6], "exposure_value": -0.5}) == {"ExposureValue": -0.5, "AwbEnable": False, "ColourGains": (1.9, 1.6)}
