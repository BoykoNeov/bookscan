# Panorama Phase 2 — pre-registration, 2026-08-31

Written and committed **before any composite was painted or any word counted**.
Phase 0 (RESULTS 2026-08-31) is the only input; its committed data
(`docs/data/panorama_phase0_20260831.json`) is what fixed the thresholds below,
and the one number taken from it before this document existed is stated in §4 so
it cannot be mistaken for a result.

## 1. The question

Phase 0 measured **placement** — can a raw close-up be put on the flattened page
without leftover displacement. It passed at 1.39 px median against a 0.09 px
floor, under two constraints (register onto the flattened page, correct over the
source's own footprint) and one warning (the tail is a word wide on 42 % of
sources).

Placement is not the deliverable. **Phase 2 asks whether a page assembled that
way READS better.** Per `docs/plans/panorama-and-next-steps.md` §1 Phase 2, the
gate is *more confident words AND a text diff*, and per §0 the word count alone
is not allowed to decide it — four times in this repo a confidence number has
risen while the text got worse.

## 2. What a result licenses

* **Pass** licenses **Phase 1 only** — building the sharpness-aware patchwork as
  a real module. It is not a claim that the book reads better (n = 1 book, 2–3
  spreads), and it does not ship anything.
* **Failure** stops the panorama route at Phase 0's placement number. It is
  **not** to be reopened by lowering the displacement threshold; the threshold
  is fixed in §4 from committed data and moving it afterwards would be choosing
  the population from the answer.

## 3. Population

