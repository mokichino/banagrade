"""Captured-frame archive so disputes have an image to send for retraining."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_frame(directory: Path, scan_id: str, image: Any, keep: int) -> Path:
    """Write the full-resolution BGR frame as JPEG and prune the oldest frames beyond ``keep``.

    Disputes copy their frame into the retrain directory, so pruning here never loses a disputed frame.
    """
    import cv2

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{scan_id}.jpg"
    if not cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"Could not write frame {target}")
    frames = sorted(directory.glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    for old in frames[: max(0, len(frames) - keep)]:
        old.unlink(missing_ok=True)
    return target
