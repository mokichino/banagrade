import importlib
from pathlib import Path

import pytest

from app.photos import PREVIEW_SCALE
from app.storage import now_iso

pytest.importorskip("httpx")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BANAGRADE_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("BANAGRADE_RETRAIN_DIR", str(tmp_path / "retrain"))
    monkeypatch.setenv("BANAGRADE_ENABLE_PIPELINE", "false")
    monkeypatch.setenv("BANAGRADE_ENABLE_MODEL_INFERENCE", "false")
    import app.api as api

    api = importlib.reload(api)
    from fastapi.testclient import TestClient

    with TestClient(api.app) as test_client:
        yield test_client, api


def _frame(path: Path, width: int = 640, height: int = 360) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, : width // 2] = (40, 160, 60)
    assert cv2.imwrite(str(path), image)
    return path


def _save_scan(api, scan_id: str, image_refs) -> None:
    session = api.storage.ensure_active_session()
    api.storage.save_scan({
        "scan_id": scan_id, "session_id": session["id"], "captured_at": now_iso(), "completed_at": now_iso(),
        "final_grade": "Class B", "processing_status": "completed", "image_refs": image_refs,
    })


def test_preview_is_a_quarter_size_jpeg_and_full_is_the_saved_frame(client, tmp_path) -> None:
    test_client, api = client
    frame = _frame(tmp_path / "frames" / "s1.jpg")
    _save_scan(api, "s1", [str(frame)])

    preview = test_client.get("/api/inspection/scans/s1/photo")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert "max-age" in preview.headers["cache-control"]
    decoded = cv2.imdecode(np.frombuffer(preview.content, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (360 // PREVIEW_SCALE, 640 // PREVIEW_SCALE)

    full = test_client.get("/api/inspection/scans/s1/photo?size=full")
    assert full.status_code == 200
    assert full.content == frame.read_bytes()
    assert test_client.get("/api/inspection/scans/s1/photo?size=huge").status_code == 422


def test_missing_photos_are_404_with_a_reason(client, tmp_path) -> None:
    test_client, api = client
    assert test_client.get("/api/inspection/scans/nope/photo").json()["detail"] == "Scan not found"

    _save_scan(api, "none", None)  # e.g. the camera failed, or the frame archive is off
    _save_scan(api, "pruned", [str(tmp_path / "frames" / "pruned.jpg")])
    for scan_id in ("none", "pruned"):
        response = test_client.get(f"/api/inspection/scans/{scan_id}/photo")
        assert response.status_code == 404
        assert response.json()["detail"] == "No photo kept for this scan"


def test_a_disputed_photo_outlives_the_frame_archive(client, tmp_path) -> None:
    test_client, api = client
    frame = _frame(tmp_path / "frames" / "d1.jpg")
    _save_scan(api, "d1", [str(frame)])
    assert test_client.post("/api/inspection/scans/d1/dispute", json={"corrected_grade": "Class A", "reason": "measured 13 cm"}).status_code == 201
    original = frame.read_bytes()
    frame.unlink()  # pruned once 1,000 newer frames were saved

    full = test_client.get("/api/inspection/scans/d1/photo?size=full")
    assert full.status_code == 200
    assert full.content == original
    assert test_client.get("/api/inspection/scans/d1/photo").status_code == 200
