from pathlib import Path

from app.storage import Storage, now_iso


def test_storage_initializes_sessions_and_analytics(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()

    session = storage.create_session("morning line")
    storage.save_scan(
        {
            "scan_id": "scan-a",
            "session_id": session["id"],
            "captured_at": now_iso(),
            "completed_at": now_iso(),
            "stage1_status": "Healthy",
            "stage2_detected": 1,
            "calculated_length_cm": 12.5,
            "final_grade": "Class A",
            "processing_status": "completed",
            "inference_time_ms": 100,
        }
    )
    storage.save_scan(
        {
            "scan_id": "scan-b",
            "session_id": session["id"],
            "captured_at": now_iso(),
            "completed_at": now_iso(),
            "stage1_status": "Healthy",
            "stage2_detected": 0,
            "final_grade": None,
            "rejection_reason": "DETECTION_FAILED",
            "processing_status": "completed",
            "inference_time_ms": 140,
        }
    )

    summary = storage.analytics_summary()
    assert summary["total_completed_scans"] == 2
    assert summary["class_a_count"] == 1
    assert summary["technical_failure_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["export_acceptance_rate"] == 50.0

    storage.close_session(session["id"])
    with storage.connect() as connection:
        assert connection.execute("SELECT status FROM sessions WHERE id = ?", (session["id"],)).fetchone()[0] == "closed"