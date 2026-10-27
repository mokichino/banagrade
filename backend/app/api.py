from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.background import BackgroundTask

from . import demo, power
from .alignment import measure_sheet
from .drift import drift_report
from .leds import GRADE_TO_LED, LedState
from .model_inference import UltralyticsInference
from .pipeline import PipelineState, PresencePipeline
from .telemetry import read_telemetry
from .storage import Storage, disputes_zip, now_iso, scans_csv


class SessionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=500)


class DisputeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    corrected_grade: str | None = Field(default=None, pattern="^(Class A|Class B|Rejected|Technical Failure)$")


ScanIds = Annotated[list[str], Field(min_length=1, max_length=5000)]


class VoidRequest(BaseModel):
    scan_ids: ScanIds
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class UnvoidRequest(BaseModel):
    scan_ids: ScanIds


class PowerRequest(BaseModel):
    action: str = Field(pattern="^(reboot|shutdown)$")


class EventHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        message = {"event_id": str(uuid.uuid4()), "event_type": event_type, "timestamp": now_iso(), **(payload or {})}
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)

db_path = Path(os.getenv("BANAGRADE_DB", Path(__file__).resolve().parents[1] / "banagrade.db"))
storage = Storage(db_path)
model_inference = UltralyticsInference.from_environment()
pipeline = PresencePipeline(storage, model_inference)
events = EventHub()
power_tasks: set[asyncio.Task[None]] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.initialize()
    storage.ensure_active_session()
    if os.getenv("BANAGRADE_ENABLE_MODEL_INFERENCE", "true").lower() == "true":
        try:
            model_inference.load()
        except (FileNotFoundError, ImportError, RuntimeError, ValueError) as error:
            model_inference.mark_error(error)
    await pipeline.start(lambda event: events.publish(event.get("event_type", "pipeline_event"), event))
    if demo_mode() and not pipeline.enabled:
        pipeline.leds.set(LedState.READY)  # presentation without a camera: start on green, not an error
    yield
    await pipeline.stop()


app = FastAPI(title="Banagrade API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("BANAGRADE_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_session(session: str | None) -> str | None:
    """`session=active` scopes analytics to the open shift; omit for all-time totals."""
    if session == "active":
        return storage.active_session_id()
    return session


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "database": storage.path.name, "demo_mode": demo_mode(), "pipeline": await pipeline.status(), "models": model_inference.status()}


def demo_mode() -> bool:
    return os.getenv("BANAGRADE_DEMO_MODE", "false").lower() == "true"


@app.get("/api/system/status")
async def system_status() -> dict[str, Any]:
    return {
        "pipeline": await pipeline.status(),
        "models": model_inference.status(),
        "websocket_clients": len(events.clients),
        "demo": {"mode": demo_mode(), "data_present": demo.has_demo_data(storage)},
        "power": await power.status(),
    }


@app.post("/api/demo/simulate-scan", status_code=201)
async def simulate_scan() -> dict[str, Any]:
    """Presentation only: create one mock scan, flash the LED mirror, and push it live."""
    if not demo_mode():
        raise HTTPException(status_code=404, detail="Demo mode is disabled (set BANAGRADE_DEMO_MODE=true)")
    import random
    from datetime import UTC, datetime

    record = demo.generate_scan(random.Random(), datetime.now(UTC), storage.active_session_id())
    storage.save_scan(record)
    scan = storage.get_scan(record["scan_id"])
    pipeline.leds.set(LedState.CAPTURE)
    await asyncio.sleep(0.3)
    pipeline.leds.set(GRADE_TO_LED.get(record.get("final_grade") or "", LedState.ERROR))
    await events.publish("scan_completed", {"scan": scan, "demo": True})

    async def back_to_ready() -> None:
        await asyncio.sleep(3)
        pipeline.leds.set(LedState.READY)

    asyncio.create_task(back_to_ready())
    return scan


LED_TEST_STEPS = [
    (LedState.READY, 1.5),
    (LedState.CAPTURE, 1.0),
    (LedState.CLASS_A, 2.0),
    (LedState.CLASS_B, 2.0),
    (LedState.REJECTED, 2.0),
    (LedState.BOOTING, 3.0),
    (LedState.ERROR, 3.0),
]


@app.post("/api/demo/led-test")
async def led_test(step_scale: float = Query(default=1.0, ge=0.0, le=5.0)) -> dict[str, Any]:
    """Step the physical LEDs and the dashboard mirror through every state. Only touches LEDs, so it needs no demo mode,
    but it is refused while the live pipeline is busy with a scan."""
    if pipeline.state in pipeline.SNAPSHOT_BUSY or pipeline.state is PipelineState.PRESENCE_DETECTED:
        raise HTTPException(status_code=409, detail="A scan is in progress; try again when the bunch is removed")
    try:
        for state, seconds in LED_TEST_STEPS:
            pipeline.leds.set(state)
            await asyncio.sleep(seconds * step_scale)
    finally:
        pipeline.leds.set(LedState.ERROR if pipeline.state is PipelineState.ERROR else LedState.READY)
    return {"states": [state.value for state, _ in LED_TEST_STEPS], "hardware": pipeline.leds.hardware_available}


