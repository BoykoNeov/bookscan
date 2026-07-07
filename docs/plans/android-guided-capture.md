# Gate 5 — Android Capture App Plan

## Context

Gate 5's desktop server (`server/`, see
`docs/plans/partitioned-questing-pillow.md`) is complete and committed
(`f1e55ff`..`f62ef92`). CLAUDE.md sequences the Android app last, "after the
desktop pipeline is proven" — it now is. This plan scopes `app-android/`,
which doesn't exist yet.

CLAUDE.md's spec for the app: guided capture — hover over a book spread, the
app auto-captures sharp frames (+ multi-zoom close-ups of large pages),
uploads over local Wi-Fi to the desktop server.

**Confirmed real server API** (`server/routes_jobs.py`, `server/app.py`;
supersedes the older plan doc's sketch, which predates the actual route
names):

- `POST /api/jobs` → `{job_id}`
- `GET /api/jobs` → `{jobs: [{job_id}, ...]}`
- `GET /api/jobs/{id}` → per-page stage status (poll this; no push transport)
- `POST /api/jobs/{id}/pages` — multipart upload, **N files in one request are
  the anchor + multi-zoom close-ups for one spread**, not one page per file.
  `frame_00` is the anchor convention. No per-file tagging needed: Stage 01
  fuse classifies anchor-vs-closeup itself, by area — a frame is a
  full-spread candidate if its area is ≥70% of the largest frame's area
  (`stage01_fuse.py` `fullspread_area_frac`), otherwise it's a close-up to
  stitch. **The app's contract: make sure a close-up frame is genuinely
  smaller-area than the anchor** (a tight crop, not just re-encoded at lower
  res) — mislabeling would starve or corrupt the anchor pick.
- No auth (single-desktop, local-Wi-Fi trust model, matches the server plan).

## Two constraints that shape every milestone below

**1. Validation without a physical phone+book.** The repo's rule is "validate
against `testset/` before declaring done," but nothing here can drive a real
camera in CI. Split every milestone's logic into what's genuinely
CI-testable off-device (pure scoring functions, the network client against a
locally-run real server) vs. what is manual-on-device-only (the capture UX
itself). Each milestone below states which is which — don't claim automated
coverage for the UX parts.

**2. Multi-zoom close-ups are a two-component risk, not just app work.**
`stage01_fuse.py`'s own docstring: the ORB-stitch close-up path has *only
ever run on synthetic unit tests* — "real multi-zoom validation is deferred
to when the Android app produces close-ups." The first real close-up upload
(M4) is simultaneously the first real test of that pipeline code. Treat bugs
surfaced there as expected fallout, not scope creep, and budget time in
`pipeline/stage01_fuse.py` for it. It's also the missing `testset/zoomset_*`
fixture `stage01_fuse.py` flags as never-shot — the first good multi-zoom
capture should be committed there (append-only, per `testset/README.md`).
Open question, not yet designed: today's stitch is one-close-up-per-region
(spatial placement only); a true multi-frame merge of *overlapping* shots of
the same region (e.g. stacking for noise/detail beyond single-frame quality)
may be needed for best image quality — revisit once real M4 captures show
whether single-frame-per-region is actually the bottleneck.

## Architecture

### Stack

- **Kotlin**, single Gradle module (`app-android/app`), **Jetpack Compose**
  UI (the screens are a handful of dynamic states — job list, capture
  overlay with live sharpness/stability indicators, upload progress — Compose
  fits better than View/XML for that than either would for something this
  small and state-driven).
- **CameraX** (`Preview` + `ImageAnalysis` + `ImageCapture` use cases) —
  Google's supported camera API, gives frame-analysis callbacks without
  hand-rolled `Camera2` boilerplate.
- **Retrofit + OkHttp + kotlinx.serialization** for the HTTP client against
  the endpoints above (multipart upload via OkHttp `MultipartBody`).
- `minSdk 26` (Android 8.0) — CameraX's `ImageAnalysis` + modern Compose both
  want this floor comfortably; no reason to chase API 21 for a
  personal/local-network tool.

### On-device metrics mirror the pipeline's own

- **Sharpness = variance of Laplacian**, the same metric Stage 00 records
  per frame (`stage00_ingest.py`) and Stage 01 uses to pick the sharpest
  anchor. Porting the identical metric on-device means auto-capture keeps
  exactly the frames the pipeline will *also* rate sharp — the two never
  diverge on what "sharp" means. Implemented as a small standalone Kotlin
  function over a downsampled luma buffer (fast enough to run per
  `ImageAnalysis` frame) — this is the one piece of capture logic that's
  genuinely unit-testable off-device (feed it fixture blurry/sharp byte
  arrays, assert ordering).
