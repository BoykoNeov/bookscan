# On-device session checklist (Gate 5, Android)

Everything in `app-android/` builds and its logic is unit-tested, but **no
session has ever driven a real camera over a real book**. Every UX claim in
`docs/plans/android-guided-capture.md` M2–M5 is "unverified without a device".
This file is the protocol for closing that — run it once, with the phone.

> **STATUS 2026-08-28 — most of this is BANKED; do not re-run it blind.**
>
> * **Goal 1 (calibrate auto-capture): CLOSED, and the feature was demoted.**
>   Thresholds were fitted on 2026-08-19; the armed confirmation run happened
>   on 2026-08-28 and the burst delivered ONE still, not the four the
>   hysteresis fix was measured to give. Manual capture is now the default
>   flow and auto-capture is an opt-in toggle (owner's call). **Do not record
>   three more frame logs** — the numbers exist, and the metric is no longer
>   load-bearing. See RESULTS 2026-08-28.
> * **Goal 2 (capture → upload → pipeline): DONE**, twice, on real spreads.
> * **Goal 3 (close-ups → `testset/zoomset_*`): fixture exists** from
>   2026-08-19. Two more real multi-image pages ran clean on 2026-08-28.
> * **Goal 4 (session UX): job list, resume and the 7/7 progress display are
>   CONFIRMED** on a live server (2026-08-28). Still open: upload retry over a
>   dropped link, and server-restart-mid-page.
>
> What a fresh device session is actually for now: the two open goal-4 items,
> and re-testing whatever the Stage 02 book-boundary fix turns into (RESULTS
> 2026-08-28 — the book detector returns the whole frame on a pale background,
> so neither real capture split into pages).

The session has four goals, in order of value:

1. **Calibrate auto-capture.** `SHARPNESS_THRESHOLD` / `STABILITY_THRESHOLD` in
   `CaptureScreen.kt` are guesses (a downsampled on-device luma buffer is not on
   `stage00_ingest.py`'s absolute scale, so they could not be copied from the
   pipeline). Produce real numbers instead of an opinion.
2. **Capture → upload → pipeline end to end** on a real spread, over Wi-Fi.
3. **Close-ups → `testset/zoomset_*`**, the fixture `stage01_fuse.py`'s
   multi-zoom path still lacks. Expect pipeline bugs to surface here.
4. **Session UX**: job list / resume / progress / retry over flaky Wi-Fi.

---

## 0. Before touching the phone

```powershell
# app builds + logic tests green
cd app-android; .\gradlew :capture:test :network:test assembleDebug

# desktop server, reachable from the LAN (not just localhost)
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Windows blocks inbound 8000 by default. One-time rule (elevated), and how to
undo it:

```powershell
New-NetFirewallRule -DisplayName "bookscan-dev 8000" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow
# undo:  Remove-NetFirewallRule -DisplayName "bookscan-dev 8000"
```

The phone must be on the **same subnet** as the PC. Check the PC's address
(`Get-NetIPAddress -AddressFamily IPv4`) and confirm the phone's Wi-Fi address
shares its first three octets — a phone on a guest SSID or a 5GHz "isolated"
band will fail with a connect timeout that looks like an app bug.

## 1. Install

```powershell
$adb = "M:\claud_projects\android-sdk\platform-tools\adb.exe"
& $adb devices            # phone must appear as "device", not "unauthorized"
& $adb install -r app-android\app\build\outputs\apk\debug\app-debug.apk
```

`unauthorized` = accept the USB-debugging prompt on the phone's screen.

## 2. Calibrate the hover gate (goal 1)

The capture screen shows a live readout:

```
sharp 62.4 ✓ (≥40)  still 3.1 ✓ (≤6)  streak 5/8
```

and a **"Log frames (calibration)"** button that records every scored frame to
a CSV.

**While the log is running nothing is captured at all** — the gate still runs
and the CSV records what it *would* have done, but no photo is taken, the
manual shutter is disabled, and the screen cannot navigate away. That is
deliberate: with auto-capture live a burst finalizes about a second and a half
in and hands off to the review screen, so "hold steady for 15 s" would only
ever yield a second and a half of data — and would yield the full 15 s only
when the thresholds are so tight they never fire, the one case that teaches
nothing.

Arming is a **mode, not a moment**. A second button reads "Auto-capture: ON —
tap to pause" / "OFF — tap to arm", and starting a log switches it OFF and
*leaves it off* after you stop. Re-arming on stop was the first version and it
did not survive contact with the phone: a passing streak is only 8 frames
(about a quarter of a second), so the gate fired and the review screen took
over before the "saved N frames" line could be read — and a second log could
never be started at all. Record all three logs with auto-capture off, then arm
it deliberately when you want to test firing.

Record **three separate logs** — start, do the thing, stop — so each file is
cleanly labelled by what you were doing:

| # | What to do for ~15 s | What it captures |
|---|---|---|
| 1 | Hold the phone over an open spread as you normally would, framing the whole spread. Let it settle. | the "should fire" distribution |
| 2 | Move: lift, re-frame, turn a page, shift sideways. Never settle. | the "must not fire" distribution |
| 3 | Use it for real: approach the spread, settle, let it capture, move to the next. | the mixed case |

Pull them off the phone and fit the thresholds:

```powershell
& $adb pull /sdcard/Android/data/com.bookscan.app/files/ M:\claud_projects\temp\framelogs
python -m tools.calibrate_hover --steady <log1>.csv --moving <log2>.csv `
    --mixed <log3>.csv --json docs\data\hover_calibration_<date>.json
```

Files are named `framelog_<epoch-ms>.csv`, so the three sort in the order you
recorded them. The tool prints both distributions, the suggested threshold
pair, and — the point — the share of steady frames it would fire on versus the
share of moving frames it would falsely fire on, measured on exactly those
frames. It also replays the real gate state machine (8 frames in a row, one
still per 400 ms, 4 per burst) over the mixed log, so you can see how often a
hover would have triggered before reinstalling anything.

Put the chosen pair into `CaptureScreen.kt`, rebuild, reinstall, and re-run
log 3 to confirm it fires when you expect. `python -m tools.calibrate_hover
--self-test` exercises the whole path on synthetic frames if you want to see
the output shape first.

**Scale, measured on an S23 (2026-08-19, 673 frames over 22 s).** Sharpness
came in at 231–1567 (median 1482) against a placeholder threshold of 40, so the
sharpness half of the gate is currently a no-op — every frame clears it.
Stability came in at 0.5–24.4 (median 2.0) against a threshold of 6, which cuts
straight through the data: 81 % of frames passed, and the gate wanted to fire
16 bursts / 46 stills in 22 seconds. Whatever the fit says, expect the
sharpness threshold to move by two orders of magnitude.

**If the two distributions overlap**, the tool says so and exits non-zero
instead of suggesting a value: the metric, not the threshold, is the problem,
and that is a finding worth recording rather than a number to fudge.

## 3. Capture → pipeline (goals 2 and 3)

1. Enter the PC's address (`http://<pc-ip>:8000`) on the server screen.
2. New job → pick the uncertainty mode → capture a spread by hovering.
3. Add close-ups: the review screen's "Add close-up" → 1×/2×/3×/4× buttons,
   two or three per spread, on text areas that look small in the anchor shot.
4. Upload. Watch the per-page stage marks advance (N/7).
5. On the PC, look at `jobs/<id>/<page>/debug/` **before** reading any code —
   that is the house rule for diagnosing a bad page.

The uploaded originals land under `jobs/<id>/<page>/00_ingest/`; that is the
material for a new `testset/zoomset_*` fixture (see `testset/README.md` for the
append-only rule — never edit existing images).

Things known to be untested that this step exercises for the first time:

- EXIF orientation baked by real camera hardware (`applyExifOrientation` has
  never run on a real EXIF-bearing file — `cv2.imwrite` writes no EXIF).
- Whether 1×–4× zoom steps produce a close-up that actually adds detail.
- Whether Stage 01's fuse path accepts a real multi-zoom set at all.

## 4. Session UX (goal 4)

- Kill Wi-Fi mid-upload and restore it: the upload should retry (4 attempts,
  doubling backoff) rather than fail outright. Known and accepted: a response
  lost *after* the server processed it retries into a duplicate page.
- Background the app, reopen it: the job list should offer the job to resume.
- Restart the server process mid-job: queued pages should be picked back up
  (`server/reconcile.py`), failed ones should not re-run forever.

## What to write down

Append a dated row to `docs/RESULTS.md` with the chosen thresholds and the
false-fire/miss numbers behind them, and commit the calibration CSVs under
`docs/data/` — the repo convention is that a result stays auditable without the
temp folder.
