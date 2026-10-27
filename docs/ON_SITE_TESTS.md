# Banagrade on-site tests

These checks close the open hardware items in `QUALITY_CHECKLIST.md` and produce the numbers for
thesis §4.7. Do them in this order at the real sorting table. Fill in every blank, then send the
filled-in copy back so the checklist can be ticked against it.

Run commands from a laptop on the same Wi-Fi, or over SSH on the Pi. `PI` below is
`http://cardavapi.local:8000`.

| | |
|---|---|
| Date | |
| People present | |
| Location | |

## 1. Mount, lighting and backdrop

1. Measure from the camera lens to the velvet surface with a tape measure. It must be the same 45 cm
   used when the dataset was photographed; the 2730.07 px threshold is only valid at that distance.
2. Check the camera is level and the ring light is centred on the lens.
3. Open **System Status** and look at the camera preview. The velvet should fill the frame with no table
   edge or floor showing.
4. Read **Lens focus** on the camera card. It should say `Fixed · 0.99 dpt (set at 45 cm)`. The lens is held
   there instead of autofocusing at boot, because autofocus on the bare velvet locked anywhere from 0.69 to
   1.31 dpt. 0.99 is what this camera read with a printed target at a tape-measured 45 cm (0.983, 0.989,
   1.012 on 2026-10-26). Its lens positions do not follow 1 ÷ metres, so do not expect 2.2.
5. Lay a short bond sheet (27.9 × 21.6 cm) flat in the middle of the velvet and press **Check camera
   alignment** on the camera card. It outlines the sheet and reports the front–back and side tilt from the
   lengths of its opposite edges, and the height at the sheet (approximate, from the camera's published field
   of view). Adjust until both tilts read "Level" (opposite edges within 2%, about 2.5°). A tilt makes the
   same bunch look wider in one part of the view: on 27 Oct the rig leaned 17.9°, so a bunch looked 15%
   wider at the bottom of the view than at the top. On the test set, 2 cm of height error costs about 8
   points of A/B accuracy. After replacing the camera or its mount, find the
   new lens position: set `BANAGRADE_LENS_POSITION=auto`, restart with the sheet in view a few times, and put
   the average back into `BANAGRADE_LENS_POSITION`.
6. With the sheet still in place, press **Set white balance from sheet**: it locks the colour so the sheet is
   neutral, as the dataset's backdrop is. Then put a fresh green bunch in the middle and press **Match dataset
   brightness** (not ripe market fruit, which is naturally brighter). Both stay set after a restart; **Reset**
   returns to automatic.
7. Remove the sheet. The trigger boxes it, but the preview labels it "Not a bunch · no banana colour" and
   nothing is captured.

| Check | Result |
|---|---|
| Lens-to-velvet distance (cm) | |
| Camera level, ring light centred (yes / no) | |
| Velvet fills the preview (yes / no) | |
| Lens focus on the camera card | |
| Paper size in the snapshot (px) | |

## 2. LED wiring

In `/etc/banagrade/banagrade.env` set `BANAGRADE_ENABLE_GPIO=true`, then run
`sudo systemctl restart banagrade`. With no bunch on the table, run:

```bash
curl -X POST "$PI/api/demo/led-test"
```

The LEDs step through the sequence below and then return to green. If the colours are swapped, fix
the wiring, or set `BANAGRADE_LED_GREEN/YELLOW/BLUE/RED` to the BCM pins actually used and restart.

| Step | Expected | Seen (✓ / what happened) |
|---|---|---|
| Ready, 1.5 s | Green steady | |
| Capture, 1 s | All LEDs flash | |
| Class A, 2 s | Yellow | |
| Class B, 2 s | Blue | |
| Rejected, 2 s | Red | |
| Booting, 3 s | Red slow blink | |
| Error, 3 s | Red fast blink | |
| End | Green again | |

Pins used (BCM), if not 17 / 27 / 22 / 23: ______

## 3. Brightness and contrast thresholds

The fast-red error fires when the preview's mean brightness falls below `BANAGRADE_MIN_BRIGHTNESS`
(lens dark) or its contrast falls below `BANAGRADE_MIN_CONTRAST` (lens covered). The empty black velvet
is dark on purpose, so both limits must sit below the empty-table reading and above the faulty
readings. For each condition, wait 3 s, then read the values:

```bash
curl -s "$PI/api/system/status" | python3 -c "import json,sys; print(json.load(sys.stdin)['pipeline']['camera']['illumination'])"
```

| Condition | mean_brightness | contrast | status |
|---|---|---|---|
| A. Empty velvet, ring light on | | | |
| B. A bunch on the velvet, ring light on | | | |
| C. Ring light off | | | |
| D. Lens covered by hand | | | |

Set `BANAGRADE_MIN_BRIGHTNESS` halfway between the brightness of A and C. Set
`BANAGRADE_MIN_CONTRAST` halfway between the contrast of A and D. Restart the service, then confirm:

| Confirmation | Result |
|---|---|
| Chosen MIN_BRIGHTNESS / MIN_CONTRAST | |
| Empty velvet for 5 minutes: no fast red (yes / no) | |
| Empty velvet, then a hand and then tools moved through the frame for 5 minutes: no box on the preview and no scan recorded (yes / count) | |
| Idle trigger counters after 5 minutes of empty table (`curl -s "$PI/api/system/status" \| python3 -c "import json,sys; print(json.load(sys.stdin)['pipeline']['trigger'])"`): skipped_unchanged should be several times model_checks | |
| Lens covered: fast red within 1 s, clears when uncovered (yes / no) | |
| Ring light off: fast red, clears when switched on (yes / no) | |

## 4. Acceptance test with known bunches

Before starting, have the person who labelled the dataset grade **10 Healthy Class A, 10 Healthy
Class B and 10 Unhealthy** bunches by hand, using the same criteria as the dataset. Number them 1–30
with a tag that isn't visible from above. Start a new shift on the dashboard, then place each bunch
in the middle of the velvet. Wait for the LED, write down the result and remove the bunch. If a bunch
comes out as a technical failure, place it once more and record both attempts. If the LED stays
green for 5 seconds with the bunch on the table, record **no capture**. The live preview on System
Status shows whether the trigger saw it (a box appears) or not (no box).

| # | Hand label | LED / dashboard result | Correct? | Notes |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| … | | | | |
| 30 | | | | |

How to read it (held-out test set for comparison):

- **No capture:** expect 0 of 30. The YOLO11n-presence trigger fired for all 225 held-out bunches,
  including all 75 Unhealthy, so note any bunch that is not captured.
- **Unhealthy → Rejected:** expect 10 / 10 of the bunches that were captured. The test set had Unhealthy recall 0.987. A miss means a
  diseased bunch would be exported, so record which bunch it was.
- **Healthy never Rejected:** expect 0 of 20 rejected. The test set had none.
- **Class A vs Class B:** the test set scored 84.7%, so about 17 / 20 is in line. Most errors were
  close to the threshold; note in the Notes column any bunch that looked borderline by hand.

| Result | Count |
|---|---|
| Unhealthy rejected | / 10 |
| Healthy rejected (should be 0) | / 20 |
| Class A / B correct | / 20 |
| Technical failures (first attempt) | / 30 |
| No capture (LED stayed green) | / 30 |

Dispute every wrong result on **Recent Scans** with the hand label. This tests the dispute flow and
puts the frames into the retraining export.

## 5. Reboot and power recovery

With no bunch on the table:

1. Note the scan count on the dashboard, then run `sudo reboot`. Start a stopwatch.
2. Record when the LED goes from slow red (booting) to green, and when the dashboard opens again.
3. Check that the same shift is still open and the scan count is unchanged.
4. Repeat by pulling the power plug while idle, then plugging it back in.

| Check | `sudo reboot` | Power pulled |
|---|---|---|
| Seconds to green LED | | |
| Seconds to dashboard reachable | | |
| Same shift, same scan count (yes / no) | | |
| System Status: camera Online, both models Loaded, autofocus locked | | |

## 6. Wi-Fi loss

1. Switch off the Wi-Fi router or hotspot for 2 minutes. The dashboard will show disconnected.
2. While it's off, grade two bunches. The LEDs must still work.
3. Switch the Wi-Fi back on. Within a minute the dashboard should reconnect by itself and show both
   scans.

| Check | Result |
|---|---|
| LEDs graded both bunches while offline (yes / no) | |
| Dashboard reconnected without reloading (yes / no, seconds) | |
| Both offline scans listed (yes / no) | |

## 7. Sustained run for §4.7

Run a real shift of at least 2 hours and at least 100 bunches. Start a new shift on the dashboard. On
the Pi, start the telemetry sampler as a background unit so it keeps running if SSH drops:

```bash
sudo systemd-run --unit banagrade-shift-sample -p User=banagrade -p WorkingDirectory=/opt/banagrade/backend \
  /opt/banagrade/.venv/bin/python scripts/shift_report.py sample --out /var/lib/banagrade/shift_telemetry.csv
```

At the end of the shift, stop the sampler, close the shift on the dashboard, and run the report:

```bash
sudo systemctl stop banagrade-shift-sample
cd /opt/banagrade/backend
sudo -u banagrade ../.venv/bin/python scripts/shift_report.py report --telemetry /var/lib/banagrade/shift_telemetry.csv
```

The report prints the scan counts, run length, end-to-end, Stage 1 and Stage 2 latency, the share
under 2 s, CPU temperature and restarts. It also checks that the dashboard totals match SQLite. That
check is the "reconcile dashboard totals" item and must print `Dashboard totals match SQLite.`

Paste the full report output here:

```
```

## 8. Backup and exports

```bash
sudo systemctl start banagrade-backup
journalctl -u banagrade-backup -n 3 --no-pager
```

| Check | Result |
|---|---|
| Backup log ends with `ok {...}` and the row counts | |
| `systemctl list-timers banagrade-backup` shows the next run | |
| Recent Scans → Export CSV with All grades: row count matches the shift's scan total | |
| Recent Scans → Export PDF opens and lists the filtered rows | |
| System Status → Export disputed frames: zip has the section 4 disputes with frames | |
