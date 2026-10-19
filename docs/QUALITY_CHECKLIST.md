# BananaGrade quality checklist

This checklist tracks what the application implements against the thesis *A Two-Stage
Deep Learning System for Cardava Banana Disease Detection and Quality Classification
with Operational Analytics Dashboard*. A ticked item means it is implemented and covered
by automated tests or a recorded device check. Physical validation items stay open until
someone performs them on the sorting table.

Last updated: 2026-10-19.

## 1. Thesis traceability

| Thesis section | Requirement | Where it lives | Evidence |
|---|---|---|---|
| §3.3.7, §3.6.4 | RGB→HSV threshold, morphological opening, largest-contour mask applied back to the RGB image, uncropped. The trained Stage 1 model uses raw frames, so the mask is off by default (`BANAGRADE_STAGE1_MASK=1` enables it). Stage 2 gets the raw image. See section 6, item 4. | `backend/app/preprocessing.py`, `PresencePipeline._stage1_image` | `test_preprocessing.py`, `test_pipeline.py` (Stage 1 gets the raw frame; mask is opt-in) |
| §3.5.2, §3.5.4 Rule 1 | Stage 1 YOLO11n-cls (`stage1_best.pt`) Healthy / Unhealthy, preprocessed exactly as in training: whole frame squashed to 224×224, scaled to [0, 1], no center crop. Unhealthy terminates as Rejected and Stage 2 is skipped. | `model_inference.classify_with`, `grading.decide_grade`, `pipeline._process_scan` | `test_model_inference.py`, `test_grading.py`, `test_pipeline.py::test_unhealthy…`; app code path on the 225-image held-out test set: 224/225 (Unhealthy recall 0.987), matching the training report |
| §3.5.3, §3.7.6, §4.4.3 | Stage 2 YOLO11n (`stage2_best.pt`) whole-bunch box. Horizontal width in the 4608×2592 frame: ≥ 2730.07 px is Class A, otherwise Class B. | `grading.py`, `model_inference.detect` (axis = width) | `test_grading.py` boundary tests, `test_pipeline.py` |
| §3.3.7 | Box coordinates reprojected to the original image coordinate system | Camera captures at 4608×2592; `scale_width_to_reference` guards other sizes | `test_pipeline.py::test_width_from_smaller_frame…` |
| §3.6.3 | Camera Module 3 at 4608×2592; autofocus locked after the initial calibration | `pipeline._open_camera`, `_lock_focus` | Device check: 4608×2592 RGB888 stream, lens locked at 0.92 dpt |
| §3.6.4, §3.11 | Hands-free trigger on a stable bunch inside the frame; reset to monitoring once the bunch is removed | `pipeline._run`, `_stable_and_in_frame` (400 ms window, frame-edge margin) | Device check: transient false trigger on a cluttered desk was rejected by the stability gate |
| §3.6.5 | Green = ready, Yellow = Class A, Blue = Class B, Red = Rejected, rapid red blink for camera blocked or poor lighting. Slow red blink while booting comes from the UI spec. | `backend/app/leds.py`, `frame_health` | `test_leds.py`; device check: GPIO opened on BCM 17/27/22/23 (green/yellow/blue/red) |
| §3.6.2, §3.6.5 | FastAPI + SQLite + Vue 3 + Chart.js on the local Wi-Fi network; live updates | `api.py` (`/ws/live`), `frontend/` | `test_api.py`, `npm run build` |
| §3 "Database Audit" | Each scan stores scan ID, timestamp, Stage 1 and Stage 2 confidence, final grade, box, threshold, timings, and model names | `storage.save_scan`, `stage2_confidence` migration | `test_storage.py`, `test_pipeline.py` |
| §4.8.2 | Semantic colour coding identical to the floor LEDs | `style.css` tokens, `lib/grades.js`, `LedIndicator.vue` | `grades.test.js`; validated Class A/B colours for colour-vision-deficiency separation (ΔE 36.8) |
| §4.8.3 | Live session metrics, yield ratio, class distribution, rejection-rate trend | `DashboardView.vue`, `/api/analytics/summary?session=active`, `/api/analytics/trend` | `test_storage.py::test_rejection_trend_buckets`, `test_api.py` |
| §1.6, §3.12 | Traceability and human oversight: audit log, PDF export, operator dispute and correction | `HistoryView.vue`, `lib/pdf.js`, `DisputeModal.vue` | `pdf.test.js` |
| §4.7 | Latency target under 2 s, uptime, and thermal stability on the Pi 5 | `/api/system/telemetry`, `OperationalSummaryCard.vue` | Device check: CPU 51.8 °C, fan level 1/4 at idle |
| §3.10.5 | SUS evaluation | Existing SUS endpoint; the SUS tab is still a placeholder | Survey was run in Google Forms (n = 20, mean 89.88) |

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
- [ ] Reconcile dashboard totals against SQLite with production data from a real shift.
- [ ] Component-level rendering tests (`@vue/test-utils`) for empty and error states.

## 3. Model and grading pipeline