- **Stability ("hover")** = frame-to-frame luma-diff of the downsampled
  analysis frame below a threshold for N consecutive frames. Also a pure,
  unit-testable function.

### Server discovery: manual first, defer auto-discovery

FastAPI/uvicorn doesn't advertise itself over mDNS/NSD today, so real
auto-discovery would mean touching `server/` too, not just the app.
Recommendation: **manual IP:port entry** in v1 (fits the existing "no auth,
local-Wi-Fi trust" model — this is a personal tool on one LAN), persisted
after first entry. Defer NSD/Zeroconf discovery until a real multi-device
usage pattern justifies the added surface on both ends. (A QR code showing
the server's LAN IP on the landing page would be a one-line, low-risk
addition later if manual entry proves annoying — not required for v1.)

## Build sequence

One milestone per Claude Code session, matching the repo's convention (Gate
5's server used the same four-step shape).

**M1 — Project scaffold + network client (no camera).** Gradle project,
Retrofit client implementing the four endpoints above, manual server-IP
entry screen, a bare UI that creates a job and uploads a **gallery-picked**
image (camera stand-in) so the client can be proven against a real running
server before any camera code exists.
*Verify:* JVM unit tests for JSON response parsing against fixture
responses (CI-able, no device). Primary proof is manual: run
`uvicorn server.app:app --reload` on the dev machine, upload a real spread
photo via the picker, confirm the page appears and stages advance through
`GET /api/jobs/{id}` polling — this is the same E2E path the server plan's
step 4 already proved via curl, now proved from the app's actual HTTP
client.

**M2 — Manual-capture camera flow.** CameraX preview + shutter button,
captures one full-resolution still per tap as a single `frame_00`, uploads
it through M1's client (replacing the gallery picker). Single-frame-per-page
is deliberately the *only* path `stage01_fuse.py` has real-photo validation
on today ("reality check" in its own docstring) — burst/multi-zoom come
later, after this simplest path works end to end.
*Verify:* manual on-device only — capture a real book spread, confirm
`page_001/raw/` populates and 00→06 clear the same way a curl upload does.

**M3 — Auto-capture ("hover to capture").** `ImageAnalysis` stream scores
every frame for sharpness + stability (the two pure functions above);
`ImageCapture` fires automatically once both gates pass for N consecutive
frames, matching CLAUDE.md's "hover over a spread" UX. While stable, keep
firing and retain only the client-side sharpest frame(s) before upload
(mirrors Stage 01's "sharpest wins," done once on-device first to avoid
uploading redundant blurry burst frames over Wi-Fi).
*Verify:* unit tests for the sharpness/stability scoring functions against
fixture frame sequences (CI-able). The auto-trigger UX itself is manual
on-device only.

*Status: built.* The scoring + gate/burst decision logic lives in a new
pure-JVM `:capture` module (`varianceOfLaplacian`, `meanAbsLumaDiff`,
`HoverGate` state machine, `pickSharpest`) — 22 unit tests green via
`./gradlew :capture:test`, exercising streak-completion, throttling,
burst-cap finalize, mid-burst interruption/reset. `CaptureScreen.kt` wires
`ImageAnalysis` + the gate into the existing M2 screen, keeping the manual
shutter as a fallback. This environment turned out to have a working Android
SDK after all (`local.properties` `sdk.dir` resolves) — unlike M1/M2,
`./gradlew assembleDebug` was run here and succeeds; still, the hover UX
itself (does it feel right, does it actually trigger on a real spread) is
unverified without a device. **Thresholds are placeholders**
(`SHARPNESS_THRESHOLD`/`STABILITY_THRESHOLD`/etc. in `CaptureScreen.kt`) —
variance-of-Laplacian on a downsampled on-device luma buffer is not on the
pipeline's absolute scale (not scale-invariant), and the stability threshold
has no pipeline equivalent at all (auto-exposure re-metering shifts luma
frame-to-frame even when the phone is perfectly still). Calibrating these
against real captures is the first on-device task, before M4.

**M4 — Multi-zoom close-ups for large pages.** Scope conservatively for v1:
a **user-triggered** "capture close-up" action (zoom in, tap to capture)
rather than automatic "this page is too small to read, zoom in" detection —
automatic large-page detection is deferred until the pipeline's ORB stitch
is proven against real close-ups from even manual use (see constraint #2
above; stacking an unvalidated on-device layout heuristic on top of an
unvalidated pipeline path in the same milestone is two risks at once).
Close-up frames upload alongside the anchor in the same
`POST /api/jobs/{id}/pages` request; the app must ensure each close-up's
pixel area is meaningfully below the anchor's before treating it as one, so
it can never be misclassified as a second full-spread candidate.
*Verify:* manual on-device, but treat the first successful upload as a
pipeline validation event, not just an app milestone — inspect
`01_fuse/fuse.json`'s `closeups` match results and `debug/01_fuse.png`
(CLAUDE.md's own "read debug overlays first" rule). Expect this to kick back
bugs into `stage01_fuse.py`. Commit the first clean capture set into
`testset/` as the first real `zoomset_*` fixture (append-only).

*Status: built, not yet device-verified.* New `CloseupScreen.kt` (fixed
zoom-ratio steps — 1x/2x/3x/4x buttons via `CameraControl.setZoomRatio`,
deliberately not a pinch gesture or a `zoomState`-bound slider, to avoid
gesture-detection/LiveData surface that can't be tuned without a device —
plus tap-to-capture, repeatable) is a separate flow from `CaptureScreen.kt`'s
M2/M3 hover state machine, which is untouched. `MainActivity.kt` now drives a
`CaptureFlow` state machine: anchor capture -> `SpreadReviewScreen.kt`
(thumbnails, add-another-closeup / discard / upload) -> optionally back into
`CloseupScreen` -> upload. `BookscanViewModel.uploadFrame(file)` became
`uploadSpread(anchor, closeups)`, uploading the whole spread in one
multipart request (anchor always index 0), per the server contract above.

**Design change from the plan's literal reading, pushed by advisor review:**
"the app must ensure each close-up's pixel area is meaningfully below the
anchor's" does NOT mean crop. A blind center-crop to hit the area target
would cut into content the user just framed by zooming — the opposite of
what a close-up is for. Instead `com.bookscan.capture.scaledCloseupSize`
(new pure function, `:capture` module, unit-tested) computes a downscale
target at `CLOSEUP_AREA_FRACTION = 0.5` (comfortably under Stage 01's
`fullspread_area_frac = 0.70`) applied to the close-up's OWN captured
resolution — CameraX zoom narrows field of view, not pixel count, so a
close-up starts at the same sensor resolution as the anchor; only this
post-capture resample actually shrinks its saved dimensions. Resampling
keeps the whole framed region while still delivering a real DPI win on it
(e.g. 3x zoom downscaled by sqrt(0.5) is still ~2.1x the anchor's effective
resolution there). `downscaleCloseupInPlace` (app module,
`CloseupImageOps.kt`) also bakes in EXIF orientation via
`androidx.exifinterface` before re-encoding — `BitmapFactory`/
`Bitmap.compress` don't round-trip the orientation tag, and
`stage00_ingest.py` applies `exif_transpose` to every ingested frame, so an
un-corrected close-up would desync from the anchor before Stage 01's ORB
stitch ever saw them (would have looked like a pipeline bug, wasn't one).

**Validated the downscale approach on real photographic texture without a
device**, per advisor's suggestion, since M4's real value (first real test of
`stage01_fuse.py`'s ORB stitch path) can't otherwise be checked here: cropped
a region of a real `testset/it_geo_07.jpg` spread photo, downscaled it by the
same `sqrt(0.5)` math `scaledCloseupSize` uses, ran it through real
`stage00_ingest.run()` + `stage01_fuse.run()` alongside the untouched full
photo as anchor. Result: ORB stitch matched with 384 inliers, closeup area
0.06 of the anchor's (well under the 0.70 threshold) — confirms downscaled
close-ups retain enough real feature texture to match, and that the
area-fraction math behaves as intended, on an actual photograph rather than
a synthetic unit-test pattern. This is NOT a substitute for a real on-device
capture — it doesn't touch camera zoom UX, EXIF-from-camera-hardware
behavior, or whether 1x-4x zoom steps produce a useful close-up in practice.
`./gradlew assembleDebug` and the full `test` task (network + capture)
pass; the capture UX itself — does zoom feel right, does the close-up
actually add useful detail, whether `CLOSEUP_AREA_FRACTION`/zoom steps need
tuning — is unverified without a device, same caveat as M2/M3.

**Threading bug caught by a second advisor review before any device use:**
the first `CloseupScreen` cut ran `takePicture`'s `OnImageSavedCallback` on
`getMainExecutor`, so `downscaleCloseupInPlace`'s full decode + EXIF-rotate +
scale + JPEG re-encode of a multi-megapixel still executed synchronously on
the UI thread — hundreds of ms per close-up, a guaranteed freeze/ANR risk on
first real capture. This does NOT inherit `CaptureScreen`'s "analyzer on
main is deliberate" reasoning (M3's per-frame work is a cheap 320x240 luma
variance, not a full-res image transform). Fixed: `takePicture` now runs on
a remembered single-thread `Executor` (shut down in `onDispose`);
`downscaleCloseupInPlace` executes there, and only the resulting
`capturing`/`error`/`onCaptured` state mutations are marshaled back to
`getMainExecutor`. Also flagged, not fixed (unverifiable without a device):
the real-texture ORB validation above used `cv2.imwrite`, which writes no
EXIF — so the EXIF-orientation-baking path (`applyExifOrientation`) is
plausible but has NOT actually been exercised by anything, unit test or
pipeline check. Treat it as unverified, same bucket as the rest of the
capture UX.

**M5 — Session UX + resilience.** Job list/resume screen (`GET /api/jobs`),
retry-with-backoff on upload over flaky Wi-Fi, a capture-progress overlay
driven by polling `GET /api/jobs/{id}` per-stage status, server address
persisted across launches.
*Verify:* unit tests for retry/backoff logic against a fake failing client
(CI-able). Session UX (job list, progress overlay) is manual on-device.

*Status: built.* Server-address persistence (`ServerPrefs`) and `listJobs()`
already existed from M1, so this milestone's actual scope was three things.
**Retry/backoff** lives in `:network` (`RetryBackoff.kt`) as the same
pure-function-plus-thin-wrapper shape as `:capture`'s `HoverGate`:
`delayForAttempt(attempt)` is a pure doubling-with-cap function, `withRetry`
loops over it. It deliberately does *not* switch dispatchers, so
`kotlinx-coroutines-test`'s virtual time advances `delay()` under `runTest` —
5 new unit tests (`RetryBackoffTest`) run instantly instead of wall-clock
sleeping. `isRetryableNetworkError` retries `IOException` (connect refused/
unreachable/DNS/timeout) but not `HttpException` (server responded);
`uploadSpread` wraps `uploadPage` in it at 4 attempts. Documented, not
solved: a lost response after a processed request (read-timeout-after-send)
retries into a genuine duplicate page — accepted as a conscious tradeoff for
this personal single-LAN tool rather than building server-side dedup.
**Job list/resume**: `UiState.Ready` gained a `jobs` field; `loadJobs()` calls
`listJobs()` on server connect and on-demand; `resumeJob(id)` re-targets
`startPolling` the same way `createJob` does post-creation. `JobScreen`'s
`jobId == null` branch now lists jobs (tap to resume) alongside "New job".
**Progress**: reused `JobScreen`'s existing per-page stage display rather
than building a second rendering path — added a `LinearProgressIndicator`
and an "N/7 stages" count next to the existing per-stage ✓/✗/… marks.
`./gradlew :network:test` (new tests green) and `./gradlew assembleDebug`
both pass. Job list/resume and progress display are UX — unverified without
a device, same caveat as M2-M4.

## Explicit non-goals (v1)

- NSD/mDNS auto-discovery of the server (manual IP entry instead; would
  need a `server/`-side change too).
- Automatic "large page → needs close-ups" detection (user-triggered
  close-up capture instead, until the pipeline path is proven).
- Auth / multi-user (matches the server's existing local-Wi-Fi trust model).
- Any on-device pipeline processing — the app captures and uploads only;
  all OCR/layout/etc. stays server-side.
- RAW capture (the pipeline's `rawpy` path is itself unvalidated/optional
  today; JPEG/PNG stills only).

## Verification summary

| Milestone | CI-able | Manual-only |
|---|---|---|
| M1 | JSON parsing unit tests | Real upload against running server |
| M2 | — | Capture → pipeline E2E on a real spread |
| M3 | Sharpness/stability scoring unit tests | Auto-trigger UX |
| M4 | — | Capture → Stage 01 fuse validation (+ likely pipeline fixes) |
| M5 | Retry/backoff unit tests | Job list / progress UX |
