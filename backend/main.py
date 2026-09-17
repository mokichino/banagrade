from datetime import date

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.database import create_scan_ticket, get_scans, get_shift, initialize_database, update_shift
from app.hardware_bridge import ENABLE_PI_HARDWARE, hardware_bridge

app = FastAPI(title="Banagrade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ShiftUpdate(BaseModel):
    isActive: bool
    workers: int = Field(ge=0, le=500)


class ScanTicket(BaseModel):
    note: str = Field(default="", max_length=500)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/")
def root() -> dict:
    return {"message": "Banagrade API is running"}


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "online", "service": "banagrade-api", "piHardwareEnabled": ENABLE_PI_HARDWARE}


@app.get("/api/dashboard")
def dashboard_data() -> dict:
    scans = get_scans()
    shift = get_shift()
    summary = {
        "sessionVolume": 1284,
        "classA": 539,
        "classB": 488,
        "rejected": 257,
        "yieldRate": 82,
        "thesisObjective": "Improve grading consistency, traceability, and supervisor decision support in banana packing operations.",
    }
    trend = [
        {"time": "09:00", "rate": 8},
        {"time": "10:00", "rate": 11},
        {"time": "11:00", "rate": 9},
        {"time": "12:00", "rate": 14},
        {"time": "13:00", "rate": 10},
    ]
    equipment = [
        {"name": "Camera Feed", "state": "Stable", "detail": "No calibration drift detected", "specs": "12 MP industrial camera · 30 FPS", "firmware": "v2.4.1", "lastService": "Sep 12, 2026", "health": 98},
        {"name": "AI Pipeline", "state": "Operational", "detail": "Model confidence average 94%", "specs": "Quality classifier · GPU inference", "firmware": "Model 1.8.0", "lastService": "Sep 15, 2026", "health": 96},
        {"name": "Raspberry Pi 5", "state": "Staging disabled", "detail": "Bridge ready; hardware transport is off", "specs": "8 GB RAM · GPIO / camera bridge", "firmware": "Bridge staged", "lastService": "Not commissioned", "health": 100},
        {"name": "Packing Line", "state": "Ready", "detail": "Next bunch queued", "specs": "Line 2 · Automated diverter", "firmware": "PLC 4.2.0", "lastService": "Sep 10, 2026", "health": 94},
    ]
    return {
        "summary": summary,
        "scans": scans,
        "shift": shift,
        "trend": trend,
        "equipment": equipment,
        "systemStatus": {
            "mode": "ready",
            "label": "System Ready",
            "detail": "Waiting for banana",
        },
    }


@app.get("/api/scans")
def scans(start_date: date | None = Query(default=None), end_date: date | None = Query(default=None)) -> dict:
    return {"scans": get_scans(start_date.isoformat() if start_date else None, end_date.isoformat() if end_date else None)}


@app.post("/api/scans/{scan_id}/ticket", status_code=201)
def ticket_scan(scan_id: str, payload: ScanTicket) -> dict:
    if not any(scan["id"] == scan_id for scan in get_scans()):
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"ticket": create_scan_ticket(scan_id, payload.note)}


@app.get("/api/v1/metrics/overview")
def overview_metrics() -> dict:
    scans = get_scans()
    counts = {"Class A": 0, "Class B": 0, "Rejected": 0}
    for scan in scans:
        counts[scan["grade"]] = counts.get(scan["grade"], 0) + 1
    total = len(scans)
    return {"sessionVolume": total, "classA": counts["Class A"], "classB": counts["Class B"], "rejected": counts["Rejected"], "yieldRate": round((total - counts["Rejected"]) / total * 100) if total else 0, "shift": get_shift()}


@app.patch("/api/v1/shift/update")
def shift_update(payload: ShiftUpdate) -> dict:
    return {"shift": update_shift(payload.isActive, payload.workers)}


@app.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"enabled": ENABLE_PI_HARDWARE, "status": "staging-disabled" if not ENABLE_PI_HARDWARE else "ready"})
    if not ENABLE_PI_HARDWARE:
        await websocket.close()
        return
    async for message in hardware_bridge.telemetry():
        await websocket.send_json(message)