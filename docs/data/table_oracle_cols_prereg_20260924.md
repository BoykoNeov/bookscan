# Pre-registration: take a table's columns from the row oracle (P6)

Written 2026-09-24, **before the arm has been run on any block**. Code:
`pipeline/table_grid.py` (`oracle_columns`, param `oracle_columns`, default
False while this is open). Probe: `docs/data/table_oracle_cols_probe_20260924.py`.

## The question

`OPEN_PROBLEMS.md` P6, known miss: `it_geo_07 page_001__left` #5, a real
three-column geological chart read well, is refused "only 1 column" because the
page pass splits `INFERIORE` into fragments that sit in the printed gutter
(3 px of whitespace), so the page pass's x-projection sees one column. Two
threshold fixes were swept and changed nothing (RESULTS 2026-08-31). The recorded
next step: take the **columns** from the psm-6 row oracle too, which reads each
row across the table.

## The arm

Only when the page pass finds fewer than `min_cols` columns (the exact block
set refused today for that reason): cut each oracle line into cells at the same
`cell_gap_mult` gap, merge the cells' x-coverage into columns at the same
`col_gap_mult` gap, and continue through the **unchanged** acceptance (span gain,
weak fraction, collision fraction, min rows). Text still comes only from the page
pass; no word is added, dropped or edited. A block the page pass already columns
never reaches the arm, so the 4 blocks that grid today are unchanged by
construction.

## Population

Every TABLE block in the Stage 05 output of the owner's job
(`jobs/20260829-084115-de3c20d3`) and of one `it_geo_07` job, run through
`grid_table_blocks` twice (arm off, arm on) from the stored words and the
`03_dewarp` subpage image, with Tesseract settings from `config.yaml`.

**Sanity first:** arm off must reproduce the 2026-08-31 census outcomes
(4 gridded; `page_003__right` #23, `page_016__right` #14, `it_geo_07` #5
abstain for their recorded reasons). If it does not, the probe is wrong and
nothing below is read.

## Gates

1. **Target:** `it_geo_07` #5 grids, and its grid, printed as rows × columns,
   is checked **by eye against the page image**: at least 3 of 4 printed rows
   keep their period / stage / age together in the right column. A grid that
   passes the structural checks but mixes rows is a FAIL, not a partial pass.
2. **Must still abstain:** `page_003__right` #23 (two lines of route names, the
   rest unread) and `page_016__right` #14 (24 junk words of a glossary; nothing
   to grid). Either one gridding is a FAIL.
3. **Unchanged:** every block gridded with the arm off has an identical
   `(table_row, table_col)` on every word with the arm on.

## What a pass licenses

The arm turns **on by default**. Reason, stated before the result: it acts only
on blocks the gridder refuses today, it changes no word (a wrong grid is a wrong
table layout, which the editor fixes by re-typing the block), and on the owner's
book gate 2 means it changes nothing at all. Honest limit, also stated now: the
positive is **one block of one book** (n = 1); a pass shows the mechanism
reaches the case it was designed for, not that it generalises.

A fail keeps the arm off and is recorded as a refusal; the gap thresholds are
not tuned on these blocks.
