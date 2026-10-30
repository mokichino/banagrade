import csv
import io
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.storage import SHIFT_FROM_SCAN, ShiftClosed, Storage, disputes_zip, now_iso


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


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_shift_rolls_over_at_manila_midnight_while_running(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    first = storage.ensure_active_session(now=_utc("2026-10-30T00:00:00"))  # 08:00 on Oct 30 in Manila
    storage.save_scan(_scan("a", first["id"], "Class A", "2026-10-30T09:30:00+00:00"))
    assert storage.ensure_active_session(now=_utc("2026-10-30T15:59:00"))["id"] == first["id"]  # 23:59, same day

    second = storage.ensure_active_session(SHIFT_FROM_SCAN, now=_utc("2026-10-30T16:01:00"))  # 00:01 on Oct 31
    assert second["id"] != first["id"]
    assert (second["notes"], second["started_at"]) == (SHIFT_FROM_SCAN, "2026-10-30T16:01:00+00:00")
    # The finished day ends at its last scan, not when the next one began.
    shifts = {row["id"]: row for row in storage.list_sessions()}
    assert (shifts[first["id"]]["status"], shifts[first["id"]]["ended_at"]) == ("closed", "2026-10-30T09:30:00+00:00")
    assert storage.ensure_active_session(now=_utc("2026-10-31T02:00:00"))["id"] == second["id"]


def test_restarts_on_the_same_day_reuse_its_shift(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    morning = storage.ensure_active_session(now=_utc("2026-10-30T00:00:00"))
    restarted = Storage(storage.path)  # what a reboot amounts to: a fresh Storage on the same file
    restarted.initialize()
    assert restarted.ensure_active_session(now=_utc("2026-10-30T07:00:00"))["id"] == morning["id"]
    assert len(restarted.list_sessions()) == 1


def test_an_empty_shift_from_an_earlier_day_is_deleted(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    idle = storage.ensure_active_session(now=_utc("2026-10-29T00:00:00"))
    with storage.connect() as connection:  # record_temperature stamps the real time, ahead of this test's clock
        connection.execute("INSERT INTO telemetry_samples (sampled_at, session_id, cpu_temperature_c) VALUES ('2026-10-29T01:00:00+00:00', ?, 48.0)", (idle["id"],))
    today = storage.ensure_active_session(now=_utc("2026-10-30T00:00:00"))
    assert [row["id"] for row in storage.list_sessions()] == [today["id"]]
    assert storage.temperature_summary() is None


def test_a_clock_gone_back_does_not_roll_over_or_backdate(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    shift = storage.ensure_active_session(now=_utc("2026-10-30T00:00:00"))
    storage.save_scan(_scan("a", shift["id"], "Class A", "2026-10-30T09:00:00+00:00"))
    # A Pi with no internet and no RTC battery boots with an old date: same shift, and the dashboard is told.
    back = _utc("2026-10-28T03:00:00")
    assert storage.ensure_active_session(now=back)["id"] == shift["id"]
    assert storage.clock_status(back)["trusted"] is False
    assert storage.clock_status(_utc("2026-10-30T09:02:00"))["trusted"] is True  # a small NTP step back is fine
    assert storage.clock_status(_utc("2026-10-30T09:20:00")) == {"trusted": True, "now": "2026-10-30T09:20:00+00:00", "newest_record": "2026-10-30T09:00:00+00:00"}

    # With no shift open, a new one starts at the newest record rather than at the wrong, earlier date.
    storage.close_session(shift["id"])
    opened = storage.ensure_active_session(now=back)
    assert opened["started_at"] == "2026-10-30T09:00:00+00:00"


def test_a_corrected_clock_moves_what_this_boot_recorded_into_today(tmp_path: Path) -> None:
    path = tmp_path / "banagrade.db"
    before = Storage(path, boot_id="before-the-power-cut")
    before.initialize()
    shift = before.ensure_active_session(now=_utc("2026-10-30T00:00:00"))  # Oct 30, 08:00 in Manila
    before.save_scan(_scan("a", shift["id"], "Class A", "2026-10-30T09:00:00+00:00"))  # 17:00, then the power goes

    # Power back at 08:00 on Oct 31 with no internet: the clock resumes near 17:00 on Oct 30, so scans land on Oct 30.
    after = Storage(path, boot_id="after-the-power-cut")
    assert after.ensure_active_session(now=_utc("2026-10-30T09:05:00"))["id"] == shift["id"]
    after.save_scan(_scan("b", shift["id"], "Class B", "2026-10-30T09:10:00+00:00", completed_at="2026-10-30T09:10:02+00:00"))
    with after.connect() as connection:
        connection.execute("INSERT INTO telemetry_samples (sampled_at, session_id, cpu_temperature_c, boot_id) VALUES ('2026-10-30T09:15:00+00:00', ?, 50.0, 'after-the-power-cut')", (shift["id"],))

    # A phone sets the clock 16 hours forward, to 09:30 on Oct 31.
    moved = after.correct_clock(16 * 3600, _utc("2026-10-30T09:30:00"), now=_utc("2026-10-31T01:30:00"))
    assert moved == {"scans": 1, "shifts": 0, "samples": 1}
    b = after.get_scan("b")
    assert (b["captured_at"], b["completed_at"]) == ("2026-10-31T01:10:00+00:00", "2026-10-31T01:10:02+00:00")
    today = after.active_session()
    assert today["id"] != shift["id"] and b["session_id"] == today["id"]
    assert after.temperature_summary(today["id"])["samples"] == 1
    # Oct 30 keeps only what happened before the power cut, untouched, and ends at its own last scan.
    assert after.get_scan("a")["captured_at"] == "2026-10-30T09:00:00+00:00"
    old = next(row for row in after.list_sessions() if row["id"] == shift["id"])
    assert (old["status"], old["ended_at"], old["scan_count"]) == ("closed", "2026-10-30T09:00:00+00:00", 1)
    # Correcting again finds nothing behind the cutoff.
    assert after.correct_clock(16 * 3600, _utc("2026-10-30T09:30:00"), now=_utc("2026-10-31T01:31:00"))["scans"] == 0


def test_a_shift_opened_while_the_clock_was_wrong_moves_with_it(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db", boot_id="this-boot")
    storage.initialize()
    wrong = storage.ensure_active_session(now=_utc("2026-10-29T01:00:00"))
    storage.save_scan(_scan("a", wrong["id"], "Class A", "2026-10-29T02:00:00+00:00"))
    storage.correct_clock(2 * 86400, _utc("2026-10-29T03:00:00"), now=_utc("2026-10-31T03:00:00"))
    [shift] = storage.list_sessions()
    assert (shift["id"], shift["started_at"], shift["status"]) == (wrong["id"], "2026-10-31T01:00:00+00:00", "open")
    assert storage.get_scan("a")["captured_at"] == "2026-10-31T02:00:00+00:00"


def test_closed_shift_scans_are_read_only(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    yesterday = storage.ensure_active_session(now=_utc("2026-10-29T00:00:00"))
    storage.save_scan(_scan("old", yesterday["id"], "Class A", "2026-10-29T03:00:00+00:00"))
    storage.save_scan(_scan("old-voided", yesterday["id"], "Class B", "2026-10-29T04:00:00+00:00"))
    storage.void_scans(["old-voided"], "Duplicate scan of the same bunch")
    storage.dispute_scan("old", "Looks small", "Class B", tmp_path / "retrain")
    today = storage.ensure_active_session(now=_utc("2026-10-30T00:00:00"))
    storage.save_scan(_scan("new", today["id"], "Class A", "2026-10-30T01:00:00+00:00"))

    for change in (
        lambda: storage.dispute_scan("old", "Too late", "Rejected", tmp_path / "retrain"),
        lambda: storage.delete_disputes("old"),
        lambda: storage.void_scans(["new", "old"], "Test run"),
        lambda: storage.unvoid_scans(["old-voided"]),
        lambda: storage.rename_session(yesterday["id"], "Kapalong batch"),
    ):
        with pytest.raises(ShiftClosed):
            change()
    # A mixed batch changes nothing, today's scan included.
    assert storage.get_scan("new")["voided_at"] is None
    assert (storage.get_scan("old")["final_grade"], len(storage.scan_disputes("old"))) == ("Class B", 1)
    assert storage.get_scan("old-voided")["voided_at"] is not None
    assert {scan["scan_id"]: scan["shift_closed"] for scan in storage.list_scans()} == {"new": 0, "old": 1, "old-voided": 1}

    # Today's shift stays editable.
    assert storage.void_scans(["new"], "Test run") == ["new"]
    assert storage.rename_session(today["id"], "  Toril batch ")["name"] == "Toril batch"
    with pytest.raises(KeyError):
        storage.rename_session("missing", "x")


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
        old = (
            SCHEMA.replace("    notes TEXT,\n    name TEXT,\n    boot_id TEXT\n", "    notes TEXT\n")
            .replace("    error_details TEXT,\n    voided_at TEXT,\n    void_reason TEXT,\n    boot_id TEXT\n", "    error_details TEXT\n")
            .replace("    fan_level INTEGER,\n    boot_id TEXT\n", "    fan_level INTEGER\n")
        )
        assert "voided_at" not in old and "name TEXT" not in old and "boot_id" not in old
        connection.executescript(old)
        connection.execute("INSERT INTO sessions (id, started_at, status, notes) VALUES ('old', '2026-10-20T04:58:24+00:00', 'open', 'Shift opened automatically at startup')")
    storage.initialize()
    [old] = storage.list_sessions()
    assert (old["notes"], old["name"], old["voided_count"]) == ("Shift opened automatically at startup", None, 0)
    with storage.connect() as connection:
        for table in ("scans", "sessions", "telemetry_samples"):
            assert "boot_id" in {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


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
    storage.record_temperature(session["id"], 51.0, 1)  # goes with its shift, not in the way of deleting it

    result = storage.clear_scans(tmp_path / "backups", frames)

    assert (result["scans"], result["disputes"], result["frames"], result["shifts"]) == (2, 1, 1, 1)
    assert storage.list_scans() == [] and storage.scan_disputes("a") == []
    # The photo moves into the backup folder instead of being deleted, so a clear can be undone completely.
    folder = Path(result["backup"])
    assert folder.parent == tmp_path / "backups" and folder.name.startswith("clear-")
    assert not frame.exists() and (folder / "frames" / "a.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert elsewhere.exists()
    assert Path(dispute["archived_frames"][0]).exists()
    with sqlite3.connect(folder / "banagrade.db") as backup:
        assert backup.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2
    # Today's shift carries on, emptied, so the day keeps its one shift; the empty past shift is in the backup only.
    assert storage.active_session()["id"] == result["session_id"] == session["id"]
    assert [row["id"] for row in storage.list_sessions()] == [session["id"]]
    with sqlite3.connect(folder / "banagrade.db") as backup:
        assert backup.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
        assert backup.execute("SELECT COUNT(*) FROM telemetry_samples").fetchone()[0] == 1
    assert storage.temperature_summary() is None


def test_cpu_temperature_is_summarised_per_shift(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    morning = storage.create_session("Shift")
    assert storage.analytics_summary(morning["id"])["cpu_temperature"] is None
    for reading in (48.0, 52.5, 50.1):
        storage.record_temperature(morning["id"], reading, 0)
    storage.close_session(morning["id"])
    afternoon = storage.create_session("Shift")
    storage.record_temperature(afternoon["id"], 60.0, 2)

    summary = storage.analytics_summary(morning["id"])["cpu_temperature"]
    assert (summary["mean_c"], summary["max_c"], summary["samples"]) == (50.2, 52.5, 3)
    assert storage.temperature_summary()["samples"] == 4


def test_a_scan_after_end_shift_opens_a_new_shift(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    ended = storage.ensure_active_session()
    storage.close_session(ended["id"])
    assert storage.active_session() is None
    opened = storage.ensure_active_session(SHIFT_FROM_SCAN)
    assert (opened["notes"], opened["status"]) == (SHIFT_FROM_SCAN, "open") and opened["id"] != ended["id"]


def test_voided_scans_stay_listed_but_count_nowhere(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    session = storage.ensure_active_session()
    storage.save_scan(_scan("dup", session["id"], "Rejected", "2026-10-26T20:28:23+00:00"))
    storage.save_scan(_scan("keep", session["id"], "Rejected", "2026-10-26T20:45:47+00:00"))
    storage.save_scan(_scan("paper", session["id"], None, "2026-10-26T20:46:00+00:00", rejection_reason="NOT_A_BUNCH"))

    assert storage.void_scans(["dup", "paper", "missing", "dup"], "Duplicate scan of the same bunch") == ["dup", "paper"]
    # A second void keeps the first reason.
    assert storage.void_scans(["dup"], "Something else") == []
    summary = storage.analytics_summary(session["id"])
    assert (summary["total_scans"], summary["rejected_count"], summary["technical_failure_count"], summary["voided_count"]) == (1, 1, 0, 2)
    assert summary["rejection_rate"] == 100.0
    assert [item["total"] for item in storage.rejection_trend(session["id"], 60)] == [1]
    assert [(row["scan_count"], row["voided_count"]) for row in storage.list_sessions()] == [(1, 2)]
    assert len(storage.recent_scans_with_disputes(10)) == 1
    listed = {scan["scan_id"]: scan for scan in storage.list_scans()}
    assert len(listed) == 3 and listed["dup"]["void_reason"] == "Duplicate scan of the same bunch" and listed["dup"]["voided_at"]

    assert storage.unvoid_scans(["dup", "keep"]) == ["dup"]
    assert storage.analytics_summary(session["id"])["total_scans"] == 2
    assert storage.get_scan("dup")["voided_at"] is None
    with storage.connect() as connection:
        events = connection.execute("SELECT event_type, description FROM system_events WHERE scan_id = 'dup' ORDER BY rowid").fetchall()
    assert [tuple(row) for row in events] == [
        ("scan_voided", "Duplicate scan of the same bunch"),
        ("scan_unvoided", "Counted again; had been voided: Duplicate scan of the same bunch"),
    ]


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
