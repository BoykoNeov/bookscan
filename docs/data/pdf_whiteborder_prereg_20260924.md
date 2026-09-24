# Pre-registration — a white border before flattening imported flat scans

Written 2026-09-24, **after the border width was fixed from geometry and before
any word count was taken with the border.** Owner's decision the same day
("add white"), choosing between a border and skipping flattening for imports.

## The defect

Stage 03's neural flattening (UVDoc) was built for curved pages photographed on
a table. On an already-flat scanned page it ENLARGES the page, and on a scan with
thin margins the start or end of a line falls off the image ("suspended" became
"spended"). Found during the text-layer test (RESULTS 2026-09-24): 40 and 16
Tesseract words touching the left/right edge on D6 pages 1 and 3, one each at
top/bottom on D2 p1, D2 p3, D4 p1 — a lower bound, since a word pushed wholly off
the page leaves no box to count.

## The fix, fixed now

On the UVDoc arm only, and only for a page whose `02_split/split.json` says
`layout_origin == "pdf_import"` (written by the importer on every page it makes;
never on a phone page), Stage 03 pads the page with white on all four sides
before flattening, and keeps the padded size (cropping it back off would cut the
text again). The classical arm is untouched (it moves text vertically only).

**Border width: 15 % of the page's width on the left and right, 15 % of its
height at top and bottom.** Derived before any outcome from how far UVDoc pushes
each imported page's own edges past the frame (SIFT + RANSAC homography from the
Stage 02 image to the Stage 03 image, all 24 pages of the text-layer test;
`docs/data/pdf_whiteborder_20260924/uvdoc_overshoot.out`): typically 3–9 % per
side, maximum 13.69 % (D5 page 2, top). Rule: the largest overshoot measured on
any side of any page, rounded up to the next 5 %.

**One fallback, fixed now:** if the padded run still maps any page's original
edge outside its output frame (the same registration, re-run), the width is
judged insufficient and ONE second width, 25 %, is run and reported. No third.

## Population

The 24 pages of the text-layer test (`docs/data/pdf_textlayer_20260924/
manifest.json`): D1–D7 (20 scanned pages) and the control C (4 pages of this
pipeline's own rendered PDF). Run on a COPY of the work folder; the audited
pages are not touched. Every page re-runs from Stage 02 (`run_all` from
`02_split`, `--mode flag --lang eng`), the importer's `origin` added to each copy's
`page_layout.json` as the importer now writes it.

## Measures, per page, before (audited run) and after (bordered run)

1. **Edge census:** Tesseract words whose box touches any edge of the Stage 03
   image (`edge_census.py`, all four sides).
2. **Agreement with the PDF's own text layer** (an independent reading of the
   same page; the control's layer is the text by construction): the number of
   Tesseract tokens inside `equal` runs of the sequence alignment
   (`pipeline/pdf_text_layer.py`'s `prep_tokens` + `align`), and total Tesseract
   tokens.
3. **Overshoot re-registration** (the fallback trigger above).

## The gate (fixed now)

Ship the border if **all** hold:

1. **It fixes the defect:** words touching an edge, summed over the 24 pages, fall
   from 60 to **at most 3**; and D6 pages 1 and 3 together gain agreeing tokens.
2. **It harms nothing else:** summed over the other 22 pages, agreeing tokens do
   not fall by more than **0.5 %**, and no single page loses more than **2 %** of
   its agreeing tokens.
3. **Control:** the 4 control pages' agreeing tokens do not fall in total.

A failure is a refusal, reported like any other; the alternative the owner was
offered (skip flattening for imported pages) is then the next thing to measure.

## Also reported, never gating

* D5, whose scans carry a black scanner border that flattening currently removes:
  what the white frame around it does, by looking at the Stage 03 image.
* The text-layer marker re-checked on the bordered pages (the reviewer's point):
  which of the 71 labelled sites vanished and how they had been labelled, how
  many new unlabelled sites appeared, and whether any clause of that test's pass
  mark could flip. The pass sat at exactly 4 documents, D6 among them.

## Stated limits, now

Scholarly and technical print, English, 7 producers; the border width is derived
from the same pages it is tested on (geometry only, fixed before any word count);
phone pages are unaffected by construction (no `layout_origin`), shown by a unit
test, not by a re-run; a PDF of a book PHOTOGRAPHED on a surface gets the border
too, and that case is not in this population.

## Correction, 2026-09-24 — before any bordered run

The baseline in gate clause 1 read "59"; the committed census sums to 60 (57
left/right: D4 p2 1, D6 p1 40, D6 p3 16; 3 top/bottom: D2 p1, D2 p3, D4 p1). The
threshold (at most 3) is unchanged.

## Addendum, 2026-09-24 — after both border widths were REFUSED, before any number for this arm

Both widths failed the gate (15 %: other pages -2.97 %, worst -23.6 %; 25 %:
-5.04 %, worst -25.5 %, control down too); no third width, as fixed above. The
reason is visible, not inferred: with a white frame UVDoc *bends* a page that was
flat (D3 page 1's right column slopes and curves).

The next arm named above is measured now, before any number exists for it:
**skip flattening for imported pages** — the Stage 03 image of an imported page
is its Stage 02 image, unchanged. Same 24 pages, same measures, same gate
(clauses 1–3 as written; the fallback clause does not apply). Produced on a copy
by writing each page's `03_dewarp/<name>` as a copy of `02_split/<name>` and
running Stages 04–06 unchanged.

Also reported: D5 (flattening was what removed its black scanner frame; without
it the frame stays — look for junk blocks or words), and the same re-check of the
text-layer marker's labelled sites. Stated limit: none of the 20 scanned pages is
a crooked scan, so what is lost by not straightening one is NOT measured here.
