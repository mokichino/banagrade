import random
from datetime import UTC, datetime

import pytest

from app import demo
from app.grading import DEFAULT_WIDTH_THRESHOLD_PX
from app.storage import Storage


def test_mock_scans_follow_the_real_grading_rule() -> None:
    rng = random.Random(1)
    for _ in range(500):
        scan = demo.generate_scan(rng, datetime.now(UTC), None)
        assert scan["model_metadata"]["demo"] is True
        if scan.get("final_grade") == "Class A":
            assert scan["pixel_length"] >= DEFAULT_WIDTH_THRESHOLD_PX
        elif scan.get("final_grade") == "Class B":
            assert scan["pixel_length"] < DEFAULT_WIDTH_THRESHOLD_PX
        elif scan.get("final_grade") == "Rejected":
            assert scan["stage1_status"] == "Unhealthy" and scan.get("pixel_length") is None
        else:
            assert scan["processing_status"] == "failed"


def test_seed_creates_tagged_shifts(tmp_path) -> None:
    storage = Storage(tmp_path / "demo.db")
    storage.initialize()
    counts = demo.seed(storage, days=2, current_shift_hours=1)
    assert counts["sessions"] == 3 and counts["scans"] > 100
    assert demo.has_demo_data(storage)
    summary = storage.analytics_summary(storage.active_session_id())
    assert 0 < summary["rejection_rate"] < 50
    assert summary["average_inference_latency_ms"] < 2000


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
        yield test_client


def test_led_test_steps_through_every_state(client, monkeypatch) -> None:
    monkeypatch.delenv("BANAGRADE_DEMO_MODE", raising=False)  # LED test works without demo mode
    body = client.post("/api/demo/led-test?step_scale=0").json()
    assert body["states"] == ["ready", "capture", "class_a", "class_b", "rejected", "booting", "error"]
    assert client.get("/api/system/status").json()["pipeline"]["led"]["state"] == "ready"


def test_simulate_endpoint_requires_demo_mode(client, monkeypatch) -> None:
    monkeypatch.delenv("BANAGRADE_DEMO_MODE", raising=False)
    assert client.post("/api/demo/simulate-scan").status_code == 404
    assert client.get("/api/system/status").json()["demo"] == {"mode": False, "data_present": False}
    monkeypatch.setenv("BANAGRADE_DEMO_MODE", "true")
    scan = client.post("/api/demo/simulate-scan").json()
    assert scan["scan_id"]
    assert client.get("/api/system/status").json()["demo"]["data_present"] is True