@app.post("/api/system/power", status_code=202)
async def system_power(payload: PowerRequest) -> dict[str, Any]:
    """Reboot or shut down the Pi. Refused mid-scan, and when polkit has not allowed it (deploy/50-banagrade-power.rules)."""
    if pipeline.state in pipeline.SNAPSHOT_BUSY or pipeline.state is PipelineState.PRESENCE_DETECTED:
        raise HTTPException(status_code=409, detail="A scan is in progress; try again when the bunch is removed")
    answer = await power.permission(payload.action)
    if answer != "yes":
        raise HTTPException(status_code=403, detail=f"The service is not allowed to {payload.action} the Pi (logind: {answer}); install deploy/50-banagrade-power.rules")
    pipeline.leds.set(LedState.BOOTING)
    await events.publish("system_power", {"action": payload.action})

    async def run() -> None:
        try:
            await power.execute(payload.action)
        except Exception as error:
            pipeline.leds.set(LedState.ERROR if pipeline.state is PipelineState.ERROR else LedState.READY)
            await events.publish("system_power_failed", {"action": payload.action, "error": str(error)})

    task = asyncio.create_task(run())
    power_tasks.add(task)  # the event loop only keeps a weak reference
    task.add_done_callback(power_tasks.discard)
    return {"action": payload.action, "delay_s": power.DELAY_S}


@app.get("/api/system/telemetry")
def system_telemetry() -> dict[str, Any]:
    return read_telemetry(pipeline.started_at, storage)


@app.get("/api/system/drift")
def system_drift() -> dict[str, Any]:
    return drift_report(storage)


@app.get("/api/camera/preview.mjpg")
async def camera_preview() -> StreamingResponse:
    if not pipeline.camera_available:
        raise HTTPException(status_code=503, detail="Camera unavailable")

    async def frames():
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        last = None
        while pipeline.camera_available:
            frame = pipeline.latest_jpeg()
            if frame is not None and frame is not last:
                last = frame
                yield boundary + frame + b"\r\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/camera/snapshot.jpg")
async def camera_snapshot() -> Response:
    if not pipeline.camera_available:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    try:
        jpeg = await pipeline.snapshot_jpeg()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/camera/alignment")
async def camera_alignment() -> dict[str, Any]:
    """Tilt and height from a short bond sheet lying flat in the middle of the view."""
    if not pipeline.camera_available:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    try:
        image = await pipeline.snapshot_array()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result = await asyncio.to_thread(measure_sheet, image)
    if result is None:
        raise HTTPException(status_code=422, detail="No whole sheet found: lay a short bond sheet flat in the middle, fully in view")
    return result


async def _calibration(run: Any) -> dict[str, Any]:
    if not pipeline.camera_available:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    try:
        return await run()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/camera/white-balance")
async def camera_white_balance() -> dict[str, Any]:
    """Lock white balance so the white sheet in view is neutral, as the dataset's backdrop is."""
    return await _calibration(pipeline.calibrate_white_balance)


@app.post("/api/camera/brightness")
async def camera_brightness() -> dict[str, Any]:
    """Set exposure compensation so the bunch in view is as bright as the dataset's bunches."""
    return await _calibration(pipeline.calibrate_brightness)


@app.delete("/api/camera/{setting}", status_code=204)
async def camera_reset(setting: str) -> None:
    """Back to automatic white balance, or exposure compensation 0."""
    if setting not in {"white-balance", "brightness"}:
        raise HTTPException(status_code=404, detail="Unknown camera setting")
    await pipeline.reset_camera_setting(setting.replace("-", "_"))


