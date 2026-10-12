from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .model_inference import UltralyticsInference
from .pipeline import UnavailablePipeline
from .storage import Storage, calculate_sus, now_iso, scans_csv


class SessionRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class ThresholdRequest(BaseModel):
    class_a_min_cm: float = Field(gt=0)
    class_b_min_cm: float = Field(gt=0)
    operator_id: str | None = Field(default=None, max_length=100)


class SusRequest(BaseModel):
    responses: list[int] = Field(min_length=10, max_length=10)
    respondent_id: str | None = Field(default=None, max_length=100)


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
pipeline = UnavailablePipeline()
model_inference = UltralyticsInference.from_environment()
events = EventHub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.initialize()
    if os.getenv("BANAGRADE_ENABLE_MODEL_INFERENCE", "false").lower() == "true":
        try:
            model_inference.load()
        except (FileNotFoundError, ImportError, RuntimeError, ValueError) as error:
            model_inference.mark_error(error)
    await pipeline.start(lambda event: events.publish(event.get("event_type", "pipeline_event"), event))
    yield
    await pipeline.stop()


app = FastAPI(title="Banagrade API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("BANAGRADE_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": str(storage.path.name), "pipeline": "unavailable", "models": model_inference.status()}


@app.get("/api/system/status")
async def system_status() -> dict[str, Any]:
    return {"pipeline": await pipeline.status(), "models": model_inference.status(), "websocket_clients": len(events.clients)}


@app.get("/api/inspection/scans")
def list_scans(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    records = storage.list_scans(limit, offset)
    return {"items": records, "limit": limit, "offset": offset}


@app.get("/api/analytics/summary")
def analytics_summary() -> dict[str, Any]:
    return storage.analytics_summary()


@app.get("/api/sessions")
def sessions() -> dict[str, Any]:
    with storage.connect() as connection:
        rows = connection.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/sessions", status_code=201)
async def create_session(payload: SessionRequest) -> dict[str, Any]:
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


@app.put("/api/config/thresholds")
async def update_thresholds(payload: ThresholdRequest) -> dict[str, Any]:
    if payload.class_a_min_cm <= payload.class_b_min_cm:
        raise HTTPException(status_code=422, detail="Class A minimum must be greater than Class B minimum")
    with storage.connect() as connection:
        old = connection.execute("SELECT * FROM system_config WHERE id = 1").fetchone()
        connection.execute(
            "UPDATE system_config SET class_a_min_cm = ?, class_b_min_cm = ?, updated_at = ? WHERE id = 1",
            (payload.class_a_min_cm, payload.class_b_min_cm, now_iso()),
        )
        for setting, previous, current in (("class_a_min_cm", old["class_a_min_cm"], payload.class_a_min_cm), ("class_b_min_cm", old["class_b_min_cm"], payload.class_b_min_cm)):
            connection.execute(
                "INSERT INTO config_audit (setting, previous_value, new_value, changed_at, operator_id) VALUES (?, ?, ?, ?, ?)",
                (setting, str(previous), str(current), now_iso(), payload.operator_id),
            )
    await events.publish("system_status", {"configuration_updated": True})
    return config()


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
    await websocket.send_json({"event_id": str(uuid.uuid4()), "event_type": "system_status", "timestamp": now_iso(), "pipeline": await pipeline.status()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        events.clients.discard(websocket)