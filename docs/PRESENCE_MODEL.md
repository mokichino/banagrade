# Building the YOLO11n-presence model

> **Status (2026-10-26): trained and in use.** `models/presence/best.pt` is the trigger. It fires for all
> 225 held-out bunches, but on a cluttered desk it fired at 0.91 with no bunch and 0.83 on a hand. If it
> also fires on the empty velvet or on hands at the rig, redo step 1 (hands, empty velvet and objects
> photographed on the rig) and retrain. The tables below compare against Stage 2 alone, the trigger
> before this model.

This guide builds the missing model. Stage 1, Stage 2 and all their results stay unchanged.

| | |
|---|---|
| Model | YOLO11n detector, one class: `banana_bunch` (any bunch: Class A, Class B or Rejected) |
| Data | The same 1,500 photos and train/val/test split as Stage 1, plus about 150 empty-table photos |
| Training | The Stage 2 final settings, on the GPU PC (about 80 minutes) |
| Done when | It finds every held-out bunch of all three classes at the trigger's settings, and never fires on an empty table |

## Step 1. Photograph the empty table (about 30 minutes, at the rig)

A presence model must also learn what "nothing there" looks like, and every one of the 1,500 photos
contains a bunch. Take about **150 photos with no bunch on the table**, using the Pi camera at the same
45 cm mount and ring light. On the dashboard: **System Status → Full-resolution snapshot**, then save
the image.

Vary what is in frame so the trigger learns to ignore it:

| What to photograph | How many |
|---|---|
| Empty velvet, ring light on | 40 |
| Empty velvet, ring light dimmer or off, room lights changed | 20 |
| A hand or arm reaching in, no bunch | 40 |
| Things that end up on the table: a knife, a crate edge, a cloth, a phone, leaves | 30 |
| Loose fingers or debris without a whole bunch | 20 |

Save them as `Background_001.jpg` … `Background_150.jpg` in `dataset/raw/Background/`. These photos
get **no box**; YOLO treats an image with an empty label file as "nothing to detect".

## Step 2. Reuse the 1,000 Class A and B boxes (no work)

`training/stage2_annotation_preview/stage2_annotation_record.csv` already has a checked whole-bunch box
for every Class A and Class B photo. They were made from the cleaned black-background images and
reviewed when Stage 2 was built. Use them unchanged.

Do not re-run the HSV box generator on the raw photos. Tested on the 269 photos available on the Pi,
it reproduced only 1 of the recorded boxes (median overlap 0.44): wherever the velvet is lit or the
floor shows, the "box" becomes the whole photo.

## Step 3. Box the 500 Rejected photos (about 1–2 hours of checking)

No cleaned images were made for the Rejected class, so these photos have no boxes yet. Let the
existing Stage 2 detector propose them, then check every one by eye:

1. **Propose:** run `training/prelabel_presence.py` on the GPU PC. For each Rejected photo it runs
   `runs/stage2_final/weights/best.pt` at 640 px with confidence ≥ 0.25 and writes a YOLO label file.
   It also writes contact sheets (12 photos per page, box drawn) and a `prelabel_review.csv` listing
   each photo with its proposed box and confidence.
2. **Check:** page through the contact sheets. In `prelabel_review.csv`, mark each photo `ok` if the
   box hugs the whole bunch (all fingers and the crown, not the shadow), or `fix` if it doesn't.
3. **Fix:** open only the `fix` photos and the ones with no proposal in a labelling tool that exports
   YOLO format (CVAT, Label Studio or makesense.ai), draw one box around the whole bunch, and export.

On the 75 held-out Rejected photos, the detector proposed a box for 67. On the 269 A/B photos it was
checked against, 266 of its boxes overlapped the recorded box by 0.90 or more. Expect to draw about
**55 of the 500 boxes by hand** and confirm the rest with a glance.

## Step 4. Assemble the dataset

Run `training/prepare_presence.py`. It:

- uses `training/stage1_split_record.csv` for the split, so all 1,500 photos keep the Stage 1 split
  (train 1,050, val 225, test 225; the test set has 67 Class A, 83 Class B and 75 Rejected). The
  presence test set is therefore the same 225 held-out photos used for Stage 1.