@app.get("/api/inspection/scans")
def list_scans(limit: int = Query(50, ge=1, le=5000), offset: int = Query(0, ge=0), session: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    return {"items": storage.list_scans(limit, offset, resolve_session(session)), "limit": limit, "offset": offset}


@app.get("/api/analytics/summary")
def analytics_summary(session: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    return storage.analytics_summary(resolve_session(session))


@app.get("/api/analytics/trend")
def analytics_trend(
    session: str | None = Query(None, max_length=64),
    bucket_minutes: int = Query(15, ge=1, le=1440),
    utc_offset_minutes: int = Query(0, ge=-840, le=840),
) -> dict[str, Any]:
    session_id = resolve_session(session)
    return {"session_id": session_id, "bucket_minutes": bucket_minutes, "items": storage.rejection_trend(session_id, bucket_minutes, utc_offset_minutes)}


@app.post("/api/inspection/scans/{scan_id}/dispute", status_code=201)
async def dispute_scan(scan_id: str, payload: DisputeRequest) -> dict[str, Any]:
    scan = storage.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["voided_at"]:
        raise HTTPException(status_code=409, detail="This scan is voided. Count it again before disputing its grade.")
    recorded = scan["final_grade"] or "Technical Failure"
    if payload.corrected_grade == recorded:
        raise HTTPException(status_code=400, detail=f"The scan is already recorded as {recorded}. Choose a different grade.")
    try:
        result = storage.dispute_scan(scan_id, payload.reason, payload.corrected_grade, os.getenv("BANAGRADE_RETRAIN_DIR", storage.path.parent / "retrain"))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Scan not found") from error
    await events.publish("scan_disputed", result)
    return {**result, "status": "open"}


# Scans are never deleted from the dashboard: there is no login, and the scan log is the audit trail. Voiding
# leaves a scan out of the totals but keeps it listed; clearing test data is scripts/clear_scans.py on the Pi.
@app.post("/api/inspection/scans/void")
async def void_scans(payload: VoidRequest) -> dict[str, Any]:
    voided = storage.void_scans(payload.scan_ids, payload.reason)
    if not voided and not any(storage.get_scan(scan_id) for scan_id in payload.scan_ids):
        raise HTTPException(status_code=404, detail="Scan not found")
    await events.publish("scans_voided", {"scan_ids": voided, "reason": payload.reason})
    return {"voided": len(voided), "skipped": len(set(payload.scan_ids)) - len(voided)}


@app.post("/api/inspection/scans/unvoid")
async def unvoid_scans(payload: UnvoidRequest) -> dict[str, Any]:
    restored = storage.unvoid_scans(payload.scan_ids)
    if not restored and not any(storage.get_scan(scan_id) for scan_id in payload.scan_ids):
        raise HTTPException(status_code=404, detail="Scan not found")
    await events.publish("scans_unvoided", {"scan_ids": restored})
    return {"restored": len(restored), "skipped": len(set(payload.scan_ids)) - len(restored)}


@app.get("/api/inspection/scans/{scan_id}/disputes")
def list_scan_disputes(scan_id: str) -> dict[str, Any]:
    return {"items": storage.scan_disputes(scan_id)}


@app.delete("/api/inspection/scans/{scan_id}/disputes")
async def delete_disputes(scan_id: str) -> dict[str, Any]:
    try:
        result = storage.delete_disputes(scan_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No disputes for this scan") from error
    await events.publish("dispute_deleted", result)
    return result


@app.get("/api/sessions")
def sessions() -> dict[str, Any]:
    return {"items": storage.list_sessions()}


@app.get("/api/sessions/active")
def active_session() -> dict[str, Any]:
    return {"session": storage.active_session()}


@app.post("/api/sessions", status_code=201)
async def create_session(payload: SessionRequest) -> dict[str, Any]:
    current = storage.active_session()
    if current:
        storage.close_session(current["id"])
    session = storage.create_session(payload.notes or "Shift started from dashboard", payload.name)
    await events.publish("session_updated", {"session_id": session["id"], "session": session})
    return session


@app.post("/api/sessions/{session_id}/close", status_code=204)
async def close_session(session_id: str) -> None:
    storage.close_session(session_id)
    await events.publish("session_updated", {"session_id": session_id})


@app.get("/api/config")
def config() -> dict[str, Any]:
    with storage.connect() as connection:
        row = connection.execute("SELECT * FROM system_config WHERE id = 1").fetchone()
    return dict(row)


@app.get("/api/exports/scans.csv", response_class=PlainTextResponse)
def export_scans(session: str | None = Query(None, max_length=64)) -> PlainTextResponse:
    return PlainTextResponse(scans_csv(storage.list_scans(100000, 0, resolve_session(session))), media_type="text/csv")


@app.get("/api/exports/disputes.zip")
def export_disputes() -> FileResponse:
    """Disputed frames sorted by the operator's corrected grade, plus labels.csv, for offline review before retraining."""
    archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    archive.close()
    disputes_zip(storage.disputed_scans(), Path(archive.name))
    return FileResponse(
        archive.name,
        media_type="application/zip",
        filename=f"banagrade-disputes-{now_iso()[:10]}.zip",
        background=BackgroundTask(os.unlink, archive.name),
    )


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    events.clients.add(websocket)
    await websocket.send_json({"event_id": str(uuid.uuid4()), "event_type": "system_status", "timestamp": now_iso(), "pipeline": await pipeline.status(), "led": pipeline.leds.state})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        events.clients.discard(websocket)


# The Pi serves the built dashboard itself, so one service on port 8000 is the whole app
# and the LAN needs no internet or Node. Mounted last so /api and /ws routes match first.
frontend_dist = Path(os.getenv("BANAGRADE_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
