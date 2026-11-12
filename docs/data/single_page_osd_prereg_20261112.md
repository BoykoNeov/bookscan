# Pre-registration — does Stage 00 turn an upright imported PDF page sideways? (2026-11-12)

Written and committed before the instrument has run on any page. Hand-off item 3
(`docs/plans/handoff-2026-11-12.md`).

## Why

Stage 00 orients every frame with `tools/normalize.py`'s cascade, designed for
photographed spreads. It accepts a 90°/270° Tesseract OSD call at confidence
≥ 2.0 (`ingest.min_osd_conf`) *because* a wrong one turns a landscape spread
portrait and the landscape check then warns. On a portrait single page that
safety net points the wrong way: a wrong 90° call makes the page landscape,
which looks right, and nothing warns. Whether this ever happens on real
imported pages is unmeasured.

## Population (fixed by rule, chosen before any OSD result exists)

1. Every PDF in `docs/data/pdf_textlayer_20260924/manifest.json` that still
   exists at its recorded path **and** has the recorded SHA-256. Per PDF: up to
   20 pages, evenly spaced from the first to the last
   (`round(linspace(1, page_count, min(20, page_count)))`, duplicates removed).
   Covers, blank pages, figure pages and index pages are kept: they are part of
   an imported book. D5 (`ADA431357.pdf`) is known to be gone and is excluded
   by this rule, not by choice. The manifest's `C` entry (this project's own
   re-typeset render, `jobs/figtext_en_coins_01/render/page.pdf`) is
   **excluded by decision**: it is software-made crisp text, not a scan, and
   would only add easy correct calls.
2. The two raw frames of `jobs/pdfimp_import_en_coins_01` (one declared spread,
   one declared single page, `raw/frame_00.png`).

Each PDF page is rendered exactly as `pipeline/pdf_import.py` renders it
(`page.get_pixmap(dpi=300, alpha=False, colorspace=csRGB)`), then oriented with
`tools.normalize.orient_upright` at the shipped floors (2.0 / 5.0) — the same
call Stage 00 makes, minus the file load — with the Tesseract binary and
tessdata folder Stage 00 itself resolves
(`stage00_ingest.resolve_tesseract(load_config(config.yaml))`), so the
`osd.traineddata` is the shipped one. Each page also gets the importer's own
verdict (`pdf_import.survey`, `--layout detect`: single or spread by aspect).

**Headline population = pages the importer calls `single`.** Pages it calls
`spread` are reported in a separate line and do not trigger the decision: a
wrong 90° on a landscape page makes it portrait, which the existing landscape
check already warns about.

**Ground truth.** A PDF page renders upright by construction, unless the book
itself prints it sideways (a landscape table). Every page on which OSD proposes
any rotation other than 0 is looked at by Claude (a downscaled render) and
recorded as `upright` or `sideways_in_source` before the decision below is
applied. The look happens on a contact sheet that does **not** show OSD's
proposed angle, so the proposal cannot steer the verdict. That adjudication is
written down per page in the output JSON.

## Arms

- **U (as rendered).** Statistic: the number of `upright` pages on which the
  cascade *applies* a rotation, split into 90/270 and 180; and the OSD
  confidence of every non-zero proposal on an `upright` page (wrong calls),
  reported with its maximum.
- **Control R (rotated on purpose).** Every page of the population is also run
  rotated 90° clockwise and 90° counter-clockwise. The right answer is known
  (270 and 90 respectively, or for a `sideways_in_source` page, the rotation
  that undoes both). Statistic: how many are restored, and the confidence of
  the correct calls, reported with its minimum — the same two-population
  report `ingest.min_osd_conf_180` was derived from. The control shows the
  instrument can see a rotation at all; it is synthetic and is not a cost
  estimate of real sideways pages.

## Decision (fixed now)

- **No `upright` single page rotated by the cascade (90/270) →** fix the warning only:
  Stage 00 reads `<page_dir>/page_layout.json` and does not emit the PORTRAIT
  warning when `layout == "single"`.
- **At least one `upright` single page rotated 90/270 →** also, for
  `origin == "pdf_import"` pages, skip the 90/270 branch entirely (keep the 180
  branch on its own floor) and record `orientation_policy` in the stage's
  `meta.json`. Its cost is reported, not gated: the `sideways_in_source` pages
  of the sample that the cascade turned correctly would no longer be turned.
- A wrong **180** on an `upright` page (at ≥ 5.0) is reported but changes
  nothing here: `min_osd_conf_180` was measured on phone captures and is not
  this item's to move. Neither floor is changed under any outcome.

## Not tested

A photographed book bound into a PDF (pages genuinely crooked or rotated in
the file); non-English PDFs; pages at a dpi other than 300. n is a sample of
6–7 scanned documents' pages; a zero count says "not seen in this sample",
not "never".
