# Scope — Stage 04 figure separation (splitting under-segmented figure boxes)

**Status:** **Phase A BUILT** (2026-07-03) — `split_merged_figures` in
`stage04_layout`, horizontal seams only; proven on it_geo_06 (figures left 3→4,
right 1→2; seg-recall 7/8→8/8 and 5/6→6/6), zero false-splits on it_geo_04/05/07,
6 new unit tests, full suite 84 green. Results + the honest grouping-arm annotation
in `docs/RESULTS.md`. **Phase B BUILT (2026-08-09)** — H-then-V + absorbed-text
ejection; the duplicated-caption output defect of §5 is GONE (C29 coverage by a
figure **0.967 → 0.000**, F30 IoU **0.633 → 0.908**), at the cost of one
geometry pair that only existed *because* of the defect (§9). **Date scoped:**
2026-07-03. **Fixture:** it_geo_06 (the grouping fixture). **Grounding:** empirical
probe of the real DocLayout-YOLO output + crops + a corner-label OCR spike
(artifacts in `M:\claud_projects\temp\bookscan_fig_sep\`; the Phase B probe +
before/after crops in `M:\claud_projects\temp\bookscan_phaseb\`). **N=1** — tuned
to one page.

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
- **Phase B — right L-shape (H-then-V + text ejection). BUILT 2026-08-09.**
  **The OUTPUT defect it fixed (measured 2026-08-09 on the real assembled
  `grouping_it06` document, not inferred):** the right subpage's remaining merged box
  (block #3, `154,1341 1554x842`) contained caption C29's box (`156,1487 440x720`) at
  **0.97** — and the crop confirmed it visually. So the rendered deliverable showed the
  **Figura 29 caption twice**: once as PIXELS inside the Figura 30 `<figure>` image,
  once as reflowed text in Figura 29's own `<figcaption>`. No amount of pairing
  (including the editor's manual pairing control) could fix this — it is a crop-
  boundary problem, i.e. exactly Phase B's ejection step.
  **What shipped:** `_cut_figure(..., axis)` generalizes Phase A's row-seam cut to
  either axis; `_split_figure_hv` runs H then V at **depth 2, not general recursion**;
  `_absorbed_text` ejects a sub-box that a non-figure detection covers by
  `fig_eject_text_cover` (0.60). Verified in a **fresh job** (`phaseb_it06` — the
  human pairing rulings in `grouping_it06` were left intact, no `--force`).

## 6. How to prove it (metric)

- `tools/layout_order_eval --image it_geo_06` — figure **seg-recall** is the headline
  (figures match GT by reading-order rank, so also **verify post-split order is
  column-major**: F25,F27,F28 then F26 — else a correct split won't be credited).
- **Regression guard:** run the eval on **it_geo_04 / 05 / 07** and confirm
  `n figures unchanged` (zero false-splits) — this is criterion 3.2 and the main
  risk. **Phase B additions:** also grade **it_geo_06-LEFT** (must stay exactly 4
  figure boxes — the likeliest false-split is a V-cut through a cliff photo) and
  **de_01**. The Phase A scoping forgot the left subpage; the false-split it missed
  turned up on it_geo_05-left (§8).
- **GAP CLOSED 2026-08-09 — `tau+figures`.** The gap was: figure reading order was
  UNGRADED, so the sentence above about verifying column-major order had no metric
  behind it. When the eval moved figure matching from reading-order rank to GT-bbox
  IoU (task #3, deliberately, to stop the match being circular), figures stopped being
  ordered by the metric at all — `tau` is computed over TEXT blocks only, in both arms
  (correctly: the Tesseract-native arm cannot order an imageless region). Phase B in
  fact **fixed** the right subpage's figure order and nothing in the harness noticed
  (§10). `tools/layout_order_eval.order_with_figures` now adds a **third, Stage-04-only**
  tau over text PLUS the **bbox-matched** figures; rank-matched figures (it_geo_04,
  de_01) are excluded as circular and print `n/a`, never a passing score. Validated as
  a **differential on real pixels** — with `--set fig_vsplit=false`, it_geo_06-right
  reads `+0.87` / `F29,F30,C29,C30` against Phase B's `+1.00` / GT, while the text-only
  arm reads `+1.00` for both. On its first run it found a NEW unfixed defect:
  **it_geo_06-LEFT is `+0.86`** — the top-right plate F26 is emitted 2nd, not last, so
  the column-major order this section demanded is in fact WRONG there.
  **FIXED 2026-08-09** (`_column_split` / `xy_column_first`): the running head ended
  7px above F26, so the H-cut banded them together and the full-width header then
  blocked the V-cut, hiding a globally-valid column gutter. left.png `+0.86 → +1.00`,
  the other nine graded subpages byte-identical, and verified carried into a fresh
  `document.json` (`figorder_it06`) — so the by-hand gap below is closed for this
  page. Numbers, the three guards and which subpage demanded each in `docs/RESULTS.md`.
  **Still by hand in general:** the metric grades Stage 04's per-subpage
  `reading_order`, not Stage 07's carrying of it into `document.json`.
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
- **False-split on a single photo with an internal margin-like band** — guarded by
  full-span + sampled-margin, verified on it_geo_04/05/07 (+ it_geo_06-left and
  de_01 for Phase B).
- **The two axes are NOT symmetric — measured, not assumed.** An unguarded V-cut
  sliced it_geo_05-left's single full-page MAP into two vertical strips
  (GT F2 IoU **1.000 → 0.702**), because a diagram drawn *on page background* legit-
  imately contains full-height background columns, whereas a stacked photo has no
  full-WIDTH cream band inside it. So Phase A's guard does not transfer to the
  x-axis, and the V-cut carries an extra one: **it is accepted only when it ejects a
  detector-confirmed text column.** With that guard, 9 of the 10 graded subpages are
  byte-identical to Phase A.
- **Residual, unfixed (no fixture):** a single figure that BOTH contains an interior
  full-height background column AND has a text detection overlapping one side would
  still be sliced. Ejecting text printed *inside* a figure needs masking, not
  cutting — out of scope.
- **`_absorbed_text` scans every non-figure detection, `abandon` included.** Those
  can be page-wide (`7,65 2113x181` on it_geo_06-left), so in principle a thin figure
  sub-box near the top edge could be >=0.60 inside a header box and be ejected.
  **Zero effect on all five fixtures** — left as-is rather than changed on
  speculation, since narrowing the eject set to text-bearing labels would also stop
  it ejecting a genuinely swallowed running header. Revisit with a fixture.

### A SIBLING defect this does NOT fix (measured 2026-08-09, it_geo_05-left)

Same output symptom, different cause, recorded here because §5 exists to record
exactly this. On it_geo_05-left, caption C2 (`255,2040 540x760`) is printed **inside**
the full-page map, and its `coverage BY a figure` is **1.000 both before and after
Phase B** — so the map crop carries the caption as pixels, while C2 is simultaneously
**absent from the document as text** (the detector emits no text detection there at
all; C2 was a straight segmentation MISS before this change and still is).

Phase B cannot reach it, and shouldn't try: with no text detection there is no
evidence to eject on, and the only cut that would separate C2 slices the map in half
— which is precisely the false-split §8 documents. **The fix for this class is
masking (paint the caption region out of the crop), not cutting**, and it needs the
caption to be detected in the first place.
- **Ejection is explicit, not left to NMS.** `nms_and_dedup` would also prune the
  it_geo_06-right caption column (0.82 contained in the conf-0.856 C29 text det, over
  the 0.80 `contain_frac`) — but a 2-point margin is not a mechanism, so ejection is
  its own step and NMS is the backstop.

## 9. Phase B's honest cost: C30→F30 was right for the wrong reason

Phase B **loses** one caption↔figure pair on it_geo_06-right (recovered pairs
4/6 → 3/6; **still 0 wrong**). This is not a capability regression — read it
carefully before "fixing" it:

The geometry arm pairs a caption to a figure that shares its **column**. C30
(`154,2239 439x581`) and the true F30 (GT `636,1400 1072x800`) share neither a
column nor a y-band — the caption is printed "**A lato**" (*to the side*), down in
the left caption column, while its photo is up and to the right. The pre-Phase-B
pair existed **only because the figure box was wrong**: the merged box spanned
`x154..1708`, so it overlapped C30's column by accident. With a correct box the arm
abstains, which is what it should do. And the pair it "won" pointed at a crop that
displayed the *other* caption's text, so the old output was worse on both counts.

The legitimate route to C30→F30 is unchanged and still open: **corner-label OCR for
the number 30** (§7 / the texture-swamped labels F27/F28/F29/F30). Do not loosen the
geometry arm's column guard to buy this pair back — the bar is zero wrong pairs.

## 10. Bonus, found only by hand: figure reading order on it_geo_06-right

**Now graded** — `tau+figures` reproduces this table by measurement (§6), scoring the
Phase A sequence `+0.87` and the Phase B one `+1.00`. Kept as written because it is the
worked example the metric was validated against.

Phase B also **corrected the reading order**, which no metric graded (§6 gap). Over
the right subpage's figure/caption blocks in the assembled `document.json`:

| | sequence |
|---|---|
| Phase A (`grouping_it06`) | F29, **F30**, **C29**, C30 |
| Phase B (`phaseb_it06`) | F29, C29, F30, C30 |
| GT | F29, C29, F30, C30 ✓ |

Cause: the merged box spanned the full page width, so XY-Cut peeled it as a
full-width band *above* C29. Tightened to `640,1341 1068x842`, F30 is a
right-column box and falls into its correct place. This is a real Gate-4 reflow
improvement — it was invisible to the harness, not absent from the output.
