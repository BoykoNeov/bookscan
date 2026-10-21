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

## Amendment (same day, before any close-up was read)

The region-level B arm is empty: by the match, **no close-up holds either
region whole** (best coverage 0.875 on R157 and on R156; 12 and 10 partial, 7
and 9 absent). Seen at that point: the anchor's region CER only (R157 2.77 %,
R156 5.26 %); no close-up reading. The unit therefore moves from the region to
the **printed line**, fixed as follows before any close-up is read:

- **Lines.** The anchor's region read is grouped by Tesseract's own lines;
  if that gives exactly as many lines as the reference (17 and 11), line *i* is
  reference line *i* (the reference was typed line for line as printed). If not,
  ink-row projection of the region crop is used instead, under the same
  count rule; if neither gives the count, the region is dropped and said so.
  Each line's band runs halfway to its neighbours.
- **Close-up placement.** The region's own match (the same crop→frame
  homography as above) maps each line band into the close-up. A close-up
  **holds a line** if all four corners of the band, shrunk 1 % horizontally,
  land inside the frame at least 1 % of its size from the edge.
- **Reading.** Each close-up reads its part of the region once (bounding
  rectangle of the region's quadrilateral clipped to the frame, turned
  upright as above). Every word's centre is mapped back into page coordinates
  and given to the band containing it; a line's text is its words in
  page-x order. The anchor's words are assigned the same way.
- **Scoring.** Per line, CER against the reference line (quotes and dashes
  normalised, whitespace collapsed; no hyphen joining, since a line is scored
  alone). Over the lines held by at least one close-up: `a` = the anchor's
  character-weighted CER on those lines; `m` = character-weighted mean of
  each line's *median* close-up CER; `b` = same with each line's *best*
  close-up. The decision rules above apply unchanged to `a`, `m`, `b`.
- Coverage reported as lines held by ≥ 1 close-up / all lines.
