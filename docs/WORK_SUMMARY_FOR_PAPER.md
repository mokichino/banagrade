# Banagrade: system build, deployment and testing summary

Prepared by Alessandra Veronica (system, dashboard and Raspberry Pi deployment) for the thesis paper.
Status as of 27 October 2026, checked against the running document version 14. Model training details
(Stage 1 and Stage 2 training, hyperparameter search, SVM baseline, end-to-end subset) are Sai Winnie's part
and are only summarised here where they affect the deployed system.

> **Note to an AI reading this:** this is the source of truth for the implemented system of the thesis
> *A Two-Stage Deep Learning System for Cardava Banana Surface Defect Screening and Size-Based Grading with an
> Edge-Based Operational Analytics Dashboard*. Use these numbers exactly as written and do not invent results.
> Items marked "open" have not been measured, so the paper must not report values for them. Section 5 lists
> the places where the paper (v14) still disagrees with the built system; revise those passages to match.

---

## 1. At a glance

- **What it is:** a hands-free Cardava grading station that runs entirely on one Raspberry Pi 5 (8 GB). A bunch
  is placed on black velvet under a Camera Module 3 at 45 cm. The Pi sees it, captures a 4608×2592 photo, runs
  two YOLO11n models and lights an LED: **yellow = Class A, blue = Class B, red = Rejected**, green = ready.
- **No cloud, no internet.** Camera, models, grading, database, LEDs and dashboard all run on the Pi. Anyone on
  the same Wi-Fi opens the dashboard at `http://cardavapi.local:8000`.
- **Grading rule:** Stage 1 Unhealthy → Rejected, at any confidence. Stage 1 Healthy → Stage 2 whole-bunch box
  width: **≥ 2730.07 px = Class A, otherwise Class B.** A Healthy result below 0.80 confidence is held for a hand
  check.
- **Held-out results through the app's own code:** Stage 1 224/225 correct (0.9956, Unhealthy recall 0.987);
  Stage 2 + width rule 127/150 (0.847). These match the training evaluation exactly.
- **On the Pi (27 Oct 2026 on-site run, 96 scans of 95 bunches):** average **0.24 s** per scan from capture to grade
  (median 0.26 s, slowest 0.38 s), none over the 2 s target, no crashes.
- **Software:** Python FastAPI + SQLite backend, Vue 3 + Chart.js dashboard, one systemd service on port 8000.
  127 backend and 57 frontend automated tests pass.

## 2. How the system works: the important functions

<!-- fig:pipeline -->

### 2.1 Hands-free capture trigger

The camera streams a small 640×360 preview. A dedicated **YOLO11n-presence** detector (one class,
`banana_bunch`, trained by the team on Class A, B and Rejected bunches) looks for a bunch at confidence ≥ 0.80.
The bunch must sit inside the frame left-to-right and **hold still for 400 ms** before anything is captured, so
a bunch being put down is not scanned mid-motion. To save CPU, a 2 ms "did anything change?" check skips the
detector when the table looks the same (forced check every 2 s); this cut idle detector time from about 67% to
about 25%. On the 225 held-out photos the trigger fires for all 225 bunches (lowest confidence 0.93), at about
210–245 ms per check.

<!-- fig:trigger -->

### 2.2 Safety checks before capture

The models only ever saw bunches, so on-site they accepted things that are not bunches. Two checks now run first:

- **Banana-colour check:** at least 10% of the trigger's box must be brown, yellow or green (by hue, inside the
  box). All 344 dataset bunches scored ≥ 27.6%; every paper-sheet frame scored ≤ 0.4%. Otherwise the preview
  says "Not a bunch · no banana colour" and nothing is captured.
- **Hand and object check:** a stock COCO YOLO11n looks for a hand ("person" ≥ 0.30) anywhere in view; capture
  waits until it is gone ("Hand in view · let go to scan"), because Stage 1 judges the whole frame. A stronger
  non-banana COCO object on the box is refused. Adds about 180 ms; on the 344 dataset photos it waited only on
  the 3 that show a hand and refused none.

### 2.3 Two-stage grading and the decision rule

1. **Capture** a full 4608×2592 photo. The frame is archived (newest 1,000 kept) so it can be reviewed later.
2. **Stage 1 (YOLO11n-cls):** the **raw** frame is resized to 224×224 with no crop and no mask, exactly as the
   model was trained. Unhealthy → **Rejected** (red) at any confidence, and Stage 2 is skipped.
