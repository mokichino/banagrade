import csv
import io
import sqlite3
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


def test_rejection_trend_follows_the_viewers_clock(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    storage.save_scan(_scan("day1", None, "Rejected", "2026-10-13T15:59:00+00:00"))  # 23:59 in Manila
    storage.save_scan(_scan("day2", None, "Class A", "2026-10-13T16:01:00+00:00"))  # 00:01 the next day
    days = storage.rejection_trend(None, 1440, utc_offset_minutes=480)
    assert [(item["bucket_start"], item["total"]) for item in days] == [("2026-10-12T16:00:00+00:00", 1), ("2026-10-13T16:00:00+00:00", 1)]
    assert [item["bucket_start"] for item in storage.rejection_trend(None, 1440)] == ["2026-10-13T00:00:00+00:00"]
    # A half-hour zone still gets buckets on its own quarter hours.
    assert storage.rejection_trend(None, 60, utc_offset_minutes=330)[0]["bucket_start"] == "2026-10-13T15:30:00+00:00"


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


def test_migration_adds_shift_names_without_renaming_old_shifts(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    from app.storage import SCHEMA

    with storage.connect() as connection:
        connection.executescript(SCHEMA.replace("    notes TEXT,\n    name TEXT\n", "    notes TEXT\n"))
        connection.execute("INSERT INTO sessions (id, started_at, status, notes) VALUES ('old', '2026-10-20T04:58:24+00:00', 'open', 'Shift opened automatically at startup')")
    storage.initialize()
    [old] = storage.list_sessions()
    assert (old["notes"], old["name"]) == ("Shift opened automatically at startup", None)


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


def test_deleting_disputes_restores_the_scanner_grade(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    frame = tmp_path / "frames" / "a.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"\xff\xd8jpeg")
    storage.save_scan(_scan("a", None, "Class B", image_refs=[str(frame)]))
    storage.save_scan(_scan("b", None, None, processing_status="failed"))
    first = storage.dispute_scan("a", "Middle finger 12.5 cm", "Class A", tmp_path / "retrain")
    second = storage.dispute_scan("a", "Middle finger 12.5 cm", "Class A", tmp_path / "retrain")
    assert [row["id"] for row in storage.scan_disputes("a")] == [second["id"], first["id"]]

    result = storage.delete_disputes("a")
    assert (result["final_grade"], result["deleted_disputes"]) == ("Class B", 2)
    assert storage.scan_disputes("a") == []
    assert not Path(first["archived_frames"][0]).exists()
    assert storage.list_scans()[-1]["disputed"] == 0
    with pytest.raises(KeyError):
        storage.delete_disputes("a")

    storage.dispute_scan("b", "Bunch was not on the table", "Rejected", tmp_path / "retrain")
    assert storage.delete_disputes("b")["final_grade"] is None


def test_scans_and_sessions_list_by_shift(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    first = storage.create_session("Kapalong batch")
    storage.save_scan(_scan("a", first["id"], "Class A"))
    storage.close_session(first["id"])
    second = storage.create_session("Toril batch")
    storage.save_scan(_scan("b", second["id"], "Class B"))
    storage.save_scan(_scan("c", second["id"], "Class B"))

    assert [scan["scan_id"] for scan in storage.list_scans(session_id=first["id"])] == ["a"]
    assert len(storage.list_scans()) == 3
    assert [(row["notes"], row["status"], row["scan_count"]) for row in storage.list_sessions()] == [
        ("Toril batch", "open", 2),
        ("Kapalong batch", "closed", 1),
    ]


def test_shift_name_is_trimmed_and_blank_means_unnamed(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    named = storage.create_session("Shift started from dashboard", "  Toril batch ")
    assert (named["name"], named["notes"]) == ("Toril batch", "Shift started from dashboard")
    assert storage.create_session("Shift started from dashboard", "   ")["name"] is None
    assert [row["name"] for row in storage.list_sessions()] == [None, "Toril batch"]


def test_clear_scans_backs_up_then_deletes_records_and_frames(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    empty = storage.create_session("Shift opened automatically at startup")
    storage.close_session(empty["id"])
    session = storage.create_session("Shift")
    frames = tmp_path / "frames"
    frames.mkdir()
    frame = frames / "a.jpg"
    frame.write_bytes(b"\xff\xd8jpeg")
    elsewhere = tmp_path / "keep.jpg"
    elsewhere.write_bytes(b"\xff\xd8jpeg")
    storage.save_scan(_scan("a", session["id"], "Class A", image_refs=[str(frame)]))
    storage.save_scan(_scan("b", session["id"], "Class B", image_refs=[str(elsewhere)]))
    dispute = storage.dispute_scan("a", "Middle finger 11 cm", "Class B", tmp_path / "retrain")

    result = storage.clear_scans(tmp_path / "backups", frames)

    assert (result["scans"], result["disputes"], result["frames"], result["shifts"]) == (2, 1, 1, 2)
    assert storage.list_scans() == [] and storage.scan_disputes("a") == []
    assert not frame.exists() and elsewhere.exists()
    assert Path(dispute["archived_frames"][0]).exists()
    with sqlite3.connect(result["backup"]) as backup:
        assert backup.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2
    active = storage.active_session()
    assert active["id"] == result["session_id"] != session["id"]
    # The emptied shifts are in the backup only; the new shift is the one left.
    assert [row["id"] for row in storage.list_sessions()] == [active["id"]]
    with sqlite3.connect(result["backup"]) as backup:
        assert backup.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


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
