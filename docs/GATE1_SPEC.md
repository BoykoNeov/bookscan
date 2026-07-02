# GATE 1 SPEC — OCR Quality Harness

## Purpose

Answer, with numbers, the go/no-go question for the whole project:

> Is Tesseract 5 word accuracy on decent phone photos of book pages good
> enough to make FULL text replacement viable, and does its per-word
> confidence actually separate correct words from wrong ones?

If yes → proceed to Gate 2 (capture enhancement).
If no → either invest in capture quality first, or pivot text extraction to a
VLM parser (MinerU/Surya) while keeping Tesseract only for flag/patch
machinery. Do not build anything else until this is answered.

## Inputs: the test set (`testset/`)

Manually captured with a phone camera (no app yet). Required composition:

| ID prefix | Content | Count |
|---|---|---|
| `en_clean_*` | modern English book, clean single/double column | 5 spreads |
| `bg_*` | Bulgarian (Cyrillic) pages | 3 spreads |
| `it_*` | Italian pages | 2 spreads |
| `de_*` | German pages | 2 spreads |
| `en_multicol_*` | multi-column or footnote-heavy English page | 2 spreads |
| `en_figures_*` | pages with images + captions | 2 spreads |
| `old_*` | older book / worn typeface | 2 spreads |
| `zoomset_*` | 1 full-spread anchor + 4 quadrant close-ups (same spread) | 3–4 sets |

Ground truth: for at least 5 pages (≥2 English, ≥1 Bulgarian, ≥1 with
footnotes), a plain-text file `testset/gt/<image_id>.txt` containing the exact
page text in reading order, one paragraph per line, hyphenated line-breaks
joined. Source: hand-typed or copied from an ebook edition of the same book.

`testset/manifest.csv` columns:
`image_id, file, language, gt_file (optional), category, notes`

Rules: the test set is append-only. Never edit or re-shoot an existing image
in place — add new IDs. All future gates benchmark against this same set.

## Deliverable: `tools/gate1_harness.py`

A CLI that, given `testset/`, produces `docs/RESULTS.md` (appended, dated) and
per-image debug artifacts. No pipeline stages required yet — the harness runs
Tesseract directly on lightly preprocessed images.

### Processing per image

1. **Light preprocessing only** (this gate measures OCR, not enhancement):
   grayscale, optional 2x upscale if median text height < 20 px, Otsu or
   adaptive binarization — try `none / otsu / adaptive` as a harness parameter
   and report all three.
2. Run Tesseract 5 with `--oem 1` (LSTM), correct `-l` per manifest language
   (`eng`, `bul`, `ita`, `deu`; use `eng+deu` style combos only as an extra
   experiment), `--psm 3`. Output TSV.
3. Parse TSV into the word list: `text, conf (0–100), bbox, line_id, block_id`.
4. Write debug overlay: page image with word boxes colored by confidence
   (green ≥ high, yellow mid, red low) → `testset/debug/<image_id>_conf.png`.
   This visualization is half the value of the gate — eyeball it.

### Metrics (per image with ground truth, and aggregated per language)

- **Word accuracy** = 1 − word-level edit distance (WER) between recognized
  text and ground truth, computed with a standard alignment
  (`jiwer` or `rapidfuzz`), after normalizing whitespace and joining
  hyphenated line breaks in the OCR output the same way the GT does.
- **Character accuracy (CER)** — more stable on short pages, report alongside.
- **Confidence separation** — the key novel metric of this gate. Using the
  GT alignment, label every recognized word correct/incorrect, then report:
  - histogram of confidence for correct vs. incorrect words (save as PNG),
  - **AUROC of confidence as a wrong-word detector** (rank-based; this is the
    number that matters, since Tesseract confidence is not calibrated and no
    global threshold is expected to work),
  - for each candidate flag-rate (5%, 10%, 20% of words flagged, i.e.
    per-document adaptive thresholds): what fraction of actual errors would
    be caught (recall of wrong words) and how many correct words get
    needlessly flagged (precision).
- **Per-language table** and per-category table (clean / multicol / old).

### Also in this gate (cheap, high-value)

- Run **EasyOCR** (`bg`,`en`) on the Bulgarian pages only; report its word
  accuracy and, on GT pages, how often Tesseract–EasyOCR disagreement predicts
  a Tesseract error (this validates "disagreement" as the second uncertainty
  trigger).
- On the `zoomset_*` sets: run Tesseract on the anchor-only image vs. on each
  quadrant close-up (crop GT accordingly is not needed — just report conf
  distribution + qualitative overlay). This is a *preview* of Gate 2's
  question, not its answer.

## Report format (`docs/RESULTS.md` appended section)

```
## Gate 1 run — YYYY-MM-DD, tesseract X.Y, preprocessing=<variant>
| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
...
Verdict: PASS / FAIL / MIXED + one-paragraph interpretation.
```

## Decision criteria

- **PASS:** clean English captures reach ≥ ~98% word accuracy (WER ≤ 2%),
  other languages within striking distance (≥ ~95%), and confidence AUROC
  comfortably above chance (≳ 0.80) so that flagging ~10% of words catches the
  majority of errors.
- **MIXED:** accuracy poor on raw photos but confidence signal good, and
  close-up shots visibly better → proceed, but Gate 2 (fusion/dewarp) becomes
  the priority and its bar is "reach the PASS numbers after enhancement."
- **FAIL:** accuracy poor even on the best close-ups AND/OR confidence does
  not separate errors → pivot: benchmark MinerU/Surya on the same test set as
  the text source before writing any pipeline stage.

## Implementation notes

- Dependencies: `pytesseract` (or direct subprocess + TSV parsing —
  preferred for control), `opencv-python`, `rapidfuzz` or `jiwer`,
  `matplotlib` (histograms), `easyocr` (Bulgarian second opinion only).
- Tesseract path and traineddata dir come from `config.yaml`
  (Windows: typically `C:\Program Files\Tesseract-OCR\tesseract.exe`;
  install `bul`, `ita`, `deu` traineddata from tessdata_best).
- Alignment for correct/incorrect word labeling: use the WER alignment ops
  (substitutions/deletions/insertions) from `jiwer`'s
  `process_words` or `rapidfuzz`'s editops over token lists.
- Keep the harness independent from `pipeline/` — it must stay runnable
  forever as a regression check whenever OCR settings or models change.
- Estimated size: one module, roughly 300–500 lines. One or two evenings
  with Claude Code.
