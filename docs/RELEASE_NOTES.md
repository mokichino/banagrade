# Banagrade 1.0.0 release note

Released 2026-10-25 for the Raspberry Pi 5 edge deployment (`cardavapi`). This note records what is
deployed, how it was verified and what it does not do. `QUALITY_CHECKLIST.md` traces each feature to
the thesis.

## Models

| Stage | File | Architecture | Task | SHA-256 |
|---|---|---|---|---|
| 1 | `models/stage 1/stage1_best.pt` | YOLO11n-cls | Healthy / Unhealthy | `f75fc364fdca64c1ccece94d15680f466de843c54bf9bc3d097e375604cd36ec` |
| 2 | `models/stage 2/stage2_best.pt` | YOLO11n detect | `banana_bunch` | `863b3d1f582b84d99bd7f656a841aae6b71cf92d0777b972fcdbb388b8a8ce9c` |
| Trigger | `models/presence/best.pt` | YOLO11n-presence, trained by the team (2026-10-26, run `presence_final`, Stage 2 settings) | `banana_bunch` (all grades) | `5d800e003143ae5734f2344004896da570ef49a129efa7464de1c3cd3b450c25` |
| Fallback trigger (unused) | `models/presence/yolo11n.pt` | YOLO11n detect, stock COCO-pretrained | COCO class 46 `banana` | `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` |

Both files are byte-identical to `training/runs/stage1_final/weights/best.pt` and
`training/runs/stage2_final/weights/best.pt`. Stage 1 uses tuning trial 04 (lr 0.000849, batch 8,
weight decay 0.000605, dropout 0.143204). Stage 2 uses trial 02 (lr 0.000867, batch 4, weight decay
0.000763). Both used AdamW and seed 42.

The capture trigger is the team's trained **YOLO11n-presence** detector (`best.pt`, one class
`banana_bunch`, trained from `yolo11n.pt` with the Stage 2 final settings on bunches of all three
grades). It runs on the 640×360 preview at 640 px with confidence ≥ 0.80, and a bunch must hold still
in frame for 400 ms. On the 225 held-out photos it fires for 67/67 Class A, 83/83 Class B and 75/75
Unhealthy bunches (lowest confidence 0.93), at about 210–245 ms per check. It is the only trigger model,
so an empty-table check costs one model instead of two. Each preview frame is first compared with the
last frame the detector ran on (a 160×90 greyscale copy, about 2 ms). If less than 0.5% changed, an
empty table or a held bunch reuses the last answer, with a forced check every 2 s. A bunch that was
seen but not yet captured is always re-checked. `/api/system/status` reports
`pipeline.trigger.model_checks` and `skipped_unchanged`. The preview on System Status draws the
trigger's box, the model that drew it and the status.

History: the trigger first ran Stage 2 alone at 320 px and fired for 1 of 225. At 640 px Stage 2 missed
9 of 75 Unhealthy bunches, because its boxes covered only Class A and B. A stock COCO YOLO11n then
backed it up for a day; it caught all 225 but mistook an open palm for a banana. The app still supports
that mode (`BANAGRADE_PRESENCE_MODEL` pointing at `yolo11n.pt`, with the hand guard), and falls back to
Stage 2 alone if no presence model loads.

## Grading rule

- Stage 1 Unhealthy → **Rejected**. Stage 2 does not run.
- Stage 1 Healthy → horizontal bounding-box width in the 4608×2592 frame. **≥ 2730.07 px is Class A**,
  otherwise **Class B**.
- Stage 1 confidence below 0.80, no Stage 2 box or a box below 0.90 confidence, or a runtime error →
  **technical failure**. Every held-out Class A/B bunch scored at least 0.96 on Stage 2. A flat hand on
  a desk passed the trigger and Stage 1 (0.807) and was graded Class A from a 0.75 box. The 0.90 gate
  stops that without losing any held-out bunch. It is
  stored and shown, but excluded from acceptance and rejection rates.

The 2730.07 px threshold was chosen on the validation set only. Out of 151 candidate boundaries it had
the highest macro-F1 (0.806); the test set was not used to choose it. It is an image-space boundary,
not a centimetre measurement.

## Held-out test results through the app's own code

| Check | Result |
|---|---|
| Stage 1, 225 test images | 224 / 225 correct (0.9956), Unhealthy recall 0.987, 1 image below the 0.80 gate |
| Stage 1 confidence | mean 0.997, median 1.000 |
| Stage 2 + width rule, 150 test images | 127 / 150 correct (0.847). Every width matches the training evaluation within 0.001 px. The errors are bunches near the threshold. |
| Stage 2 detection confidence | mean 0.978, minimum 0.960, no missed detections |

These test-set numbers are also the baselines for the drift indicators.

## Automated tests (2026-10-25)

