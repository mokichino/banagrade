import importlib.util
import sqlite3
from pathlib import Path

import pytest

from app.storage import Storage, now_iso

spec = importlib.util.spec_from_file_location("backup_db", Path(__file__).resolve().parents[1] / "scripts" / "backup_db.py")
backup_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_db)


def _db(tmp_path: Path) -> Path:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    session = storage.ensure_active_session()
    for index in range(3):
        storage.save_scan({"scan_id": f"s{index}", "session_id": session["id"], "captured_at": now_iso(), "final_grade": "Class A", "processing_status": "completed"})
    storage.dispute_scan("s0", "check", "Class B", tmp_path / "retrain")
    return storage.path


def test_backup_copies_and_verifies_live_database(tmp_path) -> None:
    target = backup_db.backup(_db(tmp_path), tmp_path / "backups", keep=14)
    copy = sqlite3.connect(target)
    assert backup_db.counts(copy) == {"sessions": 1, "scans": 3, "scan_disputes": 1}
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_keeps_only_the_newest_copies(tmp_path) -> None:
    dest = tmp_path / "backups"
    dest.mkdir()
    for day in range(1, 6):
        (dest / f"banagrade-2026010{day}-000000.db").write_bytes(b"")
    backup_db.backup(_db(tmp_path), dest, keep=2)
    names = sorted(path.name for path in dest.glob("banagrade-*.db"))
    assert len(names) == 2 and names[0] == "banagrade-20260105-000000.db"


def test_pruning_never_touches_safety_copies(tmp_path) -> None:
    dest = tmp_path / "backups"
    dest.mkdir()
    # Fourteen hand-made safety copies sort after the nightly ones; they used to fill every slot.
    safety = [dest / f"banagrade-before-step{index:02d}-20261027-000000.db" for index in range(14)]
    for path in safety:
        path.write_bytes(b"")
    (dest / "banagrade-20261026-233000.db").write_bytes(b"")
    target = backup_db.backup(_db(tmp_path), dest, keep=2)
    assert target.exists() and (dest / "banagrade-20261026-233000.db").exists()
    assert all(path.exists() for path in safety)


def test_backup_of_missing_database_fails(tmp_path) -> None:
    with pytest.raises(sqlite3.Error):
        backup_db.backup(tmp_path / "missing.db", tmp_path / "backups", keep=2)
