# Banagrade

Banagrade is a local-first Cardava banana screening and size grading application for Raspberry Pi deployment.

## Current architecture

The system implements the thesis *A Two-Stage Deep Learning System for Cardava Banana Disease Detection and Quality Classification with Operational Analytics Dashboard*. `docs/QUALITY_CHECKLIST.md` maps every feature to its thesis section.

- `backend/app/grading.py` is the authoritative grading contract. Stage 1 Unhealthy means Rejected. Healthy bunches are graded by horizontal bounding-box width in the 4608×2592 frame: **≥ 2730.07 px is Class A, otherwise Class B** (thesis §4.4.3). The threshold is an image-space boundary, not a centimetre measurement.
- Both models receive the raw frame, as they were trained. Stage 1 squashes the whole frame to 224×224. `backend/app/preprocessing.py` keeps the RGB-to-HSV mask from §3.3.7, but it is off by default (`BANAGRADE_STAGE1_MASK=1`), because in training the mask was only used to generate the Stage 2 bounding-box labels.
- `backend/app/pipeline.py` is the presence-triggered FSM. The capture trigger is the team's trained YOLO11n-presence detector (`models/presence/best.pt`, one class `banana_bunch`, trained on Class A, B and Rejected bunches), run on the low-resolution preview. If it is missing, the Stage 2 detector triggers instead. The preview on System Status draws the trigger's box and status. It captures at 4608×2592 on Camera Module 3, locks autofocus after one cycle at boot, and triggers on a stable in-frame detection held for 400 ms. After grading, the result is held until the table has looked empty for 3 s without a break (`BANAGRADE_RELEASE_S`), so straightening or briefly lifting the bunch does not scan it again. The service also starts held, so a bunch left on the table across a restart or reboot is not scanned again until it has been removed. Each result is persisted to SQLite and pushed over `/ws/live`, and the frame is archived for disputes (`backend/app/frames.py`).
- `backend/app/drift.py` compares the latest 200 scans with the held-out test set (Stage 1 and Stage 2 confidence, low-confidence and missed-detection rates, dispute rates) and flags drift on the System Status page.
- `backend/app/leds.py` drives the floor LEDs: green ready, yellow Class A, blue Class B, red Rejected, slow red blink while booting, fast red blink on error. The dashboard mirrors the same state.
- The camera lens is held at 0.99 dioptres (`BANAGRADE_LENS_POSITION`), what this Camera Module 3 read with a printed target at a tape-measured 45 cm. Autofocus on the bare velvet locked anywhere from 0.69 to 1.31, and this camera's lens positions do not follow 1 ÷ metres. `auto` brings back one autofocus cycle at boot.
- The dataset was shot on the same camera (imx708, `rpicam-apps`, 4608×2592) in daylight with automatic exposure and white balance (EXIF: 1/100–1/15 s, ISO 112–1569, 15 Aug 2026). Under the ring light the rig came out brighter (bunch 171–174 against 149, velvet 51–53 against 11, HSV value) and its white balance drifted blue. **Set white balance from sheet** and **Match dataset brightness** on the camera card (`backend/app/camera_tuning.py`) lock colour gains that make a white sheet neutral and an exposure compensation that makes a fresh green bunch as bright as the dataset's; both are saved in `camera.json` next to the database and reapplied at every start.
- The trained trigger, Stage 1 and Stage 2 only ever saw bunches, and on 2026-10-26 all three accepted a sheet of white paper (graded Class B three times). The trigger's box must be at least 10% banana-coloured (`BANAGRADE_MIN_BANANA_SHARE`; OpenCV hue 5–55, i.e. brown, yellow or green, saturation ≥ 25), checked inside the box so nothing beside the bunch counts, and by hue so a colour cast does not count: on 2026-10-27 auto white balance turned the sheet light blue, a saturation-only check read it as 91% coloured, and it was graded Class B. All 344 dataset bunches scored at least 27.6%, every paper frame (tinted or not) 0.4% or less. The preview labels such a box "Not a bunch · no banana colour" and nothing is captured; a frame that fails at capture is recorded as `NOT_A_BUNCH`. Skin is in the same hue range, so hands are left to the COCO hand check. Just before capture, the stock COCO YOLO11n (`models/presence/yolo11n.pt`, `BANAGRADE_OBJECT_MODEL`) looks at the preview frame. A "person" at 0.30 or more anywhere in view means a hand: the box reads "Hand in view · let go to scan" and capture waits, because Stage 1 judges the whole frame. Another COCO object at 0.40 or more on the bunch's box, stronger than "banana", is labelled "Not a bunch · looks like a …" and not captured. On the 344 dataset photos it waited only on the 3 that show a hand and refused none; it adds about 180 ms per scan. COCO does not recognise paper, and a flat palm seen from above scored only 0.09, so the colour check and the 0.90 Stage 2 minimum stay.
- The System Status page can reboot or shut down the Pi (`backend/app/power.py`); the service asks systemd-logind, which allows it only for the `banagrade` user once `deploy/50-banagrade-power.rules` is installed.
- `backend/app/telemetry.py` reads uptime, CPU temperature, fan state, latency and database health from the device. Unavailable readings are `null`, never estimated. While a shift is open the service also records the CPU temperature once a minute, and the dashboard shows each shift's average and peak next to it, so no separate sampler has to be started or stopped (`scripts/shift_report.py report` prints the same numbers for thesis §4.7).
- `backend/app/storage.py` owns SQLite, shift sessions, analytics, the rejection trend, and disputes. **End shift** on the dashboard closes the open shift; until **Start new shift** or the next scan opens another, no shift is open, the current-shift view is empty and no temperature is recorded.
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
sudo rsync -a --exclude .git --exclude .venv --exclude frontend/node_modules --exclude models/dataset --exclude models/check --exclude training --exclude 'backend/*.db*' ./ /opt/banagrade/
cd /opt/banagrade && sudo python3 -m venv .venv
sudo .venv/bin/pip install --resume-retries 10 --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1+cpu" "torchvision==0.29.1+cpu"
sudo .venv/bin/pip install --resume-retries 10 -r backend/requirements-runtime.txt
sudo mkdir -p /etc/banagrade /var/lib/banagrade/retrain
sudo cp backend/.env.example /etc/banagrade/banagrade.env
sudo nano /etc/banagrade/banagrade.env
sudo chown -R banagrade:banagrade /opt/banagrade /var/lib/banagrade
sudo cp deploy/banagrade.service deploy/banagrade-backup.service deploy/banagrade-backup.timer /etc/systemd/system/
sudo cp deploy/50-banagrade-power.rules /etc/polkit-1/rules.d/
sudo systemctl daemon-reload && sudo systemctl enable --now banagrade banagrade-backup.timer
```

The backup timer copies `banagrade.db` to `/var/lib/banagrade/backups` every night at 23:30 using
SQLite's online backup, checks the copy's integrity and row counts, and keeps the newest 14. Run one
by hand with `sudo systemctl start banagrade-backup` and check it with `journalctl -u banagrade-backup`.
Only those nightly copies (`banagrade-YYYYMMDD-HHMMSS.db`) are ever pruned; safety copies made by hand
before a risky change are kept until someone deletes them.

Scans are never deleted from the dashboard: it has no login, and the scan log is the audit trail. To
leave a scan out of the numbers (a bunch scanned twice, a sheet of paper, a test run), **void** it on
Recent Scans with a reason. It stays listed, marked Voided, counts nowhere, and can be counted again.
To wipe test data completely, run this on the Pi and type CLEAR; it saves a verified backup with the
scans' photos (moved, not deleted) to `/var/lib/banagrade/backups/clear-<time>/` first:

```bash
sudo -u banagrade /opt/banagrade/.venv/bin/python /opt/banagrade/backend/scripts/clear_scans.py
```

Every captured frame is saved to `/var/lib/banagrade/frames` (about 0.9 MB each, newest 1,000 kept,
`BANAGRADE_FRAME_KEEP`). Disputing a scan copies its frame into `/var/lib/banagrade/retrain`, and
**System Status → Export disputed frames** downloads those frames with a `labels.csv` for review
before retraining. The `training/` folder holds the training scripts and is not deployed.

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

Configuration variables are documented in `backend/.env.example`. When updating an existing install, make sure `/etc/banagrade/banagrade.env` sets `BANAGRADE_PRESENCE_MODEL=/opt/banagrade/models/presence/best.pt`: an empty value disables the presence model and leaves Stage 2 as the trigger. For a quick single-port check
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
npm test          # Vitest: grade labels, LED mapping, PDF export, empty and error states
npm run build
```

The frontend `.npmrc` sets `legacy-peer-deps=true`. The Debian npm 9 package crashes while resolving Vitest 4's optional peers without it.

Hardware tests must use mocks by default. Physical camera and GPIO verification is a separate, explicitly enabled deployment check.