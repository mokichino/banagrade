"""Presentation (mock) data.

Generates realistic-looking scan records for demos and screenshots. Every mock record
carries ``model_metadata.demo = true`` so the dashboard can label it, and the seeding
script refuses to write into the production database unless forced.

Distributions are chosen to resemble the thesis results, not to reproduce them:
- Stage 1 confidences are high (held-out accuracy 99.56%, §4.4.1).
- Stage 2 detection confidence is high (mAP@0.50 = 99.5%, §4.4.2).
- Bounding-box widths straddle the 2730.07 px threshold (§4.4.3); Class A >= threshold.
- End-to-end latency is around 1 s, under the 2 s target (§4.7).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .grading import DEFAULT_WIDTH_THRESHOLD_PX, REFERENCE_RESOLUTION
from .storage import Storage

DEMO_TAG = {"stage1": "stage1_best.pt", "stage2": "stage2_best.pt", "demo": True}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def generate_scan(
    rng: random.Random,
    captured_at: datetime,
    session_id: str | None,
    reject_probability: float = 0.2,
    class_a_share: float = 0.55,
) -> dict[str, Any]:
    """One mock scan that follows the real grading rule."""
    scan_id = str(uuid.uuid4())
    threshold = DEFAULT_WIDTH_THRESHOLD_PX
    stage1_ms = rng.gauss(140, 25)
    record: dict[str, Any] = {
        "scan_id": scan_id,
        "session_id": session_id,
        "captured_at": _iso(captured_at),
        "processing_status": "completed",
        "model_metadata": DEMO_TAG,
        "threshold_values": {"width_threshold_px": threshold, "reference_resolution": list(REFERENCE_RESOLUTION), "axis": "width"},
    }
    roll = rng.random()
    if roll < 0.012:  # rare technical failure: low Stage 1 confidence (Healthy only; Unhealthy is always Rejected)
        conf = rng.uniform(0.55, 0.79)
        latency = rng.gauss(620, 80)
        record.update({
            "stage1_status": "Healthy",
            "stage1_confidence": conf,
            "processing_status": "failed",
            "rejection_reason": "LOW_CONFIDENCE",
            "error_details": f"Stage 1 confidence {conf:.2f} is below 0.80",
            "inference_time_ms": latency,
            "stage_timings": {"stage1_ms": stage1_ms, "stage2_ms": None},
        })
    elif roll < 0.012 + reject_probability:
        latency = rng.gauss(640, 90)
        record.update({
            "stage1_status": "Unhealthy",
            "stage1_confidence": min(0.999, rng.betavariate(30, 1.2)),
            "final_grade": "Rejected",
            "rejection_reason": "SURFACE_UNHEALTHY",
            "inference_time_ms": latency,
            "stage_timings": {"stage1_ms": stage1_ms, "stage2_ms": None},
        })
    else:
        is_a = rng.random() < class_a_share
        width = rng.gauss(3010, 170) if is_a else rng.gauss(2430, 180)
        # Keep the mock consistent with the frozen rule, including a few near-threshold bunches.
        width = max(threshold, width) if is_a else min(threshold - 0.5, width)
        x1 = rng.uniform(300, REFERENCE_RESOLUTION[0] - width - 300)
        y1 = rng.uniform(250, 700)
        height = width * rng.uniform(0.55, 0.75)
        stage2_ms = rng.gauss(520, 70)
        latency = stage1_ms + stage2_ms + rng.gauss(420, 60)
        record.update({
            "stage1_status": "Healthy",
            "stage1_confidence": min(0.999, rng.betavariate(40, 1.0)),
            "stage2_detected": 1,
            "stage2_confidence": rng.uniform(0.92, 0.99),
            "bbox_coords": [round(x1, 1), round(y1, 1), round(x1 + width, 1), round(y1 + height, 1)],
            "pixel_length": width,
            "final_grade": "Class A" if is_a else "Class B",
            "inference_time_ms": latency,
            "stage_timings": {"stage1_ms": stage1_ms, "stage2_ms": stage2_ms},
        })
    record["completed_at"] = _iso(captured_at + timedelta(milliseconds=max(300, record["inference_time_ms"])))
    return record


def _hourly_reject_rate(rng: random.Random, hour_index: int) -> float:
    """Rejection drifts during a shift (e.g. a poorer batch arrives mid-morning)."""
    base = 0.14 + 0.06 * (1 if hour_index in (2, 3) else 0)
    return max(0.05, min(0.4, rng.gauss(base, 0.04)))


def seed(storage: Storage, *, days: int = 6, seed_value: int = 2026, now: datetime | None = None, current_shift_hours: float = 3.0) -> dict[str, int]:
    """Create closed past shifts plus today's open shift, full of mock scans."""
    rng = random.Random(seed_value)
    now = now or datetime.now(UTC)
    counts = {"sessions": 0, "scans": 0, "disputes": 0}

    def run_shift(start: datetime, end: datetime, session_id: str) -> list[str]:
        ids: list[str] = []
        moment = start
        while moment < end:
            hour_index = int((moment - start).total_seconds() // 3600)
            record = generate_scan(rng, moment, session_id, _hourly_reject_rate(rng, hour_index), rng.uniform(0.5, 0.6))
            storage.save_scan(record)
            ids.append(record["scan_id"])
            moment += timedelta(seconds=rng.uniform(55, 140))
        return ids

    with storage.connect() as connection:
        for offset in range(days, 0, -1):
            day = (now - timedelta(days=offset)).replace(hour=23, minute=0, second=0, microsecond=0)  # 07:00 PH time
            start, end = day, day + timedelta(hours=rng.uniform(6.5, 8.0))
            session_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO sessions (id, started_at, ended_at, status, notes) VALUES (?, ?, ?, 'closed', ?)",
                (session_id, _iso(start), _iso(end), "Demo shift"),
            )
            counts["sessions"] += 1
            connection.commit()
            counts["scans"] += len(run_shift(start, end, session_id))

    # Today's shift, as the service would open it; one already open today is reused, as there is one shift per day.
    opened = storage.active_session_id()
    current = storage.ensure_active_session("Demo shift (current)", now=now)
    counts["sessions"] += current["id"] != opened
    ids = run_shift(now - timedelta(hours=current_shift_hours), now - timedelta(minutes=1), current["id"])
    counts["scans"] += len(ids)

    examples = ((12, "Class B", "Bunch looked borderline; supervisor re-measured as small hand"), (40, "Rejected", "Sap staining on the underside missed by the camera"))
    for back, grade, reason in examples:
        if len(ids) < back:
            continue
        scan_id = ids[-back]
        storage.dispute_scan(scan_id, reason, grade, retrain_dir=storage.path.parent / "demo_retrain")
        counts["disputes"] += 1
    return counts


def has_demo_data(storage: Storage) -> bool:
    with storage.connect() as connection:
        row = connection.execute("SELECT 1 FROM scans WHERE model_metadata LIKE '%\"demo\":true%' LIMIT 1").fetchone()
    return row is not None
