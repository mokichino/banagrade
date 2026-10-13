"""Ultralytics model adapters for the two-stage pipeline (thesis Sections 3.5.2-3.5.3, 3.7.5-3.7.6)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Stage1Prediction:
    label: str
    confidence: float
    duration_ms: float


@dataclass(frozen=True, slots=True)
class Stage2Prediction:
    detected: bool
    bbox_xyxy: tuple[float, float, float, float] | None
    pixel_length: float | None
    confidence: float | None
    duration_ms: float
    image_width: int
    image_height: int


def pixel_length_from_bbox(bbox_xyxy: tuple[float, float, float, float], axis: str) -> float:
    x1, y1, x2, y2 = bbox_xyxy
    if axis == "width":
        return max(0.0, x2 - x1)
    if axis == "height":
        return max(0.0, y2 - y1)
    raise ValueError("BANAGRADE_LENGTH_AXIS must be 'width' or 'height'")


class UltralyticsInference:
    def __init__(
        self,
        stage1_path: str | Path,
        stage2_path: str | Path,
        length_axis: str = "width",
        presence_path: str | Path | None = None,
    ) -> None:
        self.stage1_path = Path(stage1_path)
        self.stage2_path = Path(stage2_path)
        self.presence_path = Path(presence_path) if presence_path else None
        self.length_axis = length_axis
        self._stage1: Any = None
        self._stage2: Any = None
        self._presence: Any = None
        self._error: str | None = None
        self._model_errors: dict[str, str] = {}

    @classmethod
    def from_environment(cls) -> "UltralyticsInference":
        project_models = Path(__file__).resolve().parents[2] / "models"
        return cls(
            os.getenv("BANAGRADE_STAGE1_MODEL", str(project_models / "stage 1" / "stage1_best.pt")),
            os.getenv("BANAGRADE_STAGE2_MODEL", str(project_models / "stage 2" / "stage2_best.pt")),
            os.getenv("BANAGRADE_LENGTH_AXIS", "width"),
            os.getenv("BANAGRADE_PRESENCE_MODEL") or None,
        )

    def load(self) -> None:
        self._model_errors = {}
        if self.length_axis not in {"width", "height"}:
            raise ValueError("BANAGRADE_LENGTH_AXIS must be 'width' or 'height'")
        missing = [str(path) for path in (self.stage1_path, self.stage2_path) if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Model file not found: {', '.join(missing)}")
        try:
            import torch
            from ultralytics import YOLO

            # Leave CPU headroom for the camera, FastAPI and the WebSocket on the Pi 5.
            torch.set_num_threads(int(os.getenv("BANAGRADE_TORCH_THREADS", "2")))
        except ImportError as error:
            raise RuntimeError("Install ultralytics and opencv-python to enable model inference") from error
        stage1 = YOLO(str(self.stage1_path))
        names1 = {str(name).strip().lower() for name in stage1.names.values()}
        if stage1.task != "classify" or names1 != {"healthy", "unhealthy"}:
            self._model_errors["stage1"] = "Expected a classifier with Healthy and Unhealthy classes"
            raise ValueError(self._model_errors["stage1"])
        stage2 = YOLO(str(self.stage2_path))
        names2 = {str(name).strip().lower() for name in stage2.names.values()}
        if stage2.task != "detect" or names2 != {"banana_bunch"}:
            self._model_errors["stage2"] = "Expected a detector with the banana_bunch class"
            raise ValueError(self._model_errors["stage2"])
        self._stage1, self._stage2 = stage1, stage2
        if self.presence_path:
            if self.presence_path.is_file():
                self._presence = YOLO(str(self.presence_path))
            else:
                self._model_errors["presence"] = f"Presence model not found: {self.presence_path}"
        self._error = None

    @property
    def available(self) -> bool:
        return self._stage1 is not None and self._stage2 is not None

    @property
    def error(self) -> str | None:
        return self._error

    def mark_error(self, error: Exception) -> None:
        self._error = str(error)

    def _model_state(self, key: str, path: Path | None, loaded: bool) -> str:
        if loaded:
            return "loaded"
        if key in self._model_errors or (self._error and path is not None and path.is_file()):
            return "error"
        return "missing"

    def status(self) -> dict[str, Any]:
        presence_source = "dedicated" if self._presence is not None else "stage2_fallback"
        return {
            "available": self.available,
            "stage1_model": str(self.stage1_path),
            "stage2_model": str(self.stage2_path),
            "presence_model": str(self.presence_path) if self.presence_path else None,
            "presence_source": presence_source,
            "length_axis": self.length_axis,
            "empirical_threshold_px": float(os.getenv("BANAGRADE_WIDTH_THRESHOLD_PX", "2730.07")),
            "error": self._error,
            "models": [
                {"key": "stage1", "label": self.stage1_path.name, "architecture": "YOLO11n-cls", "task": "Health screening (Healthy / Unhealthy)", "path": str(self.stage1_path), "state": self._model_state("stage1", self.stage1_path, self._stage1 is not None)},
                {"key": "stage2", "label": self.stage2_path.name, "architecture": "YOLO11n-det", "task": "Whole-bunch detection (banana_bunch)", "path": str(self.stage2_path), "state": self._model_state("stage2", self.stage2_path, self._stage2 is not None)},
            ],
        }

    def classify(self, image: Any) -> Stage1Prediction:
        if not self.available:
            raise RuntimeError("Model inference is not loaded")
        started = time.perf_counter()
        result = self._stage1.predict(source=image, imgsz=224, verbose=False)[0]
        top1 = int(result.probs.top1)
        label = str(result.names[top1])
        if label.lower() not in {"healthy", "unhealthy"}:
            raise ValueError(f"Unexpected Stage 1 label: {label}")
        return Stage1Prediction(label, float(result.probs.top1conf), (time.perf_counter() - started) * 1000)

    def detect_presence(self, image: Any, confidence_threshold: float = 0.80) -> tuple[float, float, float, float] | None:
        """Presence trigger: a dedicated YOLO11n-presence model, else the Stage 2 banana_bunch detector."""
        model = self._presence or self._stage2
        if model is None:
            return None
        result = model.predict(source=image, conf=confidence_threshold, imgsz=320, verbose=False)[0]
        if result.boxes is None or len(result.boxes.xyxy) == 0:
            return None
        best = int(result.boxes.conf.argmax())
        return tuple(float(value) for value in result.boxes.xyxy[best].tolist())  # type: ignore[return-value]

    def detect(self, image: Any) -> Stage2Prediction:
        if not self.available:
            raise RuntimeError("Model inference is not loaded")
        started = time.perf_counter()
        result = self._stage2.predict(source=image, imgsz=640, verbose=False)[0]
        height, width = image.shape[:2]
        if result.boxes is None or len(result.boxes.xyxy) == 0:
            return Stage2Prediction(False, None, None, None, (time.perf_counter() - started) * 1000, width, height)
        best = int(result.boxes.conf.argmax())
        coordinates = tuple(float(value) for value in result.boxes.xyxy[best].tolist())
        return Stage2Prediction(
            True,
            coordinates,  # type: ignore[arg-type]
            pixel_length_from_bbox(coordinates, self.length_axis),  # type: ignore[arg-type]
            float(result.boxes.conf[best]),
            (time.perf_counter() - started) * 1000,
            width,
            height,
        )
