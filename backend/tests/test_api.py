import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.storage import now_iso

pytest.importorskip("httpx")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BANAGRADE_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("BANAGRADE_ENABLE_PIPELINE", "false")
    monkeypatch.setenv("BANAGRADE_ENABLE_MODEL_INFERENCE", "false")
    import importlib

    import app.api as api

    api = importlib.reload(api)
    from fastapi.testclient import TestClient

    with TestClient(api.app) as test_client:
        yield test_client, api


def test_status_reports_disabled_pipeline_without_fabrication(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/system/status").json()
    assert body["pipeline"]["state"] == "DISABLED"
    assert body["pipeline"]["camera"]["available"] is False
    assert body["pipeline"]["camera"]["resolution"] is None
    assert body["pipeline"]["led"]["state"] == "error"
    assert body["pipeline"]["preprocessing"].startswith("Raw RGB")  # Stage 1 mask is off by default
    assert [m["label"] for m in body["models"]["models"]] == ["stage1_best.pt", "stage2_best.pt", "best.pt", "yolo11n.pt"]
    assert test_client.get("/api/camera/preview.mjpg").status_code == 503
    assert test_client.post("/api/camera/alignment").status_code == 503


def test_telemetry_and_shift_scoped_analytics(client) -> None:
    test_client, api = client
    telemetry = test_client.get("/api/system/telemetry").json()
    assert telemetry["database_connected"] is True
    assert telemetry["latency_target_ms"] == 2000.0
    session = test_client.get("/api/sessions/active").json()["session"]
    api.storage.save_scan({"scan_id": "s1", "session_id": session["id"], "captured_at": "2026-10-13T08:00:00+00:00", "final_grade": "Rejected", "processing_status": "completed"})
    assert test_client.get("/api/analytics/summary?session=active").json()["rejected_count"] == 1
    trend = test_client.get("/api/analytics/trend?session=active&bucket_minutes=30").json()
    assert trend["items"][0]["rejection_rate"] == 100.0
    daily = test_client.get("/api/analytics/trend?session=active&bucket_minutes=1440&utc_offset_minutes=480").json()
    assert daily["items"][0]["bucket_start"] == "2026-10-12T16:00:00+00:00"
    assert test_client.get("/api/analytics/trend?utc_offset_minutes=900").status_code == 422
    # The next day's shift opens on its own; yesterday's stays viewable by its id.
    api.storage.close_session(session["id"])
    new = test_client.get("/api/sessions/active").json()["session"]
    assert new["id"] != session["id"]
    assert test_client.patch(f"/api/sessions/{new['id']}", json={"name": "afternoon"}).json()["name"] == "afternoon"
    assert test_client.get("/api/analytics/summary?session=active").json()["total_scans"] == 0

    assert [scan["scan_id"] for scan in test_client.get(f"/api/inspection/scans?session={session['id']}").json()["items"]] == ["s1"]
    assert test_client.get("/api/inspection/scans?session=active").json()["items"] == []
    assert test_client.get(f"/api/analytics/summary?session={session['id']}").json()["rejected_count"] == 1
    assert "s1" in test_client.get(f"/api/exports/scans.csv?session={session['id']}").text
    assert "s1" not in test_client.get("/api/exports/scans.csv?session=active").text
    shifts = test_client.get("/api/sessions").json()["items"]
    assert [(shift["name"], shift["scan_count"]) for shift in shifts][0] == ("afternoon", 0)


def test_shifts_are_automatic_and_report_the_clock(client) -> None:
    test_client, api = client
    assert test_client.post("/api/sessions", json={"name": "x"}).status_code == 405
    session = test_client.get("/api/sessions/active").json()["session"]
    assert test_client.post(f"/api/sessions/{session['id']}/close").status_code == 405
    body = test_client.get("/api/sessions").json()
    assert [shift["id"] for shift in body["items"]] == [session["id"]]
    assert body["clock"]["trusted"] is True and "synchronized" in body["clock"]
    assert test_client.get("/api/system/status").json()["clock"]["trusted"] is True
    assert test_client.patch("/api/sessions/missing", json={"name": "x"}).status_code == 404

    # A record from later than the clock reads means the clock went back.
    api.storage.save_scan({"scan_id": "future", "session_id": session["id"], "captured_at": "2099-01-01T00:00:00+00:00", "final_grade": "Class A", "processing_status": "completed"})
    assert test_client.get("/api/sessions").json()["clock"]["trusted"] is False


def test_closed_shift_scans_are_read_only(client, tmp_path, monkeypatch) -> None:
    test_client, api = client
    monkeypatch.setenv("BANAGRADE_RETRAIN_DIR", str(tmp_path / "retrain"))
    old = test_client.get("/api/sessions/active").json()["session"]
    for scan_id in ("a", "v"):
        api.storage.save_scan({"scan_id": scan_id, "session_id": old["id"], "captured_at": "2026-10-27T08:00:00+00:00", "final_grade": "Class A", "processing_status": "completed"})
    assert test_client.post("/api/inspection/scans/a/dispute", json={"reason": "small", "corrected_grade": "Class B"}).status_code == 201
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["v"], "reason": "Test run"}).status_code == 200
    api.storage.close_session(old["id"])
    today = test_client.get("/api/sessions/active").json()["session"]
    api.storage.save_scan({"scan_id": "n", "session_id": today["id"], "captured_at": now_iso(), "final_grade": "Class A", "processing_status": "completed"})

    message = "This scan belongs to a closed shift and can no longer be changed"
    for method, path, body in (
        ("post", "/api/inspection/scans/a/dispute", {"reason": "late", "corrected_grade": "Rejected"}),
        ("delete", "/api/inspection/scans/a/disputes", None),
        ("post", "/api/inspection/scans/void", {"scan_ids": ["n", "a"], "reason": "Test run"}),
        ("post", "/api/inspection/scans/unvoid", {"scan_ids": ["v"]}),
    ):
        response = test_client.request(method.upper(), path, json=body)
        assert (response.status_code, response.json()["detail"]) == (409, message), path
    assert test_client.patch(f"/api/sessions/{old['id']}", json={"name": "x"}).status_code == 409
    scans = {scan["scan_id"]: scan for scan in test_client.get("/api/inspection/scans").json()["items"]}
    assert scans["n"]["voided_at"] is None and scans["a"]["final_grade"] == "Class B" and scans["v"]["voided_at"]
    assert (scans["n"]["shift_closed"], scans["a"]["shift_closed"]) == (0, 1)
    # Viewing and exporting a closed shift still work; today's scans stay editable.
    assert "a" in test_client.get(f"/api/exports/scans.csv?session={old['id']}").text
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["n"], "reason": "Test run"}).json()["voided"] == 1


