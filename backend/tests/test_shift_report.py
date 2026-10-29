import importlib.util
from pathlib import Path

from app.storage import Storage

spec = importlib.util.spec_from_file_location("shift_report", Path(__file__).resolve().parents[1] / "scripts" / "shift_report.py")
shift_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shift_report)


def _db(tmp_path: Path) -> tuple[Path, str]:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    session = storage.ensure_active_session()
    for index, grade in enumerate(["Class A", "Class B", "Rejected", None]):
        storage.save_scan({
            "scan_id": f"s{index}", "session_id": session["id"], "captured_at": f"2026-10-25T{8 + index:02d}:00:00+00:00",
            "final_grade": grade, "processing_status": "completed" if grade else "failed", "inference_time_ms": 900.0 + index * 100,
            "stage_timings": {"stage1_ms": 40.0, "stage2_ms": 300.0 if grade in ("Class A", "Class B") else None},
        })
    return storage.path, session["id"]


def test_report_prints_section_4_7_numbers(tmp_path, capsys) -> None:
    db, session = _db(tmp_path)
    telemetry = tmp_path / "t.csv"
    telemetry.write_text("sampled_at,cpu_temperature_c,fan_level,service_uptime_s,average_latency_ms\n"
                         "a,50.0,1,60,\nb,54.0,1,120,\nc,52.0,1,30,\n")
    assert shift_report.report(db, None, telemetry, api=None) == 0
    out = capsys.readouterr().out
    assert f"Shift {session}" in out
    assert "Scans: 4 · Class A 1 · Class B 1 · Rejected 1 · technical failures 1" in out
    assert "3.00 h between first and last scan" in out
    assert "Stage 2 latency: mean 300 ms" in out
    assert "Under the 2 s target: 3 / 3" in out
    assert "CPU temperature: mean 52.0 °C · max 54.0 °C over 3 samples" in out
    assert "Service restarts during sampling: 1" in out


def test_report_reads_cpu_temperature_the_service_recorded(tmp_path, capsys) -> None:
    db, session = _db(tmp_path)
    storage = Storage(db)
    for reading in (49.0, 53.0):
        storage.record_temperature(session, reading, 0)
    assert shift_report.report(db, None, None, api=None) == 0
    assert "CPU temperature: mean 51.0 °C · max 53.0 °C over 2 samples" in capsys.readouterr().out


def test_reconciliation_fails_when_dashboard_disagrees(tmp_path, monkeypatch, capsys) -> None:
    db, _ = _db(tmp_path)
    good = {"total_scans": 4, "class_a_count": 1, "class_b_count": 1, "rejected_count": 1, "technical_failure_count": 1, "voided_count": 0}
    monkeypatch.setattr(shift_report, "fetch", lambda api, path: good)
    assert shift_report.report(db, None, None, api="http://pi") == 0
    monkeypatch.setattr(shift_report, "fetch", lambda api, path: {**good, "class_a_count": 2})
    assert shift_report.report(db, None, None, api="http://pi") == 1
    assert "RECONCILIATION FAILED" in capsys.readouterr().out


def test_report_leaves_voided_scans_out_like_the_dashboard(tmp_path, monkeypatch, capsys) -> None:
    db, session = _db(tmp_path)
    storage = Storage(db)
    storage.void_scans(["s0"], "Duplicate scan of the same bunch")
    summary = storage.analytics_summary(session)
    monkeypatch.setattr(shift_report, "fetch", lambda api, path: summary)
    assert shift_report.report(db, None, None, api="http://pi") == 0
    out = capsys.readouterr().out
    assert "Scans: 3 · Class A 0 · Class B 1 · Rejected 1 · technical failures 1 · 1 voided, not counted" in out
    assert "Dashboard totals match SQLite." in out
