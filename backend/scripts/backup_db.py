"""Back up banagrade.db with SQLite's online backup API, verify the copy, and prune old copies.

Safe while the service is running (WAL mode). Exits non-zero if the copy fails its integrity check
or its row counts differ from the live database, so the systemd timer marks the run as failed.

    python scripts/backup_db.py --db /var/lib/banagrade/banagrade.db --dest /var/lib/banagrade/backups --keep 14
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

TABLES = ("sessions", "scans", "scan_disputes")


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def backup(db: Path, dest: Path, keep: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"banagrade-{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        # One read transaction, so the counts come from the same WAL snapshot that was copied.
        source.execute("BEGIN")
        expected = counts(source)
        source.backup(copy)
        source.rollback()
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        actual = counts(copy)
    finally:
        copy.close()
        source.close()
    if integrity != "ok" or actual != expected:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Backup verification failed: integrity={integrity}, expected {expected}, got {actual}")
    for old in sorted(dest.glob("banagrade-*.db"))[:-keep]:
        old.unlink()
    print(f"{target} ok {actual}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BANAGRADE_DB", "/var/lib/banagrade/banagrade.db")))
    parser.add_argument("--dest", type=Path, default=Path(os.getenv("BANAGRADE_BACKUP_DIR", "/var/lib/banagrade/backups")))
    parser.add_argument("--keep", type=int, default=int(os.getenv("BANAGRADE_BACKUP_KEEP", "14")))
    args = parser.parse_args()
    try:
        backup(args.db, args.dest, max(1, args.keep))
    except (sqlite3.Error, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
