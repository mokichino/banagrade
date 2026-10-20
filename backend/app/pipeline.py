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
from enum import StrEnum
from typing import Any

from .grading import REFERENCE_RESOLUTION, Stage1Result, decide_grade, scale_width_to_reference, width_threshold_px
from .leds import LedController, LedState
from .preprocessing import MaskSettings, frame_health, stage1_input
from .storage import Storage, now_iso

Publish = Callable[[dict[str, Any]], Awaitable[None]]


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
    SNAPSHOT_BUSY = (PipelineState.CAPTURING, PipelineState.CLASSIFYING, PipelineState.DETECTING, PipelineState.GRADING)

    def __init__(self, storage: Storage, inference: Any, leds: LedController | None = None) -> None:
        self.storage = storage
        self.inference = inference
        self.enabled = os.getenv("BANAGRADE_ENABLE_PIPELINE", "true").lower() == "true"
        self.stage1_min_conf = float(os.getenv("BANAGRADE_STAGE1_MIN_CONF", "0.80"))
        # Seconds between presence checks while idle. Running YOLO back-to-back pinned the
        # Pi 5 CPU above 100%; ~4 checks per second is enough to catch a bunch being placed.
        self.presence_interval_s = float(os.getenv("BANAGRADE_PRESENCE_INTERVAL_S", "0.25"))
        self.mask_settings = MaskSettings.from_environment()
        # The trained Stage 1 model saw raw frames; masking dropped held-out accuracy from 0.996 to 0.911.
        # Only enable this for a model retrained on HSV-masked images.
        self.stage1_mask = os.getenv("BANAGRADE_STAGE1_MASK", "0") == "1"
        self.leds = leds or LedController(on_change=self._on_led_change)
        self.state = PipelineState.BOOTING
        self.last_error: str | None = None
        self.last_scan_id: str | None = None
        self.started_at = time.time()
        self.illumination: dict[str, Any] | None = None
        self.lens_position: float | None = None
        self.camera_resolution: tuple[int, int] | None = None
        self._publish: Publish | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._camera: Any = None
        self._hold = False
        self._latest_jpeg: bytes | None = None
        self._latest_jpeg_at = 0.0

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
            "stage1_min_confidence": self.stage1_min_conf,
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
                "distance_cm": 45,
                "autofocus": "locked" if self.lens_position is not None else ("unlocked" if self.camera_available else None),
                "lens_position_dioptres": self.lens_position,
                "illumination": self.illumination,
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
                await asyncio.to_thread(self._open_camera)
                if not self.inference.available:
                    raise RuntimeError(self.inference.error or "Stage 1 / Stage 2 models are not loaded")
                self.last_error = None
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

    def _lock_focus(self) -> None:
        """Run one autofocus cycle at boot, then hold the lens fixed (Section 3.6.3)."""
        try:
            from libcamera import controls  # type: ignore[import-not-found]

            self._camera.set_controls({"AfMode": controls.AfModeEnum.Auto})
            self._camera.autofocus_cycle()
            position = self._camera.capture_metadata().get("LensPosition")
            if position is not None:
                self._camera.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": float(position)})
                self.lens_position = round(float(position), 3)
        except Exception as error:  # cameras without autofocus or missing controls
            self.lens_position = None
            self.last_error = f"Autofocus lock unavailable: {error}"

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
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                self._latest_jpeg = encoded.tobytes()
                self._latest_jpeg_at = now
        return cv2.resize(frame, self.DETECTION_SIZE, interpolation=cv2.INTER_AREA)

    async def snapshot_jpeg(self) -> bytes:
        """One full-resolution frame for the operator; refused while a scan is using the sensor."""
        if self._camera is None:
            raise RuntimeError("Camera unavailable")
        if self.state in self.SNAPSHOT_BUSY:
            raise RuntimeError("A scan is in progress")
        import cv2

        image = await asyncio.to_thread(self._camera.capture_array, "main")
        ok, encoded = await asyncio.to_thread(cv2.imencode, ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise RuntimeError("Snapshot encoding failed")
        return encoded.tobytes()

    async def _run(self) -> None:
        await self._set_state(PipelineState.IDLE)
        self.leds.set(LedState.READY)
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
                await self._set_state(PipelineState.IDLE)
                self.leds.set(LedState.READY)

            detection = await asyncio.to_thread(self.inference.detect_presence, frame, self.PRESENCE_CONFIDENCE)
            if detection is None:
                if self._hold or self.state is not PipelineState.IDLE:
                    self._hold = False
                    await self._set_state(PipelineState.IDLE)
                    self.leds.set(LedState.READY)
                await asyncio.sleep(self.presence_interval_s)
                continue
            if self._hold:  # result shown until the bunch is removed
                await asyncio.sleep(self.presence_interval_s)
                continue
            await self._set_state(PipelineState.PRESENCE_DETECTED)
            await self._emit("presence_detected")
            if await self._stable_and_in_frame(frame, detection):
                await self._process_scan()
                self._hold = True

    async def _stable_and_in_frame(self, first_frame: Any, first: tuple[float, float, float, float]) -> bool:
        await asyncio.sleep(self.STABILITY_WINDOW_S)
        second = await self._capture_lores()
        current = await asyncio.to_thread(self.inference.detect_presence, second, self.PRESENCE_CONFIDENCE)
        if current is None:
            return False
        height, width = second.shape[:2]
        margin = 2
        if min(current[0], current[1]) <= margin or current[2] >= width - margin or current[3] >= height - margin:
            return False
        return max(abs(a - b) for a, b in zip(first, current)) <= max(width, height) * 0.03

    async def _process_scan(self) -> None:
        scan_id = str(uuid.uuid4())
        self.last_scan_id = scan_id
        captured_at = now_iso()
        started = time.perf_counter()
        session_id = self.storage.active_session_id()
        threshold = width_threshold_px()
        try:
            await self._set_state(PipelineState.CAPTURING)
            self.leds.set(LedState.CAPTURE)
            image = await asyncio.to_thread(self._camera.capture_array, "main")

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
            decision = decide_grade(stage1_result, width_ref, threshold, stage2_detected=stage2.detected if stage2 else True)
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
                "model_metadata": {"stage1": self.inference.stage1_path.name, "stage2": self.inference.stage2_path.name},
                "threshold_values": {"width_threshold_px": threshold, "reference_resolution": list(REFERENCE_RESOLUTION), "axis": self.inference.length_axis},
            }
            await self._set_state(PipelineState.PERSISTING)
            self.storage.save_scan(record)
            if decision.is_technical_failure:
                self.leds.set(LedState.ERROR)
            else:
                self.leds.show_grade(decision.grade)
            await self._emit("scan_completed", {"scan": self.storage.get_scan(scan_id)})
            await self._set_state(PipelineState.HOLD)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.last_error = str(error)
            reason = "LOW_CONFIDENCE" if isinstance(error, LowConfidence) else "PIPELINE_ERROR"
            self.storage.save_scan({
                "scan_id": scan_id, "session_id": session_id, "captured_at": captured_at, "completed_at": now_iso(),
                "processing_status": "failed", "rejection_reason": reason, "error_details": self.last_error,
                "inference_time_ms": (time.perf_counter() - started) * 1000,
            })
            self.leds.set(LedState.ERROR)
            await self._set_state(PipelineState.HOLD)
            await self._emit("pipeline_error", {"scan_id": scan_id, "error": self.last_error})
            await self._emit("scan_completed", {"scan": self.storage.get_scan(scan_id)})

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
