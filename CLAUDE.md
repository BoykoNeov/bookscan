# bookscan — Book Scanning & Re-Typesetting Pipeline

## What this project is

A book-scanning system that produces **fully re-typeset searchable PDFs**: all
photographed text is REPLACED with real rendered text (clean reflowed layout),
while figures/illustrations are cropped from the page photos and placed back in
their correct reading-order positions. This is NOT the classic
invisible-OCR-layer-under-image approach — OCR output becomes the visible
document, so error handling is the load-bearing feature.

Three components:
1. **Android app** (`app-android/`) — guided capture: hover over a book spread,
   app auto-captures sharp frames (+ multi-zoom close-ups of large pages),
   uploads over local Wi-Fi. Built LAST, after the desktop pipeline is proven.
2. **Desktop server** (`server/`) — FastAPI on Windows + NVIDIA GPU: receives
   uploads, runs the pipeline, pushes status/previews back to the phone.
3. **Processing pipeline** (`pipeline/`) — staged, per-page, artifact-driven.

Target languages for OCR, in priority order: **English, Bulgarian (Cyrillic),
Italian, German**.

## Where the project stands (2026-09-02)

All five gates are done: the OCR harness (1), fusion/split/dewarp (2), layout
and reading order (3), the end-to-end re-typeset PDF (4), and the FastAPI server
plus the Android capture app, verified on a real phone 2026-08-28 (5). The
operator interface is the **console** (`bookscan.bat`); the editable document,
per-word uncertainty markers, reading-order review, hand-drawn book box,
higher-resolution figure assets, table rendering, per-block language labels and
the local vision-model helpers (`vlm_box`, `figure_surface`, both off by
default) are all shipped and measured.

**The chronological record of everything built, measured and refused lives in
`docs/STATUS.md`** (moved out of this file 2026-09-02; 550 lines, verbatim).
**The live problems, ranked, with the next experiment for each, live in
`docs/OPEN_PROBLEMS.md`.** Read that before choosing work. `docs/plans/README.md`
says which plan is live, parked or done.

The three things that cost the deliverable most today, in order:

1. **The book crop on a pale surface** (`docs/OPEN_PROBLEMS.md` P1). Ten of the
   owner's fifteen listed defects trace to four spreads whose dewarp ran on a
   frame containing sofa. The detector has three failure modes; one is now
   caught (unstable GrabCut draws abstain, 2026-09-02), one is aimed but not cut
   (`vlm_box` as a search window), one is open. Blocked on a fixture shoot of
   *negatives* and on the owner's postponed call about whether a model box may
   cut. `tools/split_eval` reads **19/21 and exits 1 on purpose**.
2. **Pictures split in two** (P3): a continuity test using `figure_hires`'s
   correlation machinery, measured as a census on the owner's job first.
3. **Panorama** (P4) is parked, not refused: Phase 1 needs per-region
   admission and a text spread swept on the phone before any code.

## Guardrails earned by measurement (do not undo without new data)

Each line is a RESULTS row compressed to a rule. The row is the argument; the
pointer is the date in `docs/STATUS.md` / `docs/RESULTS.md`.

- **`split_eval` is red on purpose (19/21).** `paleset_01/02` are banked
  known-failing rows; never delete, excuse or relabel them. (2026-08-28)
- **No accuracy claim without a text diff.** Four times a confidence number
  rose while the text got worse (`deu+ita`, promoted tables, table cells, the
  hyphen rejoin the count was blind to). Confident-word counts are not
  comparable across language sets. (2026-08-29, -31)
- **Never threshold a single random draw.** GrabCut and RANSAC read OpenCV's
  unseeded global RNG; the book detector gave four answers on one frame, from
  no crop to 11.9 % of the book gone. Seed, draw several times, act on the
  worst or the union. (2026-08-31, 2026-09-02)
- **Tesseract is the text and confidence backbone.** A vision-language model
  answers only questions a person answers in one second by looking (where is
  the book, is this the sofa, is this text), never as a source of text, and
  anything that discards content needs **two questions that agree**. An edited
  prompt is an unmeasured prompt. (2026-08-29)
- **A flag is not a deletion.** `is_surface`, `type_promoted`, per-word markers:
  everything a model decides is reversible in the editor until many books say
  otherwise. Promotion to text deletes pixels — recoverable is not harmless.
- **Multilingual support belongs at the block, not the page.** A page-level
  `deu+ita` loses umlauts. Re-reading a badly read block in another language
  returns different garbage. (2026-08-29, -31)
