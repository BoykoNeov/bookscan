# Pre-registration — Stage 08 renders a TABLE as a table
Written 2026-08-31 BEFORE any render was read.

## Bar
Not "better than the collapsed paragraph" (already known worse than the photo).
The bar is: **does the rendered table read as well as the photograph it replaces?**
Judged per block, by eye, against the page image.

## Expected outcome, per fixture block
- `page_003__left` #7  (route table, 328 w, median conf 91.8)  -> EXPECT WIN
- `page_004__left` #21 (route table, 264 w, median conf 92.4)  -> EXPECT WIN
- `page_017__right` #10 (grade table, 62 w here, 89.9)         -> EXPECT STILL LOSE
  Reason: its OCR is broken at the character level in a way no
  geometry can repair (`Osterreich`, `</D`, `YO`, `EB`, `mits)`,
  `facile facile`). It is German + Italian + French in one block;
  that is the per-block-language item, not this one.

## Forbidden
Do NOT tune the gridder's thresholds against `page_017__right` #10.
Any threshold change must be justified on the route tables or on the
7 pre-existing Stage 04 TABLE blocks, never on the grade table.

## Non-regression population (must be eyeballed, not counted)
7 distinct pre-existing TABLE blocks: 6 in jobs/20260829-084115-de3c20d3,
1 in it_geo_07 (repeated across 6 variant jobs).
`page_003` right-subpage #23 (8 words) is the marginal one: it SHOULD abstain.

## Necessary but not sufficient
Word conservation (no word lost vs the <p> arm) proves nothing about cell
assignment. Verify ~5 route rows as (route, time, height) tuples against
the photograph.

## AMENDMENT 1 — 2026-08-31, before any render was read

Three things measured during design changed what "win" means. Recorded here so
the final grading cannot quietly move the goalposts.

1. **Rows are NOT recoverable from the page-pass words.** Tesseract's `line_id`
   groups a CELL, not a row, and the columns are staggered by ~0.7 of the row
   pitch. Aliasing proof: shifting the name column by a whole row pitch costs
   mean 7.4 px against 8.1 px for no shift — geometry cannot tell the correct
   correspondence from an off-by-one one. A purely geometric gridder is dead.
   Rows come from a psm-6 re-read of the block crop, which has the ruled lines.

2. **The block re-read is WORSE at cell text than the page pass** (mean conf
   68.5-70.6 vs 91.8; `2,2 4½ Std.` -> `, .`, `1250` -> `[250`, `102` -> `I Ly`).
   So the shipped design must take ROWS from the re-read and TEXT from the page
   pass. Neither pass alone is acceptable.

3. **The stored words are `eng` on a German book** (05_ocr/meta.json says
   `language: eng`; job.json now says `deu`). Re-OCR in `deu` does NOT fix the
   numeric cells — mean conf 68.5 vs eng 70.6, and it adds `Hım`/`Huım`.
   So language is NOT the blocker here, and this item must not be deferred to
   the per-block-language work on that excuse.

## AMENDED BAR for a route table
The grid being correct is NECESSARY, NOT SUFFICIENT. Known-wrong cells that a
correct grid cannot repair: `2,2`->`22`, `1,3`->`13`, `4½`->`4Y`, `5¾`->`5%`,
`170`->`I70`. A correctly-gridded table full of wrong numbers is NOT a win —
it is the same failure this project has hit four times (a number improving
while the text gets worse) wearing a new costume. Report the grid and the cell
text as two separate verdicts.
