"""Drift indicators: recent production scans compared with the held-out test set.

Baselines come from the final test evaluations in ``training/runs`` (Stage 1: 225 images through the
app's own code path; Stage 2: 150 images). A warning means the table no longer looks like the test
set, for example new lighting, a dirty lens, or a different cultivar. It does not mean the model is
wrong, and it never changes a grade. The response is to review the disputed frames and decide whether
to retrain (see docs/RELEASE_NOTES.md, "Retraining loop").
"""

from __future__ import annotations

import os
from typing import Any

from .storage import Storage

ACCEPTED = ("Class A", "Class B")
GRADED = (*ACCEPTED, "Rejected")

# key, label, baseline, warn when value is beyond limit, direction ("below" or "above"), unit
INDICATORS = (
    ("stage1_mean_confidence", "Stage 1 mean confidence", 0.997, 0.95, "below", "ratio"),
    ("low_confidence_rate", "Below the Stage 1 confidence gate", 0.0044, 0.05, "above", "rate"),
    ("stage2_mean_confidence", "Stage 2 mean detection confidence", 0.978, 0.90, "below", "ratio"),
    ("detection_failure_rate", "Healthy bunches with no detection", 0.0, 0.05, "above", "rate"),
    ("health_dispute_rate", "Disputes between Rejected and accepted", 0.0044, 0.05, "above", "rate"),
    ("size_dispute_rate", "Disputes between Class A and Class B", 0.153, 0.25, "above", "rate"),
)


def _mean(values: list[float]) -> tuple[float | None, int]:
    return (sum(values) / len(values) if values else None), len(values)


def _rate(hits: int, total: int) -> tuple[float | None, int]:
    return (hits / total if total else None), total


def drift_report(storage: Storage, window: int | None = None, min_samples: int | None = None) -> dict[str, Any]:
    window = window or int(os.getenv("BANAGRADE_DRIFT_WINDOW", "200"))
    min_samples = min_samples or int(os.getenv("BANAGRADE_DRIFT_MIN_SAMPLES", "30"))
    rows = storage.recent_scans_with_disputes(window)

    screened = [r for r in rows if r["stage1_confidence"] is not None]
    healthy = [r for r in screened if (r["stage1_status"] or "").lower() == "healthy" and r["rejection_reason"] != "LOW_CONFIDENCE"]
    detected = [r for r in healthy if r["stage2_detected"] and r["stage2_confidence"] is not None]
    model_grade = [(r["model_grade"] if r["disputed"] and r["model_grade"] else r["final_grade"], r) for r in rows]
    graded = [(grade, r) for grade, r in model_grade if grade in GRADED]
    accepted = [(grade, r) for grade, r in graded if grade in ACCEPTED]

    values = {
        "stage1_mean_confidence": _mean([r["stage1_confidence"] for r in screened]),
        "low_confidence_rate": _rate(sum(r["rejection_reason"] == "LOW_CONFIDENCE" for r in screened), len(screened)),
        "stage2_mean_confidence": _mean([r["stage2_confidence"] for r in detected]),
        "detection_failure_rate": _rate(sum(r["rejection_reason"] == "DETECTION_FAILED" for r in healthy), len(healthy)),
        "health_dispute_rate": _rate(
            sum(r["disputed"] and r["corrected_grade"] in GRADED and (grade == "Rejected") != (r["corrected_grade"] == "Rejected") for grade, r in graded),
            len(graded),
        ),
        "size_dispute_rate": _rate(
            sum(r["disputed"] and r["corrected_grade"] in ACCEPTED and r["corrected_grade"] != grade for grade, r in accepted),
            len(accepted),
        ),
    }

    indicators = []
    for key, label, baseline, limit, direction, unit in INDICATORS:
        value, samples = values[key]
        if value is None or samples < min_samples:
            status = "insufficient_data"
        elif (value < limit) if direction == "below" else (value > limit):
            status = "warn"
        else:
            status = "ok"
        indicators.append({
            "key": key, "label": label, "unit": unit, "value": None if value is None else round(value, 4),
            "baseline": baseline, "limit": limit, "direction": direction, "samples": samples, "status": status,
        })

    statuses = {item["status"] for item in indicators}
    overall = "drift_suspected" if "warn" in statuses else "ok" if "ok" in statuses else "insufficient_data"
    return {"status": overall, "window": window, "min_samples": min_samples, "scans_considered": len(rows), "indicators": indicators}
