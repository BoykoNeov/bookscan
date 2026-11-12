# Pre-registration — carrying hand edits across a spread refresh (2026-11-12)

Written and committed before any run of the check on real jobs.

## What is tested

`stage07_assemble --spread page_NNN --carry-edits` (v0.3.0): a refresh of an
edited spread copies each hand edit onto the re-run page **only on an exact
match** (same page size; same block box + automatic type + automatic order;
same word box + original reading), and refuses — changing nothing on disk — if
anything would be dropped, unless `--force` is also given.

## Population

The two real jobs of the v0.2.0 refresh row (RESULTS 2026-11-12), copied into a
scratch folder, never edited in place:

- `jobs/tablegrid_e2e` (owner's book, 3 spreads / 6 pages)
- `jobs/20261021-104424-6d43b587` (sweep job, 4 spreads / 6 pages)

## The edits (instrument: `tools/spread_refresh_check.py`)

On the FIRST spread, chosen by rule, not by looking:

1. a word correction (first non-empty word of the first page of the spread, `+ "_EDIT"`);
2. a block text override on the first text block (paragraph/heading/list) of that page;
3. a type change on the next text block (paragraph -> heading, or heading -> paragraph);
4. a delete on a block the unreadable-panel pass turned into a picture if the
   spread has one (`type_promoted` and `type_auto == figure`), otherwise on the
   last block of the page;
5. a hand caption ruling on the first caption of the spread, if any: an unpair
   (`figure_ref = None`, `pair_source = user`);
6. a reorder: the first two blocks in reading order swap places.

Saved through `pipeline.editor.normalize_edits`, as a real save is, plus a
translation target on the document.

## Gates

**A — control (trace unchanged).** Refresh the edited spread with `carry`.
Pass only if, on both jobs: the returned and on-disk document equals the saved
one field for field; the carry report drops nothing; and the asset folder is
byte-identical to the full assemble's. (The trace did not change, so everything
must carry; anything else is a defect.)

**B — negative (one word box moved by 1 px).** In the copy, the edited word's
box in that spread's `06_uncertain/resolved.json` is moved 1 px to the right.
Pass only if, on both jobs: `carry` alone refuses and `document.json`,
`document.meta.json` and every asset file are byte-identical afterwards; and
`carry` + `force` reports exactly one dropped item — that word — and the
resulting document equals the saved one except that word (its text back to its
original reading, `edited` false, box moved by 1 px).

Both A and B must pass on both jobs. The statistic is pass/fail per gate per
job; the counts of carried words/blocks/orders are reported, not gated.

## Not tested

A refresh after a real re-crop (expected: almost everything dropped, by design
— the synthetic tests cover the size-change and vanished-page cases). The
console button in a browser.
