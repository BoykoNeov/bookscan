# GATE 3 SPEC — Layout + Reading Order (Stage 04)

## Purpose

Answer, with numbers where the ground truth allows and with human-eyeballed
overlays where it does not, the go/no-go question for Stage 04:

> Does explicit block detection + reading-order assignment produce the correct
> intra-page reading sequence — beating (or at least not regressing) the
> implicit order Tesseract's own page segmentation emits — and does it hand the
> downstream stages (06 uncertainty, 07 reconstruct) a correct block structure
> (types + geometry) to build on?

Stage 04 is the first stage whose PRIMARY output is *reading order*, the exact
failure the Gate 1 harness surfaced: on a raw whole-spread capture Tesseract
interleaves the two facing pages line-by-line, scrambling the sequence. Stage
02 (gutter split) already fixed the **cross-gutter** half of that scramble
(en_coins_01 whole→split WER 83.1%→21.7%). What remains is **intra-page**
order: multi-column flow, figure/caption placement, sidebars, footnotes. That
remainder is what this gate is about.

## Scope of THIS gate (honest, GT-limited)

The testset (append-only, see `testset/README.md`) currently has ground truth
for **three** spreads, and **none is multi-column**:

| GT page | category | reading-order role |
|---|---|---|
| `en_coins_01` | figures | single-column body **+ 4 figure captions + footnote + running header + page number**, both facing pages — the one page with non-trivial intra-page ordering to measure |
| `bg_01` | clean | single-column, reads in correct order — **non-regression control** |
| `bg_02` | clean | dense single-column — **non-regression control** |

The genuinely reading-order-hard pages have **no GT**: `it_geo_*` (main column +
figure-explanation sidebars — "order scrambles"), `en_coins_02` (bulleted lists
+ figs), `en_coins_03` (explicitly no GT — Tesseract interleaves the two facing
pages so a sequence WER would be pure noise).

**Therefore this gate proves, numerically, only figure/caption/footnote +
header/page-number ordering on a single-column page, plus non-regression on two
clean single-column pages.** True **multi-column reading order is UNPROVEN**
until reading-order GT is hand-typed for a multi-column / sidebar page (a
user-owned, append-only task). Multi-column is exercised **qualitatively only**,
via the debug overlays on the no-GT pages — do not read this gate as proof of
multi-column correctness.

> This is a deliberate, user-approved scoping decision (2026-07-03): build and
> prove what the current GT supports; mark the multi-column claim UNPROVEN
> rather than paper over the coverage gap. The `it_geo` overlays are a preview
> of the multi-column question, not its answer — exactly as the Gate 1
> `zoomset` overlays previewed Gate 2.

## The stage under test: `pipeline/stage04_layout.py`

Obeys the stage contract (CLAUDE.md):

- **Reads ONLY** `03_dewarp/dewarp.json` (the per-subpage manifest) + the images
  it names (`left.png` / `right.png` / `single.png`). Runs **per half-page**.
- **Writes** `04_layout/layout.json` (list of `Block`: `id`, `type`, `bbox`,
  `reading_order`, per `page_model.py`), `04_layout/meta.json`, and
  `debug/04_layout.png` (blocks drawn on the page, numbered by reading order,
  colored by type).
- Never modifies earlier artifacts; re-running overwrites only `04_layout/`.
- Stage 04 is **OCR-independent** — layout is detected from pixels; words are
  attached later at Stage 05. (The Gate 3 eval brings in Tesseract only to
  *measure* the resulting order — the stage itself does not depend on it.)

### Two arms behind one loader seam (mirror Stage 03)

- **DocLayout-YOLO** (default, `models.layout: doclayout-yolo`) — a document
  layout detector giving typed block boxes (title / plain-text / figure /
  figure-caption / table / etc.), lazy-loaded once per spread, VRAM released on
  CLI exit. Reading order is then computed over its boxes by **XY-Cut** (see
  below). The gate's numbers MUST come from this arm actually running (report
  the arm per row); the classical arm is a safety net, not a co-contender —
  projection profiles fail on exactly the complex pages the gate cares about.