3. **Stage 2 (YOLO11n detector):** finds the whole-bunch box in the raw frame; its horizontal width is measured in
   original-image pixels. **≥ 2730.07 px → Class A (yellow), otherwise Class B (blue).**
4. **Not graded ("technical failure")** instead of a guess when: Stage 1 Healthy below 0.80 confidence, no Stage 2 box, a Stage
   2 box below 0.90 confidence, or an error. These are stored with the reason and shown on the dashboard
   ("Check by hand"), but never counted as Rejected or in any rate.

<!-- fig:frames -->

**Important fix found during integration:** the first app version fed Stage 1 a centre-cropped, HSV-masked image.
Held-out accuracy dropped to **0.724** (Unhealthy recall 0.320). The trainer confirmed both models were trained on
**raw** frames. After the fix the app reproduces **0.9956**. The mask alone gives 0.911. The HSV mask is only an
offline step that produced the Stage 2 box labels; it is off at runtime.

<!-- fig:preproc -->

### 2.4 Result hold, LEDs and restarts

After a grade, the result stays until the table has looked empty for **3 s without a break**, so straightening or
briefly lifting a bunch does not scan it twice. After a restart the system starts "held" for the same reason.
LEDs (GPIO BCM green 17, yellow 27, blue 22, red 23): green = ready, all flash = capturing, yellow/blue/red = grade,
slow red blink = booting, fast red blink = error (camera blocked, poor light, model or camera fault, retried every
10 s). Grading and LEDs keep working with Wi-Fi off and with nobody watching the dashboard.

<!-- fig:wiring -->

### 2.5 Live Dashboard

Per-shift processing volume, Class A / Class B / Rejected cards on one denominator (% of graded), a yield doughnut,
and a rejection-rate trend on a real clock axis with the shift average and a table view. Shifts can be named,
started and ended; past shifts can be viewed. While a shift is open the Pi records its CPU temperature once a minute
and shows the shift's average and peak (afternoon shift of 27 Oct: **47.1 °C average, 50.1 °C peak**, 29 readings).
Colours match the floor LEDs. Updates arrive live over a WebSocket.

<!-- shot:dashboard -->

### 2.6 Recent Scans (audit log and human oversight)

Every scan with time, Stage 1 result and confidence, Stage 2 grade and final grade. Search, shift and grade filters,
PDF and CSV export of exactly the listed rows. **Dispute** a scan with the correct grade: the model's original grade
is kept and the photo is copied to a retraining folder (a B → A dispute asks for the measured finger length).
**Void** a scan with a reason to leave it out of every total; scans are never deleted from the dashboard, and both
disputes and voids can be undone.

<!-- shot:history -->

### 2.7 System Status (setup and health)

- **Camera preview** with the trigger's box and status, full screen and a placement guide.
- **Check camera alignment** from a short bond sheet: front–back and side tilt and an approximate height.
- **Set white balance from sheet** and **Match dataset brightness** so the rig's colours match the dataset photos.
- Lens held at **0.99 dioptres**, measured at a tape-measured 45 cm (autofocus on bare velvet wandered 0.69–1.31).
- Device telemetry: uptime, CPU temperature, fan, latency against 2 s, database health (never estimated).
- Hardware and model status (Loaded / Missing / Error) for all four models.
- **Model drift:** the latest 200 scans against the held-out baselines on six indicators. It warns; it never changes
  a grade. After both on-site shifts 3.0% of scans (4 of 134) are Healthy results below the Stage 1 confidence
  gate (test set 0.4%), under the 5% warning level. Before Unhealthy results were exempted from the gate it was 6.7%
  and flagged.
- **Export disputed frames** as a zip with `labels.csv`; reboot and shut down the Pi.

<!-- shot:status-camera -->

<!-- shot:status-health -->

### 2.8 Reliability and records

One systemd service starts at boot without Wi-Fi; CPU-only PyTorch. Nightly database backup at 23:30 with an
integrity check (newest 14 kept). Retraining loop: dispute → frame copied → drift monitor → export with labels →
a person reviews every label → retrain → deploy only if held-out results are at least as good. Demo data lives in a
separate database and is labelled "Demo data" on screen. No login (accepted for a closed farm Wi-Fi).

