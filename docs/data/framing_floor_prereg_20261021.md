# Pre-registration: the framing noise floor of `layout_order_eval` on every block-GT row (P1, P9)

Written 2026-10-21, before any run below exists.

## The question

The reframing control (RESULTS 2026-10-21) found that trimming 4–41 px of
background off `it_geo_06`/`it_geo_07`, with no model, moves caption typing,
segmentation, reading order and once a caption pair. So a single uncut run
cannot tell a crop that hurts the layout from ordinary framing noise, and
every past layout delta on these rows may be partly that noise (P9). This run
measures, for **every** row that has block-order ground truth, how far each
graded number moves under small model-free reframings of the same photograph:
the noise floor. It is a measurement, not a gate; it licenses no change.

## Instrument

`docs/data/framing_floor_20261021/floor_probe.py`: `tools.layout_order_eval`,
default arm (Stage 05 on), shipped `config.yaml`, with
`book_boundary.find_book` replaced by a hand-built rectangle
(`applied=True, emit=search=<rect>`, no model, no pad), exactly as
`trim_control_20261021/trim_probe.py`. All-zero runs `find_book` as shipped;
`--rect` hands the whole frame through the rectangle path. Runner:
`run_all.sh` (75 runs, sequential, one GPU process at a time, BelowNormal).
Summary: `summarize.py`.

Code state: the only pipeline commit since `geom_thin_20261021` was graded
(d19cff1) is `8090858` (Stage 01 blending), which the eval does not call — it
reads the testset JPEG directly. `find_book` abstains (whole frame) on all 8
rows today, so "base" is the full upright frame (4000 × 3000) on every row.

## Which sides may be trimmed (measured before any run)

A side is trimmed only if every pixel within 100 px of that frame edge is
background — no page, no fanned edge of closed pages. Read by eye at full
resolution with rulers at 4/41/60/100 px (strips in `W:\temp\claude\framing_floor`,
not committed; the rows' JPEGs are in `testset/`):

| row | L | T | R | B | nearest book pixel on a trimmed side |
|---|---|---|---|---|---|
| `de_01` | yes | yes | yes | yes | ≥ 150 px (blue blanket all round) |
| `it_geo_05` | yes | yes | yes | yes | ≥ 200 px (sofa) |
| `it_geo_06` | yes | yes | yes | yes | > 150 px (recorded 2026-10-21) |
| `it_geo_07` | yes | yes | yes | yes | > 150 px (recorded 2026-10-21) |
| `en_coins_01` | no — page at x = 0 | yes | no — page at the edge | yes | T ≈ 135 px, B ≈ 115 px |
| `en_coins_02` | no — page at x = 0 | yes | no — page at the edge | yes | T ≈ 140 px, B ≈ 150 px |
| `en_coins_03` | no | no — header text at the edge | no | yes | B ≥ 160 px |
| `it_geo_04` | no — closed-page fan from ≈ 18 px | no — header text at the edge | no — fan | yes | B ≥ 160 px |

The cable in the top margin of `en_coins_01/02` is background. The coin rows
and `it_geo_04` therefore get a **thin floor** (6, 6, 3, 3 reframing arms),
and that is how it will be written; no fan or page is trimmed to widen it.

## Arms

Same structure on every row, restricted to its allowed sides.

| arm | trim (px removed) | role |
|---|---|---|
| `base` | none (`find_book` as shipped) | the uncut run |
| `repeat` | none, run again | run-to-run control |
| `rect0` (`it_geo_07` only) | none, through the rectangle path | control for the path itself |
| `X4` for each allowed side X | 4 px off side X | knife edge |
| `X41` for each allowed side X | 41 px off side X | single-side, the size of the model's strip |
| `all25` | 25 px off every allowed side | multi-side, like the model's rectangle (25–41 px each side) |
| `all41` (rows with ≥ 2 allowed sides) | 41 px off every allowed side | multi-side |

Reframing arms (the floor) = every arm except `base`, `repeat`, `rect0`:
10 on the four-side rows, 6 on `en_coins_01/02`, 3 on `en_coins_03` and
`it_geo_04` (B4, all25 = B25, B41).

## Statistics (fixed now)

Per subpage: segmentation matched, type accuracy, `tau_layout` (text blocks),
`tau_all` (text + position-honest figures), production caption pairs correct,
production caption pairs wrong, and — reported, not part of "moved" — the
number of emitted figures thinner than 0.04 of the page on their thin side
(the `figure_grouping` thinness floor; the scale-bar slivers). Per row: total
segmentation matched and total pairs correct/wrong.

For every (row, statistic): the base value, the minimum and maximum over the
reframing arms, and the number and names of the reframing arms whose value
differs from base.

## Preconditions

0. `repeat` equals `base` on every statistic, on every row. If not, the row
   has run-to-run noise; its floor is reported but marked as not a framing
   measurement.
1. `rect0` equals `base` on `it_geo_07`. If not, the rectangle path itself
   changes the result and every trim arm is suspect; reported and the run is
   not read.
2. Every arm with a counterpart in `docs/data/geom_thin_20261021/` (graded
   2026-10-21 at today's shipped `geom_min_fig_frac` 0.04) reproduces it on
   every statistic: `base` on all 8 rows; `it_geo_06` L4, L41, R41, T41, B41;
   `it_geo_07` L4, L41, R41, T41, B41. A failure is reported by name; it means
   the instrument has drifted since this afternoon and the floor is read only
   with that stated.

## What is reported, and what it licenses

- The floor table above, per row; the number of rows on which any reframing arm
  moves any graded statistic; per statistic, the number of rows it moves on.
- The sliver count per arm, linking to the scale-bar diagnosis (RESULTS
  2026-10-21, same day): how often a reframing makes Stage 04 emit a
  figure thinner than the thinness floor, on any row.
- **Proposed for the next pre-registration, not adopted here:** a crop
  change's delta on (row, statistic) counts as an effect only if the changed
  value lies outside that row's reframing [min, max]; on a thin-floor row it is
  reported as "inside/outside a thin floor". Whether to adopt it, and whether
  to require the change on several rows, is that pre-registration's call.
- Re-reading earlier RESULTS rows' layout deltas against this floor (P9) is a
  follow-on, not part of this run.

n = scenes: `de_01` (one book, blanket), `en_coins_01–03` (one book, one
surface), `it_geo_04–07` (one book, one sofa). Three books, three surfaces.