- **Classical projection-profile fallback** (no torch / model absent) — column
  detection by vertical projection valleys, block segmentation by horizontal
  projection gaps within each column, reading order by XY-Cut. Honest-fallback
  rule (as in Stage 03): if it produces a degenerate single block covering the
  page, it is FLAGGED in meta.warnings, never silently passed off as a real
  layout.

### Reading order: XY-Cut (++ later)

Recursive alternating horizontal/vertical cuts on projection-gap valleys, with
full-width spanners (page-spanning titles/figures) cut before columns so a
banner headline is not sucked into one column's flow. This classic core is the
pragmatic first cut; the "++" refinements (overlap handling, manhattan-layout
edge cases) are added later, on the specific pages the numbers/overlays expose —
not speculatively.

## Deliverable: `tools/layout_ab.py` (the measurement)

Mirrors `tools/dewarp_ab.py`. **OCR settings identical across arms**, so only the
word ORDER differs between them — this isolates reading order from recognition.

The clean isolation (improves on a naive re-OCR-per-crop, which would confound
recognition): OCR each dewarped half **once** to get words+boxes, then produce
two linearizations of the **same words**:

- **whole** arm — words in Tesseract's native TSV order (its implicit page
  segmentation / reading order). This is the split+dewarp path from Gate 2.
- **layout** arm — assign each word to the Stage 04 block whose box contains its
  center; emit words block-by-block in `reading_order`, words within a block in
  natural (line, word) order. Words in no block ("orphans", a detection-coverage
  diagnostic reported per image) are slotted by position via the same XY-Cut so
  they still appear (no artificial deletions).

Concatenate halves in reading order (left then right), WER + CER vs the
reading-order GT. `Δlayout = layout − whole`.

Keep **all** blocks including header / page-number — the GT includes them; the
CLAUDE.md "strip running headers/page numbers by default" rule is a Stage 07
*reconstruction* toggle, not a reading-order measurement concern, and stripping
here would only add spurious deletions vs this GT.

## Metrics

- **Per-image + mean**: whole WER/CER, layout WER/CER, ΔWER/ΔCER (pp), the arm
  (doclayout-yolo | classical) that produced the layout, block count, orphan
  rate.
- **Read the rows, not the mean** — N=3 GT, same humility as Gate 2.

## Report (`docs/RESULTS.md`, appended dated section)

```
## Gate 3 layout A/B — YYYY-MM-DD, tesseract X.Y, layout=<arm>
| image | lang | whole WER | layout WER | ΔWER | whole CER | layout CER | ΔCER | arm | blocks | orphans |
...
Findings (per-image; read the rows). Verdict: PASS / MIXED / NEUTRAL + interpretation.
```

## Decision criteria

- **PASS (measurable part):** on `en_coins_01`, layout order does not regress vs
  whole and ideally improves it (correct figure/caption/footnote/header
  sequencing), AND on `bg_01`/`bg_02` (single column) layout is within noise of
  whole (non-regression — a stage that scrambles a clean single column is
  broken). AND the debug overlays on the no-GT complex pages (`it_geo_*`,
  `en_coins_02`) show visibly correct block detection + reading-order numbering
  on eyeball inspection ("half the value of the gate is the overlay" — Gate 1).
- **NEUTRAL is a valid honest result** on the GT pages: `en_coins_01` is
  effectively single-column-stacked, so Tesseract's implicit order is already
  close; a near-zero ΔWER there is expected and is NOT a stage failure — it means
  the measurable page doesn't exercise the hard case. The hard case
  (multi-column/sidebar) is the UNPROVEN part, gated on new GT.
- **FAIL:** layout scrambles the clean control pages, OR the overlays show the
  detector missing blocks / mis-ordering columns on the complex pages.

## Notes

- Dependencies: `doclayout-yolo` (+ its checkpoint under `models/`, gitignored),
  `opencv-python`, reuse `tools/ocr_metrics.py` + `tools/gate1_harness.py`
  Tesseract path + `tools/normalize.py` upright ingest. Torch/CUDA already
  present (the 5090; UVDoc uses it in Stage 03).
- `tools/layout_ab.py` MAY depend on `pipeline/` (it measures the pipeline); it
  reuses `gate1_harness`'s Tesseract path but does not modify it (that stays a
  pipeline-independent regression check).
- Multi-column proof is the first follow-up when reading-order GT lands for a
  multi-column / `it_geo` sidebar page.
```
