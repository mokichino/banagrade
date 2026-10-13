"""Create mock data for presentations.

Usage (from backend/):
    python scripts/seed_demo.py                     # writes backend/demo.db
    python scripts/seed_demo.py --reset --days 6    # rebuild from scratch
    python scripts/seed_demo.py --live --interval 6 # stream a new mock scan every 6 s

Run the API against the demo database with demo mode on:
    BANAGRADE_DB=demo.db BANAGRADE_DEMO_MODE=true python -m uvicorn main:app --host 0.0.0.0 --port 8000

Mock records are tagged ``"demo": true`` and the dashboard shows a "Demo data" label.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import demo  # noqa: E402
from app.storage import Storage  # noqa: E402


def stream(api: str, interval: float) -> None:
    url = f"{api.rstrip('/')}/api/demo/simulate-scan"
    print(f"Streaming one mock scan every {interval:g}s to {url} (Ctrl+C to stop)", flush=True)
    while True:
        request = urllib.request.Request(url, method="POST", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                scan = json.loads(response.read())
                print(f"  {scan['captured_at']}  {scan.get('final_grade') or 'Technical failure'}", flush=True)
        except Exception as error:  # keep streaming through transient API restarts
            print(f"  request failed: {error}", flush=True)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(BACKEND / "demo.db"), help="target SQLite file (default backend/demo.db)")
    parser.add_argument("--days", type=int, default=6, help="past shifts to generate")
    parser.add_argument("--hours", type=float, default=3.0, help="length of the current open shift so far")
    parser.add_argument("--seed", type=int, default=2026, help="random seed for repeatable data")
    parser.add_argument("--reset", action="store_true", help="delete the target database first")
    parser.add_argument("--force", action="store_true", help="allow writing into banagrade.db")
    parser.add_argument("--live", action="store_true", help="stream mock scans to a running API instead of seeding")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=6.0)
    args = parser.parse_args()

    if args.live:
        stream(args.api, args.interval)
        return

    path = Path(args.db).resolve()
    if path.name == "banagrade.db" and not args.force:
        sys.exit("Refusing to put mock data into banagrade.db. Use the default demo.db, or pass --force.")
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
    storage = Storage(path)
    storage.initialize()
    counts = demo.seed(storage, days=args.days, seed_value=args.seed, current_shift_hours=args.hours)
    summary = storage.analytics_summary(storage.active_session_id())
    print(f"Wrote {counts['scans']} mock scans in {counts['sessions']} shifts ({counts['disputes']} disputes) to {path}", flush=True)
    print(f"Current shift: {summary['total_scans']} scans · A {summary['class_a_count']} · B {summary['class_b_count']} · rejected {summary['rejected_count']} ({summary['rejection_rate']}%)", flush=True)


if __name__ == "__main__":
    main()
