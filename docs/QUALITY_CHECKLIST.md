# Banagrade quality checklist

This checklist tracks what the application implements against the thesis *A Two-Stage
Deep Learning System for Cardava Banana Disease Detection and Quality Classification
with Operational Analytics Dashboard*. A ticked item means it is implemented and covered
by automated tests or a recorded device check, or closed by a recorded decision. Physical
validation items stay open until someone performs them on the sorting table; the procedure and
record sheets are in `ON_SITE_TESTS.md`. `RELEASE_NOTES.md` lists the deployed model hashes,
configuration, test results and known limitations.

Last updated: 2026-10-25.

## 1. Thesis traceability

| Thesis section | Requirement | Where it lives | Evidence |
|---|---|---|---|
| §3.3.7, §3.6.4 | RGB→HSV threshold, morphological opening, largest-contour mask applied back to the RGB image, uncropped. The trained Stage 1 model uses raw frames, so the mask is off by default (`BANAGRADE_STAGE1_MASK=1` enables it). Stage 2 gets the raw image. See section 6, item 4. | `backend/app/preprocessing.py`, `PresencePipeline._stage1_image` | `test_preprocessing.py`, `test_pipeline.py` (Stage 1 gets the raw frame; mask is opt-in) |
| §3.5.2, §3.5.4 Rule 1 | Stage 1 YOLO11n-cls (`stage1_best.pt`) Healthy / Unhealthy, preprocessed exactly as in training: whole frame squashed to 224×224, scaled to [0, 1], no center crop. Unhealthy terminates as Rejected and Stage 2 is skipped. | `model_inference.classify_with`, `grading.decide_grade`, `pipeline._process_scan` | `test_model_inference.py`, `test_grading.py`, `test_pipeline.py::test_unhealthy…`; app code path on the 225-image held-out test set: 224/225 (Unhealthy recall 0.987), matching the training report |
| §3.5.3, §3.7.6, §4.4.3 | Stage 2 YOLO11n (`stage2_best.pt`) whole-bunch box. Horizontal width in the 4608×2592 frame: ≥ 2730.07 px is Class A, otherwise Class B. | `grading.py`, `model_inference.detect` (axis = width) | `test_grading.py` boundary tests, `test_pipeline.py` |
| §3.3.7 | Box coordinates reprojected to the original image coordinate system | Camera captures at 4608×2592; `scale_width_to_reference` guards other sizes | `test_pipeline.py::test_width_from_smaller_frame…` |
| §3.6.3 | Camera Module 3 at 4608×2592; autofocus locked after the initial calibration | `pipeline._open_camera`, `_lock_focus` | Device check: 4608×2592 RGB888 stream, lens locked at 0.92 dpt |
| §3.6.4, §3.11 | Hands-free trigger on a stable bunch inside the frame; reset to monitoring once the bunch is removed. On the 640×360 preview the Stage 2 `banana_bunch` detector triggers, backed up by the stock COCO-pretrained YOLO11n `banana` class for bunches Stage 2 misses (in place of the untrained YOLO11n-presence model). | `pipeline._run`, `_stable_and_in_frame` (400 ms window, frame-edge margin), `model_inference.detect_presence` | Held-out set through the app code: 225/225 bunches trigger; device check: transient false trigger on a cluttered desk was rejected by the stability gate |
| §3.6.5 | Green = ready, Yellow = Class A, Blue = Class B, Red = Rejected, rapid red blink for camera blocked or poor lighting. Slow red blink while booting comes from the UI spec. | `backend/app/leds.py`, `frame_health` | `test_leds.py`; device check: GPIO opened on BCM 17/27/22/23 (green/yellow/blue/red) |
| §3.6.2, §3.6.5 | FastAPI + SQLite + Vue 3 + Chart.js on the local Wi-Fi network; live updates | `api.py` (`/ws/live`, serves `frontend/dist` on the same port), `frontend/`, `deploy/banagrade.service` | `test_api.py::test_serves_built_dashboard_without_shadowing_api`, `npm run build` |
| §3 "Database Audit" | Each scan stores scan ID, timestamp, Stage 1 and Stage 2 confidence, final grade, box, threshold, timings, and model names | `storage.save_scan`, `stage2_confidence` migration | `test_storage.py`, `test_pipeline.py` |
| §4.8.2 | Semantic colour coding identical to the floor LEDs | `style.css` tokens, `lib/grades.js`, `LedIndicator.vue` | `grades.test.js`; validated Class A/B colours for colour-vision-deficiency separation (ΔE 36.8) |
| §4.8.3 | Live session metrics, yield ratio, class distribution, rejection-rate trend | `DashboardView.vue`, `/api/analytics/summary?session=active`, `/api/analytics/trend` | `test_storage.py::test_rejection_trend_buckets`, `test_api.py` |
| §1.6, §3.12 | Traceability and human oversight: audit log, PDF export, operator dispute and correction. Each dispute keeps the model's original grade and copies the archived frame for retraining. | `HistoryView.vue`, `lib/pdf.js`, `DisputeModal.vue`, `storage.dispute_scan`, `frames.save_frame` | `pdf.test.js`, `test_storage.py::test_dispute_keeps_model_grade…`, `test_pipeline.py::test_captured_frame_is_archived…` |
| §3.12 | Drift monitoring against the held-out test set and a reviewed export of disputed frames | `drift.py`, `/api/system/drift`, `/api/exports/disputes.zip`, `DriftCard.vue` | `test_drift.py`, `test_api.py::test_dispute_export_zip`, `states.test.js` |
| §4.7 | Latency target under 2 s, uptime, and thermal stability on the Pi 5 | `/api/system/telemetry`, `OperationalSummaryCard.vue` | Device check: CPU 51.8 °C, fan level 1/4 at idle |
| §3.10.5 | SUS evaluation | Not part of the dashboard; the SUS endpoint and tab were removed | Survey was run in Google Forms (n = 20, mean 89.88) |