- Backend: `python -m pytest backend/tests -q`, **75 passed**.
- Frontend: `npm test`, **18 passed**, covering grade logic, LED mapping, PDF export, and the empty
  and error states of the dashboard, history and status pages. `npm run build` succeeds.

Runtime: Debian 13 (trixie), Python 3.13, torch 2.14.1+cpu, Ultralytics 8.4.175, OpenCV 5.0.0,
Node 20.19 (build only).

## Configuration

Every variable, with its default, is listed in `backend/.env.example`. Production values live in
`/etc/banagrade/banagrade.env`. These are the ones that change behaviour:

| Variable | Default | Effect |
|---|---|---|
| `BANAGRADE_WIDTH_THRESHOLD_PX` | 2730.07 | Class A / B boundary |
| `BANAGRADE_STAGE1_MIN_CONF` | 0.80 | Below this, a scan is a technical failure |
| `BANAGRADE_STAGE2_MIN_CONF` | 0.90 | A Stage 2 box below this is a technical failure, not a grade |
| `BANAGRADE_STAGE1_MASK` | 0 | HSV mask before Stage 1. Keep at 0: the model was trained on raw frames and masking lowers test accuracy to 0.911. |
| `BANAGRADE_MIN_BRIGHTNESS`, `BANAGRADE_MIN_CONTRAST` | 8, 1.5 | Fast-red "camera blocked / poor lighting" error. Tune on site. |
| `BANAGRADE_ENABLE_GPIO` | false | Drive the physical LEDs (BCM `BANAGRADE_LED_*`: green 17, yellow 27, blue 22, red 23) |
| `BANAGRADE_FRAME_KEEP` | 1000 | Frames archived for disputes (~0.9 MB each). 0 disables. |
| `BANAGRADE_DRIFT_WINDOW`, `BANAGRADE_DRIFT_MIN_SAMPLES` | 200, 30 | Drift indicator window |
| `BANAGRADE_BACKUP_KEEP` | 14 | Nightly database backups kept |

## Retraining loop

1. An operator disputes a scan on **Recent Scans** and enters the correct grade. The scan's frame is
   copied to `/var/lib/banagrade/retrain`, and the model's original grade is kept with the dispute.
2. **System Status → Model drift** compares the latest 200 scans with the test-set baselines above. A
   warning means conditions on the table have changed, for example lighting, the lens or the cultivar.
   It never changes a grade.
3. **Export disputed frames** downloads a zip of the frames, sorted by corrected grade, with a
   `labels.csv` (model grade, corrected grade, confidences, width).
4. A reviewer checks every label before it enters the training set. Operator corrections are not used
   unreviewed.
5. Retrain with the scripts in `training/`, re-run the held-out checks, and deploy only if they are at
   least as good as the table above. Then record the new hashes in this note.

## Known limitations

- **The presence model fires on scenes that are not the rig.** Pointed at a cluttered desk, it scored
  0.91 on the empty desk and 0.83 on a hand lying on a laptop, both above the 0.80 trigger. It was
  trained on photos of the velvet rig, and whether its training set included "no bunch" photos (empty
  velvet, hands, tools) has not been confirmed. A false trigger costs at most a technical failure: a
  hand cannot be graded Class A or B because grading needs a Stage 2 box of 0.90 or more. Measure it on
  the rig (`ON_SITE_TESTS.md` §3). If it fires on the empty velvet or on hands there, retrain it with
  "no bunch" photos taken on the rig (`PRESENCE_MODEL.md` step 1).
- **The presence model's train/test split is unconfirmed.** If it used the Stage 1 split, the 225/225
  result is held-out. If those 225 photos were in its training set, the result is optimistic.
- **No operator login.** Anyone on the local Wi-Fi can open the dashboard, start a shift, file
  disputes and void scans. This is acceptable on a closed farm network: nothing on the dashboard deletes
  a scan, and every dispute and void can be undone. Add authentication before exposing the Pi to a
  wider network.
- **The physical checks are still open.** LED wiring, the 45 cm mount and lighting, brightness tuning
  on the black velvet, the acceptance test with known bunches, reboot and Wi-Fi recovery, and the §4.7
  sustained run are in `ON_SITE_TESTS.md`.
- **Class A / B errors cluster at the threshold.** 15.3% of test bunches (23 of 150) were graded wrong.
  17 of the 23 were within 200 px of 2730.07 px, and the furthest was 574 px away. Disputes are the remedy, and the drift indicator
  only warns above 25%.
- **Size is a pixel width at a fixed 45 cm distance.** Moving the camera or changing the zoom
  invalidates the threshold.
- Disputes recorded before this release have no stored model grade, and live scans before this
  release have no archived frame.
- One camera and one bunch at a time; no conveyor integration.
