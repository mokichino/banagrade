import os
import time

import pytest

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
    new = test_client.post("/api/sessions", json={"notes": "afternoon"}).json()
    assert test_client.get("/api/analytics/summary?session=active").json()["total_scans"] == 0
    assert test_client.get("/api/sessions/active").json()["session"]["id"] == new["id"]


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