## 2. Frontend and analytics

- [x] Use FastAPI endpoints as the only data source. No demo or fabricated totals are shipped.
- [x] Fixed sidebar and sticky header on desktop; sticky top navigation on phones.
- [x] LED mirror in the header and sidebar, driven by `led_changed` WebSocket events, with a legend tooltip and reduced-motion support.
- [x] Dashboard shows the shift processing volume as a hero number, a Class A vs Class B yield doughnut with text labels, and a rejection-rate trend line with interval control.
- [x] Technical failures are excluded from acceptance and rejection rates and shown separately. A technical failure is never shown as "Rejected".
- [x] Recent Scans: search by Scan ID or timestamp, grade filter, PDF of the filtered rows, CSV export, a dispute button per row.
- [x] System Status card order: camera preview, operational summary, hardware (exactly four components), AI models with path tooltips and Loaded/Missing/Error badges.
- [x] Backend time-bucket analytics endpoint (`/api/analytics/trend`).
- [x] Automated Vue logic tests (Vitest): grade labels, Stage 2 N/A rule, confidence formatting, filters, LED mapping, PDF generation.
- [x] Live preview draws the capture trigger's box and status: hold still, touching the edge, scanning, then the held grade in its LED colour. It is drawn on a display copy only and expires after 1 s without a detection (`pipeline.draw_overlay`, `test_pipeline.py::test_preview_draws…`, `test_stability_check_labels…`).
- [x] Component-level rendering tests (`@vue/test-utils` + jsdom) for empty and error states: scan table, every status card, Dashboard, Recent Scans and System Status with the API down (`components/__tests__/states.test.js`).
- [x] Grade descriptions on the dashboard and LED legend use the pixel rule (width ≥ 2730.07 px) instead of the old 8–12 cm ranges, which the system never measured.
- [ ] Reconcile dashboard totals against SQLite with production data from a real shift. The tool is ready: `scripts/shift_report.py report` exits non-zero on any mismatch (`test_shift_report.py`). Run it in `ON_SITE_TESTS.md` §7.

## 3. Model and grading pipeline

