from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .clock import boot_id as current_boot_id

log = logging.getLogger(__name__)



SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
    notes TEXT,
    name TEXT,
    boot_id TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    captured_at TEXT NOT NULL,
    completed_at TEXT,
    stage1_status TEXT,
    stage1_confidence REAL,
    stage2_detected INTEGER,
    stage2_confidence REAL,
    bbox_coords TEXT,
    pixel_length REAL,
    calculated_length_cm REAL,
    calibration_factor_used REAL,
    final_grade TEXT,
    rejection_reason TEXT,
    processing_status TEXT NOT NULL,
    inference_time_ms REAL,
    stage_timings TEXT,
    image_refs TEXT,
    model_metadata TEXT,
    threshold_values TEXT,
    error_details TEXT,
    voided_at TEXT,
    void_reason TEXT,
    boot_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_captured_at ON scans(captured_at);
CREATE INDEX IF NOT EXISTS idx_scans_session_id ON scans(session_id);
CREATE INDEX IF NOT EXISTS idx_scans_final_grade ON scans(final_grade);
CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    calibration_factor REAL,
    class_a_min_cm REAL NOT NULL DEFAULT 12.0,
    class_b_min_cm REAL NOT NULL DEFAULT 8.0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    operator_id TEXT
);
CREATE TABLE IF NOT EXISTS system_events (
    event_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    scan_id TEXT REFERENCES scans(scan_id),
    session_id TEXT REFERENCES sessions(id)
);
CREATE TABLE IF NOT EXISTS scan_disputes (
    id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id),
    reason TEXT,
    corrected_grade TEXT,
    archived_frames TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved'))
);
CREATE INDEX IF NOT EXISTS idx_scan_disputes_scan_id ON scan_disputes(scan_id);
CREATE TABLE IF NOT EXISTS telemetry_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    cpu_temperature_c REAL NOT NULL,
    fan_level INTEGER,
    boot_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_samples_session_id ON telemetry_samples(session_id);
"""


# One shift per calendar day in the packinghouse's time zone, opened and closed by the service itself: at startup, by
# the first scan of a new day, or when the dashboard or the temperature sampler asks for the current shift. Grading
# never waits on the dashboard, which may be out of reach.
SHIFT_TIMEZONE = ZoneInfo(os.getenv("BANAGRADE_TIMEZONE", "Asia/Manila"))
SHIFT_AT_STARTUP = "Daily shift opened automatically"
SHIFT_FROM_SCAN = "Daily shift opened by the first scan of the day"
# NTP may step the clock back a few seconds; only a bigger jump means the date cannot be trusted.
CLOCK_SLACK = timedelta(minutes=5)


class ShiftClosed(Exception):
    """The scan's shift has ended, so its totals are final and the scan can no longer be disputed or voided."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse(moment: str) -> datetime:
    parsed = datetime.fromisoformat(moment)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def shift_date(moment: str | datetime) -> date:
    """The calendar day a moment belongs to, which is the day of its shift."""
    return (_parse(moment) if isinstance(moment, str) else moment).astimezone(SHIFT_TIMEZONE).date()


def clock_trusted(now: datetime, newest: datetime | None) -> bool:
    """False when the clock is behind the newest record, as on a Pi that booted with no internet and no RTC battery."""
    return newest is None or now >= newest - CLOCK_SLACK


