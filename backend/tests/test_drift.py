from pathlib import Path

from app.drift import drift_report
from app.storage import Storage, now_iso


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path / "drift.db")
    storage.initialize()
    return storage


def _scan(storage: Storage, scan_id: str, grade: str | None, stage1: str = "Healthy", conf: float = 0.99, **extra) -> None:
    storage.save_scan({
        "scan_id": scan_id, "captured_at": now_iso(), "processing_status": "completed", "final_grade": grade,
        "stage1_status": stage1, "stage1_confidence": conf,
        "stage2_detected": 1 if grade in ("Class A", "Class B") else None,
        "stage2_confidence": 0.97 if grade in ("Class A", "Class B") else None, **extra,
    })


def _indicator(report: dict, key: str) -> dict:
    return next(item for item in report["indicators"] if item["key"] == key)


def test_too_few_scans_reports_insufficient_data(tmp_path) -> None:
    storage = _storage(tmp_path)
    for index in range(5):
        _scan(storage, f"s{index}", "Class A")
    report = drift_report(storage, window=200, min_samples=30)
    assert report["status"] == "insufficient_data"
    assert {item["status"] for item in report["indicators"]} == {"insufficient_data"}


def test_healthy_production_matches_baseline(tmp_path) -> None:
    storage = _storage(tmp_path)
    for index in range(40):
        _scan(storage, f"a{index}", "Class A" if index % 2 else "Class B")
    for index in range(20):
        _scan(storage, f"r{index}", "Rejected", stage1="Unhealthy")
    report = drift_report(storage, window=200, min_samples=10)
    assert report["status"] == "ok"
    assert _indicator(report, "stage1_mean_confidence")["value"] == 0.99
    assert _indicator(report, "size_dispute_rate")["value"] == 0


def test_low_confidence_and_missed_detections_raise_drift(tmp_path) -> None:
    storage = _storage(tmp_path)
    for index in range(30):
        _scan(storage, f"a{index}", "Class A")
    for index in range(5):
        storage.save_scan({"scan_id": f"l{index}", "captured_at": now_iso(), "processing_status": "failed",
                           "rejection_reason": "LOW_CONFIDENCE", "stage1_status": "Healthy", "stage1_confidence": 0.6})
    for index in range(5):
        _scan(storage, f"d{index}", None, stage2_detected=0, rejection_reason="DETECTION_FAILED")
    report = drift_report(storage, window=200, min_samples=10)
    assert report["status"] == "drift_suspected"
    assert _indicator(report, "low_confidence_rate")["status"] == "warn"  # 5 / 40
    assert _indicator(report, "detection_failure_rate")["status"] == "warn"  # 5 / 35 healthy, gate passed


def test_disputes_are_counted_against_the_model_grade(tmp_path) -> None:
    storage = _storage(tmp_path)
    for index in range(20):
        _scan(storage, f"a{index}", "Class A")
    for index in range(8):
        storage.dispute_scan(f"a{index}", None, "Class B", tmp_path / "retrain")  # A -> B, size disputes
    storage.dispute_scan("a8", None, "Rejected", tmp_path / "retrain")  # A -> Rejected, health dispute
    report = drift_report(storage, window=200, min_samples=10)
    assert _indicator(report, "size_dispute_rate")["value"] == 0.4  # 8 / 20, model grades restored
    assert _indicator(report, "size_dispute_rate")["status"] == "warn"
    assert _indicator(report, "health_dispute_rate")["value"] == 0.05  # 1 / 20
