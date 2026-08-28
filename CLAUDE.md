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

## Current status

<!-- UPDATE THIS SECTION AS WORK PROGRESSES -->
- [x] Gate 1: OCR quality harness (see `docs/GATE1_SPEC.md`) — DONE
- [x] Gate 2: fusion + split + dewarp improve OCR accuracy — DONE
- [x] Gate 3: layout + reading order correct on complex pages — DONE
- [x] Gate 4: end-to-end re-typeset PDF reads correctly — DONE
- [x] Gate 5: server + Android app — desktop FastAPI server DONE (see
      `docs/plans/partitioned-questing-pillow.md`); Android app M1–M5 BUILT and
      **VERIFIED ON A REAL PHONE 2026-08-28** (see
      `docs/plans/android-guided-capture.md` and RESULTS 2026-08-28): job
      list/resume, 7/7 stage progress, manual capture → upload → all seven
      stages, an 18-image page, upload retry over a dropped link, server killed
      mid-page and recovered, and the uncertainty mode chosen on the phone.
      **Auto-capture was demoted to an opt-in toggle** by that session — armed
      on a real spread it delivered one still, not the measured four — so
      manual capture is the flow.
      **Known open defect, not an app one:** neither real capture split into
      pages. `pipeline/book_boundary.py` returns the whole frame on a pale
      background, so the crop abstains and Stage 02's ink cue picks a white
      channel *inside* a page. Fix not attempted (13+ non-regression fixtures);
      planned in `docs/plans/book-detector-pale-background.md`. Its **Phase 0 is
      DONE 2026-08-28**: both failing frames are committed, labelled fixtures
      (`testset/paleset_01/02` + book-box and gutter GT), so **`tools/split_eval`
      now reads 19/21 and exits 1 on purpose** — the owner chose a red suite over
      hiding two known failures, so do NOT "fix" it by removing those rows.
      Scouting 2026-08-28 already closed the obvious fix: retuning the HSV
      thresholds cannot work (see the plan's section 5). **Phase 1 is DONE
      2026-08-28**: the artifacts no longer claim things they did not measure —
      the abstain reason stopped asserting "already tightly framed", the
      spine-pinch cue declares itself inapplicable where it cannot measure (and
      Layer 2 is skipped), and `corroborated` became `pinch_corroborated` plus a
      `corroborated_by` about the column that actually shipped. Zero accuracy
      change, verified by diffing the eval against HEAD. It also **closed B1's
      classifier by measurement** — six cheap ways to ask "was a book actually
      found?" all fail, because on a tight scan the book really does reach the
      frame border, so the only route is asking whether there is a background at
      all. **A10 (background-first) was then MEASURED 2026-08-28 and
      NOT shipped:** it fixes `paleset_02` outright (0.00% clipping, gutter 1752
      vs 1778) and wrecks `paleset_01` (clips 20.85% of the book, because that
      book runs off the left frame edge so the background model gets fitted to
      paper). Half the precondition is solved — how many frame sides the candidate
      blob touches — but "is there a background at all" has no cheap answer:
      eight families measured, all fail, structurally, because on a tight scan the
      method finds the printed area and a printed area is also large, rectangular,
      compact and darker-bordered. **n = 1:** the 31 archived pale captures are two
      scenes, not 31 examples, so more fixtures must be NEW photographs of NEW
      surfaces. Awaiting an owner call between shipping it off-by-default (the
      `per_page_source` precedent), gathering that data, or escalating to A9 (the
      phone supplies the box).

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
| 05 | `stage05_ocr` | word-level text + bbox + confidence; caption ejection (`caption_eject.py`) + starved-block re-read (`block_reocr.py`) + figure-edge text absorption (`figure_text.py`) | **Tesseract 5 TSV (backbone)**; EasyOCR second opinion for Cyrillic |
| 06 | `stage06_uncertainty` | per-word decision using user mode a/b/c | own code |
| 07 | `stage07_assemble` | job-level: build editable `document.json` + self-contained `document_assets/` | own code |
| 08 | `stage08_render` | `document.json` → re-typeset HTML (always) → PDF (re-runnable) | own code; WeasyPrint/headless-Chromium (PDF, TBD), Noto fonts |

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
  CLAUDE.md              <- this file
  docs/GATE1_SPEC.md     <- current work spec
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
  (append a dated row; never overwrite history).

## Commands

```
# run one stage on one page
python -m pipeline.stage05_ocr jobs/demo/page_001/

# run full pipeline on a folder of captures
python -m pipeline.run_all --input testset/spread_03/ --job demo --mode flag

# open the visual editor on an assembled job (edit OCR/type/order/translation,
# then Preview / re-render). Reads+writes ONLY document.json + document_assets/.
python -m pipeline.editor jobs/<job>/ [--port 8000]

# Gate 1 harness
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md
```
