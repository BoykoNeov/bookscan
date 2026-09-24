# Handoff: one real sweep, then the panorama verdict (written 2026-09-24)

A session plan, not a design. It exists because the owner said, 2026-09-24,
"to fight bad pixels we must do the phone panorama stitching correctly", and
the answer was "yes, for one of the two kinds of bad pixel — and the next step
needs the owner with a phone". This is the step list for that session. The
reasoning behind every step lives in `panorama-and-next-steps.md` §1 and in
RESULTS 2026-08-31; read §1 Phase 0 and Phase 2 before running anything.

## What stitching can and cannot fix

- **Cannot fix: the wrong crop.** Ten of the owner's fifteen PDF defects are the
  sofa inside the frame, so Stage 03 flattened fabric (`OPEN_PROBLEMS.md` P1).
  Close-ups are placed onto the *flattened* page, so a page flattened wrong is a
  wrong base for any number of sharp close-ups. P1 is fixed by the crop (today:
  a hand-drawn box in `tools/book_box_editor`), not by this plan.
- **Can fix: not enough resolution** — small print, the translation panels
  (P2, *after* P1), anything a single full-spread photo resolves too coarsely.

## Why the thread is parked, in one paragraph

Placement works: a raw close-up registered onto the flattened page and
corrected over its own footprint lands 1.39 px from home (control 0.09 px).
But 42 % of placed close-ups have a worst-twentieth off by ~30 px — a word
width — so painting a source whole prints a doubled or broken word somewhere.
Phase 2 could not say whether a page *reads* better: of 40 registered sources,
5 cleared the 10 px bar and 4 of those sat on one map. That is a **data famine,
not a refusal**. The phone's sweep mode (`SweepScreen`, M7) was built to end the
famine and has never run on a phone.

## The session, in order

### 1. Build and install the app (Claude, needs the owner only for pairing)

```
cd app-android && ./gradlew assembleDebug
adb mdns services                       # empty list = wireless debugging OFF
adb pair <ip>:<pairing_port> <code>     # first pairing only — ASK the owner
adb connect <ip>:<connect_port>
adb install -r app-android/app/build/outputs/apk/debug/app-debug.apk
```

`adb` is `M:\claud_projects\android-sdk\platform-tools\adb.exe`. Wi-Fi install
is the method here; do not offer the browser-download route (see `CLAUDE.md`).

### 2. The owner shoots (the only part Claude cannot do)

- **One spread of dense running text**, not maps or photographs — Phase 2's
  no-verdict came from sources landing on a map. Same German guidebook if
  possible (Phase 2's `LANG = "deu"` and its three pages give continuity).
- Normal full-spread shots first (they supply the anchor), then **Sweep
  close-ups** from the spread review screen at **2–3×**, sliding slowly across
  the text. The 24-frame budget is per spread.
- A **hand-drawn book box** if the surface is pale, so P1 does not contaminate
  the result.
- Turn the frame log on during the sweep and save it (`sweeplog_<ms>.csv`).

### 3. Pull the sweep log and fit the motion threshold

```
& $adb pull /sdcard/Android/data/com.bookscan.app/files/ W:\temp\claude\sweeplogs
python -m tools.calibrate_sweep --logs <sweeplog_*.csv> --json docs/data/sweep_calibration_<date>.json
```

Until a real sweep log is replayed, `SweepGate`'s motion threshold (200) is
fitted to a hold-and-re-frame recording, not a sweep — a rate control, never an
overlap guarantee. Also record by eye: did 24 frames cover the text, and how
far apart were they? That is the M7 "verified on a phone" line, which is open.

### 4. Pre-register, then run Phase 2 on the new spread

A new spread is a **new population**, so `docs/data/panorama_phase2_prereg_20260831.md`
does not cover it. Write `docs/data/panorama_phase2b_prereg_<date>.md` first,
keeping every Phase 2 rule unchanged (10 anchor px on the **worst of three
seeded draws**, `MIN_OWN_SCALE` 1.0, confident words inside the painted union,
`MIN_UNION_WORDS` 50, arm X — painting the *rejected* sources — as the control
that must lose). Then:

```
python -m tools.panorama_phase2 --job jobs/<new_job> --pages page_NNN \
    --out docs/data/panorama_phase2b_<date>.json --dump W:\temp\claude\phase2b
```

Grade on **confident words AND a text diff**, never the count alone (four times
here a confidence number rose while the text got worse; once, a count tied while
the diff showed a real gain). Check `ingest.json` `source` for `_sweep` so "the
sweep helped" is separable from "more close-ups helped".

### 5. What each outcome licenses

| outcome | means | next |
|---|---|---|
| enough sources admitted, text diff better, arm X loses | the method reads better on text | build Phase 1 as redesigned: **per-region** admission + word-aligned seams (§1 Phase 2 RUN) |
| enough admitted, text no better or worse | a real negative | record it as a refusal; stitching is not the lever for text |
| still too few admitted (< `MIN_UNION_WORDS`) | capture is still the blocker | the sweep's framing/spacing, not the code — adjust how it is shot and repeat 2–4 |
| arm X does not lose | the instrument is blind | uninterpretable; fix the control before reading anything |

## Do not, whatever the result

- Do not lower `min_inliers` (8) or loosen `HoverGate` for a sweep.
- Do not "paint every registered source" — the tail inside a source is the
  defect; whole-source admission cannot fix it.
- Do not flatten the close-up separately ("flatten both" is refused).
- Do not threshold a single RANSAC/FLANN draw.
- Append the RESULTS row, update `OPEN_PROBLEMS.md` P4/P5 and
  `plans/README.md`, and append to `STATUS.md`.