def test_a_dashboards_time_sets_the_clock_only_forward_and_without_internet_time(client, monkeypatch) -> None:
    test_client, api = client
    set_to: list[float] = []
    monkeypatch.setattr(api, "set_clock", set_to.append)
    offer = lambda ahead_s: test_client.post("/api/system/clock", json={"now_ms": (time.time() + ahead_s) * 1000})

    monkeypatch.setattr(api, "time_synchronized", lambda: True)  # internet time wins
    assert offer(3600).json()["set"] is False
    monkeypatch.setattr(api, "time_synchronized", lambda: None)  # not a systemd host, e.g. a laptop
    assert offer(3600).json()["set"] is False
    monkeypatch.setattr(api, "time_synchronized", lambda: False)
    assert offer(30).json()["set"] is False  # close enough
    assert offer(-3600).json()["set"] is False  # never back
    assert set_to == []

    cutoff = datetime.now(UTC)
    corrections = []
    monkeypatch.setattr(api, "clock_watch", SimpleNamespace(check=lambda: (3600.0, cutoff)))
    monkeypatch.setattr(api.storage, "correct_clock", lambda jump, at: corrections.append((jump, at)) or {"scans": 2, "shifts": 0, "samples": 1})
    body = offer(3600).json()
    assert (body["set"], body["moved"]) == (True, {"scans": 2, "shifts": 0, "samples": 1})
    assert abs(set_to[0] - (time.time() + 3600)) < 5 and corrections == [(3600.0, cutoff)]
    assert test_client.get("/api/system/status").json()["clock"]["set_by_dashboard_at"]

    def refuse(_: float) -> None:
        raise PermissionError

    monkeypatch.setattr(api, "set_clock", refuse)
    assert offer(3600).status_code == 403


