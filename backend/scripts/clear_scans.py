"""Delete every scan, dispute and event, for example after a test run, keeping a verified backup with the photos.

The dashboard has no button for this on purpose: anyone on the Wi-Fi can open it and there is no login. To leave
a few scans out of the totals, void them on Recent Scans instead; they stay in the audit trail.

Run it on the Pi as the service user, and type CLEAR when asked:
    sudo -u banagrade /opt/banagrade/.venv/bin/python /opt/banagrade/backend/scripts/clear_scans.py

The backup goes to <backups>/clear-<time>/ with banagrade.db and the scans' photos (moved, not deleted). To undo,
stop the service, copy that banagrade.db back over the live one and the photos back into the frames folder.
Reload any open dashboard afterwards.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.storage import Storage  # noqa: E402


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BANAGRADE_DB", "/var/lib/banagrade/banagrade.db")))
    parser.add_argument("--backups", type=Path, default=Path(os.getenv("BANAGRADE_BACKUP_DIR", "/var/lib/banagrade/backups")))
    parser.add_argument("--frames", type=Path, default=Path(os.getenv("BANAGRADE_FRAME_DIR", "/var/lib/banagrade/frames")))
    parser.add_argument("--yes", action="store_true", help="skip the CLEAR prompt")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"No database at {args.db}", file=sys.stderr)
        return 1
    storage = Storage(args.db)
    storage.initialize()
    shifts = storage.list_sessions()
    total = sum(shift["scan_count"] + shift["voided_count"] for shift in shifts)
    print(f"{args.db}: {plural(total, 'scan')} in {plural(sum(1 for shift in shifts if shift['scan_count'] + shift['voided_count']), 'shift')}.")
    if not args.yes and input("Delete them all? A verified backup with their photos is saved first. Type CLEAR: ").strip() != "CLEAR":
        print("Nothing deleted.")
        return 1
    try:
        result = storage.clear_scans(args.backups, args.frames)
    except (sqlite3.Error, RuntimeError) as error:
        print(f"Nothing deleted: {error}", file=sys.stderr)
        return 1
    print(f"Cleared {plural(result['scans'], 'scan')}, {plural(result['disputes'], 'dispute')} and {plural(result['shifts'], 'shift')}; "
          f"moved {plural(result['frames'], 'photo')} into the backup.")
    print(f"Backup: {result['backup']}. A new shift has started; reload any open dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
