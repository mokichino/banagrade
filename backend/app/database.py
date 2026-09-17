from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "banagrade.db"
MOCK_DATA_PATH = BASE_DIR / "mock_scans.json"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                stage1 TEXT NOT NULL,
                stage2 TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                grade TEXT NOT NULL,
                quality_index INTEGER NOT NULL,
                line TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shift_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                is_active INTEGER NOT NULL DEFAULT 1,
                workers INTEGER NOT NULL DEFAULT 12,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL UNIQUE,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0:
            records = json.loads(MOCK_DATA_PATH.read_text(encoding="utf-8"))
            connection.executemany(
                "INSERT INTO scans VALUES (:id, :captured_at, :stage1, :stage2, :confidence, :grade, :quality_index, :line)",
                records,
            )
        if connection.execute("SELECT COUNT(*) FROM shift_settings").fetchone()[0] == 0:
            connection.execute(
                "INSERT INTO shift_settings (id, is_active, workers, updated_at) VALUES (1, 1, 12, ?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )


def row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["timestamp"] = datetime.fromisoformat(item.pop("captured_at")).strftime("%H:%M:%S")
    item["qualityIndex"] = item.pop("quality_index")
    item["capturedAt"] = row["captured_at"]
    return item


def get_scans(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    query = "SELECT * FROM scans"
    values: list[str] = []
    clauses = []
    if start_date:
        clauses.append("date(captured_at) >= date(?)")
        values.append(start_date)
    if end_date:
        clauses.append("date(captured_at) <= date(?)")
        values.append(end_date)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY captured_at DESC"
    with get_connection() as connection:
        records = []
        for row in connection.execute(query, values).fetchall():
            item = row_to_dict(row)
            ticket = connection.execute(
                "SELECT note, created_at FROM scan_tickets WHERE scan_id = ?",
                (item["id"],),
            ).fetchone()
            item["ticketed"] = ticket is not None
            item["ticketNote"] = ticket["note"] if ticket else None
            item["ticketedAt"] = ticket["created_at"] if ticket else None
            records.append(item)
        return records


def create_scan_ticket(scan_id: str, note: str) -> dict:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO scan_tickets (scan_id, note, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(scan_id) DO UPDATE SET note = excluded.note, created_at = excluded.created_at",
            (scan_id, note, created_at),
        )
    return {"scanId": scan_id, "note": note, "createdAt": created_at}


def get_shift() -> dict:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM shift_settings WHERE id = 1").fetchone()
    return {"isActive": bool(row["is_active"]), "workers": row["workers"], "label": "Shift active" if row["is_active"] else "Shift inactive"}


def update_shift(is_active: bool, workers: int) -> dict:
    with get_connection() as connection:
        connection.execute(
            "UPDATE shift_settings SET is_active = ?, workers = ?, updated_at = ? WHERE id = 1",
            (int(is_active), workers, datetime.now().isoformat(timespec="seconds")),
        )
    return get_shift()
