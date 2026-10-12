from __future__ import annotations

import os
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
    duration_ms: float
    image_width: int
    image_height: int


def pixel_length_from_bbox(
    bbox_xyxy: tuple[float, float, float, float],
    axis: str,
) -> float:
    x1, y1, x2, y2 = bbox_xyxy
    if axis == "width":
        return max(0.0, x2 - x1)
    if axis == "height":
        return max(0.0, y2 - y1)
    raise ValueError("BANAGRADE_LENGTH_AXIS must be 'width' or 'height'")


class UltralyticsInference:
    def __init__(self, stage1_path: str | Path, stage2_path: str | Path, length_axis: str = "height") -> None:
        self.stage1_path = Path(stage1_path)
        self.stage2_path = Path(stage2_path)
        self.length_axis = length_axis
        self._stage1: Any = None
        self._stage2: Any = None
        self._cv2: Any = None
        self._error: str | None = None

    @classmethod
    def from_environment(cls) -> "UltralyticsInference":
        return cls(
            os.getenv("BANAGRADE_STAGE1_MODEL", "models/yolo11n-cls.pt"),
            os.getenv("BANAGRADE_STAGE2_MODEL", "models/yolo11n.pt"),
            os.getenv("BANAGRADE_LENGTH_AXIS", "height"),
        )

    def load(self) -> None:
        if not self.stage1_path.is_file():
            raise FileNotFoundError(f"Stage 1 model not found: {self.stage1_path}")
        if not self.stage2_path.is_file():
            raise FileNotFoundError(f"Stage 2 model not found: {self.stage2_path}")
        if self.length_axis not in {"width", "height"}:
            raise ValueError("BANAGRADE_LENGTH_AXIS must be 'width' or 'height'")
        try:
            import cv2
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError("Install ultralytics and opencv-python to enable model inference") from error
        self._cv2 = cv2
        self._stage1 = YOLO(str(self.stage1_path))
        self._stage2 = YOLO(str(self.stage2_path))
        self._error = None

    @property
    def available(self) -> bool:
        return self._stage1 is not None and self._stage2 is not None

    @property
    def error(self) -> str | None:
        return self._error

    def mark_error(self, error: Exception) -> None:
        self._error = str(error)

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "stage1_model": str(self.stage1_path),
            "stage2_model": str(self.stage2_path),
            "length_axis": self.length_axis,
            "error": self._error,
        }

    def classify(self, image: Any) -> Stage1Prediction:
        if not self.available:
            raise RuntimeError("Model inference is not loaded")
        import time

        started = time.perf_counter()
        result = self._stage1.predict(source=image, verbose=False)[0]
        top1 = int(result.probs.top1)
        confidence = float(result.probs.top1conf)
        label = str(result.names[top1])
        if label.lower() not in {"healthy", "unhealthy"}:
            raise ValueError(f"Unexpected Stage 1 label: {label}")
        return Stage1Prediction(label, confidence, (time.perf_counter() - started) * 1000)

    def detect(self, image: Any) -> Stage2Prediction:
        if not self.available:
            raise RuntimeError("Model inference is not loaded")
        import time

        started = time.perf_counter()
        result = self._stage2.predict(source=image, verbose=False)[0]
        height, width = image.shape[:2]
        if result.boxes is None or len(result.boxes.xyxy) == 0:
            return Stage2Prediction(False, None, None, (time.perf_counter() - started) * 1000, width, height)
        coordinates = tuple(float(value) for value in result.boxes.xyxy[0].tolist())
        return Stage2Prediction(
            True,
            coordinates,
            pixel_length_from_bbox(coordinates, self.length_axis),
            (time.perf_counter() - started) * 1000,
            width,
            height,
        )