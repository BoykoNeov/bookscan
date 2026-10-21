# Pre-registration — keep sliver "figures" out of the geometric caption pairing (2026-10-21)

Written before any run below exists.

## The defect

RESULTS 2026-10-21 (reframing control): two sofa-only trims of `it_geo_07`
(L41, mirror) make the production grouping pair caption C31 ("Figura 31 Schema
evolutivo…") to a **wrong** figure by geometry; the uncut page abstains. Read
off the committed outputs (`docs/data/trim_control_20261021/lo_it_geo_07_*.json`)
before writing this: under those trims Stage 04 emits the map's two scale bars
("0.5 cm = 200 m", "0.5 cm = 5 Km") as FIGURE blocks 257 × 12 and 257 × 18 px
(uncut: orphan text), between C31 and its real partner D1, and the geometric
arm pairs C31 to the nearest — a 12 px sliver. The bar is zero wrong pairs.

## Change under test

`figure_grouping` already has a thinness test, `_too_thin`:
`min(w/page_w, h/page_h) < sole_min_fig_frac` (0.04, measured 2026-08-26 for
the sole-figure arm: over-segmented strip 0.027, smallest whole figure 0.063),
deliberately scoped to arm 3. The change applies the **same statistic at the
same value, 0.04** to the figures arm 2 (geometry) may pair to, as a new knob
`geom_min_fig_frac`. Not tuned: the value is the one measured for arm 3. A
figure below it keeps type FIGURE and still renders; it can only no longer be
handed a caption by proximity. Arm 1 (printed numbers) and arm 3 are unchanged.

Mechanically a filter on arm 2's candidates can (i) remove a pair whose figure
is thin, (ii) turn an "ambiguous" abstention into a pair when the removed thin
block was the runner-up, (iii) change a mutual-nearest outcome. All three are
graded.

## Instrument

`docs/data/geom_thin_20261021/thin_probe.py` wraps `tools.layout_order_eval`
(default arm, Stage 05 on, shipped config), optionally with `find_book`
replaced by a hand-built rectangle exactly as `trim_probe.py` did, and runs
`group_figures` **twice on the same blocks** — knob 0 (today) and 0.04 — so
both arms see identical detections. The eval grades the 0.04 arm; the 0
arm's pairs are logged beside it (and must equal the committed run's where one
exists — a reproducibility check, not a gate).

`docs/data/geom_thin_20261021/owner_probe.py` runs `group_figures` both ways
over every subpage of the owner's book (`jobs/20260829-084115-de3c20d3`,
`06_uncertain` blocks, its page image, its language) as Stage 07 calls it.

## Population

- The 8 block-GT rows, uncut: `de_01`, `en_coins_01/02/03`, `it_geo_04/05/06/07`.
- The trim arms of the reframing control: `it_geo_06` L41, L4, R41, T41, B41;
  `it_geo_07` L41 T27 R34 B25 (the model's), L4, L41, R41, T41, B41, mirror
  (L34 T25 R41 B27).
- The owner's book (no block GT): every subpage.

## Gates (all must hold to ship with the knob at 0.04)

- **G1 zero wrong.** No graded run has a wrong pair under 0.04.
- **G2 no loss.** No pair graded correct under 0 is missing under 0.04, on any
  graded run.
- **G3 owner's book.** Every pair that differs between the arms is adjudicated
  by eye from the page image (caption, both candidate figures) and written
  down; any lost correct pair or any new wrong pair refuses.
- **G4 effect.** The C31 wrong pairs of `it_geo_07` L41 and mirror are gone.

If G1–G3 hold and G4 holds, the default becomes 0.04. If G4 fails, the
mechanism above is wrong: not shipped, recorded.

## What this cannot say

The trims are one book and one surface; the thinness value was measured on a
different arm's population (stated, not hidden — that is why the gates re-grade
every row). It does not stop Stage 04 from emitting scale bars as figures; that
upstream question stays open.