class Storage:
    def __init__(self, path: str | Path, boot_id: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.boot_id = boot_id or current_boot_id()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(scan_disputes)")}
            if "corrected_grade" not in columns:
                connection.execute("ALTER TABLE scan_disputes ADD COLUMN corrected_grade TEXT")
            if "archived_frames" not in columns:
                connection.execute("ALTER TABLE scan_disputes ADD COLUMN archived_frames TEXT")
            if "original_grade" not in columns:
                connection.execute("ALTER TABLE scan_disputes ADD COLUMN original_grade TEXT")
            scan_columns = {row["name"] for row in connection.execute("PRAGMA table_info(scans)")}
            if "stage2_confidence" not in scan_columns:
                connection.execute("ALTER TABLE scans ADD COLUMN stage2_confidence REAL")
            for column in ("voided_at", "void_reason"):
                if column not in scan_columns:
                    connection.execute(f"ALTER TABLE scans ADD COLUMN {column} TEXT")
            # Shifts once used notes as their name; name now holds only what the operator typed.
            if "name" not in {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}:
                connection.execute("ALTER TABLE sessions ADD COLUMN name TEXT")
            # Which boot wrote a record, so a clock corrected after boot moves only what was stamped with the wrong time.
            for table in ("scans", "sessions", "telemetry_samples"):
                if "boot_id" not in {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN boot_id TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO system_config (id, updated_at) VALUES (1, ?)",
                (now_iso(),),
            )

    def dispute_scan(
        self,
        scan_id: str,
        reason: str | None,
        corrected_grade: str | None,
        retrain_dir: str | Path = "/dataset/retrain",
    ) -> dict[str, Any]:
        dispute_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scan = connection.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
            if scan is None:
                raise KeyError(scan_id)
            self._check_shift_open(connection, [scan_id])
            # A correction overwrites final_grade, so keep the model's own grade from the first dispute.
            first = connection.execute(
                "SELECT original_grade FROM scan_disputes WHERE scan_id = ? AND original_grade IS NOT NULL ORDER BY created_at, rowid LIMIT 1",
                (scan_id,),
            ).fetchone()
            original_grade = first["original_grade"] if first else (scan["final_grade"] or "Technical Failure")
            archived: list[str] = []
            image_refs = json.loads(scan["image_refs"]) if scan["image_refs"] else []
            if isinstance(image_refs, str):
                image_refs = [image_refs]
            destination = Path(retrain_dir)
            destination.mkdir(parents=True, exist_ok=True)
            for image_ref in image_refs:
                source = Path(image_ref)
                if source.is_file():
                    target = destination / f"{scan_id}_{source.name}"
                    shutil.copy2(source, target)
                    archived.append(str(target))
            connection.execute(
                "INSERT INTO scan_disputes (id, scan_id, reason, corrected_grade, original_grade, archived_frames, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (dispute_id, scan_id, reason, corrected_grade, original_grade, json.dumps(archived), now_iso()),
            )
            if corrected_grade:
                stored_grade = None if corrected_grade == "Technical Failure" else corrected_grade
                connection.execute("UPDATE scans SET final_grade = ? WHERE scan_id = ?", (stored_grade, scan_id))
        return {"id": dispute_id, "scan_id": scan_id, "reason": reason, "corrected_grade": corrected_grade, "original_grade": original_grade, "archived_frames": archived}

    def clear_scans(self, backup_dir: Path, frame_dir: Path) -> dict[str, Any]:
        """Verified backup first, then delete all scans, disputes, events and the past shifts left empty.

        Today's shift stays open, emptied with its temperature readings, so the day still has exactly one shift.

        The backup is a folder with the database copy and the scans' photos, which are moved there rather than
        deleted, so a clear can be undone completely. Retraining copies of disputed frames stay where they are.
        """
        folder = backup_dir / f"clear-{datetime.now():%Y%m%d-%H%M%S}"
        folder.mkdir(parents=True)
        target = folder / "banagrade.db"
        tables = ("sessions", "scans", "scan_disputes")
        source = self.connect()
        copy = sqlite3.connect(target)
        try:
            # One read transaction, so the counts come from the same WAL snapshot that was copied.
            source.execute("BEGIN")
            expected = {table: source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            source.backup(copy)
            source.rollback()
            integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
            actual = {table: copy.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            if integrity != "ok" or actual != expected:
                raise RuntimeError(f"backup verification failed (integrity={integrity}, expected {expected}, got {actual})")
            backed_up = copy.execute("SELECT scan_id, image_refs FROM scans").fetchall()
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            copy.close()
            source.close()
        # Delete only what the backup holds, so a scan saved meanwhile is kept rather than lost.
        ids = [(scan_id,) for scan_id, _ in backed_up]
        with self.connect() as connection:
            connection.executemany("DELETE FROM scan_disputes WHERE scan_id = ?", ids)
            connection.execute("DELETE FROM system_events")
            connection.executemany("DELETE FROM scans WHERE scan_id = ?", ids)
            connection.execute("DELETE FROM telemetry_samples WHERE session_id IN (SELECT id FROM sessions WHERE status = 'open')")
            empty = "SELECT id FROM sessions WHERE status = 'closed' AND NOT EXISTS (SELECT 1 FROM scans WHERE session_id = sessions.id)"
            connection.execute(f"DELETE FROM telemetry_samples WHERE session_id IN ({empty})")
            shifts = connection.execute(f"DELETE FROM sessions WHERE id IN ({empty})").rowcount
        frames = [path for _, refs in backed_up if refs for path in (json.loads(refs) if refs.startswith("[") else [refs])]
        moved = 0
        for frame in map(Path, frames):
            # Only frames the scanner saved; a stray reference elsewhere is left alone.
            if frame.parent == frame_dir and frame.is_file():
                (folder / "frames").mkdir(exist_ok=True)
                shutil.move(frame, folder / "frames" / frame.name)
                moved += 1
        session = self.ensure_active_session()
        return {"backup": str(folder), "scans": expected["scans"], "disputes": expected["scan_disputes"], "frames": moved, "shifts": shifts, "session_id": session["id"]}

    def _event(self, connection: sqlite3.Connection, event_type: str, description: str, scan_id: str | None = None, session_id: str | None = None) -> None:
        connection.execute(
            "INSERT INTO system_events (event_id, occurred_at, event_type, severity, description, scan_id, session_id) VALUES (?, ?, ?, 'info', ?, ?, ?)",
            (str(uuid.uuid4()), now_iso(), event_type, description, scan_id, session_id),
        )

    @staticmethod
    def _check_shift_open(connection: sqlite3.Connection, scan_ids: list[str]) -> None:
        """Raise ShiftClosed if any of the scans is in a closed shift. Run it inside the write's own transaction (after
        BEGIN IMMEDIATE), so a shift that rolls over between page load and click is still caught."""
        closed = connection.execute(
            f"SELECT 1 FROM scans s JOIN sessions ON sessions.id = s.session_id WHERE sessions.status = 'closed' AND s.scan_id IN ({','.join('?' * len(scan_ids))}) LIMIT 1",
            scan_ids,
        ).fetchone()
        if closed:
            raise ShiftClosed("This scan belongs to a closed shift and can no longer be changed")

    def void_scans(self, scan_ids: list[str], reason: str) -> list[str]:
        """Leave scans out of every count, rate and chart without deleting them.

        A voided scan stays in the audit trail, marked with when and why, and can be counted again. Scans that are
        missing or already voided are skipped, so an earlier reason is never overwritten. Returns the ids voided.
        If any scan is in a closed shift, nothing is voided and ShiftClosed is raised.
        """
        voided_at = now_iso()
        done: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_shift_open(connection, list(dict.fromkeys(scan_ids)))
            for scan_id in dict.fromkeys(scan_ids):
                row = connection.execute("SELECT session_id FROM scans WHERE scan_id = ? AND voided_at IS NULL", (scan_id,)).fetchone()
                if row is None:
                    continue
                connection.execute("UPDATE scans SET voided_at = ?, void_reason = ? WHERE scan_id = ?", (voided_at, reason, scan_id))
                self._event(connection, "scan_voided", reason, scan_id, row["session_id"])
                done.append(scan_id)
        return done

    def unvoid_scans(self, scan_ids: list[str]) -> list[str]:
        """Count voided scans again. The void and its reason stay in system_events. Returns the ids restored.

        If any scan is in a closed shift, nothing is restored and ShiftClosed is raised.
        """
        done: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_shift_open(connection, list(dict.fromkeys(scan_ids)))
            for scan_id in dict.fromkeys(scan_ids):
                row = connection.execute("SELECT session_id, void_reason FROM scans WHERE scan_id = ? AND voided_at IS NOT NULL", (scan_id,)).fetchone()
                if row is None:
                    continue
                connection.execute("UPDATE scans SET voided_at = NULL, void_reason = NULL WHERE scan_id = ?", (scan_id,))
                self._event(connection, "scan_unvoided", f"Counted again; had been voided: {row['void_reason']}", scan_id, row["session_id"])
                done.append(scan_id)
        return done

    def scan_disputes(self, scan_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, reason, corrected_grade, original_grade, created_at FROM scan_disputes WHERE scan_id = ? ORDER BY created_at DESC, rowid DESC",
                (scan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_disputes(self, scan_id: str) -> dict[str, Any]:
        """Remove every dispute of a scan and put the grade back to the one the scanner gave."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_shift_open(connection, [scan_id])
            disputes = connection.execute(
                "SELECT original_grade, archived_frames FROM scan_disputes WHERE scan_id = ? ORDER BY created_at, rowid",
                (scan_id,),
            ).fetchall()
            if not disputes:
                raise KeyError(scan_id)
            # Disputes saved before original_grade existed have no model grade; leave final_grade alone then.
            grade = next((row["original_grade"] for row in disputes if row["original_grade"]), None)
            connection.execute("DELETE FROM scan_disputes WHERE scan_id = ?", (scan_id,))
            if grade:
                connection.execute("UPDATE scans SET final_grade = ? WHERE scan_id = ?", (None if grade == "Technical Failure" else grade, scan_id))
            final_grade = connection.execute("SELECT final_grade FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()["final_grade"]
        for frame in {frame for row in disputes for frame in json.loads(row["archived_frames"] or "[]")}:
            Path(frame).unlink(missing_ok=True)
        return {"scan_id": scan_id, "final_grade": final_grade, "deleted_disputes": len(disputes)}

    def disputed_scans(self) -> list[dict[str, Any]]:
        """One row per disputed scan: the model's grade, the latest operator correction, and archived frames."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.scan_id, s.captured_at, s.stage1_status, s.stage1_confidence, s.stage2_confidence,
                       s.pixel_length, s.rejection_reason, s.final_grade,
                       (SELECT original_grade FROM scan_disputes d WHERE d.scan_id = s.scan_id AND original_grade IS NOT NULL ORDER BY created_at, rowid LIMIT 1) AS model_grade,
                       (SELECT corrected_grade FROM scan_disputes d WHERE d.scan_id = s.scan_id AND corrected_grade IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT 1) AS corrected_grade,
                       (SELECT reason FROM scan_disputes d WHERE d.scan_id = s.scan_id ORDER BY created_at DESC, rowid DESC LIMIT 1) AS reason,
                       (SELECT archived_frames FROM scan_disputes d WHERE d.scan_id = s.scan_id ORDER BY created_at DESC, rowid DESC LIMIT 1) AS archived_frames,
                       (SELECT MAX(created_at) FROM scan_disputes d WHERE d.scan_id = s.scan_id) AS disputed_at
                FROM scans s
                WHERE EXISTS (SELECT 1 FROM scan_disputes d WHERE d.scan_id = s.scan_id)
                ORDER BY s.captured_at
                """
            ).fetchall()
        return [{**dict(row), "archived_frames": json.loads(row["archived_frames"] or "[]")} for row in rows]

    def recent_scans_with_disputes(self, limit: int) -> list[dict[str, Any]]:
        """The newest scans for drift checks, with the model's grade restored for disputed scans."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.stage1_status, s.stage1_confidence, s.stage2_detected, s.stage2_confidence,
                       s.final_grade, s.processing_status, s.rejection_reason,
                       (SELECT original_grade FROM scan_disputes d WHERE d.scan_id = s.scan_id AND original_grade IS NOT NULL ORDER BY created_at, rowid LIMIT 1) AS model_grade,
                       (SELECT corrected_grade FROM scan_disputes d WHERE d.scan_id = s.scan_id AND corrected_grade IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT 1) AS corrected_grade,
                       EXISTS (SELECT 1 FROM scan_disputes d WHERE d.scan_id = s.scan_id) AS disputed
                FROM scans s WHERE s.voided_at IS NULL ORDER BY s.captured_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_session(self, notes: str | None = None, name: str | None = None) -> dict[str, Any]:
        """`notes` says how the shift began; `name` is what the operator called it, if anything."""
        with self.connect() as connection:
            return self._insert_session(connection, notes, name, now_iso())

    def _insert_session(self, connection: sqlite3.Connection, notes: str | None, name: str | None, started_at: str) -> dict[str, Any]:
        session = {"id": str(uuid.uuid4()), "started_at": started_at, "status": "open", "notes": notes, "name": (name or "").strip() or None, "boot_id": self.boot_id}
        connection.execute("INSERT INTO sessions (id, started_at, status, notes, name, boot_id) VALUES (?, ?, ?, ?, ?, ?)", tuple(session.values()))
        return session

    def rename_session(self, session_id: str, name: str | None) -> dict[str, Any]:
        """Name the open shift (a batch, say). Nothing starts or ends; a closed shift keeps the name it ended with."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            if row["status"] != "open":
                raise ShiftClosed("This shift has ended and can no longer be renamed")
            connection.execute("UPDATE sessions SET name = ? WHERE id = ?", ((name or "").strip() or None, session_id))
            return dict(connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())

    def close_session(self, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET status = 'closed', ended_at = ? WHERE id = ? AND status = 'open'",
                (now_iso(), session_id),
            )

    def save_scan(self, record: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "scan_id", "session_id", "captured_at", "completed_at", "stage1_status",
            "stage1_confidence", "stage2_detected", "stage2_confidence", "bbox_coords", "pixel_length",
            "calculated_length_cm", "calibration_factor_used", "final_grade",
            "rejection_reason", "processing_status", "inference_time_ms", "stage_timings",
            "image_refs", "model_metadata", "threshold_values", "error_details", "boot_id",
        )
        values = [record.get(field) for field in fields[:-1]] + [self.boot_id]
        for index in (8, 16, 17, 18, 19):
            if values[index] is not None and not isinstance(values[index], str):
                values[index] = json.dumps(values[index], separators=(",", ":"))
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO scans ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                values,
            )
        return record

    def list_scans(self, limit: int = 50, offset: int = 0, session_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE s.session_id = ?" if session_id else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT s.*, EXISTS (SELECT 1 FROM scan_disputes d WHERE d.scan_id = s.scan_id) AS disputed,
                       EXISTS (SELECT 1 FROM sessions WHERE id = s.session_id AND status = 'closed') AS shift_closed,
                       (SELECT original_grade FROM scan_disputes d WHERE d.scan_id = s.scan_id AND original_grade IS NOT NULL ORDER BY created_at, rowid LIMIT 1) AS model_grade,
                       (SELECT reason FROM scan_disputes d WHERE d.scan_id = s.scan_id ORDER BY created_at DESC, rowid DESC LIMIT 1) AS dispute_reason
                FROM scans s {where} ORDER BY s.captured_at DESC LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset) if session_id else (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*, (SELECT COUNT(*) FROM scans WHERE session_id = s.id AND voided_at IS NULL) AS scan_count,
                       (SELECT COUNT(*) FROM scans WHERE session_id = s.id AND voided_at IS NOT NULL) AS voided_count
                FROM sessions s ORDER BY started_at DESC, rowid DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def active_session(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE status = 'open' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def active_session_id(self) -> str | None:
        session = self.active_session()
        return session["id"] if session else None

    @staticmethod
    def _newest_record(connection: sqlite3.Connection) -> datetime | None:
        rows = connection.execute(
            "SELECT MAX(captured_at) FROM scans UNION ALL SELECT MAX(started_at) FROM sessions UNION ALL SELECT MAX(sampled_at) FROM telemetry_samples"
        ).fetchall()
        return max((_parse(value) for (value,) in rows if value), default=None)

    def clock_status(self, now: datetime | None = None) -> dict[str, Any]:
        """Whether the clock can be trusted to tell which day it is (see clock_trusted)."""
        now = now or datetime.now(UTC)
        with self.connect() as connection:
            newest = self._newest_record(connection)
        return {"trusted": clock_trusted(now, newest), "now": now.astimezone(UTC).isoformat(timespec="seconds"), "newest_record": newest.astimezone(UTC).isoformat(timespec="seconds") if newest else None}

    def ensure_active_session(self, notes: str = SHIFT_AT_STARTUP, now: datetime | None = None) -> dict[str, Any]:
        """Today's shift, opened first if needed: there is one shift per calendar day in SHIFT_TIMEZONE.

        An open shift from an earlier day ends at its last scan, or is deleted if it has none. When the clock is behind
        the newest record, the date is not trusted: the open shift carries on instead of rolling over, and a new shift
        is never dated before what is already recorded.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")  # the scanner, the sampler and the API all call this; one rollover at a time
            return self._ensure(connection, notes, now or datetime.now(UTC))

    def _ensure(self, connection: sqlite3.Connection, notes: str, now: datetime) -> dict[str, Any]:
        shifts = connection.execute("SELECT * FROM sessions WHERE status = 'open' ORDER BY started_at DESC, rowid DESC").fetchall()
        if shifts and shift_date(shifts[0]["started_at"]) >= shift_date(now):
            return dict(shifts[0])
        newest = self._newest_record(connection)
        if not clock_trusted(now, newest):
            log.warning("Clock reads %s, behind the newest record at %s; keeping the current shift until the clock is right", now, newest)
            if shifts:
                return dict(shifts[0])
            now = newest
        for shift in shifts:
            self._end_shift(connection, shift["id"])
        return self._insert_session(connection, notes, None, now.astimezone(UTC).isoformat(timespec="seconds"))

    @staticmethod
    def _end_shift(connection: sqlite3.Connection, shift_id: str) -> None:
        """Close a shift at its last scan, or delete it if it has none."""
        last_scan = connection.execute("SELECT MAX(captured_at) FROM scans WHERE session_id = ?", (shift_id,)).fetchone()[0]
        if last_scan:
            connection.execute("UPDATE sessions SET status = 'closed', ended_at = ? WHERE id = ?", (last_scan, shift_id))
        else:
            connection.execute("DELETE FROM telemetry_samples WHERE session_id = ?", (shift_id,))
            connection.execute("UPDATE system_events SET session_id = NULL WHERE session_id = ?", (shift_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (shift_id,))

    def correct_clock(self, jump_s: float, cutoff: datetime, now: datetime | None = None) -> dict[str, int]:
        """Move what this boot recorded up to `cutoff` forward by `jump_s`: the clock was behind by exactly that much.

        Scans and temperature readings that now fall on today go into today's shift; a shift they leave ends at its
        last remaining scan, or is deleted if none is left. Disputes, voids and events keep the times they were given.
        Returns how many scans, shifts and readings were moved.
        """
        moved = {"scans": 0, "sessions": 0, "telemetry_samples": 0}
        if not self.boot_id:
            return moved
        jump = timedelta(seconds=jump_s)
        later = lambda value: (_parse(value) + jump).astimezone(UTC).isoformat(timespec="seconds") if value else value
        records = {"scans": ("scan_id", "captured_at", "completed_at"), "sessions": ("id", "started_at", "ended_at"), "telemetry_samples": ("id", "sampled_at")}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table, (key, *columns) in records.items():
                rows = connection.execute(f"SELECT {key}, {', '.join(columns)} FROM {table} WHERE boot_id = ?", (self.boot_id,)).fetchall()
                behind = [row for row in rows if _parse(row[columns[0]]) <= cutoff]
                connection.executemany(
                    f"UPDATE {table} SET {', '.join(f'{column} = ?' for column in columns)} WHERE {key} = ?",
                    [(*(later(row[column]) for column in columns), row[key]) for row in behind],
                )
                moved[table] = len(behind)
            now = now or datetime.now(UTC)
            today = self._ensure(connection, SHIFT_AT_STARTUP, now)
            left: set[str] = set()
            for table, key, stamp in (("scans", "scan_id", "captured_at"), ("telemetry_samples", "id", "sampled_at")):
                rows = connection.execute(f"SELECT {key}, session_id, {stamp} FROM {table} WHERE boot_id = ? AND session_id IS NOT ?", (self.boot_id, today["id"])).fetchall()
                rehomed = [row for row in rows if shift_date(row[stamp]) == shift_date(now)]
                connection.executemany(f"UPDATE {table} SET session_id = ? WHERE {key} = ?", [(today["id"], row[key]) for row in rehomed])
                left.update(row["session_id"] for row in rehomed if row["session_id"])
            for shift_id in left:
                self._end_shift(connection, shift_id)
        return {"scans": moved["scans"], "shifts": moved["sessions"], "samples": moved["telemetry_samples"]}

    def record_temperature(self, session_id: str, cpu_temperature_c: float, fan_level: int | None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO telemetry_samples (sampled_at, session_id, cpu_temperature_c, fan_level, boot_id) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), session_id, cpu_temperature_c, fan_level, self.boot_id),
            )

    def temperature_summary(self, session_id: str | None = None) -> dict[str, Any] | None:
        """CPU temperature over the minute readings taken while the shift was open, or None if there are none."""
        query = "SELECT AVG(cpu_temperature_c), MAX(cpu_temperature_c), COUNT(*), MIN(sampled_at), MAX(sampled_at) FROM telemetry_samples"
        with self.connect() as connection:
            mean, peak, samples, first, last = connection.execute(
                query + (" WHERE session_id = ?" if session_id else ""), (session_id,) if session_id else ()
            ).fetchone()
        if not samples:
            return None
        return {"mean_c": round(mean, 1), "max_c": peak, "samples": samples, "first_at": first, "last_at": last}

    def _graded_rows(self, session_id: str | None) -> list[sqlite3.Row]:
        query = "SELECT captured_at, final_grade, processing_status, inference_time_ms, voided_at FROM scans"
        params: tuple[Any, ...] = ()
        if session_id:
            query += " WHERE session_id = ?"
            params = (session_id,)
        with self.connect() as connection:
            return connection.execute(query, params).fetchall()

    def analytics_summary(self, session_id: str | None = None) -> dict[str, Any]:
        """Grade counts. Technical failures are excluded from commercial rates (Section 4.4.3); voided scans from everything."""
        every = self._graded_rows(session_id)
        rows = [row for row in every if row["voided_at"] is None]
        class_a = sum(row["final_grade"] == "Class A" for row in rows)
        class_b = sum(row["final_grade"] == "Class B" for row in rows)
        rejected = sum(row["final_grade"] == "Rejected" for row in rows)
        graded = class_a + class_b + rejected
        accepted = class_a + class_b
        latencies = [row["inference_time_ms"] for row in rows if row["inference_time_ms"] is not None and row["processing_status"] == "completed"]
        return {
            "session_id": session_id,
            "total_scans": len(rows),
            "total_completed_scans": graded,
            "class_a_count": class_a,
            "class_b_count": class_b,
            "rejected_count": rejected,
            "technical_failure_count": len(rows) - graded,
            "voided_count": len(every) - len(rows),
            "export_acceptance_rate": round(accepted / graded * 100, 2) if graded else 0,
            "class_a_share_of_accepted": round(class_a / accepted * 100, 2) if accepted else 0,
            "rejection_rate": round(rejected / graded * 100, 2) if graded else 0,
            "average_inference_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "cpu_temperature": self.temperature_summary(session_id),
        }

    def rejection_trend(self, session_id: str | None = None, bucket_minutes: int = 15, utc_offset_minutes: int = 0) -> list[dict[str, Any]]:
        """Rejection rate per time bucket over graded scans, oldest first.

        Buckets follow the viewer's clock (`utc_offset_minutes`, +480 in the Philippines), so a 1-day bucket starts at
        local midnight rather than 08:00. Intervals without a graded scan are left out.
        """
        if bucket_minutes <= 0:
            raise ValueError("bucket_minutes must be positive")
        size = bucket_minutes * 60
        offset = utc_offset_minutes * 60
        buckets: dict[datetime, dict[str, int]] = {}
        for row in self._graded_rows(session_id):
            if row["voided_at"] or row["final_grade"] not in ("Class A", "Class B", "Rejected") or not row["captured_at"]:
                continue
            try:
                captured = datetime.fromisoformat(row["captured_at"])
            except ValueError:
                continue
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            local = int(captured.timestamp()) + offset
            start = datetime.fromtimestamp(local - local % size - offset, UTC)
            bucket = buckets.setdefault(start, {"total": 0, "rejected": 0})
            bucket["total"] += 1
            bucket["rejected"] += row["final_grade"] == "Rejected"
        return [
            {"bucket_start": start.isoformat(timespec="seconds"), "total": value["total"], "rejected": value["rejected"], "rejection_rate": round(value["rejected"] / value["total"] * 100, 2)}
            for start, value in sorted(buckets.items())
        ]

    def latency_stats(self, limit: int = 50) -> float | None:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT inference_time_ms FROM scans WHERE processing_status = 'completed' AND inference_time_ms IS NOT NULL ORDER BY captured_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return round(sum(row[0] for row in rows) / len(rows), 1) if rows else None

    def ping(self) -> bool:
        try:
            with self.connect() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False


DISPUTE_LABEL_FIELDS = (
    "scan_id", "captured_at", "disputed_at", "model_grade", "corrected_grade", "reason", "stage1_status",
    "stage1_confidence", "stage2_confidence", "pixel_length", "rejection_reason", "frame",
)


def disputes_zip(disputes: list[dict[str, Any]], target: Path) -> Path:
    """Write labels.csv and each archived frame under frames/<corrected grade>/. JPEGs are stored, not recompressed."""
    labels = io.StringIO()
    writer = csv.DictWriter(labels, fieldnames=DISPUTE_LABEL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for dispute in disputes:
            folder = (dispute["corrected_grade"] or "unlabelled").replace(" ", "_")
            frame = ""
            for path in map(Path, dispute["archived_frames"]):
                if path.is_file():
                    frame = f"frames/{folder}/{path.name}"
                    archive.write(path, frame)
                    break
            writer.writerow({**dispute, "frame": frame})
        archive.writestr("labels.csv", labels.getvalue())
    return target


def scans_csv(records: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(records[0]) if records else ["scan_id"])
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()