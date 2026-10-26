"""Presence-triggered grading pipeline (thesis Sections 3.6.4 and 3.11).

FSM: BOOTING -> IDLE -> PRESENCE_DETECTED -> CAPTURING -> CLASSIFYING
     -> DETECTING -> GRADING -> PERSISTING -> HOLD -> IDLE, plus ERROR / DISABLED.

Hardware (Picamera2, gpiozero) and ML dependencies are imported only when the
worker starts, so development machines and tests remain safe.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import camera_tuning
from .frames import save_frame
from .grading import REFERENCE_RESOLUTION, Stage1Result, decide_grade, scale_width_to_reference, width_threshold_px
from .leds import LedController, LedState
from .model_inference import HAND_CONFIDENCE, PresenceHit
from .preprocessing import MaskSettings, banana_share, frame_health, stage1_input
from .storage import Storage, now_iso

Publish = Callable[[dict[str, Any]], Awaitable[None]]

# BGR colours for the preview box. Grades match the floor LEDs and the dashboard tokens.
OVERLAY_CHECKING = (0, 176, 255)  # amber
OVERLAY_READY = (94, 197, 34)  # green
OVERLAY_PROBLEM = (38, 38, 220)  # red
OVERLAY_GRADE = {"Class A": (0, 163, 217), "Class B": (235, 99, 37), "Rejected": (38, 38, 220)}
OVERLAY_FAILURE = (128, 128, 128)
NOT_A_BUNCH_LABEL = "Not a bunch · no banana colour"
STARTUP_HOLD_LABEL = "On the table at startup · remove it to scan"

# The width threshold only holds at the thesis rig height (Section 3.6.3), lens to velvet surface.
RIG_DISTANCE_CM = 45
# This Camera Module 3's LensPosition with a printed target at a tape-measured 45 cm: 0.983, 0.989 and
# 1.012 dpt (2026-10-26). It does not follow 1 / metres (that would be 2.22), and autofocus on the bare
# velvet locked anywhere from 0.69 to 1.31 dpt, so the lens is held here instead of autofocusing at boot.
RIG_LENS_POSITION = "0.99"


@dataclass(frozen=True, slots=True)
class PreviewOverlay:
    box: tuple[float, float, float, float]  # in DETECTION_SIZE coordinates
    label: str
    color: tuple[int, int, int]
    updated_at: float


def change_signature(frame: Any) -> Any:
    """160x90 greyscale copy of a preview frame for the change check (~1 ms on the Pi 5)."""
    import cv2

    return cv2.cvtColor(cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype("int16")


def frame_changed(before: Any, after: Any, level: int = 25, fraction: float = 0.005) -> bool:
    """True when more than ``fraction`` of pixels changed by more than ``level`` grey levels.

    Counting changed pixels, not the mean difference, ignores sensor noise on the dark velvet but still
    catches a hand or a bunch entering a corner (0.5% is about a 12×6 px patch of the 160×90 copy).
    """
    import numpy as np

    return float(np.mean(np.abs(after - before) > level)) > fraction


def draw_overlay(frame: Any, overlay: PreviewOverlay, scale: float) -> Any:
    """Copy of the preview frame with the trigger's box and status label. Display only; grading never sees it."""
    import cv2

    image = frame.copy()
    x1, y1, x2, y2 = (int(round(value * scale)) for value in overlay.box)
    cv2.rectangle(image, (x1, y1), (x2, y2), overlay.color, 3)
    font, size, weight = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    (text_w, text_h), baseline = cv2.getTextSize(overlay.label, font, size, weight)
    top = y1 - text_h - baseline - 8 if y1 - text_h - baseline - 8 >= 0 else y1 + 3  # inside the box at the top edge
    cv2.rectangle(image, (x1, top), (x1 + text_w + 12, top + text_h + baseline + 8), overlay.color, cv2.FILLED)
    cv2.putText(image, overlay.label, (x1 + 6, top + text_h + 4), font, size, (255, 255, 255), weight, cv2.LINE_AA)
    return image


class PipelineState(StrEnum):
    BOOTING = "BOOTING"
    IDLE = "IDLE"
    PRESENCE_DETECTED = "PRESENCE_DETECTED"
    CAPTURING = "CAPTURING"
    CLASSIFYING = "CLASSIFYING"
    DETECTING = "DETECTING"
    GRADING = "GRADING"
    PERSISTING = "PERSISTING"
    HOLD = "HOLD"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


