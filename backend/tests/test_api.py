import os

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
    assert {m["label"] for m in body["models"]["models"]} == {"stage1_best.pt", "stage2_best.pt"}
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
