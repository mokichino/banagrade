import csv
import io
import zipfile
from pathlib import Path

import pytest

from app.storage import Storage, disputes_zip, now_iso


def _scan(scan_id: str, session_id: str | None, grade: str | None, captured_at: str | None = None, **extra) -> dict:
    return {
        "scan_id": scan_id,
        "session_id": session_id,
        "captured_at": captured_at or now_iso(),
        "completed_at": now_iso(),
        "final_grade": grade,
        "processing_status": "completed",
        "inference_time_ms": 100,
        **extra,
    }


def test_analytics_exclude_technical_failures_from_rates(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    session = storage.ensure_active_session()
    storage.save_scan(_scan("a", session["id"], "Class A", stage1_confidence=0.97, stage2_confidence=0.91))
    storage.save_scan(_scan("b", session["id"], "Class B"))
    storage.save_scan(_scan("r", session["id"], "Rejected"))
    storage.save_scan(_scan("t", session["id"], None, rejection_reason="DETECTION_FAILED"))

    summary = storage.analytics_summary(session["id"])
    assert summary["total_scans"] == 4
    assert summary["total_completed_scans"] == 3
    assert summary["technical_failure_count"] == 1
    assert summary["rejection_rate"] == round(100 / 3, 2)
    assert summary["export_acceptance_rate"] == round(200 / 3, 2)
    assert summary["class_a_share_of_accepted"] == 50.0
    assert storage.get_scan("a")["stage2_confidence"] == 0.91


def test_active_session_is_reused_and_scopes_analytics(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    first = storage.ensure_active_session()
    assert storage.ensure_active_session()["id"] == first["id"]
    storage.save_scan(_scan("old", first["id"], "Rejected"))
    storage.close_session(first["id"])
    second = storage.ensure_active_session()
    assert second["id"] != first["id"]
    storage.save_scan(_scan("new", second["id"], "Class A"))
    assert storage.analytics_summary(second["id"])["total_completed_scans"] == 1
    assert storage.analytics_summary()["total_completed_scans"] == 2


def test_rejection_trend_buckets(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    storage.save_scan(_scan("1", None, "Rejected", "2026-10-13T08:01:00+00:00"))
    storage.save_scan(_scan("2", None, "Class A", "2026-10-13T08:10:00+00:00"))
    storage.save_scan(_scan("3", None, "Class B", "2026-10-13T08:20:00+00:00"))
    storage.save_scan(_scan("4", None, None, "2026-10-13T08:21:00+00:00"))
    trend = storage.rejection_trend(None, 15)
    assert [item["bucket_start"] for item in trend] == ["2026-10-13T08:00:00+00:00", "2026-10-13T08:15:00+00:00"]
    assert trend[0]["rejection_rate"] == 50.0
    assert trend[1] == {"bucket_start": "2026-10-13T08:15:00+00:00", "total": 1, "rejected": 0, "rejection_rate": 0.0}


def test_migration_adds_stage2_confidence(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    from app.storage import SCHEMA

    with storage.connect() as connection:
        connection.executescript(SCHEMA.replace("    stage2_confidence REAL,\n", ""))
        assert "stage2_confidence" not in {row["name"] for row in connection.execute("PRAGMA table_info(scans)")}
    storage.initialize()
    with storage.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(scans)")}
    assert "stage2_confidence" in columns


def test_dispute_keeps_model_grade_across_repeated_corrections(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    storage.save_scan(_scan("a", None, "Class A"))
    storage.save_scan(_scan("b", None, "Class B"))
    first = storage.dispute_scan("a", "Looks small", "Class B", tmp_path / "retrain")
    second = storage.dispute_scan("a", "Actually bruised", "Rejected", tmp_path / "retrain")
    assert first["original_grade"] == second["original_grade"] == "Class A"
    assert storage.get_scan("a")["final_grade"] == "Rejected"
    [row] = storage.disputed_scans()
    assert (row["model_grade"], row["corrected_grade"], row["reason"]) == ("Class A", "Rejected", "Actually bruised")
    assert {scan["scan_id"]: scan["disputed"] for scan in storage.list_scans()} == {"a": 1, "b": 0}


def test_deleting_disputes_restores_the_previous_grade(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    frame = tmp_path / "frames" / "a.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"\xff\xd8jpeg")
    storage.save_scan(_scan("a", None, "Class B", image_refs=[str(frame)]))
    first = storage.dispute_scan("a", "Middle finger 12.5 cm", "Class A", tmp_path / "retrain")
    second = storage.dispute_scan("a", "Rotting", "Rejected", tmp_path / "retrain")
    assert [row["id"] for row in storage.scan_disputes("a")] == [second["id"], first["id"]]

    assert storage.delete_dispute("a", second["id"])["final_grade"] == "Class A"
    assert Path(first["archived_frames"][0]).exists()
    result = storage.delete_dispute("a", first["id"])
    assert (result["final_grade"], result["remaining_disputes"]) == ("Class B", 0)
    assert not Path(first["archived_frames"][0]).exists()
    assert storage.list_scans()[0]["disputed"] == 0
    with pytest.raises(KeyError):
        storage.delete_dispute("a", first["id"])


def test_disputes_zip_sorts_frames_by_corrected_grade(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    frame = tmp_path / "frames" / "a.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"\xff\xd8jpeg")
    storage.save_scan(_scan("a", None, "Class A", image_refs=[str(frame)]))
    storage.save_scan(_scan("t", None, None, rejection_reason="LOW_CONFIDENCE"))
    storage.dispute_scan("a", None, "Class B", tmp_path / "retrain")
    storage.dispute_scan("t", "No grade given", None, tmp_path / "retrain")

    target = disputes_zip(storage.disputed_scans(), tmp_path / "out.zip")
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["frames/Class_B/a_a.jpg", "labels.csv"]
        assert archive.read("frames/Class_B/a_a.jpg") == b"\xff\xd8jpeg"
        labels = list(csv.DictReader(io.StringIO(archive.read("labels.csv").decode())))
    assert [(r["scan_id"], r["model_grade"], r["corrected_grade"], r["frame"]) for r in labels] == [
        ("a", "Class A", "Class B", "frames/Class_B/a_a.jpg"),
        ("t", "Technical Failure", "", ""),
    ]