- **Do not lower `min_inliers` (8), `min_ncc` (0.60), `min_coverage` (0.90), or
  retune `search_pad`.** Each has a measured false positive behind it.
- **Do not fit a book detector to `gt/book_box.json`**; it grades clipping only.
  The clip metric is knife-edge on the paleset rows (one label pixel ≈ 0.04 %);
  adjudicate small edge-band clips by looking, and write the adjudication down.
- **Rows from the two `layout_order_eval` arms are different quantities.**
  Never compare `--no-stage05` against the default.
- **Verify pictures by checkerboard, never side by side** — a sharper crop
  reveals text the blurry one hid, which reads as a framing change.
- **n counts scenes, not frames.** Thirty-one photographs of one sofa are n = 1;
  new fixtures must be new photographs of new surfaces.
- **The cheapest lever keeps being the operator's.** Three measurements ended
  at "the photograph was framed wrong". Capture guidance before the next
  algorithm.
- **Panorama Phase 1 is not licensed**; the "flatten first, stitch second"
  reorder is refused; painting registered sources wholesale doubles text.
- **The stitching gate that nothing could pass** (sharpness ratio 1.0) stays,
  for a different reason than first recorded: warping a close-up down into the
  anchor destroys the resolution before anything is written.

## Measurement discipline

- **Pre-register** the gate, the population and the statistic before a number
  exists (`docs/data/*_prereg_*.md`), and commit the inputs and outputs under
  `docs/data/` so a RESULTS row is auditable without `temp/`.
- Every measurement has a **control** (the target's own pixels through the same
  machinery; the rejected sources painted; the enlarged canvas with nothing
  pasted). A gate nothing can pass and a gate everything passes are both found
  this way.
- Report the **refusal** as a result. This repo has shipped negatives
  (per-page frame source, CLAHE, caption proximity, A10, the language re-read).
- **Append** a dated row to `docs/RESULTS.md`; correct a wrong row with a new
  clause, never by rewriting it. Then update `docs/OPEN_PROBLEMS.md` (the one
  document that is rewritten) and `docs/STATUS.md` (append).
- A change with **no measurable effect** (a seed, a warning) still says so and
  says what it could not check.

## Architecture: the stage contract (IMPORTANT)

The pipeline is a chain of stages. **Every stage obeys the same contract:**

1. Each stage is an independently runnable CLI:
   `python -m pipeline.stage04_layout jobs/<job_id>/<page>/`
2. A stage reads ONLY the artifacts of the previous stage from the page
   directory, and writes its own artifacts into its own numbered subfolder.
3. Every stage writes THREE things:
   - its output image(s) and/or JSON,
   - a `meta.json` (stage version, params used, timings, warnings),
   - a **debug overlay image** in `debug/` (e.g. detected boxes drawn on the
     page) so failures are visible to a human at a glance.
4. Stages NEVER modify earlier artifacts. Re-running a stage overwrites only
   its own folder. Any page can be re-run from any stage.
5. All inter-stage data structures conform to `pipeline/page_model.py`
   (the single shared schema). Change the schema ONLY deliberately, in its own
   commit, updating all stages that touch the changed fields.

**Editable-document exception (Stages 07–08).** Items 1–4 describe the per-page,
immutable pipeline trace (00–06). The editable document (`Document` in
`page_model.py`) is deliberately different: it is **job-level** and **mutable** —
the user's editable working copy (translate / fix OCR / reorder before, or after,
baking a PDF). Stage 07 `assemble` builds it from the whole job; Stage 08
`render` is a **pure, re-runnable** function of it. Both read ONLY `document.json`
+ `document_assets/` — never the per-page folders — so a saved document survives
upstream re-runs (self-containment). Assemble won't clobber an edited document
without `--force`. See `docs/GATE4_SPEC.md`.

**Operator-book-box exception (Stage 02).** Item 2 says a stage reads only the
previous stage's artifacts. `<page_dir>/book_box.json` is not an artifact of any
stage: it is **user input**, the same kind of thing as `config.yaml` or
`--mode patch`, and it lives at the page-dir ROOT rather than in a numbered
folder so it can never be mistaken for one. No stage writes it —
`tools/book_box_editor` does, from a human's mouse. It exists because the book
detector provably cannot find the book on a pale or cluttered surface (eight cue
families measured and closed, RESULTS 2026-08-28), and a hand-drawn box splits
8/8 including both frames that fail today. Because it carries a human's
confidence it is checked, not trusted blindly: Stage 02 **refuses** a box whose
recorded frame or frame size does not match the current anchor (a box drawn
before Stage 01 re-ran is a confidently wrong crop), the box is **padded outward**
before anything is cut (measured: cutting to the drag exactly loses 1.95–9.73 %
of the book on a 1–5 % undersized drag, padding loses 0.00 %), and a missing or
corrupt file means the detector runs exactly as before.

