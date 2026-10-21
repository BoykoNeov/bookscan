# Pre-registration: reframing control for the model-box cut's layout regression (P1)

Written 2026-10-21, before any run below exists.

## The question

RESULTS 2026-10-21 found that cutting `it_geo_06` and `it_geo_07` to the vision
model's (padded) box makes the shipped block set worse:

| row | uncut | cut |
|---|---|---|
| `it_geo_06` caption pairs (production grouping) | 5/6, 0 wrong | 3/6, 0 wrong |
| `it_geo_07` segmentation | 30/30 | 28/30 (D1, T5right lost) |
| `it_geo_07` right tau | +1.00 | +0.83 |

Every cut strip is sofa. That row left the cause open ("no reframing
control"). This run answers one question: **does trimming the same pages by
strips of the same size, with no model involved, do the same damage?** It does
not bear on whether `vlm_box.cut` may be switched on; that needs its own
pre-registration (RESULTS 2026-10-21, last paragraph).

## Instrument

`docs/data/trim_control_20261021/trim_probe.py`: runs `tools.layout_order_eval`
(default arm, Stage 05 on, shipped `config.yaml`) with `book_boundary.find_book`
replaced by a `BookBoundary(applied=True, emit=search=<rect>)` built by hand —
no model, no padding. Rectangles are in upright-frame coordinates
(4000 × 3000 for both rows). The model's padded rectangles, recomputed with
`padded_boxes` on the upright frames:

- `it_geo_06`: (41, 0, 4000, 3000) — left 41 px only.
- `it_geo_07`: (41, 27, 3966, 2975) — L41 T27 R34 B25.

Both photographs carry well over 150 px of sofa on every side (looked at
2026-10-21), so no trim below removes any of the book.

Runs are sequential (one GPU process at a time), BelowNormal priority.

## Arms

Trims are written L/T/R/B in px removed from that side of the upright frame.

| arm | `it_geo_06` | `it_geo_07` | role |
|---|---|---|---|
| `base` | none | none | reproducibility of the committed uncut run |
| `ident` | L41 (= the model's) | L41 T27 R34 B25 (= the model's) | reproducibility of the committed cut run, by hand |
| `tiny` | L4 | L4 | knife-edge probe |
| `L41` | (= `ident`, not re-run) | L41 | control |
| `R41` | R41 | R41 | control |
| `T41` | T41 | T41 | control |
| `B41` | B41 | B41 | control |
| `mirror` | — | L34 T25 R41 B27 | control (the model's rectangle, mirrored) |

Control set **C**: `it_geo_06` {R41, T41, B41} (3 arms); `it_geo_07`
{L41, R41, T41, B41, mirror} (5 arms).

## Statistics (fixed now)

Per row, the **flagged statistic** is the one that moved:

- `it_geo_06`: production caption pairs correct on the left subpage (base 5),
  and the count of wrong pairs (base 0).
- `it_geo_07`: segmentation matched over both subpages (base 30/30), and
  right-subpage layout tau (base +1.00).

An arm **moves** a row if any flagged statistic differs from that row's `base`
run, in either direction. All per-subpage metrics (seg, type acc, tau layout,
pairs ok/wrong, misses) are reported for every arm, whether they moved or not.

## Decision rule (fixed now)

0. **Precondition.** `base` must reproduce the committed
   `vlm_cut_20261021/lo_<row>_base.json`, and `ident` the committed
   `lo_<row>_cut.json`, on the flagged statistics. If either fails on either
   row, the verdict is **(n) run-to-run noise**: the 2026-10-21 regression is
   not established, and the control arms are reported but not read.
1. **(c) knife edge** — `tiny` moves the row.
2. **(a) the framing itself** — at least half of the row's C arms move it
   (`it_geo_06` ≥ 2 of 3, `it_geo_07` ≥ 3 of 5).
3. **(b) specific to the model's rectangle** — no C arm and not `tiny` moves it.
4. Otherwise **(m) partly framing**: some, fewer than half, of the C arms move
   it. Reported as framing-sensitive, not as every framing.

(c) and (a) can both hold; both are reported. Verdicts are per row; n = 2 pages
from one book, which is how it will be written.