def test_temperature_is_sampled_into_todays_shift(client, monkeypatch) -> None:
    _, api = client
    from app import telemetry

    monkeypatch.setattr(telemetry, "cpu_temperature_c", lambda: 47.5)
    session = api.storage.active_session()
    assert telemetry.sample_temperature(api.storage) is True
    monkeypatch.setattr(telemetry, "cpu_temperature_c", lambda: None)  # off the Pi
    assert telemetry.sample_temperature(api.storage) is False
    assert api.storage.temperature_summary()["samples"] == 1
    assert api.storage.temperature_summary(session["id"])["mean_c"] == 47.5


def test_serves_built_dashboard_without_shadowing_api(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Banagrade</title>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setenv("BANAGRADE_FRONTEND_DIST", str(dist))
    monkeypatch.setenv("BANAGRADE_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("BANAGRADE_ENABLE_PIPELINE", "false")
    monkeypatch.setenv("BANAGRADE_ENABLE_MODEL_INFERENCE", "false")
    import importlib

    import app.api as api

    api = importlib.reload(api)
    from fastapi.testclient import TestClient

    with TestClient(api.app) as test_client:
        assert "Banagrade" in test_client.get("/").text
        assert test_client.get("/assets/app.js").status_code == 200
        assert test_client.get("/api/health").json()["status"] == "ok"
        with test_client.websocket_connect("/ws/live") as socket:
            assert socket.receive_json()["event_type"] == "system_status"


def test_presence_model_can_be_disabled(monkeypatch) -> None:
    from app.model_inference import UltralyticsInference

    monkeypatch.setenv("BANAGRADE_PRESENCE_MODEL", "")
    inference = UltralyticsInference.from_environment()
    assert inference.presence_path is None
    assert [m["key"] for m in inference.status()["models"]] == ["stage1", "stage2", "objects"]


def test_drift_endpoint_reports_insufficient_data_on_empty_database(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/system/drift").json()
    assert body["status"] == "insufficient_data"
    assert len(body["indicators"]) == 6


def test_dispute_export_zip(client, tmp_path, monkeypatch) -> None:
    import io
    import zipfile

    test_client, api = client
    monkeypatch.setenv("BANAGRADE_RETRAIN_DIR", str(tmp_path / "retrain"))
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8")
    api.storage.save_scan({"scan_id": "z1", "captured_at": "2026-10-25T08:00:00+00:00", "final_grade": "Class A", "processing_status": "completed", "image_refs": [str(frame)]})
    dispute = test_client.post("/api/inspection/scans/z1/dispute", json={"corrected_grade": "Class B"}).json()
    assert dispute["original_grade"] == "Class A"

    response = test_client.get("/api/exports/disputes.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["frames/Class_B/z1_f.jpg", "labels.csv"]

    [listed] = test_client.get("/api/inspection/scans/z1/disputes").json()["items"]
    assert listed["id"] == dispute["id"]
    deleted = test_client.delete("/api/inspection/scans/z1/disputes")
    assert deleted.json()["final_grade"] == "Class A"
    assert test_client.delete("/api/inspection/scans/z1/disputes").status_code == 404


def test_dispute_refuses_the_recorded_grade(client) -> None:
    test_client, api = client
    api.storage.save_scan({"scan_id": "n1", "captured_at": "2026-10-25T08:00:00+00:00", "final_grade": None, "processing_status": "failed"})
    response = test_client.post("/api/inspection/scans/n1/dispute", json={"corrected_grade": "Technical Failure", "reason": "same"})
    assert response.status_code == 400
    assert "already recorded as Technical Failure" in response.json()["detail"]
    assert test_client.post("/api/inspection/scans/missing/dispute", json={"corrected_grade": "Class A"}).status_code == 404
    assert api.storage.scan_disputes("n1") == []


def test_scans_are_voided_not_deleted(client) -> None:
    test_client, api = client
    for scan_id, grade in (("v1", "Class A"), ("v2", "Rejected")):
        api.storage.save_scan({"scan_id": scan_id, "captured_at": "2026-10-25T08:00:00+00:00", "final_grade": grade, "processing_status": "completed"})
    # The dashboard can no longer delete scans at all.
    assert test_client.post("/api/inspection/scans/clear", json={"confirm": "CLEAR"}).status_code in (404, 405)

    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["v1"], "reason": "   "}).status_code == 422
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": [], "reason": "Test run"}).status_code == 422
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["nope"], "reason": "Test run"}).status_code == 404
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["v1", "v1"], "reason": "  Test object, not a bunch "}).json() == {"voided": 1, "skipped": 0}
    assert test_client.post("/api/inspection/scans/void", json={"scan_ids": ["v1", "v2"], "reason": "Test run"}).json() == {"voided": 1, "skipped": 1}
    assert api.storage.get_scan("v1")["void_reason"] == "Test object, not a bunch"
    summary = test_client.get("/api/analytics/summary").json()
    assert (summary["total_scans"], summary["voided_count"]) == (0, 2)
    assert len(test_client.get("/api/inspection/scans").json()["items"]) == 2

    refused = test_client.post("/api/inspection/scans/v1/dispute", json={"corrected_grade": "Class B", "reason": "Middle finger 11 cm"})
    assert refused.status_code == 409 and "Count it again" in refused.json()["detail"]
    assert test_client.post("/api/inspection/scans/unvoid", json={"scan_ids": ["v1"]}).json() == {"restored": 1, "skipped": 0}
    assert test_client.get("/api/analytics/summary").json()["total_scans"] == 1
    assert test_client.post("/api/inspection/scans/v1/dispute", json={"corrected_grade": "Class B", "reason": "Middle finger 11 cm"}).status_code == 201


