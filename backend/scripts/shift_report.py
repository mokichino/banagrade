"""Thesis §4.7 numbers for one shift, and a reconciliation of the dashboard totals against SQLite.

During the run, sample telemetry once a minute (Ctrl+C to stop):
    python scripts/shift_report.py sample --out shift_telemetry.csv

After the run (as a user that can read the database, e.g. sudo -u banagrade):
    python scripts/shift_report.py report --db /var/lib/banagrade/banagrade.db --telemetry shift_telemetry.csv

`report` uses the open shift, or the newest one when none is open; pass --session to choose.
It exits non-zero if the dashboard API totals differ from a direct count in SQLite.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

GRADES = ("Class A", "Class B", "Rejected")


def fetch(api: str, path: str) -> dict:
    with urllib.request.urlopen(f"{api}{path}", timeout=10) as response:
        return json.load(response)


def sample(api: str, out: Path, interval: float) -> None:
    fields = ("sampled_at", "cpu_temperature_c", "fan_level", "service_uptime_s", "average_latency_ms")
    new = not out.exists()
    with out.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new:
            writer.writeheader()
        print(f"Sampling {api}/api/system/telemetry every {interval:.0f} s into {out}. Ctrl+C to stop.")
        try:
            while True:
                try:
                    t = fetch(api, "/api/system/telemetry")
                    writer.writerow({
                        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "cpu_temperature_c": t.get("cpu_temperature_c"),
                        "fan_level": (t.get("fan") or {}).get("level"),
                        "service_uptime_s": t.get("service_uptime_s"),
                        "average_latency_ms": t.get("average_latency_ms"),
                    })
                    handle.flush()
                except OSError as error:  # a Wi-Fi drop must not end the run
                    print(f"{datetime.now():%H:%M:%S} telemetry unavailable: {error}", file=sys.stderr)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("Stopped.")


def _pick_session(connection: sqlite3.Connection, session: str | None) -> sqlite3.Row:
    if session:
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session,)).fetchone()
    else:
        row = connection.execute("SELECT * FROM sessions ORDER BY status = 'open' DESC, started_at DESC LIMIT 1").fetchone()
    if row is None:
        raise SystemExit("No such shift in the database")
    return row


def _stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    values = sorted(values)
    p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
    return f"mean {statistics.mean(values):.0f} ms · median {statistics.median(values):.0f} ms · p95 {p95:.0f} ms · max {values[-1]:.0f} ms (n={len(values)})"


def report(db: Path, session: str | None, telemetry: Path | None, api: str | None) -> int:
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    shift = _pick_session(connection, session)
    scans = connection.execute("SELECT * FROM scans WHERE session_id = ? ORDER BY captured_at", (shift["id"],)).fetchall()

    counts = {grade: sum(scan["final_grade"] == grade for scan in scans) for grade in GRADES}
    failures = len(scans) - sum(counts.values())
    completed = [scan for scan in scans if scan["processing_status"] == "completed" and scan["inference_time_ms"] is not None]
    timings = [json.loads(scan["stage_timings"]) for scan in completed if scan["stage_timings"]]
    duration = "n/a"
    if len(scans) > 1:
        span = datetime.fromisoformat(scans[-1]["captured_at"]) - datetime.fromisoformat(scans[0]["captured_at"])
        duration = f"{span.total_seconds() / 3600:.2f} h between first and last scan"

    print(f"Shift {shift['id']} ({shift['status']}), started {shift['started_at']}, ended {shift['ended_at'] or 'still open'}")
    print(f"Scans: {len(scans)} · Class A {counts['Class A']} · Class B {counts['Class B']} · Rejected {counts['Rejected']} · technical failures {failures}")
    print(f"Sustained run: {duration}")
    print(f"End-to-end latency: {_stats([scan['inference_time_ms'] for scan in completed])}")
    print(f"Stage 1 latency: {_stats([t['stage1_ms'] for t in timings if t.get('stage1_ms') is not None])}")
    print(f"Stage 2 latency: {_stats([t['stage2_ms'] for t in timings if t.get('stage2_ms') is not None])}")
    within = sum(scan["inference_time_ms"] < 2000 for scan in completed)
    print(f"Under the 2 s target: {within} / {len(completed)}")

    if telemetry and telemetry.exists():
        rows = list(csv.DictReader(telemetry.open()))
        temps = [float(row["cpu_temperature_c"]) for row in rows if row["cpu_temperature_c"]]
        if temps:
            print(f"CPU temperature: mean {statistics.mean(temps):.1f} °C · max {max(temps):.1f} °C over {len(temps)} samples ({rows[0]['sampled_at']} to {rows[-1]['sampled_at']})")
        uptimes = [float(row["service_uptime_s"]) for row in rows if row["service_uptime_s"]]
        restarts = sum(later < earlier for earlier, later in zip(uptimes, uptimes[1:]))
        print(f"Service restarts during sampling: {restarts}")

    if not api:
        return 0
    summary = fetch(api, f"/api/analytics/summary?session={shift['id']}")
    expected = {"total_scans": len(scans), "class_a_count": counts["Class A"], "class_b_count": counts["Class B"],
                "rejected_count": counts["Rejected"], "technical_failure_count": failures}
    mismatches = {key: (summary.get(key), value) for key, value in expected.items() if summary.get(key) != value}
    if mismatches:
        print(f"RECONCILIATION FAILED (dashboard, SQLite): {mismatches}")
        return 1
    print("Dashboard totals match SQLite.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    sub = parser.add_subparsers(dest="command", required=True)
    sampler = sub.add_parser("sample")
    sampler.add_argument("--out", type=Path, default=Path("shift_telemetry.csv"))
    sampler.add_argument("--interval", type=float, default=60)
    reporter = sub.add_parser("report")
    reporter.add_argument("--db", type=Path, default=Path("/var/lib/banagrade/banagrade.db"))
    reporter.add_argument("--session")
    reporter.add_argument("--telemetry", type=Path)
    reporter.add_argument("--no-api", action="store_true", help="skip the dashboard reconciliation")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.api, args.out, args.interval)
        return 0
    return report(args.db, args.session, args.telemetry, None if args.no_api else args.api)


if __name__ == "__main__":
    sys.exit(main())