- [x] Load the trained `stage1_best.pt` (classify: Healthy / Unhealthy) and `stage2_best.pt` (detect: banana_bunch). The loader validates task and class names.
- [x] Keep camera frames OpenCV/Ultralytics-compatible (Picamera2 `RGB888` gives BGR arrays). Verified visually on the live preview.
- [x] Persist model names, both confidences, timings, the threshold, and the rejection reason for every scan.
- [x] Record low Stage 1 confidence, missing detections, and runtime errors as technical failures, never as commercial rejects.
- [x] A Stage 2 box below 0.90 confidence is a technical failure, not a grade (`BANAGRADE_STAGE2_MIN_CONF`). On 2026-10-25 a flat hand on a desk passed the trigger (backup banana 0.53, no "person" seen because the arm was out of frame) and Stage 1 (Healthy 0.807), and was graded Class A from a 0.75 box spanning hand, laptop and desk. All 150 held-out A/B bunches score ≥ 0.96 through the app code, and the archived hand frame scores 0.77 (`test_pipeline.py::test_weak_stage2_box…`).
- [x] Pipeline survives camera or model errors: retries every 10 s with the fast-red LED.
- [x] Deployed weights match the final training runs (SHA-256 identical to `runs/stage1_final` and `runs/stage2_final` `best.pt`).
- [x] Stage 1 preprocessing matches training. Ultralytics `predict()` center-crops the 16:9 frame and the HSV mask was not used in training; together they dropped held-out accuracy to 0.724 (Unhealthy recall 0.320). Fixed path: 0.9956 (recall 0.987).
- [x] Stage 2 detection and width grading in the app reproduce the final test evaluation: on the 150 held-out images every width matches within 0.001 px and every grade matches (127/150, accuracy 0.847). The remaining errors are bunches near the 2730.07 px threshold, not app defects.
- [x] Confirm whether Stage 1 was trained on masked or raw images: raw (confirmed by the model trainer). HSV tuning of `BANAGRADE_HSV_LOWER/UPPER` is not needed while the runtime mask stays off.
- [x] Capture trigger is the team's trained YOLO11n-presence (`models/presence/best.pt`, `banana_bunch`, delivered 2026-10-26). Through the app code it fires for 67/67 Class A, 83/83 Class B and 75/75 Unhealthy held-out bunches (lowest 0.93) at ~210–245 ms per check, as the only trigger model. Before it: Stage 2 alone at 320 px fired for 1 of 225; at 640 px it missed 9 of 75 Unhealthy; a stock COCO YOLO11n backup caught all 225 but mistook a palm for a banana. Both older modes remain as fallbacks (`test_model_inference.py::test_trained_presence_model…`, `test_trigger_*`).
- [x] Idle trigger skips the detectors while the frame is unchanged: a 160×90 change check (~2 ms) reuses the last answer for an empty table or a held bunch, with a forced detector run every 2 s. Idle detector time falls from ~67% to ~25%. Counters in `/api/system/status` → `pipeline.trigger` (`test_pipeline.py::test_change_check…`, `test_unchanged_empty_table…`, `test_held_bunch…`).
- [ ] Measure presence-model false triggers on the rig: empty velvet, hands, tools (`ON_SITE_TESTS.md` §3). On a cluttered desk it fired at 0.91 with no bunch and 0.83 on a hand. Confirm with the trainer whether "no bunch" photos and the Stage 1 split were used, and retrain with rig negatives if it fires there (`PRESENCE_MODEL.md` step 1).
- [x] Every captured frame is archived (`BANAGRADE_FRAME_DIR`, newest 1,000 kept), so disputes have an image. Low-confidence failures now keep their Stage 1 label and confidence.
- [x] Drift monitoring and a reviewed retraining loop for disputed frames: six indicators compared with the test-set baselines on System Status, a zip export of disputed frames with `labels.csv`, and a manual review step before retraining (`RELEASE_NOTES.md`, "Retraining loop").
- [ ] Tune `BANAGRADE_MIN_BRIGHTNESS/CONTRAST` on site so the black velvet backdrop never trips the error state (`ON_SITE_TESTS.md` §3).
- [ ] Run an on-device acceptance test with known Healthy A, Healthy B and Unhealthy bunches (`ON_SITE_TESTS.md` §4).

## 4. Hardware and deployment

- [x] Raspberry Pi 5, Camera Module 3 (IMX708) and GPIO detected from the project virtualenv.
- [x] `deploy/banagrade.service` installed and enabled on `cardavapi` (device check 2026-10-25: active since boot, `uvicorn main:app`).
- [x] Nightly database backup: `scripts/backup_db.py` uses SQLite's online backup, verifies integrity and row counts, and keeps 14 copies; `deploy/banagrade-backup.timer` runs it at 23:30 (`test_backup.py`). The CSV export round-trips every stored value, including commas, quotes and newlines (`test_api.py::test_csv_export_round_trips…`); the PDF is covered by `pdf.test.js`.
- [ ] Confirm the physical LED wiring matches BCM green 17, yellow 27, blue 22, red 23, or set `BANAGRADE_LED_*` (`ON_SITE_TESTS.md` §2).
- [ ] Verify the 45 cm mounting, ring light and black velvet on the real sorting table. Mount confirmed at 45 cm by tape and paper snapshot on 2026-10-26; the lens is now held at 0.99 dpt, measured there, instead of autofocusing on the velvet (`ON_SITE_TESTS.md` §1).
- [ ] Fill §4.7 of the thesis: Stage 1 and Stage 2 latency, end-to-end time, a sustained run duration, scan count and average CPU temperature (`ON_SITE_TESTS.md` §7, `scripts/shift_report.py`).
- [ ] Test recovery after reboot, power loss and Wi-Fi loss (`ON_SITE_TESTS.md` §5–6).
- [ ] Install the backup timer on the Pi and run the export checks (`ON_SITE_TESTS.md` §8).