**Higher-resolution figure exception (Stage 07).** Item 2 again. Stage 07 reads
`03_dewarp` and `06_uncertain`; `pipeline/figure_hires.py` makes `00_ingest` a
third per-page folder it reads — still upstream, still never written. It has to be
that one: the extra pixels a picture needs exist ONLY in the frames as shot, and
`01_fuse/anchor.png` is where Stage 01 already threw them away (it warps a
close-up DOWN into the anchor, so reading the anchor would be reading the loss).
The upgrade is an ADDITION, never a replacement: `Block.figure_asset` is optional,
None means "crop the page image" and is the normal case, and Stage 08 falls back
to the page crop whenever `figure_asset_box` does not equal the block's live bbox
— the document is mutable, and a high-resolution picture of a figure's OLD
outline is a wrong picture, which is worse than a soft one.

**Per-page frame-source exception (Stage 02, opt-in and OFF by default).** Item 2
says a stage reads only the previous stage's artifacts. Per-page frame selection
(`pipeline/page_source.py`, config `per_page_source.mode: ocr`) lets `left.png`
and `right.png` be cut from **different** full-spread photographs, so it needs
the gutter (Stage 02) *and* the candidate pixels (Stage 00) at once. With the
mode on — and only then — Stage 02 reads those frames back out of `00_ingest/`,
named by `01_fuse/fuse.json`'s `fullspread_frames`. The rule's purpose is
preserved: `00_ingest` is upstream, is never written, and the speculative
dewarp+OCR probe that decides is entirely in memory and writes no artifacts.
Consequence for the schema: `SubPage.box` is in the coordinates of the frame
named by the new `SubPage.source` — with the mode off that is always
`01_fuse/anchor.png` and the old "ORIGINAL spread coordinates" wording holds
verbatim. Default is off for a **measured** reason, not caution (RESULTS
2026-08-26); do not turn it on without reading that row.

### Job folder layout

```
jobs/<job_id>/<page_NNN>/            <- per-page, immutable pipeline trace
  00_ingest/    raw uploads normalized to RGB PNG + capture metadata
  01_fuse/      anchor image after multi-zoom stitch (or best single frame)
  02_split/     left.png, right.png (gutter split) — or single.png
  03_dewarp/    dewarped page image(s), full resolution
  04_layout/    layout.json (blocks: type, bbox, reading_order) + overlay
  05_ocr/       ocr.json (words: text, bbox, confidence, engine) + overlay
  06_uncertain/ resolved.json (per-word decision: keep/flag/patch) + patches/
  debug/        one overlay PNG per stage (04_layout.png, 05_ocr.png, ...)

jobs/<job_id>/                       <- JOB-LEVEL, editable (Stages 07–08)
  document.json         editable re-typeset doc (all pages, MUTABLE working copy)
  document_assets/      self-contained images: dewarp pages + flag/patch crops
  document.meta.json    Stage 07 assemble meta
  render/               page.html (always) + page.pdf (when a PDF engine exists)
```

### Pipeline stages

| Stage | Module | Does | Primary tools |
|---|---|---|---|
| 00 | `stage00_ingest` | RAW/JPEG → normalized RGB, EXIF, per-page folder | Pillow, rawpy |
| 01 | `stage01_fuse` | multi-zoom stitch onto anchor frame; pick sharpest frame | OpenCV (features + homography, ECC refine) |
| 02 | `stage02_split` | book-boundary crop (`book_boundary.py`) → gutter detection → left/right pages; optional per-page frame source (`page_source.py`, off by default) | OpenCV (projection profile, GrabCut) |
| 03 | `stage03_dewarp` | flatten page curvature | UVDoc (default), DocTr++ (partial crops) |
| 04 | `stage04_layout` | block detection + reading order | DocLayout-YOLO + XY-Cut++ |
| 05 | `stage05_ocr` | word-level text + bbox + confidence; caption ejection (`caption_eject.py`) + starved-block re-read (`block_reocr.py`) + figure-edge text absorption (`figure_text.py`) + per-block language label (`block_lang.py`) + table cell assignment (`table_grid.py`) | **Tesseract 5 TSV (backbone)**; EasyOCR second opinion for Cyrillic |
| 06 | `stage06_uncertainty` | per-word decision using user mode a/b/c | own code |
| 07 | `stage07_assemble` | job-level: build editable `document.json` + self-contained `document_assets/`; higher-resolution figure assets (`figure_hires.py`) | own code; OpenCV (SIFT + RANSAC + ECC) |
| 08 | `stage08_render` | `document.json` → re-typeset HTML (always, incl. real `<table>` from `Word.table_row`/`table_col`) → PDF (re-runnable) | own code; WeasyPrint/headless-Chromium (PDF, TBD), Noto fonts |