- [x] Load the trained `stage1_best.pt` (classify: Healthy / Unhealthy) and `stage2_best.pt` (detect: banana_bunch). The loader validates task and class names.
- [x] Keep camera frames OpenCV/Ultralytics-compatible (Picamera2 `RGB888` gives BGR arrays). Verified visually on the live preview.
- [x] Persist model names, both confidences, timings, the threshold, and the rejection reason for every scan.
- [x] Record low Stage 1 confidence, missing detections, and runtime errors as technical failures, never as commercial rejects.
- [x] Pipeline survives camera or model errors: retries every 10 s with the fast-red LED.
- [x] Deployed weights match the final training runs (SHA-256 identical to `runs/stage1_final` and `runs/stage2_final` `best.pt`).
- [x] Stage 1 preprocessing matches training. Ultralytics `predict()` center-crops the 16:9 frame and the HSV mask was not used in training; together they dropped held-out accuracy to 0.724 (Unhealthy recall 0.320). Fixed path: 0.9956 (recall 0.987).
- [x] Stage 2 detection and width grading in the app reproduce the final test evaluation: on the 150 held-out images every width matches within 0.001 px and every grade matches (127/150, accuracy 0.847). The remaining errors are bunches near the 2730.07 px threshold, not app defects.
- [ ] Tune `BANAGRADE_HSV_LOWER/UPPER` against the 1,500 hand-masked reference images (§3.3.3). Only needed if Stage 1 is retrained on masked images; the mask is off by default.
- [ ] Tune `BANAGRADE_MIN_BRIGHTNESS/CONTRAST` on site so the black velvet backdrop never trips the error state.
- [ ] Train or supply a dedicated YOLO11n-presence model. Until then the Stage 2 detector is the capture trigger.
- [ ] Run an on-device acceptance test with known Healthy A, Healthy B and Unhealthy bunches.
- [ ] Drift monitoring and a reviewed retraining loop for disputed frames.

## 4. Hardware and deployment

- [x] Raspberry Pi 5, Camera Module 3 (IMX708) and GPIO detected from the project virtualenv.
- [ ] Confirm the physical LED wiring matches BCM green 17, yellow 27, blue 22, red 23, or set `BANAGRADE_LED_*`.
- [ ] Verify the 45 cm mounting, ring light, and black velvet on the real sorting table.
- [ ] Fill §4.7 of the thesis: Stage 1 and Stage 2 latency, end-to-end time, a sustained run duration, scan count and average CPU temperature. The System Status page and `/api/system/telemetry` now provide these values.
- [ ] Install `deploy/banagrade.service` (now `uvicorn main:app`) and test recovery after reboot and Wi-Fi loss.
- [ ] Back up `banagrade.db` and check CSV and PDF export integrity.

## 5. Usability, safety, and release

- [x] Keyboard-focusable navigation, LED legend and model path tooltips; visible focus ring; table headers use `scope`.
- [ ] Operator authentication if disputes or shift control must be restricted.
- [ ] Release note: model hashes, threshold, environment variables, test results, known limitations.

## 6. Thesis text that disagrees with the implemented system

Chapter 4 evaluates a pixel-width rule. Several Chapter 3 passages still describe the
earlier centimetre conversion. The app follows Chapter 4. Revise these passages so the
document is internally consistent:

1. **§3.3.7, final paragraph.** It says the reprojection keeps the "pixel-to-centimeter conversion dimensionally accurate". No centimetre conversion exists.
2. **§3.4.1.** It still defines the deterministic grading function h(L̂) with ≥ 12 cm, 8–12 cm and < 8 cm, and the composite D(x) = h(m(g(x))). It should be D(x) = h(w(g(x))) using the 2730.07 px rule given just above it. It also uses `>` and `<` in the rule; the implementation and `grading_config.txt` use ≥ for Class A.
3. **§3.5.4 Rules 2–5.** They describe centimetre extraction and a size-based rejection below 8 cm. The evaluated system has no size-based rejection.
4. **§3.3.7, §3.6.4 (Stage 1 input).** They say Stage 1 receives the HSV-masked image. The final Stage 1 model was trained and tested on raw, unmasked frames (`prepare_stage1.py` copies `dataset/raw`), squashed to 224×224. On the held-out test set, feeding it the masked image lowers accuracy from 0.9956 to 0.911. Either revise the text to say Stage 1 uses the raw frame, or retrain Stage 1 on masked images and set `BANAGRADE_STAGE1_MASK=1`.
4. **§3.10.3.** It says "converted to cm using the camera calibration factor… or size-based rejection outcomes".
5. **§3.12.** It says size is determined by "the longitudinal length". The implementation measures the horizontal bounding-box width.
6. **§4.4.3.** It says "fell below the 2730.07-pixel equivalent for 12 cm" and "pixel-to-centimeter translation". This contradicts §1.6 and §3.4.2, which state the threshold is not a centimetre measurement.
7. **§4.7.** Bracketed `[insert …]` placeholders remain for latency, uptime, scan count and temperature.
8. **§3.6.5.** It describes the GPIO as "the microcontroller's GPIO pins". The Raspberry Pi 5 is a single-board computer, not a microcontroller.
9. **Figure 1.** It labels the dashboard "Flask & Chart.js"; the implementation and §3.6.2 use FastAPI.
10. **Table of contents.** It lists "3.5.3 Stage 1 — Health Screening"; the body heading is "3.5.3 Stage 2 — Size Grading".
