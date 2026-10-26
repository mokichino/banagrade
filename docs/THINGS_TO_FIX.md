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
4. **Decide the rule for doubtful Stage 1 results.** Recommended: reject any Unhealthy result regardless of
   confidence (thesis rule "Unhealthy → Rejected"), and keep "check by hand" only for a Healthy result below
   0.80. On the 225 test photos this changes nothing (no healthy bunch rejected); on the rig it would have
   rejected the "Unhealthy 65%" and "Unhealthy 54%" bunches. Not applied yet: it is a grading-rule change for
   the team to agree on and to state in the thesis.

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
7. **The on-site tests so far used market fruit, not fresh harvest-mature bunches.** Size (A/B) can still be
   evaluated against measured finger length; health screening cannot, because ripening is outside the
   training data. Run a second test with fresh green Cardava and record it separately. In the thesis, say which
   fruit each test used.

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

10. **Disputes to review from the 27 Oct run.**
    - #SCN-F7DBAD, #SCN-EC7458 and #SCN-E0C181 were saved with the same grade as recorded (B → B) although
      the reasons describe rejects. Re-dispute them with the intended grade.
    - The six B → A disputes (#SCN-27A785, C0EBB5, 9A27FE, 026F46, 6C6E3C, 7CE262) only say "thick, full
      fingers". Add the measured finger length, and re-check #SCN-9A27FE (2164 px) and #SCN-026F46 (2246 px),
      which are narrower than every Class B of the run.
    - Overripe bunches were graded both ways (some Rejected for "black patches and over ripe", some kept as
      Class A with similar damage). Apply one rule: grade overripe-but-intact fruit by measured size and note
      the ripeness, and reserve Rejected for disease, rot, broken or missing fingers and peeled skin.
11. **The dispute form makes a no-change dispute easy.** It opens with the recorded grade selected. Refuse to
    save when the corrected grade equals the recorded one, and remind the operator to give the finger length
    when correcting B → A.
12. **Clearing test scans needs a shell.** Each reset so far was done by hand (database backup, delete scans,
    disputes, events and frames, close the shift). Add a **Clear all scans** button with a confirm step and an
    automatic backup.