### Non-negotiable design decisions (do not "optimize" these away)

- **Tesseract 5 is the confidence/bounding-box backbone.** VLMs and Surya may
  be added as second opinions for hard passages, but they must NEVER be the
  sole text source or the confidence source (no reliable word boxes, no
  calibrated confidence, hallucination risk).
- **Confidence thresholds are adaptive per document**, never a single global
  hard-coded cutoff. Cross-engine disagreement is a second trigger for
  "uncertain", independent of raw confidence.
- **Uncertainty modes (user-selectable, all three must exist):**
  - `flag` — low-confidence words rendered in a highlighted span in the output;
  - `best_guess` — emit text plainly;
  - `patch` — crop the word's image box from the full-res dewarped page
    (03_dewarp output, NOT a downscaled copy) and inline it as a tiny `<img>`.
  - Markers are **per-word**: a marker clears only when *that* word is edited or
    deleted (Stage 08 renders on `Word.flag_visible`), never wholesale.
- **Reading-order mode (user-selectable, parallel to the uncertainty modes).**
  `DocSettings.order_mode`: `auto` (trust Stage 04's proposed order) or `review`
  (the editor surfaces every block's reading order for the user to confirm/correct
  before reconstruction). Unlike the uncertainty modes it changes **zero pipeline
  computation** — it is editor-review state over an already-assembled document.
  A block's "needs review" marker clears **per-block** and keyed on the *order
  field specifically* (`Block.order_review_visible`): the user renumbers
  (`reading_order` ≠ `order_auto`) OR explicitly accepts (`order_confirmed`); a
  type-only edit must NOT clear it. This is the *linear-order review* half only —
  caption↔figure **grouping** (ranked above exact order by the owner) is a
  separate, still-open concern.
- **Editable document before finalize (Stages 07–08).** The pipeline must save an
  editable-by-the-program `document.json` BEFORE finalizing to PDF, so the text
  can be corrected/translated first — or a PDF baked now and edited later.
  Render is a pure, re-runnable function of that document; edits round-trip.
  Editable text is a word-level layer with provenance (`text` = current,
  `text_ocr` = original OCR, kept forever); a block-level `text` override carries
  a translation and supersedes the words.
- **Figures are cropped from the full-resolution dewarped image** and placed
  with their captions as a single block in reading order.
- **De-hyphenation rule on reflow:** join a line-end hyphen with the next line
  only if the next line starts lowercase AND the joined token is in the
  per-language dictionary; otherwise keep the hyphen.
- **Running headers / page numbers are stripped by default** (user toggle to
  keep them).
- Reconstruction output is real text → the PDF is inherently searchable.
  Embed Noto fonts covering Latin + Cyrillic.

## Repo layout

```
bookscan/
  CLAUDE.md              <- this file: orientation, contract, guardrails
  docs/OPEN_PROBLEMS.md  <- ranked register of what is unsolved + next experiment
  docs/STATUS.md         <- chronological log of everything built/measured/refused
  docs/RESULTS.md        <- dated measurement rows (append-only)
  docs/plans/README.md   <- index of plans with their state (live/parked/done)
  docs/GATE*_SPEC.md     <- the gate specs (all gates done)
  docs/data/             <- machine-readable inputs+outputs behind a RESULTS row
                            (committed so a result is auditable without temp/)
  pipeline/              <- stages + page_model.py + run_all.py
  server/                <- FastAPI upload/status/preview server (BUILT)
  app-android/           <- Kotlin app, 3 Gradle modules (BUILT, unverified on
                            a real device): app/ UI+VM, capture/ frame scoring
                            + hover gate, network/ API client + retry
  testset/               <- fixed benchmark images + ground truth (NEVER edit
                            images; append-only). See testset/README.md
  jobs/                  <- runtime output, gitignored
  tools/                 <- harness scripts (accuracy eval, debug viewers)
  config.yaml            <- paths, languages, thresholds, model choices
```

## Conventions for working in this repo

- Python 3.11+, type hints everywhere, `pydantic` models in `page_model.py`.
- One stage per Claude Code session where possible. Always validate against
  `testset/` before declaring a stage done; commit per working stage.
- Every stage gets a `--debug` flag that also dumps intermediate arrays/crops.
- Windows host: prefer `pathlib`, no shell-isms in subprocess calls; Tesseract
  binary path comes from `config.yaml`.
- When debugging a bad page, inspect `jobs/<id>/<page>/debug/` overlays FIRST
  before reading code.
- **`tools/layout_order_eval` grades the SHIPPED block set (Stage 04 + Stage 05).**
  It runs the three later block-creating passes itself — orphan-word rescue,
  `caption_eject`, `block_reocr` — so a "miss" is a real absence from the
  document, not a stage boundary. (Closed 2026-08-26; before that the eval
  stopped after Stage 04 and understated segmentation recall by 3 of 112.)
  `--no-stage05` reproduces pre-2026-08-26 rows and does NOT grade the
  deliverable. **Never compare a row from one arm against a row from the other**:
  the tau column especially is a different quantity, because an orphan block
  re-ranks the whole set through XY-Cut before anything ships.
- GPU: assume a single consumer NVIDIA card; load models lazily per stage,
  release VRAM when a stage CLI exits.
- Accuracy numbers reported by `tools/` scripts go into `docs/RESULTS.md`
  (append a dated row; never overwrite history). A session that changes what
  is known also updates `docs/OPEN_PROBLEMS.md` (rewritten in place) and
  appends to `docs/STATUS.md`; the guardrail list in this file changes only
  when a measurement earns a new rule or retires one.
- `tools/split_eval` grades two rows (`de_01`/`de_02`) on anchors that live in
  gitignored `jobs/`; off the owner's machine they print `UNAVAILABLE` and the
  run still exits 1. The 19 rows it can grade from the repo are the
  non-regression bar everywhere else.
- **The Android app is installed over Wi-Fi debugging. That is the method this
  project uses** — not a USB cable, and not sideloading the APK through a
  browser. Build with `./gradlew assembleDebug` in `app-android/`, then push it
  to the phone with `adb install -r` over a wireless connection (recipe in
  **Commands** below). Do not offer the browser-download route as the default;
  it needs the operator to tap through an "install unknown apps" prompt and
  leaves a port open on the LAN, and adb reports success or failure of the
  install itself, which a browser download does not.
  **The one part Claude cannot do alone:** on Android 11+ a first pairing needs a
  six-digit code and a *random* pairing port that only exist while the phone's
  "Pair device with pairing code" dialog is open, and only the operator can read
  them off the screen. So ASK for the code and `IP:port` and wait — do not fall
  back to another install method because the phone is not yet visible. Once
  paired, the phone is remembered and later installs need only `adb connect`.

## Commands

**The console is the interface. Start here, not with a Python command.**
Double-click `bookscan.bat` (or `python -m uvicorn server.app:app --host 0.0.0.0
--port 8000`) and everything the operator does lives at `http://127.0.0.1:8000/`:
the job list, a per-page view of every stage overlay, the block and per-word
certainty inspector, re-run a page, assemble, render, and the text editor. The
CLIs below still exist and are still the contract — the console calls exactly
them, through `server/worker.py`'s subprocess — but they are for development and
measurement, not for processing a book.

```
# run one stage on one page
python -m pipeline.stage05_ocr jobs/demo/page_001/

# run full pipeline on a folder of captures
python -m pipeline.run_all --input testset/spread_03/ --job demo --mode flag

# draw the book box by hand when the detector could not find the book
# (writes <page>/book_box.json; "Save & re-split" re-runs Stage 02 only)
python -m tools.book_box_editor jobs/<job>/ [--port 8011]

# open the visual editor on an assembled job (edit OCR/type/order/translation,
# then Preview / re-render). Reads+writes ONLY document.json + document_assets/.
python -m pipeline.editor jobs/<job>/ [--port 8000]

# the console (the operator interface for everything above)
bookscan.bat            # or: python -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# Gate 1 harness
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md

# build + install the Android app over Wi-Fi (THE install method here)
cd app-android && ./gradlew assembleDebug
#   phone: Settings > Developer options > Wireless debugging > ON
#   first time only: tap "Pair device with pairing code", read off the 6-digit
#   code and the IP:PORT it shows (that port is random and dies with the dialog)
adb pair <ip>:<pairing_port> <code>      # first time on this machine only
adb connect <ip>:<connect_port>          # the port on the Wireless debugging screen
adb install -r app-android/app/build/outputs/apk/debug/app-debug.apk
#   adb lives at M:\claud_projects\android-sdk\platform-tools\adb.exe
#   `adb mdns services` lists the phone when wireless debugging is on; an empty
#   list means it is OFF, not that the network is broken
```
