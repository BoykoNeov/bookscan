# Pre-registration — re-reading past layout deltas against the framing floor (2026-11-12)

Committed before any past RESULTS row is read against the floor. Follow-on
named in OPEN_PROBLEMS P9 ("Framing is a draw too … Not yet done: re-reading
earlier rows' layout deltas against those ranges") and in the RESULTS row
2026-10-21 "The framing noise floor of `layout_order_eval`".

No pipeline code runs. This is a desk re-read of committed numbers.

## The floor

`docs/data/framing_floor_20261021/summary.json` — per (row, subpage, statistic)
the uncut `base` value and the values under 3–10 model-free reframings
(4–41 px of background trimmed). Default `layout_order_eval` arm (Stage 05 on),
shipped config of 2026-10-21. Statistic keys (checked in
`tools/layout_order_eval.py:806-810` and `summarize.py`): `seg` = GT blocks
matched, `type_acc`, `tau_layout` = text-only Kendall tau, `tau_all` =
figure-inclusive tau ("tau+figures"), `pairs_ok`, `pairs_wrong`, `slivers`;
row totals `row.seg`, `row.pairs_ok`, `row.pairs_wrong`.

## Population (mechanical)

Every `docs/RESULTS.md` row dated before 2026-10-21's floor row that reports a
change in a block-order / `layout_order_eval` statistic on any of the 8
block-GT rows (`de_01`, `en_coins_01/02/03`, `it_geo_04/05/06/07`) and
attributes it to a **pipeline** change (a stage, a pass, a parameter). Gains and
losses both. Rows that report no such number are not in the population.

**Excluded, by kind (a change of the instrument, not of the pipeline):**
- 2026-07-06 "figure matching → bbox-overlap + tau over text-only" (metric).
- 2026-08-09 "Figure-inclusive reading order — a metric …" (metric; its own
  A/B demonstration is a metric proof, not a pipeline gain).
- 2026-08-26 "The harness measures the stage it stops at" and "The harness had
  its own copy of the OCR call" (harness).
- The 2026-10-21 crop rows (model-box cut, reframing control, scale-bar
  diagnosis) and the floor row itself: they are about framing, and are what
  the floor was built from.
- 2026-07-03 Gate 3 rows that are first measurements with no before/after.

## Unit

One (row, subpage where the RESULTS row resolves it, statistic) cell, with
`before` and `after` as the RESULTS row states them. A corpus total
("pairs 14/19 → 16/19") is broken down to the page(s) that moved using the
row's own text or its `docs/data/` folder; if the breakdown is not recorded
there, the cell is **unresolved** — not guessed. Numbers come from RESULTS
rows (and their committed data), never from memory notes.

## Comparison

The floor is centred on today's code, so an old `before` value is not placed
inside today's range. Instead, for a cell with past delta `d = after − before`:

- `swing` = max − min over {base} ∪ {defined reframing values};
  `n_moved` = reframing arms whose value differs from base (a value turning
  undefined counts as moved).
- `n_moved == 0` → **OUTSIDE** (no reframing ever moved this cell).
- `n_moved > 0` and `|d| ≤ swing` → **INSIDE**: the gain/loss was shown on one
  framing only, and a framing change alone has moved this cell by as much.
  The pipeline is deterministic (repeat = base), so this does **not** mean the
  change was false or random; it means the measurement cannot tell it from
  what a few pixels of background do.
- `n_moved > 0` and `|d| > swing` → **OUTSIDE** (larger than any reframing
  swing).

## Cannot judge (a third verdict, never forced into inside/outside)

- **Different harness arm.** Rows graded with Stage 04 only (every block-order
  row before 2026-08-26, or any row run with `--no-stage05`). CLAUDE.md: the two
  arms are different quantities. For these, report as a pointer only whether
  the cell is framing-sensitive today (`n_moved`, `swing`), with no verdict.
- **Before the 2026-07-06 matching change** (also Stage-04-only).
- **Thin floor.** `en_coins_03` and `it_geo_04` (3 bottom-only trims): report the
  numbers, verdict "thin".
- **Statistic the floor does not carry** (anchor recall, word counts,
  `tau_native`, a named-block typing claim not reducible to `type_acc`, …).
- **Unresolved** (corpus total with no per-page breakdown on record).

## Outputs

`docs/data/layout_floor_reread_20261112/`: `deltas.json` (each transcribed cell
with its RESULTS line reference and arm), `reread.py` (applies the rule above
to `deltas.json` + `summary.json`), `verdicts.json` + `verdicts.md`. One new
dated RESULTS row; OPEN_PROBLEMS P9 bullet and STATUS updated.

## Named follow-on (NOT run here)

For each change judged INSIDE that is a config switch, a paired run of the same
reframings with the switch off (the "on" half already exists in the floor
folder). Proposed in OPEN_PROBLEMS; owner's call.
