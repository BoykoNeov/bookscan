# bookscan

Book-scanning system that produces **fully re-typeset searchable PDFs**:
photographed text is *replaced* with clean rendered text (reflowed layout),
while figures are cropped from the page photos and placed back in reading
order. OCR output becomes the visible document — so error handling is the
load-bearing feature.

See [`CLAUDE.md`](CLAUDE.md) for the full architecture and the stage contract.

## Components

- **`pipeline/`** — staged, per-page, artifact-driven processing. Each stage is
  an independent CLI (`python -m pipeline.stageNN jobs/<job>/<page>/`) sharing
  the schema in `pipeline/page_model.py`.
- **`server/`** — FastAPI on Windows + NVIDIA GPU (built at Gate 5).
- **`app-android/`** — guided-capture Kotlin app (built at Gate 5).
- **`tools/`** — harness / eval scripts, independent of `pipeline/`.
- **`testset/`** — fixed benchmark images + ground truth (append-only).

Target OCR languages (priority order): English, Bulgarian, Italian, German.

## Status

Gate 1 (OCR quality harness) is in progress — see
[`docs/GATE1_SPEC.md`](docs/GATE1_SPEC.md). Results land in `docs/RESULTS.md`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

Install Tesseract 5, then build the language-data dir (downloads
`eng`/`bul`/`ita`/`deu` from `tessdata_best` and copies Tesseract's output
configs so TSV works):

```bash
# Windows: winget install --id UB-Mannheim.TesseractOCR
python -m tools.setup_tessdata
```

Adjust the Tesseract binary path in [`config.yaml`](config.yaml) if it isn't at
the Windows default.

## Commands

```bash
# Gate 1 harness (built during Gate 1)
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md

# run one stage on one page (once stages exist)
python -m pipeline.stage05_ocr jobs/demo/page_001/
```
