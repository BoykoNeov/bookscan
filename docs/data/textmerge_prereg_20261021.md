# Pre-registration — do full-size close-ups READ better than the whole-spread photo? (ceiling check, 2026-10-21)

Written before any reading of the regions below exists. The owner approved the
capture plan the same day: one whole-spread photograph plus tapped close-ups,
text combined as *readings* (each close-up read on its own, the readings merged
by placement), never as pasted pixels. This is the step before building any
merger: if a single close-up does not read its region clearly better than the
whole-spread photograph does, no merge of close-ups can help, and nothing is
built.

## Why this is not a re-run of a refused experiment

OPEN_PROBLEMS P4 lists "reading each close-up separately and merging words" as
REFUSED, from RESULTS 2026-08-29 ("a wash"). That row is bounded in its own
words: close-ups framed on the *page*, median **1.30×** linear, shrunk by the
phone to half their area. Today's close-ups (job `20261021-104424-6d43b587`,
page_003) are uploaded at full sensor size, tapped by hand, and sit
**2.2–2.8×** the anchor's scale (RESULTS 2026-10-21, sweep placement). That is
the new data that licenses asking again. The merge itself is not tested here.

## Fixture and reference text

Page_003 of that job: the coin book, pp. 156–157, one whole-spread frame
(`frame_00`) and 19 close-ups. Read on the page as re-run today with Stage 01
v0.4.0 (no close-up blended into the anchor; the earlier anchor printed text
twice — RESULTS 2026-10-21).

Two regions, each inside one page (the job ran this spread as one `single`
page; Tesseract lines must not run across the gutter):

- **R157**: p. 157, the two "Description" paragraphs (17 lines, ending
  "1835-45."; the footnote marker and footnote excluded).
- **R156**: p. 156, the last two body paragraphs ("Though the superior
  fineness…" to "…on p. 233."; 11 lines).

Reference text: `textmerge_20261021/gt_p157_description.txt`,
`gt_p156_body.txt`, **typed by Claude from the sharpest close-ups**
(frames 02, 14, 18, cross-checked against 05/17 and the line starts on others),
not by the owner, committed with this file before any OCR of the regions. No
word was unreadable; the typographic quotes, en dash and the superscript "th" in
"19th" are typed as printed, and those characters are normalised before
scoring (below). Typed from close-up pixels, the reference can only lean
toward the close-up arm where the pixels are ambiguous; none was found
ambiguous. The owner is offered a spot check.

Region rectangles are drawn by eye on the re-run `03_dewarp/single.png` and
committed as `textmerge_20261021/regions.json` before any OCR is run.

## Arms (the same reader on both)

The reader is Tesseract as Stage 05 calls it (config binary, `eng`, the
stage's page-segmentation mode), on a crop. Words are kept if their centre lies
inside the region (mapped into the frame for a close-up).

- **A — whole-spread photograph**: the region cut from the re-run dewarped page.
- **B — each close-up that holds the whole region**: the region is located in
  the raw close-up by `figure_hires`' crop→frame SIFT match (seeded RANSAC,
  ECC refine), required to lie wholly inside the frame (coverage 1.0); the
  bounding rectangle of that quadrilateral (plus a 2 % margin) is read raw —
  no dewarp — and words outside the quadrilateral are dropped. Several
  close-ups are stored sideways (Stage 00 does not turn close-ups), so the crop
  is first turned by the multiple of 90° that brings the region's top edge
  (from the match) nearest to upright; nothing else is warped. A close-up
  holding only part of the region is counted, not read.

## Scoring

`tools.ocr_metrics`: CER on normalised text and WER on its tokens, against
the reference. Normalisation for both sides: ‘ ’ “ ” → ' ", – — → -,
line-end hyphens joined (`normalize_text`), whitespace collapsed. Case and
other punctuation kept. Every word-level difference is listed (the text diff),
not only the rate.

## Decision (fixed now)

Per region: the anchor's CER `a`; the median CER `m` and best CER `b` over the
close-ups holding the whole region.

- **Build the merger** if, on at least one region, `m ≤ a − 1.0` points **and**
  `m ≤ 0.75 · a` — the *typical* covering close-up reads clearly better, not
  only the luckiest one.
- **Stop (record a refusal)** if on both regions `b ≥ a` — no close-up reads
  better.
- Anything in between: recorded as "close-ups read better only sometimes";
  no merger built before the owner sees the diffs.

Also reported: per region, how many close-ups hold it whole, in part, or not at
all (coverage), and both arms' word diffs.

## What this cannot say

One spread, one book, one session, one reader; a raw (unflattened) close-up;
two regions of plain body text (no tables, no small print). It says nothing
about the merge, about placement of partial close-ups, or about text a model
writes.
