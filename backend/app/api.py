from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import demo
from .leds import GRADE_TO_LED, LedState
from .model_inference import UltralyticsInference
from .pipeline import PresencePipeline
from .telemetry import read_telemetry
from .storage import Storage, calculate_sus, now_iso, scans_csv


class SessionRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class SusRequest(BaseModel):
    responses: list[int] = Field(min_length=10, max_length=10)
    respondent_id: str | None = Field(default=None, max_length=100)


class DisputeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    corrected_grade: str | None = Field(default=None, pattern="^(Class A|Class B|Rejected|Technical Failure)$")


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


@app.get("/api/system/telemetry")
def system_telemetry() -> dict[str, Any]:
    return read_telemetry(pipeline.started_at, storage)


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


@app.get("/api/inspection/scans")
def list_scans(limit: int = Query(50, ge=1, le=5000), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return {"items": storage.list_scans(limit, offset), "limit": limit, "offset": offset}


@app.get("/api/analytics/summary")
def analytics_summary(session: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    return storage.analytics_summary(resolve_session(session))


@app.get("/api/analytics/trend")
def analytics_trend(session: str | None = Query(None, max_length=64), bucket_minutes: int = Query(15, ge=1, le=1440)) -> dict[str, Any]:
    session_id = resolve_session(session)
    return {"session_id": session_id, "bucket_minutes": bucket_minutes, "items": storage.rejection_trend(session_id, bucket_minutes)}


@app.post("/api/inspection/scans/{scan_id}/dispute", status_code=201)
async def dispute_scan(scan_id: str, payload: DisputeRequest) -> dict[str, Any]:
    try:
        result = storage.dispute_scan(scan_id, payload.reason, payload.corrected_grade, os.getenv("BANAGRADE_RETRAIN_DIR", "/dataset/retrain"))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Scan not found") from error
    await events.publish("scan_disputed", result)
    return {**result, "status": "open"}


@app.get("/api/sessions")
def sessions() -> dict[str, Any]:
    with storage.connect() as connection:
        rows = connection.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/sessions/active")
def active_session() -> dict[str, Any]:
    return {"session": storage.active_session()}


@app.post("/api/sessions", status_code=201)
async def create_session(payload: SessionRequest) -> dict[str, Any]:
    current = storage.active_session()
    if current:
        storage.close_session(current["id"])
    session = storage.create_session(payload.notes)
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


@app.post("/api/sus/responses", status_code=201)
def submit_sus(payload: SusRequest) -> dict[str, Any]:
    try:
        converted, score = calculate_sus(payload.responses)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    survey_id = str(uuid.uuid4())
    with storage.connect() as connection:
        connection.execute(
            "INSERT INTO sus_responses VALUES (?, ?, ?, ?, ?, ?)",
            (survey_id, payload.respondent_id, now_iso(), str(payload.responses), str(converted), score),
        )
    return {"survey_id": survey_id, "converted_scores": converted, "total_score": score}


@app.get("/api/exports/scans.csv", response_class=PlainTextResponse)
def export_scans() -> PlainTextResponse:
    return PlainTextResponse(scans_csv(storage.list_scans(100000, 0)), media_type="text/csv")


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