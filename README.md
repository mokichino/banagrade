# Banagrade

Banagrade is a local-first Cardava banana screening and size grading application for Raspberry Pi deployment.

## Current architecture

- `backend/app/grading.py` is the authoritative deterministic grading contract.
- `backend/app/storage.py` owns SQLite initialization, WAL mode, append-only scan records, sessions, configuration audit, analytics, and SUS scoring.
- `backend/app/api.py` exposes REST endpoints and `/ws/live`.
- `backend/app/pipeline.py` defines the integration boundary for the existing camera/inference/GPIO pipeline. The default adapter reports unavailable and does not open hardware.
- `deploy/banagrade.service` describes production startup through systemd.

No camera, model, GPIO, telemetry, or scan data is fabricated. The real pipeline must implement the `Pipeline` protocol and publish persisted scan outcomes before `scan_completed` events are emitted.

## Development on a remote SSH machine

The commands below assume a Linux remote host, such as a Raspberry Pi, opened in
VS Code using Remote - SSH. Run all commands in the remote VS Code terminal, not
in a local terminal on your laptop.

### 1. Set up the backend

From the repository root:

```bash
cd /home/admin/Documents/banagrade
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

For normal development, install the API and test dependencies:

```bash
python -m pip install fastapi "uvicorn[standard]" pydantic pytest httpx
```

This is sufficient because model inference is disabled by default. The complete
`backend/requirements-runtime.txt` also installs Ultralytics, PyTorch, OpenCV,
and Pillow, which may not have compatible distributions for every Raspberry Pi
Python/ARM64 environment. Install it only when model inference is required and
compatible packages are available:

```bash
python -m pip install -r backend/requirements-runtime.txt
```

Start the backend in the first terminal:

```bash
export PYTHONPATH="$PWD/backend"
python -m uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Leave this terminal running. Verify the backend from a second remote terminal:

```bash
cd /home/admin/Documents/banagrade
curl http://127.0.0.1:8000/api/health
```

The response should contain `"status":"ok"`.

### 2. Set up and start the frontend

Open a second terminal in the same Remote - SSH window:

```bash
cd /home/admin/Documents/banagrade/frontend
npm install
npm run dev -- --host 0.0.0.0
```

Leave this terminal running. The Vite development server listens on port `5173`
and proxies `/api` and `/ws` requests to the backend on port `8000`.

### 3. Open the application from your laptop

Because the application is running on the remote host, forward port `5173` in
VS Code:

1. Open the **Ports** panel.
2. Select **Forward a Port**.
3. Enter `5173`.
4. Open the forwarded port URL in your laptop browser.

Do not use the laptop's `localhost:5173` unless VS Code has forwarded that port.
Keep both server terminals running while using the application. If the page
stops responding, check that both terminals are still running and refresh the
forwarded URL.

To verify the frontend proxy from the remote terminal:

```bash
curl http://127.0.0.1:5173/api/health
```

### Stopping the development servers

In each server terminal, press `Ctrl+C`.

The production entry point is `backend.production:app`. Production deployment
is described in `deploy/banagrade.service`.

## Verification

Run the focused backend tests with:

```bash
cd /home/admin/Documents/banagrade
source .venv/bin/activate
export PYTHONPATH="$PWD/backend"
python -m pytest backend/tests -q
```

Hardware tests must use mocks by default. Physical camera and GPIO verification is a separate, explicitly enabled deployment check.