def test_csv_export_round_trips_every_stored_value(client) -> None:
    import csv
    import io

    test_client, api = client
    tricky = 'Bruise, "soft" spot\nnear the crown'
    api.storage.save_scan({"scan_id": "c1", "captured_at": "2026-10-25T08:00:00+00:00", "final_grade": "Class A", "processing_status": "completed",
                           "bbox_coords": [1.5, 2.0, 2900.25, 900.0], "threshold_values": {"width_threshold_px": 2730.07}, "error_details": tricky})
    api.storage.save_scan({"scan_id": "c2", "captured_at": "2026-10-25T08:01:00+00:00", "final_grade": None, "processing_status": "failed", "rejection_reason": "LOW_CONFIDENCE"})
    rows = list(csv.DictReader(io.StringIO(test_client.get("/api/exports/scans.csv").text)))
    stored = {scan["scan_id"]: scan for scan in api.storage.list_scans(100, 0)}
    assert len(rows) == len(stored) == 2
    for row in rows:
        assert row == {key: "" if value is None else str(value) for key, value in stored[row["scan_id"]].items()}
    assert next(row for row in rows if row["scan_id"] == "c1")["error_details"] == tricky


def fake_logind(monkeypatch, api, answer):
    calls = []

    async def run(*args):
        calls.append(args)
        return (0, f's "{answer}"') if args[0] == "busctl" else (0, "")

    monkeypatch.setattr(api.power, "_run", run)
    monkeypatch.setattr(api.power, "DELAY_S", 0)
    return calls


def test_power_is_refused_until_polkit_allows_it(client, monkeypatch) -> None:
    test_client, api = client
    calls = fake_logind(monkeypatch, api, "challenge")
    assert test_client.get("/api/system/status").json()["power"]["reboot"] == {"allowed": False, "permission": "challenge"}
    response = test_client.post("/api/system/power", json={"action": "reboot"})
    assert response.status_code == 403
    assert not [call for call in calls if call[0] == "systemctl"]


def test_power_runs_systemctl_when_allowed(client, monkeypatch) -> None:
    test_client, api = client
    calls = fake_logind(monkeypatch, api, "yes")
    assert test_client.post("/api/system/power", json={"action": "shutdown"}).status_code == 202
    for _ in range(50):
        if ("systemctl", "poweroff", "-i") in calls:
            break
        time.sleep(0.01)
    assert ("systemctl", "poweroff", "-i") in calls
    assert test_client.post("/api/system/power", json={"action": "halt"}).status_code == 422