## 5. Usability, safety, and release

- [x] Keyboard-focusable navigation, LED legend and model path tooltips; visible focus ring; table headers use `scope`.
- [x] Operator authentication: not required on the closed farm Wi-Fi (decision 2026-10-25). Recorded as a known limitation in `RELEASE_NOTES.md`; add it before exposing the Pi to a wider network.
- [x] Release note: model hashes, threshold, environment variables, test results, known limitations (`RELEASE_NOTES.md`).

## 6. Thesis text that disagrees with the implemented system

Chapter 4 evaluates a pixel-width rule. Several Chapter 3 passages still describe the
earlier centimetre conversion. The app follows Chapter 4. Revise these passages so the
document is internally consistent:

1. **§3.3.7, final paragraph.** It says the reprojection keeps the "pixel-to-centimeter conversion dimensionally accurate". No centimetre conversion exists.
2. **§3.4.1.** It still defines the deterministic grading function h(L̂) with ≥ 12 cm, 8–12 cm and < 8 cm, and the composite D(x) = h(m(g(x))). It should be D(x) = h(w(g(x))) using the 2730.07 px rule given just above it. It also uses `>` and `<` in the rule; the implementation and `grading_config.txt` use ≥ for Class A.
3. **§3.5.4 Rules 2–5.** They describe centimetre extraction and a size-based rejection below 8 cm. The evaluated system has no size-based rejection.
4. **§3.3.7, §3.6.4 (Stage 1 input and the role of the mask).** They say Stage 1 receives the HSV-masked image. The model trainer confirmed (2026-10-19) that both models were trained on raw, unmasked frames. The mask was only used offline to generate the Stage 2 whole-bunch bounding-box labels (`prepare_stage2.py` takes each box from the cleaned black-background image and trains on the matching raw image). On the held-out test set, feeding Stage 1 the masked image lowers accuracy from 0.9956 to 0.911. Revise the text: Stage 1 receives the raw frame squashed to 224×224; masking is an annotation step for Stage 2 labels, not a runtime step.
5. **§3.10.3.** It says "converted to cm using the camera calibration factor… or size-based rejection outcomes".
6. **§3.12.** It says size is determined by "the longitudinal length". The implementation measures the horizontal bounding-box width.
7. **§4.4.3.** It says "fell below the 2730.07-pixel equivalent for 12 cm" and "pixel-to-centimeter translation". This contradicts §1.6 and §3.4.2, which state the threshold is not a centimetre measurement.
8. **§4.7.** Bracketed `[insert …]` placeholders remain for latency, uptime, scan count and temperature.
9. **§3.6.5.** It describes the GPIO as "the microcontroller's GPIO pins". The Raspberry Pi 5 is a single-board computer, not a microcontroller.
10. **Figure 1.** It labels the dashboard "Flask & Chart.js"; the implementation and §3.6.2 use FastAPI.
11. **Table of contents.** It lists "3.5.3 Stage 1 — Health Screening"; the body heading is "3.5.3 Stage 2 — Size Grading".
12. **YOLO11n-presence (theoretical framework, "Autonomous Trigger" requirement, architecture figure).** The model now exists (`best.pt`, trained 2026-10-26) and is the trigger, so these passages are correct. Chapter 3 still needs its training data (how many bunch and "no bunch" photos, how the Rejected boxes were made, which split) and settings, and Chapter 4 needs its results: the 225/225 held-out trigger result and the on-site false-trigger count.
13. **Data collection (raw photo count).** It says 1,500 images were collected and 1,500 remained after cleaning, while also saying blurry and poorly lit images were removed. The kept filenames run up to Class_A_695, Class_B_873 and Rejected_612 (500 each), which suggests at least about 2,180 photos were taken if numbering started at 1. Confirm the real count with whoever took the photos.
14. **Stage 1 hyperparameter selection.** Describe the rule as highest validation accuracy, then lowest validation loss. Trials 02 and 04 both reach 1.000 in the corrected re-evaluation (`stage1_hparam_corrected_ranking.csv`) and trial 04 wins on loss (0.0055 vs 0.0103). Do not quote `stage1_hparam_final_ranking.csv`: it was scored with the center-crop preprocessing bug and ranks trial 02 first.