## 3. Results the paper can use

### 3.1 Held-out test set through the app's code

| Check | Result |
|---|---|
| Stage 1, 225 test images | 224/225 (0.9956), Unhealthy recall 0.987; mean confidence 0.997 |
| Stage 2 + width rule, 150 test images | 127/150 (0.847); every width within 0.001 px of the training evaluation |
| Stage 2 detection confidence | mean 0.978, minimum 0.960, no missed detections |
| YOLO11n-presence trigger, 225 test images | 67/67 Class A, 83/83 Class B, 75/75 Unhealthy; ~210–245 ms per check |

The 2730.07 px threshold was chosen on validation data only (best macro-F1, 0.806, of 151 candidates). On the test
set, 70/75 Class A and 57/75 Class B were right; 17 of the 23 errors were within 200 px of the threshold. Real A
widths ran 2452–3774 px and B widths 2051–3304 px, so the classes overlap.

<!-- fig:widths -->

### 3.2 Speed and stability on the Pi (on-site run, 27 Oct 2026, 02:52–04:53)

Source: the Pi's own scan records (`inference_time_ms` and `stage_timings` per scan).

| Measure | Value |
|---|---|
| Scans | 96 in about two hours, of 95 bunches (one scan was later voided as a duplicate of the same bunch); the longest run after a service restart was 82 in a row, 03:26–04:53, including a 35-minute pause with no scans (03:39–04:14) |
| Stage 1 (YOLO11n-cls) | **35 ms** average |
| Stage 2 (YOLO11n detector, Healthy bunches only) | **184 ms** average |
| Whole scan, capture to grade decision | **0.24 s** average, 0.26 s median, 0.38 s slowest; 0 of 96 over 2 s |
| Drift over the 82-scan run | 233 ms average for the first 20 scans, 206 ms for the last 20 |
| CPU temperature | not logged for this run; the afternoon shift (38 scans) averaged 47.1 °C, peak 50.1 °C |

The scan time runs from the start of capture to the grade decision; the database write and the LED follow straight
after and are not timed. Before capture, a bunch must hold still for 400 ms, and the trigger (~0.2 s per check)
and hand check (~0.18 s) run on the preview, so placing a bunch to seeing the LED takes roughly 1 s in practice
(an estimate, not measured per scan).

<!-- fig:latency -->

### 3.3 On-site tests, 26–27 October 2026

Tested at the real rig in two shifts on 27 October, with different fruit:

- **First shift (02:52–04:53, 95 bunches): market-bought, ripening Cardava from Toril, Davao City** (not
  harvest-mature bunches from Davao del Norte). Scanner grades: **19 Class A, 58 Class B, 15 Rejected, 3 not
  graded** (2 Healthy below the Stage 1 confidence gate, 1 with no Stage 2 box). A 96th scan, a Class A duplicate of
  the same bunch, was voided and is not counted. The operator corrected six B
  bunches to A.
- **Second shift (15:22–15:59, 38 bunches): green, mature bunches.** Scanner grades: **14 Class A, 11 Class B,
  11 Rejected, 2 not graded** (both Healthy below the Stage 1 confidence gate; the operator rejected both for dark
  patches, black spots and bruises). No Class A/B grade was disputed.

These counts use the final rule (finding 6). The shifts themselves ran under the earlier rule, under which 2
Unhealthy results below 0.80 in the first shift (13 Rejected, 5 not graded) and 3 in the second (8 Rejected,
5 not graded) were "not graded"; the stored records were re-graded on 27 Oct.

<!-- fig:onsite -->

Problems found and fixed in the app:

- A white sheet of paper was graded **Class B** three times → banana-colour check (by hue, inside the box).
- Auto white balance turned the sheet blue and it slipped past a saturation check → hue check + white balance locked
  from the sheet.
- A flat hand on a desk was graded **Class A** (Stage 1 Healthy 0.807, Stage 2 box 0.75) → 0.90 Stage 2 minimum
  (every held-out A/B bunch scores ≥ 0.96).
