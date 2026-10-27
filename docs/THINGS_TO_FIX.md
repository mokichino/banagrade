# Things to fix

Open problems found during the on-site tests on 26–27 Oct 2026, most important first. Each item says what
was seen, why it matters and what to do. Tick it off here when it is done, and move anything that becomes a
decided limitation to `RELEASE_NOTES.md`.

## How Class A and Class B are decided

Two different measurements are involved, and they do not always agree.

| | What is measured | Class A if |
|---|---|---|
| **Official standard** (thesis Table 1 / Table 5) | Length of one finger: the middle finger of the outer row, along its outer curve, from the tip to where the stalk joins the fruit (stalk not included) | ≥ 12 cm ("large hand"); Class B is 8–12 cm |
| **The scanner** (thesis §4.4.3) | Horizontal width of the whole bunch in the photo: Stage 2's box, from the leftmost to the rightmost finger tip, in the 4608 × 2592 frame | ≥ 2730.07 px, roughly 33 cm across at the 45 cm rig height |

The scanner never measures finger length, thickness or the height of each banana. Bunch width is a stand-in:
bunches with longer fingers usually fan out wider. The cutoff was chosen on the validation photos as the
width that best separated the team's A and B labels. On the 150 held-out test photos it matched the label on
127 (84.7%): 70 of 75 Class A were graded A, but 18 of 75 Class B were graded A. Widths of real A bunches
ranged from 2452 to 3774 px and of B bunches from 2051 to 3304 px, so 114 of the 150 fall in the range where
both classes occur.

**For disputes, the finger length is the truth.** A B → A dispute must give the measured finger length, for
example "Class A by size: middle finger 12.5 cm, outer curve, tip to stalk joint". A bunch can have 12.5 cm
fingers yet measure narrow when its fingers curl inward or it has few of them.

## Grading

1. **Width alone cannot separate A from B well.** See above: 84.7% at best on the test set, and on-site the
   operator corrected six B bunches to A. Fixing this means changing the thesis method (for example also
   measuring finger length from the box or the mask, or counting fingers) and retraining or re-validating.
   Until then, report the width method's on-site agreement with measured finger length as a result.
2. **Camera height has to match the dataset to the centimetre.** Re-grading the test photos as if taken from
   other heights: 43 cm gives 77% accuracy, 45 cm 85%, 47 cm 83%, 41 cm 68%. The tape says 45 cm, the
   paper-snapshot estimate said 42–46 cm. Ask the groupmate who shot the dataset exactly how the 45 cm was
   measured (from the lens glass, the camera board or the mount) and measure the rig the same way. Better
   still, photograph the same short bond sheet on the original setup if it still exists, so the pixel widths
   can be compared directly.
3. **The camera must look straight down.** On 27 Oct the rig leaned 17.9° front to back, then 6.5° front to
   back and 3.6° to the side after adjustment: the same bunch looked up to 15% wider at the bottom of the view
   than at the top. Use **Check camera alignment** on the camera card with the sheet in the middle and adjust
   until both tilts read "Level".
4. **Done 2026-10-27: doubtful Stage 1 results.** An Unhealthy result is now Rejected at any confidence
   (thesis rule "Unhealthy → Rejected"), and "check by hand" is kept only for a Healthy result below 0.80. On
   the 225 test photos this changes nothing (the only result below 0.80 is Healthy). The five stored
   Unhealthy scans below 0.80 (0.55–0.79) were re-graded to Rejected. Still to do: state the rule in the
   thesis (§3.5.4 and the runtime-safeguards subsection).

## Models and training data

5. **Stage 1 does not recognise overripe or bruised fruit.** It learned "Unhealthy" from green bunches with
   disease lesions. Market-bought, ripening Cardava with black patches and bruises was called Healthy at
   95–99.6%, so no threshold can catch it. If the packinghouse can receive such fruit, retrain Stage 1 with
   reviewed overripe examples labelled Unhealthy (disputed frames are copied to `/var/lib/banagrade/retrain`
   and exported with **Export disputed frames**). Otherwise state in the thesis that the system is for
   harvest-mature green fruit only.
6. **The capture trigger (`models/presence/best.pt`) fires on things that are not bunches.** It boxed a white
   sheet of paper at 0.93 and a hand opening and closing. The app now stops these (banana-colour check inside
   the box, COCO hand and object check), but the fix at the source is to retrain the trigger with background
   photos taken on the rig (paper, hands, a phone, the tape measure, tools), each with an empty label file. The
   paper and hand frames already in the retraining folder are a start. A flat, still palm seen from above
   (COCO "person" 0.09) can still reach Stage 2, where the 0.90 box minimum turns it into a technical failure.
7. **Say which fruit each on-site test used.** The first shift (27 Oct, 95 bunches) used market-bought,
   ripening fruit from Toril; size (A/B) can still be checked against measured finger length, but health
   screening cannot, because ripening is outside the training data. The second shift (27 Oct afternoon,
   38 bunches) used green, mature bunches and should be reported separately. The acceptance test with
   hand-labelled bunches (`ON_SITE_TESTS.md` §4) is still open.

## Camera and lighting

8. **Brightness has not been matched to the dataset yet.** The dataset was shot on the same camera (imx708,
   `rpicam-apps`) in daylight with automatic exposure and white balance. Under the ring light the rig came out
   brighter (bunch 171–180 against 149, velvet 43–53 against 11, HSV value). White balance is now locked from
   the sheet and exposure is back at EV 0. With a **fresh green bunch** in view, press **Match dataset
   brightness** (it refuses riper fruit). The rig's velvet also looks lighter than the dataset's, so check
   whether it is the same fabric.
9. **Keep the lighting fixed.** Use the same ring-light colour (white, not blue) for calibration and
   operation, and either always or never use the ceiling lights. Changing the light means redoing **Set white
   balance from sheet**.

## Records and the dashboard

10. **The 27 Oct disputes were reset.** All 38 disputes (23 scans) were deleted on 27 Oct at 14:36, so every
    scan carries the scanner's own grade again: 20 Class A, 59 Class B, 13 Rejected, 5 technical failures. The
    disputed state and the 23 retraining photos it held are saved in
    `/var/lib/banagrade/backups/dispute-reset-20261027-143620/`. The scans' own photos were deleted by Clear all
    scans at 13:46 and cannot be recovered, so a new dispute on these scans has no photo to copy for retraining.
    When disputing again:
    - B → A needs the measured length of the middle finger of the outer row; under 12 cm stays Class B. Finger
      width does not count.
    - Grade overripe-but-intact fruit by measured size and note the ripeness. Reserve Rejected for disease, rot,
      broken or missing fingers and peeled skin. #SCN-080763 and #SCN-D730E4 are one rotting bunch scanned twice.
11. ~~**The dispute form makes a no-change dispute easy.**~~ Done: the form opens with no grade chosen,
    refuses the recorded grade (the API refuses it too), and asks for the measured finger length when the
    correction is Class A or Class B.
12. ~~**Clearing test scans needs a shell.**~~ Done differently. A **Clear all scans** button deleted the 97
    scans of the 27 Oct run and their photos for good (the records came back from its backup, the photos did
    not), and with no login anyone on the Wi-Fi could press it. So the dashboard no longer deletes scans:
    **Void** on Recent Scans (per row, or "Void all N listed" for a narrowed list) leaves scans out of every
    total with a reason and can be undone. A full wipe of test data is `scripts/clear_scans.py` on the Pi
    (README), which moves the photos into its backup folder instead of deleting them.