Job `jobs/20260829-084115-de3c20d3` (the owner's 25-spread via-ferrata guide),
the same job Phase 0 measured. Three spreads, chosen in the plan **before** this
work from Phase 0's placement data, for stated structural reasons:

| page | why | Phase 0 |
|---|---|---|
| `page_021` | the only spread in the book with enough well-placed sources to show a difference either way | 25 of 27 placed |
| `page_013` | a **second population**, not continuity — see §7 | 6 of 10 placed |
| `page_024` | every source is badly placed; the admission rule should refuse them all | 10 of 28 placed |

The four sofa spreads (`page_001`–`page_004`) are out of scope, as in Phase 0:
their flattened pages are geometrically wrong for an unrelated recorded reason.

## 4. Placement and admission — frozen here

**Placement is arm D of Phase 0, unchanged**: SIFT at detect scale 0.5, ratio
0.75, RANSAC 4 px, accept at inliers >= 20 **and** masked NCC >= 0.45,
homography from the raw close-up onto the **native dewarped subpage**; the
homography is then lifted to the canvas scale and the local-bend correction
(`figure_hires._mesh_refine`) is estimated over the **source's own footprint**.
No parameter of the registration is re-tuned for Phase 2.

A registered source is **admitted to the paint** only if all three hold:

1. it registered under the rule above;
2. its **own scale is >= 1.0** relative to the native dewarped subpage — a
   source may not paint pixels it does not have. (`figure_hires` uses 1.15 for
   figures; that value is *not* imported. How many admitted sources fall in
   1.0–1.15 is reported, so the figure value can be checked against this
   population later rather than assumed.)
3. its **worst-twentieth leftover displacement <= 10 anchor-equivalent px** —
   the 95th percentile of dense optical flow over the footprint, divided by the
   dewarped-px-per-anchor-px scale. Dense flow, not the tile statistic, because
   the correction is phase correlation and grading it with phase correlation is
   circular (Phase 0 §diagnostics).

**Why 10 and not 5.** Measured on the committed Phase 0 data before this
document was written — the one pre-existing number, stated so it is auditable:
a 5 px rule admits **zero** sources on all three spreads, so it can only produce
a null. A 10 px rule admits 7 sources on `page_021`-right (whose footprints
between them contain **170 of its 170** Stage 05 words), 3 on `page_013`, and
**0** on `page_024`. 10 px is roughly 0.55 of an x-height on this book.
No third threshold will be tried.

## 5. The canvas

Painting at the flattened page's own scale would throw the extra resolution away
— that is what Stage 01 already does. So the target is enlarged (INTER_CUBIC) by

> **S = the median own-scale of the ADMITTED sources for that subpage**, 2 d.p.

so the admitted close-ups land at approximately their own size. S is therefore a
consequence of §4, not a free parameter, and it is reported per subpage.

## 6. Arms, instrument, and the statistic

Four arms per subpage:

| arm | canvas | painted |
|---|---|---|
| **N** | native | — (context only) |
| **E** | enlarged S | nothing — **the control** |
| **P** | enlarged S | the admitted sources — **the arm under test** |
| **X** | enlarged S | the **rejected** sources — inverted selection |

**Paint**: sharpest-first (own scale descending), each source painting only
pixels no better source has already claimed, exposure matched with
`figure_hires._harmonise`, and a **hard narrow seam** (2 px feather, against
`figure_hires`' measured 24 px, which is for a figure and is what smeared two
disagreeing sources in the under-covered composite). No per-pixel sharpness
comparator: that would be a new untuned parameter and Phase 2 is not where one
earns its place.

**Instrument, and the layout is frozen across arms.** Stage 04's blocks are
taken once from the **native** dewarped subpage and their boxes scaled by S.
Every arm is read from the *same* scaled boxes, cropped from its own canvas, via
`stage05_ocr.ocr_subpage` with the shipped Tesseract settings and
**`--lang deu`** (this book is German; Phase 0's neighbouring row records that
reading it as `eng` costs 11 confident words for nothing). Freezing the layout is
deliberate: the earlier failed run's total words went 360 -> 431 while confident
words fell, which is as consistent with re-detection on a bigger canvas as with
doubling, and this instrument cannot confuse the two.

**High-confidence word = Tesseract confidence >= 80**, this repo's existing
convention (`page_source.py`, `anchor_choice_census.py`).

**Primary statistic**: high-confidence words in the TEXT blocks whose scaled box
lies **fully inside the painted union**, arm **P** against arm **E**. Whole-page
counts are secondary — a 7-source paint diluted by hundreds of untouched words
is a statistic that cannot see its own subject.

### The gate

> **P beats E on high-confidence words inside the painted union, AND a text diff
> over those same blocks shows no degradation.**

Words present in E and absent in P are read and adjudicated by eye. **A loss of
correct words fails the gate regardless of the count**, per plan §0.

### The control that makes a null readable

`page_024` painting nothing is an assertion that the rule fires, not an OCR
measurement — its composite is byte-identical to its control. The real control is
arm **X**: painting the sources the rule *rejects*. X is expected to **lose**
confident words, in the manner the earlier run recorded (431 total words, 270
confident, text visibly doubled).

> **If X does not lose, the instrument cannot see the failure it exists to
> prevent, and the whole measurement is uninterpretable** — that outcome is to be
> reported as such, not as a pass. This is the same role Phase 0's 0.09 px floor
> played.

### Underpower rule

If a subpage's painted union contains fewer than **50** high-confidence words on
arm E, that subpage reports **no verdict**. Fixed here so it cannot be invoked
selectively afterwards.

### Recorded, deciding nothing

Mean confidence per arm; per-source painted area and its share of the subpage;
how many admitted sources fall in own-scale 1.0–1.15; and — only if P loses
words — whether the lost boxes touch a painted-region boundary. That last one is
free and is what would license a word-aligned-seam design in Phase 1; it is a
diagnostic, not a rescue.

## 7. What this is NOT comparable to

**The 324 / 336 / 270 confident-word table (RESULTS 2026-08-29) is not a baseline
for anything here.** It was read in `eng`, onto the **anchor** rather than the
flattened page, at a 1.58x canvas, with every registered source painted and a
wide feather. Three of those four differ here. `page_013` is therefore a
**second population**, not a continuation of that row, and no arithmetic relating
the two is to be reported.

## 8. Honest limits, stated in advance

* n = **1 book**, 2–3 spreads, one operator, one camera.
* Phase 0's placement pass already carried a tail warning; this measurement
  inherits it. A pass here says a paint that *skips most sources* helps — it says
  nothing about a paint that does not.
* Reading a block crop with `ocr_subpage` is not identical to a full pipeline
  run; both arms get exactly the same treatment, so the comparison is valid and
  the absolute numbers are instrument numbers. A full stages 02–05 confirmation
  is owed only if the frozen-layout arm passes.
