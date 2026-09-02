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

All five gates are done (OCR harness, fusion/split/dewarp, layout, end-to-end
re-typeset PDF, server + Android app). Start with
[`CLAUDE.md`](CLAUDE.md) for the contract and the measured guardrails,
[`docs/OPEN_PROBLEMS.md`](docs/OPEN_PROBLEMS.md) for what is still unsolved and
the next experiment for each, [`docs/STATUS.md`](docs/STATUS.md) for the
chronological record, and [`docs/RESULTS.md`](docs/RESULTS.md) for the numbers.

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
# the operator console (the interface)
bookscan.bat            # or: python -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# Stage 02 split guard (red on purpose at 19/21 — see CLAUDE.md)
python -m tools.split_eval

# Gate 1 harness
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md

# run one stage on one page
python -m pipeline.stage05_ocr jobs/demo/page_001/

# unit tests (no GPU, no Tesseract needed)
python -m pytest pipeline/tests tools/tests -q
```