- splits the background photos 70 / 15 / 15 the same way (`random_state=42`).
- writes `dataset/presence_det/{train,val,test}/{images,labels}` and `data.yaml` with one class,
  `banana_bunch`.
- refuses to run if any of the 1,500 photos has no label file, so a missed Rejected box cannot slip
  through.

## Step 5. Train (about 80 minutes on the GPU)

Run `training/train_presence_final.py`. It is `train_stage2_final.py` with the dataset and output
paths changed. Everything else is identical: YOLO11n from `yolo11n.pt`, 640 px, 50 epochs, batch 4,
AdamW, lr 0.000867, weight decay 0.000763, seed 42 and the same flip, brightness, contrast and noise
augmentations. The task is the same as Stage 2 (one whole-bunch box per photo), so its tuned settings
are reused rather than running a new search. Say this in the thesis.

Output: `runs/presence_final/weights/best.pt`. Copy it to the repo as
`models/presence/presence_best.pt`.

## Step 6. Test it the way the app will use it (about 10 minutes, can run on the Pi)

`training/test_presence_final.py` runs the model exactly as the trigger does: each test photo is
shrunk to the 640×360 preview, then detected at 640 px with confidence ≥ 0.80. It reports:

| Measure | Pass | Current trigger (Stage 2 detector) |
|---|---|---|
| Class A bunches detected | 67 / 67 | 67 / 67 |
| Class B bunches detected | 83 / 83 | 83 / 83 |
| **Rejected bunches detected** | **75 / 75** | **66 / 75** |
| Empty-table test photos with a false detection | 0 of about 23 | not measured |
| mAP50-95 on the test set | report it | — |
| Time per check on the Pi 5 | about 225 ms | 224 ms |

Both columns use the same 225 held-out photos, so the comparison is direct.

If any Rejected bunch is still missed, look at it before retraining: a bunch cut off by the frame edge
or a very dark bunch may need a few more examples like it in the training set.

## Step 7. Put it in the app (Claude)

- Restore the `BANAGRADE_PRESENCE_MODEL` setting (removed on 2026-10-25 while no model existed),
  pointing at `models/presence/presence_best.pt`, and use it for the trigger and the preview box.
- The loader checks that it is a detector with the single class `banana_bunch`. If the file is
  missing, the app falls back to the Stage 2 detector and shows the presence model as **Missing** on
  System Status, so grading never stops.
- System Status lists three models; the release note gets the new SHA-256.
- Re-run the backend tests, then the on-site checks in `ON_SITE_TESTS.md` §3–4. The "No capture" row
  should drop to 0.

## Step 8. Update the thesis

- **Chapter 3:** a short subsection on the presence model: its purpose, the 1,500 photos plus 150
  empty-table photos, the labelling method (recorded A/B boxes, detector-proposed and hand-checked
  Rejected boxes), and the reused Stage 2 settings.
- **Chapter 4:** the Step 6 table, including the comparison with the Stage 2 detector as trigger,
  which is the reason the model exists.
- The architecture figure is already correct. Remove item 12 from section 6 of
  `QUALITY_CHECKLIST.md` once the text describes a model that now exists.

## Who does what

| Step | Who | Where |
|---|---|---|
| 1. Empty-table photos | Team, at the rig | Pi camera |
| 2. Reuse A/B boxes | — | — |
| 3. Rejected boxes: propose / check / fix | Script, then a teammate | GPU PC |
| 4. Assemble dataset | Script | GPU PC (it has the full 1,500 photos) |
| 5. Train | Groupmate who trained Stage 2 | GPU PC |
| 6. Test | Script | Pi or GPU PC |
| 7. App integration | Claude | Repo |
| 8. Thesis text | Team | Thesis document |

The scripts named in steps 3–6 (`prelabel_presence.py`, `prepare_presence.py`,
`train_presence_final.py`, `test_presence_final.py`) still need to be written. They follow the
existing Stage 2 scripts in `training/`.
