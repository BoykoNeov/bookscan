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
- [ ] Gate 3: layout + reading order correct on complex pages — IN PROGRESS
- [ ] Gate 4: end-to-end re-typeset PDF reads correctly
- [ ] Gate 5: server + Android app

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
| 02 | `stage02_split` | gutter detection → left/right pages | OpenCV (projection profile) |
| 03 | `stage03_dewarp` | flatten page curvature | UVDoc (default), DocTr++ (partial crops) |
| 04 | `stage04_layout` | block detection + reading order | DocLayout-YOLO + XY-Cut++ |
| 05 | `stage05_ocr` | word-level text + bbox + confidence | **Tesseract 5 TSV (backbone)**; EasyOCR second opinion for Cyrillic |
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
  pipeline/              <- stages + page_model.py + run_all.py
  server/                <- FastAPI (built at Gate 5, empty until then)
  app-android/           <- Kotlin app (built at Gate 5, empty until then)
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

# Gate 1 harness
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md
```
