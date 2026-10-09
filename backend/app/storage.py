from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .grading import GradeThresholds


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
    notes TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    captured_at TEXT NOT NULL,
    completed_at TEXT,
    stage1_status TEXT,
    stage1_confidence REAL,
    stage2_detected INTEGER,
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
    error_details TEXT
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
CREATE TABLE IF NOT EXISTS sus_responses (
    survey_id TEXT PRIMARY KEY,
    respondent_id TEXT,
    submitted_at TEXT NOT NULL,
    responses TEXT NOT NULL,
    converted_scores TEXT NOT NULL,
    total_score REAL NOT NULL CHECK(total_score >= 0 AND total_score <= 100)
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
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

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
            connection.execute(
                "INSERT OR IGNORE INTO system_config (id, updated_at) VALUES (1, ?)",
                (now_iso(),),
            )

    def thresholds(self) -> GradeThresholds:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT class_a_min_cm, class_b_min_cm FROM system_config WHERE id = 1"
            ).fetchone()
        return GradeThresholds(row["class_a_min_cm"], row["class_b_min_cm"])

    def create_session(self, notes: str | None = None) -> dict[str, Any]:
        session = {"id": str(uuid.uuid4()), "started_at": now_iso(), "status": "open", "notes": notes}
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, started_at, status, notes) VALUES (?, ?, ?, ?)",
                tuple(session.values()),
            )
        return session

    def close_session(self, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET status = 'closed', ended_at = ? WHERE id = ? AND status = 'open'",
                (now_iso(), session_id),
            )

    def save_scan(self, record: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "scan_id", "session_id", "captured_at", "completed_at", "stage1_status",
            "stage1_confidence", "stage2_detected", "bbox_coords", "pixel_length",
            "calculated_length_cm", "calibration_factor_used", "final_grade",
            "rejection_reason", "processing_status", "inference_time_ms", "stage_timings",
            "image_refs", "model_metadata", "threshold_values", "error_details",
        )
        values = [record.get(field) for field in fields]
        for index in (7, 15, 16, 17, 18):
            if values[index] is not None and not isinstance(values[index], str):
                values[index] = json.dumps(values[index], separators=(",", ":"))
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO scans ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                values,
            )
        return record

    def list_scans(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scans ORDER BY captured_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]

    def analytics_summary(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT final_grade, rejection_reason, calculated_length_cm, inference_time_ms "
                "FROM scans WHERE processing_status = 'completed'"
            ).fetchall()
        total = len(rows)
        class_a = sum(row["final_grade"] == "Class A" for row in rows)
        class_b = sum(row["final_grade"] == "Class B" for row in rows)
        rejected = sum(row["final_grade"] == "Rejected" for row in rows)
        accepted_lengths = [row["calculated_length_cm"] for row in rows if row["final_grade"] in ("Class A", "Class B") and row["calculated_length_cm"] is not None]
        latencies = [row["inference_time_ms"] for row in rows if row["inference_time_ms"] is not None]
        commercial_rejections = sum(row["final_grade"] == "Rejected" for row in rows)
        return {
            "total_completed_scans": total,
            "class_a_count": class_a,
            "class_b_count": class_b,
            "rejected_count": rejected,
            "technical_failure_count": sum(row["final_grade"] is None for row in rows),
            "export_acceptance_rate": round((class_a + class_b) / total * 100, 2) if total else 0,
            "rejection_rate": round(commercial_rejections / total * 100, 2) if total else 0,
            "mean_accepted_length_cm": round(sum(accepted_lengths) / len(accepted_lengths), 2) if accepted_lengths else None,
            "average_inference_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        }


def calculate_sus(responses: list[int]) -> tuple[list[int], float]:
    if len(responses) != 10 or any(response not in range(1, 6) for response in responses):
        raise ValueError("SUS requires exactly ten responses from 1 through 5")
    converted = [response - 1 if index % 2 == 0 else 5 - response for index, response in enumerate(responses)]
    return converted, sum(converted) * 2.5


def scans_csv(records: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(records[0]) if records else ["scan_id"])
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()