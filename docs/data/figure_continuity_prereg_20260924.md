# Pre-registration: figure continuity census (P3, pictures split in two)

Written 2026-09-24, **before any continuity score exists**. Tool:
`tools/figure_continuity_census.py`. Nothing in `pipeline/` changes; this is a
census that decides whether a merge rule is worth building.

## The question

`OPEN_PROBLEMS.md` P3: the owner's book renders single photographs as two
pictures with a white line between them, because the layout detector cut one
figure into two blocks. A whiteness-of-the-gap rule was rejected by inspection
(it glued orange text sidebars onto photographs). The proposed replacement:
**do the pixels continue across the seam?** This census asks whether any
continuity statistic separates "one picture cut in two" from "two things that
touch", on the owner's book, *before* anything is built.

The plan's counts (45 pairs: 35 with nothing between, 10 split by a caption)
have **no committed code or data behind them**. This census rebuilds the
population from its own rule and reports whether it reproduces those counts; a
mismatch is a finding, and the rule below is not to be adjusted to hit 45.

Honesty note: before writing this, one loose exploratory listing of figure
pairs (gap < 150 px, overlap > 0.5) was printed to see that the population is
non-empty (64 raw pairs, many of them small stacked icons). No pixel statistic
of any kind had been computed.

## Population

- **Job:** `jobs/20260829-084115-de3c20d3` (the owner's German guidebook),
  `document.json`, 50 subpages. Pixels are the document's own page image
  (`document_assets/<page_id>.png`), never the two block crops.
- **A pair** is two blocks of current `type == "figure"` on the same subpage,
  `a` above `b`, where
  - horizontal overlap ≥ **0.5 × the narrower block's width**;
  - vertical gap `b.y − (a.y + a.h)` in **[−0.02 × page height, 0.05 × page height]**;
  - **immediate neighbours:** no third figure lies between them (its vertical
    extent inside the gap, with horizontal overlap ≥ 0.5 of the narrower of it
    and either block).
- **Classes, reported separately:**
  - `empty` — no non-figure block intersects the gap rectangle (the overlap
    columns × the gap rows);
  - `between` — one or more non-figure blocks intersect it (the plan's
    "caption printed on the photograph" class; a seam statistic means
    something different there, so it is **not gated**, only listed);
  - `surface` — either block has `is_surface` true;
  - `sofa_spread` — the pair is on spreads `page_001`–`page_004` (known-bad
    crop, P1). Surface and sofa-spread pairs are listed and excluded from the
    gate: sofa next to sofa would read as continuous.
- **Recorded per pair, for the later build:** whether either block carries a
  `figure_asset` (a higher-resolution crop). A merge changes the bbox, and
  Stage 08 then falls back to the page crop, silently discarding the upgrade.

## Adjudication — BEFORE scores

Every pair is labelled by eye from a crop of the page image with both boxes
drawn: `one` (one picture cut in two), `two` (two separate pictures), `sidebar`
(a picture touching a text panel / coloured box), or `unclear`. Labels go into
`docs/data/figure_continuity_labels_20260924.json` and are **committed before
the scoring pass is run**. Labels are not revised after scores exist; a label
found to be wrong later is corrected by a dated note, not in place.

## The statistic

On the page image, Gaussian-blurred (σ = 1.0), per-pixel vertical step
`D(y, x) = max over RGB channels |I(y+1, x) − I(y, x)|`, over the pair's
overlap columns.

- `τ` = the **95th percentile** of `D` over the two blocks' interiors (each
  block minus its 3 rows nearest the seam) — relative to the pair's own pixels.
- **Seam band** = rows `[a.bottom − 3, b.top + 3]` (for a negative gap, the
  band spans the overlap ± 3 rows).
- **C = max over rows in the seam band of the fraction of overlap columns with
  `D > τ`.** A printed boundary (photo → white, photo → orange panel, a frame
  line) is a straight row where nearly every column jumps; a picture cut
  arbitrarily by a detector has no such row. High C = boundary, low C =
  continuous.

## Controls

- **Positive control (the floor):** the target's own pixels through the same
  machinery. Every owner figure that is in no candidate pair, not `is_surface`,
  not on spreads 1–4, with h ≥ 600 and w ≥ 300, and that I judge by eye to be a
  single picture, is cut at **5 seeded heights** (seed 0,
  uniform in [0.25 h, 0.75 h]) into a fake pair. The fake gap for each cut is
  drawn (same seed) from the census's `empty`-class gaps clipped to ≥ 0, so a
  fake band is as tall as a real one (C is a max over rows; a taller band
  alone raises it).
- **Negative control (named trap):** `jobs/figtext_it_geo_06`, the column of
  real, separate stacked figures the plan names as the opposite trap — every
  pair that meets the population rule there, confirmed separate by eye. Plus
  the owner's pairs labelled `two` / `sidebar`.

## Threshold and gate (fixed now)

- **T = the 95th percentile of C over the positive control.** A pair with
  C ≤ T reads as continuous.
- **PASS (a merge rule is worth building):** zero negative-control pairs and
  zero owner `two`/`sidebar` pairs at C ≤ T (a merge is a wrong merge), **and**
  at least half of the owner's gated `one` pairs at C ≤ T.
- **FAIL:** any `two`/`sidebar`/negative-control pair at C ≤ T, or fewer than
  half the `one` pairs.
- **NO VERDICT:** fewer than 10 gated `one` pairs, or fewer than 5 gated
  `two`/`sidebar` plus negative-control pairs, or a positive control of fewer
  than 20 fake seams. If the positive control and the negatives overlap, that
  is reported as such; the population is not narrowed to rescue it.

Outputs: `docs/data/figure_continuity_20260924.json` (every pair and control
with its C, τ, class, label, asset flag), overlays under
`W:\temp\claude\figure_continuity\`.