- Hands in view at capture → COCO hand check.
- The same bunch rescanned when straightened → 3 s release rule; start "held" after restart.
- Autofocus on velvet wandered → lens held at 0.99 dpt.
- The rig leaned **17.9°**, so a bunch looked up to 15% wider at the bottom of the view → camera alignment check.
- The rig was brighter and bluer than the dataset photos → white balance and brightness calibration.
- A "Clear all scans" button deleted photos for good → replaced by **void**, which can be undone.

Findings the paper should state:

1. **Width is a stand-in for finger length.** The standard measures one finger (Class A ≥ 12 cm); the scanner
   measures the whole bunch's width in pixels. The best case on the test set is 84.7%.
2. **The cutoff encodes the dataset's bunches.** The dataset's Class A came from Kapalong and nearly fill the view;
   Class A bought in Toril is smaller, so the cutoff grades it B.
3. **Camera height must match the dataset to the centimetre.** Re-grading the test photos as if taken from other
   heights: 41 cm → 68%, 43 cm → 77%, **45 cm → 85%**, 47 cm → 83%.
4. **Stage 1 does not recognise overripe or bruised fruit.** In the first shift, ripening market fruit with black
   patches was called Healthy at 95–99.6%. Either retrain with such examples or state the system is for harvest-mature green fruit.
5. **The trigger fires on non-bunches** (paper 0.93, a hand; 0.91 on an empty cluttered desk). The app's checks stop
   these; retraining with "no bunch" photos would fix it at the source.
6. **Unhealthy is Rejected at any confidence (applied 27 Oct).** Only a Healthy result below 0.80 goes for a hand
   check. On the rig, five Unhealthy results fell below 0.80 (0.55–0.79): two in the first shift and three in the
   second, where the operator rejected all three for black spots, bruises or lesions. On the 225 test photos nothing
   changes: the only result below 0.80 is Healthy (Class_B_771, 0.784). The five stored scans were re-graded to
   Rejected.

<!-- fig:height -->

## 4. Hardware and software as deployed

| Part | Detail |
|---|---|
| Computer | Raspberry Pi 5, 8 GB, active cooler (hostname `cardavapi`) |
| OS and runtime | Raspberry Pi OS (Debian 13 trixie), Python 3.13, PyTorch 2.14.1+cpu, Ultralytics 8.4.175, OpenCV 5.0.0 |
| Camera | Camera Module 3 (IMX708), 4608×2592 capture, 640×360 preview, lens fixed at 0.99 dpt |
| Rig | 45 cm overhead, ring light, black velvet |
| Models | `stage1_best.pt` (YOLO11n-cls), `stage2_best.pt` (YOLO11n), `best.pt` (YOLO11n-presence trigger), `yolo11n.pt` (stock COCO, hand check) |
| Stage 1 / 2 settings | trial 04 (lr 0.000849, batch 8, wd 0.000605, dropout 0.143204) / trial 02 (lr 0.000867, batch 4, wd 0.000763); AdamW, seed 42; deployed files byte-identical to the final runs |

## 5. Paper check: running document v14 against the system

**Already fixed in v14 (good):** the centimetre wording in §3.3.7, §3.4.1 (now D(x) = h(w(x)) with ≥), §3.5.4
(no size rejection), §3.10.3, §3.12 and §4.4.3; §3.6.5 now says Raspberry Pi GPIO; the table of contents; the
Stage 1 selection rule (§3.7.4, §4.3.4); §4.7 now has numbers.

**Still to fix:**

