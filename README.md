# Banagrade

Banagrade is a local-first Cardava banana screening and size grading application for Raspberry Pi deployment.

## Current architecture

The system implements the thesis *A Two-Stage Deep Learning System for Cardava Banana Disease Detection and Quality Classification with Operational Analytics Dashboard*. `docs/QUALITY_CHECKLIST.md` maps every feature to its thesis section.

- `backend/app/grading.py` is the authoritative grading contract. Stage 1 Unhealthy means Rejected. Healthy bunches are graded by horizontal bounding-box width in the 4608×2592 frame: **≥ 2730.07 px is Class A, otherwise Class B** (thesis §4.4.3). The threshold is an image-space boundary, not a centimetre measurement.
- `backend/app/preprocessing.py` builds the RGB-to-HSV mask that Stage 1 receives (§3.3.7). Stage 2 receives the raw frame.
- `backend/app/pipeline.py` is the presence-triggered FSM. It captures at 4608×2592 on Camera Module 3, locks autofocus after one cycle at boot, and triggers on a stable in-frame detection held for 400 ms. Each result is persisted to SQLite and pushed over `/ws/live`.
- `backend/app/leds.py` drives the floor LEDs: green ready, yellow Class A, blue Class B, red Rejected, slow red blink while booting, fast red blink on error. The dashboard mirrors the same state.
- `backend/app/telemetry.py` reads uptime, CPU temperature, fan state, latency and database health from the device. Unavailable readings are `null`, never estimated.
- `backend/app/storage.py` owns SQLite, shift sessions, analytics, the rejection trend, and disputes.
- `frontend/` is a Vue 3 + Chart.js app with three pages: Live Dashboard, Recent Scans and System Status. In production the backend serves its build on the same port.

On Raspberry Pi OS, `picamera2`, `libcamera` and `gpiozero` are apt packages. The backend appends `/usr/lib/python3/dist-packages` to `sys.path` when they are missing from the virtualenv, so the venv does not need `--system-site-packages`.

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
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

This is the launch command from the thesis (`uvicorn main:app --host 0.0.0.0 --port 8000`). Leave this terminal running. Verify the backend from a second remote terminal:

```bash
cd /home/admin/Documents/banagrade
curl http://127.0.0.1:8000/api/health
```

The response should contain `"status":"ok"`.


When all dependencies are already installed, the quick start is:

```bash
cd /home/admin/Documents/banagrade/backend
source ../.venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```


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

## Production on the Pi (edge deployment)

In production the Pi is the whole system: camera, both models, grading, SQLite, LEDs and the
dashboard. No cloud service or internet connection is used. The backend serves the built
dashboard from `frontend/dist` (override with `BANAGRADE_FRONTEND_DIST`), so a single service on
port 8000 is the full app and Node is only needed to build it. Grading and the floor LEDs run
whether or not anyone has the dashboard open. Supervisors open `http://<hostname>.local:8000` (this Pi: `http://cardavapi.local:8000`) from
any phone or laptop on the same Wi-Fi (mDNS via `avahi-daemon`, on by default in Raspberry Pi OS).

Install once (from the repository root):

```bash
sudo useradd --system --home /opt/banagrade --shell /usr/sbin/nologin banagrade
(cd frontend && npm run build)
sudo rsync -a --exclude .git --exclude .venv --exclude frontend/node_modules --exclude models/dataset --exclude models/check --exclude 'backend/*.db*' ./ /opt/banagrade/
cd /opt/banagrade && sudo python3 -m venv .venv
sudo .venv/bin/pip install --resume-retries 10 --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1+cpu" "torchvision==0.29.1+cpu"
sudo .venv/bin/pip install --resume-retries 10 -r backend/requirements-runtime.txt
sudo mkdir -p /etc/banagrade /var/lib/banagrade/retrain
sudo cp backend/.env.example /etc/banagrade/banagrade.env
sudo nano /etc/banagrade/banagrade.env
sudo chown -R banagrade:banagrade /opt/banagrade /var/lib/banagrade
sudo cp deploy/banagrade.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now banagrade
```

PyTorch is installed from the CPU-only index first. The ARM64 wheel on PyPI is a CUDA build that
pulls about 3 GB of NVIDIA libraries the Pi cannot use; with torch already present, Ultralytics
keeps the CPU build.

In `nano`, set `BANAGRADE_ENABLE_GPIO=true` once the LEDs are wired, then save with Ctrl+O, Enter,
Ctrl+X. The production database starts empty in `/var/lib/banagrade`; the development and demo
databases are not copied.

The unit starts at boot without waiting for Wi-Fi and runs with the `video` and `gpio` groups
for the camera and LEDs. Check it with `systemctl status banagrade` and
`journalctl -u banagrade -f`. Scan timestamps rely on the Pi 5 real-time clock when there is no
internet for NTP, so fit the RTC battery if the device will boot offline.

Configuration variables are documented in `backend/.env.example`. For a quick single-port check
during development, run `npm run build` in `frontend/` and open port 8000 instead of 5173.

## Presentation mode (mock data)

Mock data lives in its own database, `backend/demo.db` (git-ignored), so real scans in `banagrade.db` are never mixed with it. The seeding script refuses to write into `banagrade.db` unless you pass `--force`.

```bash
cd /home/admin/Documents/banagrade/backend
source ../.venv/bin/activate
python scripts/seed_demo.py --reset          # 6 past shifts + a 3-hour current shift (~1,700 scans)
BANAGRADE_DB=demo.db BANAGRADE_DEMO_MODE=true python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

To make the dashboard and LED board update live during the talk, run this in a second terminal:

```bash
cd /home/admin/Documents/banagrade/backend
../.venv/bin/python scripts/seed_demo.py --live --interval 6
```

Each streamed scan flashes the LED mirror (capture, then yellow, blue or red) and appears on the dashboard. Mock scans follow the real grading rule. Widths of 2730.07 px or more are Class A and narrower widths are Class B. Rejected comes only from Stage 1 Unhealthy, and latency is about 1 s.

Every mock record is tagged `"demo": true`, and the header shows a **Demo data** label while mock scans exist. Do not present mock numbers as thesis results. To return to real data, restart the API without `BANAGRADE_DB=demo.db` and `BANAGRADE_DEMO_MODE`.

## Verification

Run the focused backend tests with:

```bash
cd /home/admin/Documents/banagrade
source .venv/bin/activate
export PYTHONPATH="$PWD/backend"
python -m pytest backend/tests -q

cd frontend
npm test          # Vitest: grade labels, LED mapping, PDF export
npm run build
```

The frontend `.npmrc` sets `legacy-peer-deps=true`. The Debian npm 9 package crashes while resolving Vitest 4's optional peers without it.

Hardware tests must use mocks by default. Physical camera and GPIO verification is a separate, explicitly enabled deployment check.