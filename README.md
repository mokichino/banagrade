# Banagrade

Banagrade is a local-first Cardava banana screening and size grading application for Raspberry Pi deployment.

## Current architecture

- `backend/app/grading.py` is the authoritative deterministic grading contract.
- `backend/app/storage.py` owns SQLite initialization, WAL mode, append-only scan records, sessions, configuration audit, analytics, and SUS scoring.
- `backend/app/api.py` exposes REST endpoints and `/ws/live`.
- `backend/app/pipeline.py` defines the integration boundary for the existing camera/inference/GPIO pipeline. The default adapter reports unavailable and does not open hardware.
- `deploy/banagrade.service` describes production startup through systemd.

No camera, model, GPIO, telemetry, or scan data is fabricated. The real pipeline must implement the `Pipeline` protocol and publish persisted scan outcomes before `scan_completed` events are emitted.

## Development

Create a virtual environment, install the existing backend requirements, and run:

```powershell
python -m pip install -r backend/requirements-runtime.txt
$env:PYTHONPATH = "backend"
python -m uvicorn app.api:app --reload
```

The production entry point is `backend.production:app`. The frontend remains a separate Vite build during development and should be served as static assets by the production deployment once its build is available.

## Verification

Run the focused backend tests with:

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -q
```

Hardware tests must use mocks by default. Physical camera and GPIO verification is a separate, explicitly enabled deployment check.