def ensure_system_packages() -> None:
    """Make Raspberry Pi OS apt packages (picamera2, libcamera, gpiozero, lgpio) importable.

    They are not on PyPI for this platform, so a plain virtualenv cannot see them.
    Appending (not prepending) keeps the virtualenv's numpy/opencv authoritative.
    """
    system_path = "/usr/lib/python3/dist-packages"
    if system_path not in sys.path and os.path.isdir(system_path):
        sys.path.append(system_path)


def import_picamera2() -> Any:
    try:
        from picamera2 import Picamera2
    except ImportError:
        ensure_system_packages()
        from picamera2 import Picamera2
    return Picamera2


class PresencePipeline:
    PRESENCE_CONFIDENCE = 0.80
    STABILITY_WINDOW_S = 0.4
    PREVIEW_INTERVAL_S = 0.2
    PREVIEW_SIZE = (1280, 720)  # operator preview; detection still runs on a 640x360 copy
    DETECTION_SIZE = (640, 360)
    OVERLAY_TTL_S = 1.0  # drop a box that no detection has refreshed, so a stale box never lingers
    # An unchanged empty table (or an unchanged held bunch) skips the detectors, which cost ~505 ms per
    # check on an empty table. They still run at least this often, for lighting drift and a second look.
    FORCED_CHECK_S = 2.0
    SNAPSHOT_BUSY = (PipelineState.CAPTURING, PipelineState.CLASSIFYING, PipelineState.DETECTING, PipelineState.GRADING)

    def __init__(self, storage: Storage, inference: Any, leds: LedController | None = None) -> None:
        self.storage = storage
        self.inference = inference
        self.enabled = os.getenv("BANAGRADE_ENABLE_PIPELINE", "true").lower() == "true"
        self.stage1_min_conf = float(os.getenv("BANAGRADE_STAGE1_MIN_CONF", "0.80"))
        # Every held-out Class A/B bunch scored >= 0.96 at full resolution; a flat hand on a desk scored 0.75
        # and was graded Class A. A weaker box is a technical failure, never a grade.
        self.stage2_min_conf = float(os.getenv("BANAGRADE_STAGE2_MIN_CONF", "0.90"))
        # Seconds between presence checks while idle. Running YOLO back-to-back pinned the
        # Pi 5 CPU above 100%. A model check takes ~225 ms when Stage 2 sees the bunch and ~505 ms on an empty
        # table (Stage 2, then the COCO backup); the change check in _presence_check skips most idle ones.
        self.presence_interval_s = float(os.getenv("BANAGRADE_PRESENCE_INTERVAL_S", "0.25"))
        # A graded bunch is held until the table has looked empty this long without a break. One missed check
        # used to end the hold, so a hand straightening the bunch, or lifting it to turn it, started a new scan.
        self.release_s = float(os.getenv("BANAGRADE_RELEASE_S", "3"))
        self.mask_settings = MaskSettings.from_environment()
        # The trained Stage 1 model saw raw frames; masking dropped held-out accuracy from 0.996 to 0.911.
        # Only enable this for a model retrained on HSV-masked images.
        self.stage1_mask = os.getenv("BANAGRADE_STAGE1_MASK", "0") == "1"
        # Full-resolution frames for disputes; ~0.9 MB each, so the default cap is about 1 GB. 0 disables.
        self.frame_dir = Path(os.getenv("BANAGRADE_FRAME_DIR", storage.path.parent / "frames"))
        self.frame_keep = int(os.getenv("BANAGRADE_FRAME_KEEP", "1000"))
        # The trigger's box must be at least this share banana-coloured to be graded (not paper, an empty tray).
        # The palest dataset bunch scored 0.276 and paper 0.004 or less, tinted or not; 0 disables the check.
        self.min_banana_share = float(os.getenv("BANAGRADE_MIN_BANANA_SHARE", "0.10"))
        # Dioptres to hold the lens at, or "auto" for one autofocus cycle at boot.
        self.lens_setting = os.getenv("BANAGRADE_LENS_POSITION", RIG_LENS_POSITION).strip().lower()
        # White balance and exposure calibrated to match the dataset (camera_tuning.py), reapplied at every start.
        self.camera_settings_path = Path(os.getenv("BANAGRADE_CAMERA_SETTINGS", storage.path.parent / "camera.json"))
        self.camera_settings = camera_tuning.load_settings(self.camera_settings_path)
        self._calibrating = False
        self.leds = leds or LedController(on_change=self._on_led_change)
        self.state = PipelineState.BOOTING
        self.last_error: str | None = None
        self.last_scan_id: str | None = None
        self.started_at = time.time()
        self.illumination: dict[str, Any] | None = None
        self.lens_position: float | None = None
        self.focus_mode: str | None = None  # "fixed" or "autofocus" once set
        self.camera_resolution: tuple[int, int] | None = None
        self._publish: Publish | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._camera: Any = None
        self._hold = False
        self._ignored_label: str | None = None  # the trigger's box is on something that is not a bunch, e.g. paper
        self._capture_box: tuple[float, float, float, float] | None = None  # trigger box that passed, in DETECTION_SIZE px
        self._empty_since: float | None = None  # while holding: when the bunch went missing from the checks
        self._latest_jpeg: bytes | None = None
        self._latest_jpeg_at = 0.0
        self._overlay: PreviewOverlay | None = None
        self._held_label = "Technical failure"
        self._held_color = OVERLAY_FAILURE
        self._reference: Any = None  # change signature of the frame the detectors last ran on
        self._last_detection: PresenceHit | None = None
        self._last_model_check = 0.0
        self.trigger_stats = {"model_checks": 0, "skipped_unchanged": 0}

    # ------------------------------------------------------------------ status
    @property
    def camera_available(self) -> bool:
        return self._camera is not None

    def latest_jpeg(self) -> bytes | None:
        return self._latest_jpeg

    async def status(self) -> dict[str, Any]:
        resolution = self.camera_resolution
        return {
            "available": self.camera_available,
            "enabled": self.enabled,
            "state": self.state,
            "last_error": self.last_error,
            "last_scan_id": self.last_scan_id,
            "led": self.leds.status(),
            "motion_window_ms": int(self.STABILITY_WINDOW_S * 1000),
            "trigger": dict(self.trigger_stats),
            "stage1_min_confidence": self.stage1_min_conf,
            "stage2_min_confidence": self.stage2_min_conf,
            "width_threshold_px": width_threshold_px(),
            "reference_resolution": list(REFERENCE_RESOLUTION),
            "preprocessing": (
                "RGB-to-HSV threshold + morphological opening + largest-contour mask (Stage 1); raw RGB (Stage 2)"
                if self.stage1_mask
                else "Raw RGB squashed to 224x224 (Stage 1, as trained); raw RGB (Stage 2)"
            ),
            "camera": {
                "available": self.camera_available,
                "resolution": f"{resolution[0]}x{resolution[1]}" if resolution else None,
                "expected_distance_cm": RIG_DISTANCE_CM,
                "focus": self.focus_mode if self.lens_position is not None else ("unset" if self.camera_available else None),
                "lens_position_dioptres": self.lens_position,
                "illumination": self.illumination,
                "white_balance": (
                    {"mode": "locked", "colour_gains": self.camera_settings["colour_gains"], "set_at": self.camera_settings.get("white_balance_set_at")}
                    if self.camera_settings.get("colour_gains")
                    else {"mode": "auto"}
                ),
                "brightness": {
                    "exposure_value": self.camera_settings.get("exposure_value", 0.0),
                    "bunch_brightness": self.camera_settings.get("bunch_brightness"),
                    "dataset_bunch_brightness": camera_tuning.DATASET_BUNCH_BRIGHTNESS,
                    "set_at": self.camera_settings.get("brightness_set_at"),
                },
            },
        }

    # --------------------------------------------------------------- lifecycle
    async def start(self, publish: Publish) -> None:
        self._publish = publish
        self._loop = asyncio.get_running_loop()
        ensure_system_packages()
        self.leds.open()
        self.leds.set(LedState.BOOTING)
        if not self.enabled:
            self.state = PipelineState.DISABLED
            self.last_error = "Pipeline disabled by BANAGRADE_ENABLE_PIPELINE"
            self.leds.set(LedState.ERROR)
            return
        self._task = asyncio.create_task(self._boot_and_run(), name="banagrade-presence-pipeline")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._close_camera()
        self.leds.close()

    def _close_camera(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.close()
            except Exception:
                pass
        self._camera = None

    async def _boot_and_run(self) -> None:
        while True:
            try:
                await self._set_state(PipelineState.BOOTING)
                self.leds.set(LedState.BOOTING)
                self.last_error = None  # cleared before opening the camera, so a lens focus error stays visible
                await asyncio.to_thread(self._open_camera)
                if not self.inference.available:
                    raise RuntimeError(self.inference.error or "Stage 1 / Stage 2 models are not loaded")
                await self._run()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # keep the service alive; retry after a pause
                self.last_error = str(error)
                self._close_camera()
                await self._set_state(PipelineState.ERROR)
                self.leds.set(LedState.ERROR)
                await self._emit("pipeline_error", {"error": self.last_error})
                await asyncio.sleep(10)

    def _open_camera(self) -> None:
        if self._camera is not None:
            return
        picamera2_cls = import_picamera2()
        camera = picamera2_cls()
        width, height = REFERENCE_RESOLUTION
        config = camera.create_still_configuration(
            main={"size": (width, height), "format": "RGB888"},
            lores={"size": self.PREVIEW_SIZE, "format": "RGB888"},
            buffer_count=2,
        )
        camera.configure(config)
        camera.start()
        self._camera = camera
        self.camera_resolution = (width, height)
        self._lock_focus()
        self._apply_camera_settings()

    def _apply_camera_settings(self) -> None:
        try:
            self._camera.set_controls(camera_tuning.controls_for(self.camera_settings))
        except Exception as error:  # a bad saved setting must not stop grading
            self.last_error = f"Camera colour/brightness settings not applied: {error}"

    def _lock_focus(self) -> None:
        """Hold the lens at BANAGRADE_LENS_POSITION, or run one autofocus cycle and hold that (Section 3.6.3)."""
        try:
            from libcamera import controls  # type: ignore[import-not-found]

            if self.lens_setting != "auto":
                position = float(self.lens_setting)
                self._camera.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": position})
                self.lens_position, self.focus_mode = round(position, 3), "fixed"
                return
            self._camera.set_controls({"AfMode": controls.AfModeEnum.Auto})
            self._camera.autofocus_cycle()
            position = self._camera.capture_metadata().get("LensPosition")
            if position is not None:
                self._camera.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": float(position)})
                self.lens_position, self.focus_mode = round(float(position), 3), "autofocus"
        except Exception as error:  # cameras without autofocus, missing controls or a bad setting
            self.lens_position = None
            self.last_error = f"Lens focus unavailable: {error}"

    # -------------------------------------------------------------- event plumbing
    def _on_led_change(self, state: LedState) -> None:
        if self._loop and self._publish:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._emit("led_changed", {"led": state})))

    async def _emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if self._publish:
            await self._publish({"event_type": event_type, **(payload or {})})

    async def _set_state(self, state: PipelineState) -> None:
        if state is self.state:
            return
        self.state = state
        await self._emit("fsm_state_changed", {"state": state})

    # ----------------------------------------------------------------- main loop
    async def _capture_lores(self) -> Any:
        frame = await asyncio.to_thread(self._camera.capture_array, "lores")
        import cv2

        now = time.monotonic()
        if now - self._latest_jpeg_at >= self.PREVIEW_INTERVAL_S:
            preview = frame
            overlay = self._overlay
            if overlay is not None and now - overlay.updated_at <= self.OVERLAY_TTL_S:
                preview = draw_overlay(frame, overlay, frame.shape[1] / self.DETECTION_SIZE[0])
            ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                self._latest_jpeg = encoded.tobytes()
                self._latest_jpeg_at = now
        return cv2.resize(frame, self.DETECTION_SIZE, interpolation=cv2.INTER_AREA)

    def _capture_with_metadata(self) -> tuple[Any, dict[str, Any]]:
        request = self._camera.capture_request()
        try:
            return request.make_array("main"), request.get_metadata()
        finally:
            request.release()

    async def _calibrate(self, measure: Any) -> dict[str, Any]:
        """Run a calibration with scanning paused; whatever is on the table afterwards is held, not scanned."""
        if self._camera is None:
            raise RuntimeError("Camera unavailable")
        if self.state in self.SNAPSHOT_BUSY or self._calibrating:
            raise RuntimeError("A scan or another calibration is in progress")
        self._calibrating = True
        try:
            result = await measure()
        finally:
            self._calibrating = False
            self._hold, self._empty_since = True, None
            self._held_label, self._held_color = "Calibration · remove it to scan", OVERLAY_FAILURE
        camera_tuning.save_settings(self.camera_settings_path, self.camera_settings)
        return result

    async def calibrate_white_balance(self) -> dict[str, Any]:
        """Fixed colour gains that make a white sheet in view neutral, refined until within 2%."""

        async def measure() -> dict[str, Any]:
            applied = None
            for attempt in range(4):
                image, metadata = await asyncio.to_thread(self._capture_with_metadata)
                sheet = await asyncio.to_thread(camera_tuning.sheet_colour, image)
                if sheet is None:
                    raise ValueError("No whole sheet found: lay a white sheet flat in the middle, fully in view")
                cast = camera_tuning.colour_cast(sheet)
                current = tuple(metadata.get("ColourGains") or applied or (1.0, 1.0))
                if cast <= camera_tuning.NEUTRAL_TOLERANCE or attempt == 3:
                    applied = applied or current
                    break
                applied = camera_tuning.neutral_gains(sheet, current)
                await asyncio.to_thread(self._camera.set_controls, {"AwbEnable": False, "ColourGains": applied})
                await asyncio.sleep(1.0)  # a few frames for the new gains
            self.camera_settings.update(colour_gains=list(applied), white_balance_set_at=now_iso())
            return {"colour_gains": list(applied), "sheet_bgr": [round(value, 1) for value in sheet], "cast": round(cast, 3), "neutral": cast <= camera_tuning.NEUTRAL_TOLERANCE}

        return await self._calibrate(measure)

    async def calibrate_brightness(self) -> dict[str, Any]:
        """Exposure compensation that makes the bunch in view as bright as the dataset's, refined until within 5."""

        async def measure() -> dict[str, Any]:
            ev = float(self.camera_settings.get("exposure_value", 0.0))
            for attempt in range(5):
                image, _ = await asyncio.to_thread(self._capture_with_metadata)
                brightness = await asyncio.to_thread(camera_tuning.bunch_brightness, image)
                if brightness is None:
                    raise ValueError("No bunch in view: put a fresh green bunch in the middle of the table")
                if abs(brightness - camera_tuning.DATASET_BUNCH_BRIGHTNESS) <= camera_tuning.BRIGHTNESS_TOLERANCE or attempt == 4:
                    break
                ev = camera_tuning.next_exposure_value(ev, brightness)
                await asyncio.to_thread(self._camera.set_controls, {"ExposureValue": ev})
                await asyncio.sleep(1.5)  # automatic exposure settles over several frames
            self.camera_settings.update(exposure_value=ev, bunch_brightness=round(brightness, 1), brightness_set_at=now_iso())
            matched = abs(brightness - camera_tuning.DATASET_BUNCH_BRIGHTNESS) <= camera_tuning.BRIGHTNESS_TOLERANCE
            return {"exposure_value": ev, "bunch_brightness": round(brightness, 1), "dataset_bunch_brightness": camera_tuning.DATASET_BUNCH_BRIGHTNESS, "matched": matched}

        return await self._calibrate(measure)

    async def reset_camera_setting(self, setting: str) -> None:
        """Back to automatic white balance ("white_balance") or EV 0 ("brightness")."""
        keys = {"white_balance": ("colour_gains", "white_balance_set_at"), "brightness": ("exposure_value", "bunch_brightness", "brightness_set_at")}[setting]
        for key in keys:
            self.camera_settings.pop(key, None)
        camera_tuning.save_settings(self.camera_settings_path, self.camera_settings)
        if self._camera is not None:
            await asyncio.to_thread(self._apply_camera_settings)

    async def snapshot_array(self) -> Any:
        """One full-resolution BGR frame for the operator; refused while a scan is using the sensor."""
        if self._camera is None:
            raise RuntimeError("Camera unavailable")
        if self.state in self.SNAPSHOT_BUSY:
            raise RuntimeError("A scan is in progress")
        return await asyncio.to_thread(self._camera.capture_array, "main")

    async def snapshot_jpeg(self) -> bytes:
        """One full-resolution frame for the operator; refused while a scan is using the sensor."""
        import cv2

        image = await self.snapshot_array()
        ok, encoded = await asyncio.to_thread(cv2.imencode, ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise RuntimeError("Snapshot encoding failed")
        return encoded.tobytes()

    async def _run(self) -> None:
        await self._set_state(PipelineState.IDLE)
        self.leds.set(LedState.READY)
        # Start held: a bunch already on the table was probably graded before a restart, so it is only
        # scanned once the table has been cleared. An empty table is released after release_s as usual.
        self._hold = True
        self._held_label, self._held_color = STARTUP_HOLD_LABEL, OVERLAY_FAILURE
        while True:
            frame = await self._capture_lores()
            health = frame_health(frame)
            self.illumination = {"status": health.status, "mean_brightness": round(health.mean_value, 1), "contrast": round(health.std_value, 1)}
            if not health.ok:
                if self.state is not PipelineState.ERROR:
                    self.last_error = "Camera obstructed" if health.status == "obstructed" else "Inadequate lighting"
                    await self._set_state(PipelineState.ERROR)
                    self.leds.set(LedState.ERROR)
                    await self._emit("pipeline_error", {"error": self.last_error})
                await asyncio.sleep(0.2)
                continue
            if self.state is PipelineState.ERROR:
                self.last_error = None
                self._reference = None
                await self._set_state(PipelineState.IDLE)
                self.leds.set(LedState.READY)

            detection = await self._presence_check(frame)
            if detection is None:
                self._overlay = None
                self._ignored_label = None
                if self._hold:
                    now = time.monotonic()
                    if self._empty_since is None:
                        self._empty_since = now
                    if now - self._empty_since < self.release_s:  # covered, missed or lifted, not yet removed
                        await asyncio.sleep(self.presence_interval_s)
                        continue
                    self._empty_since = None
                if self._hold or self.state is not PipelineState.IDLE:
                    self._hold = False
                    await self._set_state(PipelineState.IDLE)
                    self.leds.set(LedState.READY)
                await asyncio.sleep(self.presence_interval_s)
                continue
            box, confidence, source = detection
            self._empty_since = None
            if self._calibrating:
                self._show(box, "Calibrating the camera", OVERLAY_FAILURE)
                await asyncio.sleep(self.presence_interval_s)
                continue
            if self._hold:  # result shown until the bunch is removed
                self._show(box, self._held_label, self._held_color)
                await asyncio.sleep(self.presence_interval_s)
                continue
            # The trigger was trained on bunches only and also boxes paper; show those, never capture them.
            if self._ignored_label is None and banana_share(frame, box) < self.min_banana_share:
                self._ignored_label = NOT_A_BUNCH_LABEL
            if self._ignored_label:
                self._show(box, self._ignored_label, OVERLAY_FAILURE)
                if self.state is not PipelineState.IDLE:
                    await self._set_state(PipelineState.IDLE)
                    self.leds.set(LedState.READY)
                await asyncio.sleep(self.presence_interval_s)
                continue
            # Checked at first sight too: a moving hand never passes the stability check, so it would
            # otherwise be shown as a bunch until it held still.
            if not await self._objects_clear(frame, box):
                await asyncio.sleep(self.presence_interval_s)
                continue
            self._show(box, f"Checking {confidence:.2f} ({source}) · hold still", OVERLAY_CHECKING)
            await self._set_state(PipelineState.PRESENCE_DETECTED)
            await self._emit("presence_detected")
            if await self._stable_and_in_frame(frame, box):
                await self._process_scan()
                self._hold = True

    async def _presence_check(self, frame: Any) -> PresenceHit | None:
        """Run the trigger detectors, or reuse their last answer when nothing in the frame has changed.

        Reuse is limited to the two steady states: an empty table, and a held bunch still sitting there.
        A bunch that was seen but not yet captured is always checked again.
        """
        signature = change_signature(frame)
        now = time.monotonic()
        changed = self._reference is None or frame_changed(self._reference, signature)
        steady = self._last_detection is None or self._hold or self._ignored_label is not None
        if steady and not changed and now - self._last_model_check < self.FORCED_CHECK_S:
            self.trigger_stats["skipped_unchanged"] += 1
            return self._last_detection
        if changed:  # something moved on the table, so an ignored object gets a fresh look
            self._ignored_label = None
        detection = await asyncio.to_thread(self.inference.detect_presence, frame, self.PRESENCE_CONFIDENCE)
        self.trigger_stats["model_checks"] += 1
        self._reference, self._last_detection, self._last_model_check = signature, detection, now
        return detection

    def _show(self, box: tuple[float, float, float, float], label: str, color: tuple[int, int, int]) -> None:
        self._overlay = PreviewOverlay(box, label, color, time.monotonic())

    async def _objects_clear(self, frame: Any, box: tuple[float, float, float, float]) -> bool:
        """False, with the reason on the box, when a hand is in view or the box is on another COCO object.

        Stage 1 judges the whole frame, so a hand in view can sway it; other COCO objects are not bunches.
        """
        objects = await asyncio.to_thread(self.inference.check_objects, frame, box)
        if objects.hand >= HAND_CONFIDENCE:
            self._show(box, f"Hand in view ({objects.hand:.2f}) · let go to scan", OVERLAY_CHECKING)
            return False
        if objects.other:
            name, score = objects.other
            self._ignored_label = f"Not a bunch · looks like a {name} ({score:.2f})"
            self._show(box, self._ignored_label, OVERLAY_FAILURE)
            return False
        return True

    async def _stable_and_in_frame(self, first_frame: Any, first: tuple[float, float, float, float]) -> bool:
        await asyncio.sleep(self.STABILITY_WINDOW_S)
        second = await self._capture_lores()
        detection = await asyncio.to_thread(self.inference.detect_presence, second, self.PRESENCE_CONFIDENCE)
        if detection is None:
            self._overlay = None
            return False
        current, confidence, source = detection
        height, width = second.shape[:2]
        margin = 2
        if min(current[0], current[1]) <= margin or current[2] >= width - margin or current[3] >= height - margin:
            self._show(current, f"Checking {confidence:.2f} ({source}) · touching the edge, move it in", OVERLAY_PROBLEM)
            return False
        if max(abs(a - b) for a, b in zip(first, current)) > max(width, height) * 0.03:
            self._show(current, f"Checking {confidence:.2f} ({source}) · moving, hold still", OVERLAY_CHECKING)
            return False
        if not await self._objects_clear(second, current):  # a hand may have come in during the window
            return False
        self._show(current, f"Bunch {confidence:.2f} ({source}) · scanning", OVERLAY_READY)
        self._capture_box = current
        return True

    async def _process_scan(self) -> None:
        scan_id = str(uuid.uuid4())
        self.last_scan_id = scan_id
        captured_at = now_iso()
        started = time.perf_counter()
        session_id = self.storage.active_session_id()
        threshold = width_threshold_px()
        image = None
        stage1 = None
        frame_refs = [str(self.frame_dir / f"{scan_id}.jpg")] if self.frame_keep > 0 else None
        try:
            await self._set_state(PipelineState.CAPTURING)
            self.leds.set(LedState.CAPTURE)
            image = await asyncio.to_thread(self._camera.capture_array, "main")
            scale = image.shape[1] / self.DETECTION_SIZE[0]
            box = tuple(value * scale for value in self._capture_box) if self._capture_box else None
            self._capture_box = None
            share = await asyncio.to_thread(banana_share, image, box)
            if share < self.min_banana_share:
                raise NotABunch(f"Only {share:.1%} of the bunch's box is banana-coloured (needs {self.min_banana_share:.0%}), so it is not graded as a bunch")

            await self._set_state(PipelineState.CLASSIFYING)
            prepared = await asyncio.to_thread(self._stage1_image, image)
            stage1 = await asyncio.to_thread(self.inference.classify, prepared)
            await self._emit("stage1_completed", {"scan_id": scan_id, "confidence": stage1.confidence, "status": stage1.label})
            if stage1.confidence < self.stage1_min_conf:
                raise LowConfidence(f"Stage 1 confidence {stage1.confidence:.2f} is below {self.stage1_min_conf:.2f}")
            stage1_result = Stage1Result.HEALTHY if stage1.label.lower() == "healthy" else Stage1Result.UNHEALTHY

            stage2 = None
            width_ref = None
            if stage1_result is Stage1Result.HEALTHY:
                await self._set_state(PipelineState.DETECTING)
                stage2 = await asyncio.to_thread(self.inference.detect, image)
                if stage2.pixel_length is not None:
                    width_ref = scale_width_to_reference(stage2.pixel_length, stage2.image_width)

            await self._set_state(PipelineState.GRADING)
            weak_detection = stage2 is not None and stage2.detected and (stage2.confidence or 0.0) < self.stage2_min_conf
            detected = stage2.detected and not weak_detection if stage2 else True
            decision = decide_grade(stage1_result, width_ref, threshold, stage2_detected=detected)
            record = {
                "scan_id": scan_id,
                "session_id": session_id,
                "captured_at": captured_at,
                "completed_at": now_iso(),
                "stage1_status": stage1.label,
                "stage1_confidence": stage1.confidence,
                "stage2_detected": int(stage2.detected) if stage2 else None,
                "stage2_confidence": stage2.confidence if stage2 else None,
                "bbox_coords": stage2.bbox_xyxy if stage2 else None,
                "pixel_length": width_ref,
                "final_grade": decision.grade,
                "rejection_reason": decision.rejection_reason,
                "processing_status": "completed",
                "inference_time_ms": (time.perf_counter() - started) * 1000,
                "stage_timings": {"stage1_ms": stage1.duration_ms, "stage2_ms": stage2.duration_ms if stage2 else None},
                "image_refs": frame_refs,
                "model_metadata": {"stage1": self.inference.stage1_path.name, "stage2": self.inference.stage2_path.name},
                "threshold_values": {"width_threshold_px": threshold, "reference_resolution": list(REFERENCE_RESOLUTION), "axis": self.inference.length_axis},
                "error_details": f"Stage 2 confidence {stage2.confidence:.2f} is below {self.stage2_min_conf:.2f}" if weak_detection else None,
            }
            await self._set_state(PipelineState.PERSISTING)
            self.storage.save_scan(record)
            if decision.is_technical_failure:
                self.leds.set(LedState.ERROR)
                self._held_label, self._held_color = "Technical failure", OVERLAY_FAILURE
            else:
                self.leds.show_grade(decision.grade)
                self._held_label, self._held_color = str(decision.grade), OVERLAY_GRADE.get(str(decision.grade), OVERLAY_FAILURE)
            await self._emit("scan_completed", {"scan": self.storage.get_scan(scan_id)})
            await self._set_state(PipelineState.HOLD)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.last_error = str(error)
            reason = "LOW_CONFIDENCE" if isinstance(error, LowConfidence) else "NOT_A_BUNCH" if isinstance(error, NotABunch) else "PIPELINE_ERROR"
            self.storage.save_scan({
                "scan_id": scan_id, "session_id": session_id, "captured_at": captured_at, "completed_at": now_iso(),
                "stage1_status": stage1.label if stage1 else None,
                "stage1_confidence": stage1.confidence if stage1 else None,
                "processing_status": "failed", "rejection_reason": reason, "error_details": self.last_error,
                "inference_time_ms": (time.perf_counter() - started) * 1000,
                "image_refs": frame_refs if image is not None else None,
            })
            self.leds.set(LedState.ERROR)
            self._held_label = NOT_A_BUNCH_LABEL if isinstance(error, NotABunch) else "Technical failure"
            self._held_color = OVERLAY_FAILURE
            await self._set_state(PipelineState.HOLD)
            await self._emit("pipeline_error", {"scan_id": scan_id, "error": self.last_error})
            await self._emit("scan_completed", {"scan": self.storage.get_scan(scan_id)})
        # Written after the result is shown so the JPEG encode does not add to grading latency.
        if frame_refs and image is not None:
            try:
                await asyncio.to_thread(save_frame, self.frame_dir, scan_id, image, self.frame_keep)
            except Exception as error:  # a full disk must not stop grading
                self.last_error = f"Frame archive failed: {error}"

    def _stage1_image(self, image: Any) -> Any:
        """Raw frame for Stage 1, downscaled to 1152 px wide.

        Stage 1 squashes to 224 px anyway; on the 225-image held-out set the downscale gave identical
        labels to the full frame and cut classification from ~105 ms to ~37 ms on the Pi 5.
        """
        import cv2

        height, width = image.shape[:2]
        scale = 1152 / width if width > 1152 else 1.0
        small = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
        return stage1_input(small, self.mask_settings) if self.stage1_mask else small


class LowConfidence(ValueError):
    pass


class NotABunch(ValueError):
    pass
