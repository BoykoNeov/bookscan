# Scope — Stage 04 figure separation (splitting under-segmented figure boxes)

**Status:** scoped, not started. **Date:** 2026-07-03. **Fixture:** it_geo_06 (the
grouping fixture). **Grounding:** empirical probe of the real DocLayout-YOLO output
+ crops + a corner-label OCR spike (artifacts in
`M:\claud_projects\temp\bookscan_fig_sep\`). **N=1** — tuned to one page.

## 1. Problem

DocLayout-YOLO under-segments physically adjacent figures into a single figure
box. This is the blocker gating the owner's #1 priority (caption↔figure
**grouping**, C26→F26) and Gate-4 reflow. It is NOT a parser gap — the
`caption_parser` (Task #4) already types + numbers the caption side; the figure
side has no per-figure box to attach to or to OCR a number from.

## 2. What the detector ACTUALLY emits (probed, not assumed)

Ran `stage04` detect+NMS on it_geo_06 (`probe_figboxes.py`). The GT's
"one merged box" note undersold it — real output:

**LEFT subpage (2129×3000)** — GT has 4 figures (F25/F27/F28 stacked in the left
column + F26 top-right plate):
| detected figure box | conf | maps to |
|---|---|---|
| x1611 y253 w498 h622 | 0.79 | **F26** — already clean ✓ |
| x203 y262 w1358 **h2550** | 0.33 | **tall merged F25+F27+F28** (whole left column) |
| x212 y272 w1345 h777 | 0.38 | partial **F25** dupe (top third; overlaps the tall box) |

**RIGHT subpage (1951×3000)** — GT has 2 figures (F29 top, F30 bottom-right):
| detected figure box | conf | maps to |
|---|---|---|
| x154 y279 w1554 h1925 | 0.44 | **merged F29+F30** — and it **absorbed the C29 caption** text |

Two distinct merge geometries (crops confirm both, `left/right.png_figure_*.png`):

- **LEFT = clean vertical stack.** The three cliff photos are separated by **wide,
  uniform page-background (cream) gutters** — NOT abutting. Each photo carries its
  corner label (25 / 27 / 28, bottom-right). → **projection-valley split is highly
  tractable.**
- **RIGHT = L-shape.** F29 spans the top full-width; the bottom band is
  **caption-column (C29 text) on the left | F30 photo on the right**, and the box
  swallowed the C29 caption. → needs recursive **H-then-V** cut **plus ejection of
  the absorbed caption text.** Harder.

## 3. Success criteria (read this before grading)

Per advisor, tracing C26 (x≈1604, y1480–2111) against the probe coords: after the
left split, C26's **nearest figure by edge-gap is F27** (x-gap≈43px, same y-band),
**not** its true partner F26 (~600px above). So:

- **Figure separation moves NO grouping metric on its own.** The geometric
  `nearest_ok` arm still mispairs C25/C26/C27/C28 **by design** (that's the trap the
  fixture was built around); `n_pairs_by_number` stays 0 until figure numbers are
  OCR'd (#2, §7).
- **It may make the geometric grouping arm look *worse*** (more distinct
  wrong-nearest figures). **Expect and state this** so the post-change eval doesn't
  read as a regression.

**#1's success bar is therefore:**
1. **Figure seg-recall up** — left 3→4 clean figure boxes (F25/F27/F28/F26),
   right 1→2 (F29/F30).
2. **Zero false-splits on the single-figure pages** (it_geo_04 / it_geo_05 /
   it_geo_07) — a single photo must never be cut.
3. **Figures individually boxed → OCR-ready** (each figure now has its own tight
   box for #2 to localize the corner label within).

NOT "grouping improves." Grouping is a **#1+#2 unit** (§7).

## 4. Approach — `split_merged_figures` (post-detector geometry pass)

A pure geometry function operating on each `figure` detection's crop:

1. **Background mask.** A pixel is "page background" if close (in Lab/HSV) to the
   **sampled page-margin color** — sample from the subpage's outer margins, do NOT
   hard-code cream (the sofa shot's lighting drifts; advisor). Photo content (sky,
   grass, rock) never matches the warm low-saturation page cream, so this is
   specific.
2. **Recursive H-then-V cut** (mirror `xy_cut_order` / `_split_by_gaps`): a **seam**
   is a run of rows (then cols) that are (a) background-colored **AND** (b) span the
   **full box width** (resp. height), wider than `fig_gap_frac` of the box
   dimension. The **full-span + sampled-margin** pair is the over-split guard — no
   full-width margin-colored band exists *inside* one photo (F29's smooth sky is
   low-texture but blue, not cream).
3. **Accept a split only if** it yields ≥2 sub-boxes each above `fig_min_area_frac`
   of the original; else keep the original box unchanged. Never over-split.
4. **Eject absorbed text** (right case): a sub-band that is text-like / matches a
   separately-detected caption box is re-typed (or dropped) so it isn't counted a
   figure. (Left case has no absorbed text.)
5. **Reconcile overlaps.** After splitting, re-run the containment prune
   (`nms_and_dedup`) so the conf-0.38 partial-F25 dupe is absorbed by its sub-box
   and the C29 caption isn't double-counted.

**Where it plugs in:** `stage04_layout.dets_to_blocks`, **after** `nms_and_dedup`
and **before** `xy_cut_order` — split figure `RawDet`s, then order/type the
expanded set as usual. New knobs live in `DEFAULTS` (layout-geometry heuristics,
same class as the existing XY-cut gaps — NOT the forbidden global OCR thresholds).

## 5. Staging (do NOT let the hard case block the easy 80%)

- **Phase A — left column (clean stacked split).** Wide full-width cream gutters,
  unambiguous valleys. Ship this alone: left figure seg-recall 3→4. This is the
  high-confidence win.
- **Phase B — right L-shape (H-then-V + text ejection).** Recursive cut + eject the
  absorbed C29 caption. Separately scoped; lower confidence.

## 6. How to prove it (metric)

- `tools/layout_order_eval --image it_geo_06` — figure **seg-recall** is the headline
  (figures match GT by reading-order rank, so also **verify post-split order is
  column-major**: F25,F27,F28 then F26 — else a correct split won't be credited).
- **Regression guard:** run the eval on **it_geo_04 / 05 / 07** and confirm
  `n figures unchanged` (zero false-splits) — this is criterion 3.2 and the main
  risk.
- Expect the geometric grouping arm to stay red (or dip) — annotate, don't chase.

## 7. Relationship to #2 (corner-label OCR) — the actual grouping win

Grouping (C26→F26) only lands when figure numbers feed `caption_parser.pair_by_number`.
Geometric nearest-figure **cannot** do it (advisor traced C26→F27). So the number is
the only route, and the number lives in the in-photo corner label.

**Spike result** (`spike_corner_ocr2.py`, tight bottom-right crop + 5× upscale +
whitelist OCR): **2/5 clean hits** — F25→'25', F29→'29' — and the ink is clearly
present on the rest (F27 reads '7'/'2' separately; F28/F30 return fragments; all
five are legible to the eye). Verdict: corner-label OCR is **feasible but not free**
— reliable 6/6 needs real digit-localization (a tight glyph bbox via white-glyph
connected-components, not a fixed corner fraction) + de-textured preprocessing.

**Consequence for framing:** #1 is **step one of the grouping win**, not a dead-end
segmentation nicety — but #1 alone shows **zero** grouping-metric movement. Build
#1 (seg-recall, OCR-ready boxes) → then #2 (localize+OCR the label per split box) →
`pair_by_number` 0→6, defeating the trap. Do not expect the owner's #1 to move
until #2 lands.

## 8. Risks / caveats

- **N=1.** Params tuned to it_geo_06. `sample-the-margin + full-span + min-gap-as-
  fraction` keeps it from being pixel-tuned, but generalization is **unproven** until
  a second merged-figure fixture exists. State this in RESULTS.
- **Right L-case fragility** (absorbed caption text, F30 overlapping the body
  column) — deferred to Phase B; may not fully resolve.
- **False-split on a single photo with an internal margin-like band** — guarded by
  full-span + sampled-margin, must be verified on it_geo_04/05/07.