1. **Stage 1 input is the raw frame, not the masked image.** Still says masked in the Abstract ("RGB to HSV …
   prior to Stage 1 inference"), §1.5.4, §1.6, Figure 2, §3.3.7 ("masked RGB image serves as the model input for
   Stage 1"), §3.4.1 first sentence, §3.6.2 (OpenCV for background subtraction), §3.6.4 (2nd and 3rd paragraphs) and
   §4.7 ("including the HSV preprocessing"). §4.4.1 already describes plain 224×224 resizing, so the paper
   contradicts itself. Suggested wording: *"Stage 1 receives the raw frame resized to 224 × 224. HSV masking was used
   offline only, to generate the Stage 2 whole-bunch box labels."*
2. **§4.7 stage times do not match the Pi's records.** It says Stage 1 72 ms and Stage 2 168 ms; the records give
   **35 ms** and **184 ms** (section 3.2). The 0.26 s matches the median (mean 0.24 s). The timer stops at the grade
   decision, so "to the final LED classification signal" and "including … SQLite database logging" overstate it.
   "96 bunches" were 96 scans of 95 bunches (one duplicate was voided). 82 in a row and 233 → 206 ms are
   confirmed. "1 hour 39 minutes" could not be confirmed: the 82 scans span 03:26–04:53 (1 h 26 min between first
   and last scan, including a 35-minute pause). 790 MB RAM and "no throttling" are not in the records.
3. **Chapter 5 drafting note and §5.1.2 placeholders.** The note says §4.7 still has placeholders; it no longer
   does. Fill §5.1.2 with: Stage 1 35 ms, Stage 2 184 ms, 0.24 s average (0.26 s median); 96 scans (95 bunches) in about two
   hours, 82 consecutive without crashes; temperature 47.1 °C average / 50.1 °C peak from the 38-scan afternoon
   shift (or drop temperature); verdict **meets** the 2 s target. Then delete the drafting note.
4. **Autofocus.** §1.6 and §3.6.3 say "autofocus locked after initial focusing". The system now holds the lens at a
   fixed 0.99 dioptres measured at 45 cm, because autofocus on bare velvet locked anywhere from 0.69 to 1.31.
5. **Figure 1** still says "Flask & Chart.js" (it is FastAPI) and "Cropped and Isolated" (nothing is cropped).
   **Figure 2** still says "Stage 1: Disease Classification" and HSV background removal.
6. **YOLO11n-presence has no methods or results.** §3.6.4 says only "the YOLO11n model". Add its training data and
   settings (from the trainer), the 400 ms stability rule, and the 225/225 held-out trigger result (section 2.1).
7. **Runtime safeguards are not described.** The deployed system has a fourth outcome, "not graded" (Stage 1 Healthy < 0.80,
   no Stage 2 box or < 0.90, error), plus the banana-colour and hand checks and the 3 s release. Add a short
   subsection after §3.6.4; say the offline D(x) has three outcomes and the deployed one adds "not graded".
8. **On-site findings are missing.** Chapter 4 has no on-site observations and §5.2.1 does not mention overripe
   fruit, the Kapalong vs Toril size difference, camera tilt or height sensitivity (section 3.3). Also say which
   fruit each shift used: the first shift's market fruit came from Toril, outside the Davao del Norte scope of
   §3.3.1; the second shift used green, mature bunches.
9. **Table 7 lists only the training laptop.** §3.6.2 asks for the Pi versions to be distinguished; add the row
   from section 4 (Debian 13, Python 3.13, PyTorch 2.14.1+cpu, Ultralytics 8.4.175, OpenCV 5.0.0).
10. **Data collection count (§3.3.2–3.3.3).** Still says 1,500 collected and 1,500 kept after removing blurry
    photos. Kept filenames go up to Class_A_695, Class_B_873, Rejected_612. §3.3.3 also says all 1,500 were hand
    masked, but the repo notes say no cleaned images were made for the Rejected class. Confirm both with whoever
    collected and masked the photos.
11. **§5.2.2 recommendations partly exist already:** low-confidence Healthy results are already held for a hand check
    ("not graded"), the camera alignment check exists, and the dispute → retraining loop exists. Say so, and keep
    the rest as future work.

## 6. Still open (do not report numbers for these yet)

- A sustained run of at least 2 hours with CPU temperature logged for the whole run.
- Acceptance test with 30 hand-labelled bunches (10 Healthy A, 10 Healthy B, 10 Unhealthy), ideally fresh
  harvest-mature fruit, with finger lengths measured.
- Trigger false-trigger count on the rig (empty velvet, hands, tools); LED wiring sign-off; levelling the camera.
- Reboot, power-loss and Wi-Fi-loss recovery; backup and export checks.

## 7. Known limitations (for §5.2.1)

- Size is a pixel width at a fixed 45 cm; changing camera height, tilt or zoom invalidates the threshold.
- A/B errors cluster near the threshold (15.3% of test bunches wrong).
- Stage 1 was trained on green fruit; ripening or bruised fruit is outside its training data.
- The trigger's train/test split is unconfirmed; if the 225 test photos were in its training set, 225/225 is optimistic.
- No operator login; acceptable only on a closed network. One bunch at a time; sorting is still by hand.
