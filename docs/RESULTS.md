# Gate results (append-only history)

## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=none (SUPERSEDED — EXIF-applied/portrait input; see the normalized re-run + reconciliation below)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 25.0% | 18.4% | 0.751 | 44.3% |
| eng | 3 | 56.3% | 45.7% | 0.748 | 23.7% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 25.0% | 18.4% | 0.751 |
| figures | 6 | 56.3% | 45.7% | 0.748 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=otsu (SUPERSEDED — EXIF-applied/portrait input; see the normalized re-run + reconciliation below)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 26.1% | 18.5% | 0.775 | 44.3% |
| eng | 3 | 59.3% | 46.2% | 0.758 | 21.3% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 26.1% | 18.5% | 0.775 |
| figures | 6 | 59.3% | 46.2% | 0.758 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=adaptive (best variant) (SUPERSEDED — EXIF-applied/portrait input; see the normalized re-run + reconciliation below)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 25.8% | 16.3% | 0.906 | 47.9% |
| eng | 3 | 53.3% | 31.0% | 0.775 | 22.3% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 25.8% | 16.3% | 0.906 |
| figures | 6 | 53.3% | 31.0% | 0.775 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


---

## Gate 1 — interpretation (2026-07-03, first real testset)

**Read the auto-verdict above with care: the FAIL is a reading-order artifact,
not an OCR-quality result, and its "benchmark MinerU/Surya / abandon Tesseract"
recommendation should NOT be actioned.** Details below.

### Why the auto-verdict fails

`interpret()` keys PASS/MIXED/FAIL on **English only** and gates on the
*sequence-based* AUROC (`label_ocr_words`, Levenshtein over token order). These
are full two-page **spreads** run through raw Tesseract (no split/dewarp — that
is deliberate; Gate 1 measures the raw baseline). On the English coin pages and
the Italian geology pages, **figure-caption sidebars create false column
boundaries**: Tesseract reads the left half of each justified line, then the
right halves as a separate block, and on `en_coins_03` it interleaves the two
facing pages line-by-line. Correctly-recognized words then land out of order →
`label_ocr_words` marks them wrong → and because they were read well they carry
**high** confidence → the "wrong" class fills with high-conf members → AUROC
sags below 0.80 and WER inflates. None of that is a recognition or confidence
failure; it is a layout failure, which is precisely Stage 02 (split) / Stage 04
(layout + reading order)'s job.

### Order-robust probe (the fair read)

Same Tesseract words + confidences, but a word is labeled correct iff it is
present in the GT bag (order ignored) instead of by sequence alignment:

| image (variant=none) | words | seq-AUROC (harness) | ms-AUROC (order-robust) | seq word-acc | ms word-acc |
|---|---|---|---|---|---|
| en_coins_01 (English) | 593 | 0.748 | **0.868** | 63.7% | **79.3%** |
| bg_01 (Bulgarian, clean order) | 770 | 0.772 | **0.890** | 90.5% | **94.0%** |
| bg_02 (Bulgarian) | 687 | 0.731 | **0.856** | 78.9% | **90.1%** |

Order-robust AUROC is **0.86–0.89 across all three, all above the 0.80 bar**.
Note the bracketing: seq-AUROC is an order-depressed *lower* bound; ms-AUROC is
an *upper* bound (bag membership over-credits garbage tokens that collide with
common GT words), so the true English AUROC sits between 0.75 and 0.87 — the
point is only that it is **not** the sub-0.80 the harness reports. The
unassailable proof is elsewhere: **bg_01 in correct order gives sequence AUROC
0.881 (adaptive), bg_02 0.932 — the harness's own metric, no caveat** (see
below). (Reproduce: `python -m tools.gate1_order_robust_probe`.)

Recognition (order-free word accuracy) also exposes a real gap: **Bulgarian 90–94%
vs English 79%**. The English shortfall is genuine recognition, not layout — the
coin book's dense reference lines (`KM# 77.1-77.17`, auction lot strings, italic
small-caps captions) are what Tesseract misses. That is fine and expected: those
are exactly the low-confidence words the flag / patch / second-opinion machinery
(CLAUDE.md) exists to catch, so it validates the architecture rather than
undermining it.

### Headline result: Bulgarian (the clean datapoint)

`bg_01` reads in correct order (two clean single columns → left page then
right), so its sequence numbers are trustworthy: **WER 13.0%, CER 18.4%**
raw (`none`), i.e. ~87% word accuracy on a dense Cyrillic spread with a
footnote and many proper nouns, with confidence that separates errors. That is
the real "can Tesseract read these photos" answer, and it is yes.

### Preprocessing: adaptive wins

Adaptive thresholding is the best variant on this set — it cuts English CER
45.7% → 31.0% and lifts Bulgarian AUROC 0.751 → **0.906** (bg_02 alone hits
0.932). Recommend adaptive as the Gate 1 default preprocessing; revisit once
dewarp/split exist.

### Engineering conclusion

Recognition quality and confidence calibration are **good enough to build on**:
Bulgarian ~87% raw word acc with **clean-order sequence AUROC 0.881–0.932**
(the un-caveated proof), and English confidence still separates once order is
removed. English body recognition is the weaker end (79% order-free) and its
dense reference lines drag it down — precisely the case the confidence-flag +
second-opinion design targets. The failure mode Gate 1 actually exposed is
**reading-order scramble
on complex layouts (figure sidebars, multi-block pages)** — the remit of Gate 2
(fuse/split/dewarp) and Gate 4 layout/reading-order, not a reason to swap the
OCR engine. **Proceed to Gate 2.** Keep the Tesseract backbone (per CLAUDE.md).

### Follow-up (own commit, not this pass)

`interpret()` being English-only, and `label_ocr_words` being order-sensitive
for the *confidence* metric, are genuine limitations: a confidence-separation
measure should not depend on reading order. An order-robust labeling option for
AUROC (multiset / bag alignment) would let English and Italian contribute a
fair confidence number even on scrambled spreads. That is a deliberate metric
change with unit tests — file it separately, matching the existing
report-with-caveat philosophy.

---

## Stage 02 (gutter split) — 2026-07-03, before/after WER

First pipeline stage. Splits a two-page spread into `left.png` / `right.png` at
the central gutter (low-ink valley in the middle 30–70% band; cut biased into
the whitespace with a small overlap so no text is lost). Directly attacks the
Gate 1 finding — **reading-order scramble on complex layouts**.

Method: OCR the whole normalized landscape spread (baseline) vs OCR `left.png`
then `right.png` concatenated left-then-right (split). Same orientation for
both — the only difference is the split. Raw Tesseract (`preprocessing=none`),
same binary/tessdata as the Gate 1 harness.

| spread (GT) | lang | base WER | split WER | base CER | split CER |
|---|---|---|---|---|---|
| en_coins_01 (EN figures) | eng | 54.9% | **23.9%** | 45.0% | **15.9%** |
| bg_01 (clean order, guardrail) | bul | 12.5% | **9.4%** | 8.2% | **5.9%** |
| bg_02 (BG dense) | bul | 35.5% | **27.0%** | 25.8% | **21.9%** |

- **Split reduces WER on all three GT spreads.** Biggest win on the English
  figure spread (−31 WER pts): its figure-caption sidebars made raw Tesseract
  read across the gutter; splitting removes the cross-gutter scramble.
- **`bg_01` guardrail did not regress — it improved** (12.5→9.4). It already
  read in correct order as a spread, so a bad cut could only have hurt it.
- Residual en_coins_01 WER (23.9%) is intra-page sidebar order — **Stage 04**
  (layout + reading order)'s job, not split's.
- **`en_coins_03`** (no GT, the facing-page interleaver): after split the left
  half OCRs as "Chopmarked Coins … Hawai'i", the right as "… Honduras" — the
  line-by-line interleave of the two facing pages is gone.

Detector: all 9 testset spreads split with the cut landing in the central
whitespace; confidence ratio (valley/page-ink) 0.11–0.47, threshold 0.55.
Overlays in `jobs/<id>/debug/02_split.png`. Unit tests:
`pipeline/tests/test_stage02_split.py` (synthetic spread + single-page).

### Follow-ups (own commits)

- **Stage 00 EXIF normalization + shared ingest helper.** The testset JPEGs
  carry EXIF orientation=6; `cv2.imread` (OpenCV 5.0) auto-applies it and hands
  Tesseract a *sideways* buffer, while Stage 02 reads `IMREAD_IGNORE_ORIENTATION`
  (readable landscape). Tesseract auto-orients internally, so Gate 1 WER numbers
  are unaffected — but once Stage 00 normalizes, the harness (raw `cv2.imread`)
  and the pipeline will feed differently-oriented images, so word boxes/layout
  diverge even at equal WER. Fix: one shared ingest/normalize helper both call;
  general orientation (180°, single-page portrait) needs Tesseract OSD.
- **Single-page discrimination is unvalidated** — the testset has no single-page
  capture, so the `valley_ratio` single/split boundary is only checked on
  synthetic data. Append a single-page test image.
- **Off-center gutter is unexercised.** The search window is fixed at 30–70% of
  width; all 9 testset gutters fall near center (±100 px). A strongly tilted or
  unequal-width spread could put the true gutter outside the window, and the
  detector would then pick a wrong in-window minimum with a confident-looking
  ratio. Widen/adapt the window (or key off dewarp) when such a capture exists.

## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=none (CURRENT — normalized upright-landscape input via shared ingest helper)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 25.4% | 18.9% | 0.796 | 45.3% |
| eng | 3 | 83.1% | 65.4% | 0.692 | 14.5% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 25.4% | 18.9% | 0.796 |
| figures | 6 | 83.1% | 65.4% | 0.692 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=otsu (CURRENT — normalized upright-landscape input via shared ingest helper)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 26.5% | 19.0% | 0.819 | 44.5% |
| eng | 3 | 83.7% | 65.9% | 0.725 | 14.2% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 26.5% | 19.0% | 0.819 |
| figures | 6 | 83.7% | 65.9% | 0.725 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=adaptive (CURRENT — normalized upright-landscape input via shared ingest helper)

| language | images | WER | CER | conf AUROC | err-recall @10% flagged |
|---|---|---|---|---|---|
| bul | 3 | 30.3% | 20.5% | 0.899 | 45.4% |
| eng | 3 | 52.6% | 36.1% | 0.798 | 25.2% |
| ita | 3 | — | — | — | — |

**By category:**

| category | images | WER | CER | conf AUROC |
|---|---|---|---|---|
| clean | 3 | 30.3% | 20.5% | 0.899 |
| figures | 6 | 52.6% | 36.1% | 0.798 |

Verdict: FAIL — confidence does not separate errors (AUROC <0.80) and/or accuracy poor. Benchmark MinerU/Surya before building stages.

> Caveat: confidence is labeled per raw Tesseract word (1:1 with the conf value), while WER uses hyphen-joined text. Line-end hyphenations (e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on hyphen-heavy pages. A borderline MIXED verdict on real English pages may be this artifact rather than genuine OCR failure.


---

## Gate 2 / Stage 00 — harness re-run through the shared orientation helper (2026-07-03)

**What changed.** The three Gate 1 sections dated 2026-07-03 *immediately above*
are a re-run of the harness after it was switched to load images through the new
shared ingest helper (`tools/normalize.py`: PIL exif_transpose → Tesseract OSD →
upright, EXIF stripped). The pipeline (Stage 00) and the harness now feed
Tesseract **identically-oriented** pixels — closing the divergence flagged after
Stage 02. These supersede the earlier same-dated `none/otsu/adaptive` sections
(which fed Tesseract the testset's *misleading* EXIF orientation, i.e. a
portrait-rotated spread).

**Helper is verified correct.** For `en_coins_01`, the helper's output is
**pixel-identical** to `cv2.IMREAD_IGNORE_ORIENTATION` (upright 4000×3000
landscape), and OSD independently calls that buffer upright (rotate 0) while
calling the EXIF-applied portrait buffer rotate 270. All 9 spreads normalize to
upright landscape; one output was eyeballed as genuinely upright (not merely
landscape-shaped).

**The delta, reconciled (per-orientation `en_coins_01`, harness code held fixed):**

| input orientation | none WER | none AUROC | adaptive WER | adaptive AUROC |
|---|---|---|---|---|
| portrait (old, EXIF applied) | 56.3% | 0.748 | 53.3% | 0.775 |
| **upright landscape (new)**  | **83.1%** | 0.692 | **52.6%** | 0.798 |

- **Bulgarian is stable** (clean single-column reading order → orientation-neutral):
  `none` bul 25.0→25.4%, bg_01 12.7% (≈ prior 13.0%). No regression.
- **The big English move is reading order, not recognition.** Under raw `none`,
  the old portrait orientation *accidentally* stacked the two pages top/bottom,
  which reads close to canonical order; upright-landscape places them side by
  side and re-exposes the **cross-gutter scramble** — the exact Gate 1 finding,
  and exactly what Stage 02 split fixes (Stage 02 drove `en_coins_01` 54.9→23.9%).
- **Why `adaptive` barely moved (53.3→52.6) while `none` jumped:** `adaptive`'s
  binarization + 2× upscale let Tesseract's layout analysis separate the two
  pages regardless of orientation, so the scramble only bites the raw path.
  Reassuringly, the **recommended preprocessing is orientation-invariant**, and
  `adaptive` remains the best variant (bul AUROC 0.899, en_coins_01 AUROC 0.798).

**Bottom line:** the upright-landscape baseline is the honest one and both callers
now agree on it; the worse-looking raw-`none` English number is an accidental
benefit removed, targeted by Stage 02. The auto-verdict FAIL is still the known
English-only / order-sensitive artifact (see the Gate 1 interpretation above) —
not actioned.


## Gate 2 dewarp A/B — 2026-07-03, tesseract 5.4.0.20240606, dewarp=classical (classical text-line rectification)

OCR path identical across arms (grayscale + probe-upscale); only page geometry differs. Δdewarp = split+dewarp − split.

| image | lang | whole WER | split WER | split+dewarp WER | Δdewarp WER | whole CER | split CER | split+dewarp CER | Δdewarp CER | dewarp |
|---|---|---|---|---|---|---|---|---|---|---|
| en_coins_01 | eng | 83.1% | 21.7% | 26.6% | +4.9 pp | 65.4% | 15.0% | 21.2% | +6.1 pp | left.png:classical/64px/rms7; right.png:classical/72px/rms4 |
| bg_01 | bul | 12.7% | 9.6% | 3.7% | -5.9 pp | 8.9% | 5.9% | 0.8% | -5.1 pp | left.png:classical/39px/rms5; right.png:classical/69px/rms8 |
| bg_02 | bul | 38.1% | 31.5% | 2.5% | -29.0 pp | 28.9% | 27.4% | 0.7% | -26.7 pp | left.png:classical/72px/rms7; right.png:classical/82px/rms7 |
| **mean** | — | 44.6% | 20.9% | 10.9% | -10.0 pp | 34.4% | 16.1% | 7.6% | -8.5 pp | — |

Findings (per-image; the mean is carried by one image so read the rows, not the mean):
- **Single-column body text (bg_01, bg_02): large, real gains.** bg_02 split->dewarp WER 31.5%->2.5% (CER 27.4%->0.7%). Mechanism verified by diffing the OCR text: it is RECOGNITION recovery, not reordering — on the curved split the recognized word count was 720 (vs 817 GT) with garbled words (e.g. `избягали към Гюмурджина`->`избчали към Е мура`); after straightening it is 815 correctly-recognized words. Curl was corrupting character recognition; dewarp fixed it.
- **Figure/multi-block page (en_coins_01): dewarp regressed** (WER 21.7%->26.6%). A full-page warp fit to body-text baselines extrapolates across figure gaps and heterogeneous list/caption lines. WER understates the harm: since figures are cropped from the dewarped image, those crops are also distorted. The cause is that the classical arm extrapolates a text-baseline polynomial across the figure gaps. NB the recorded `rms` did NOT flag this page (all pages ~4-8px) — the extrapolation happens in figure regions that have no baselines, which a residual over sampled baselines can't see; baseline COVERAGE would be the signal. [UPDATE — see the uvdoc run below: UVDoc's coherent learned flattening does NOT regress this page (21.7%->12.0%). So this regression is a limitation of the classical baseline-fit specifically, NOT an inherent "any full-page warp bends figures / needs layout awareness" law as first hypothesized here.] [VISUAL QA 2026-07-03 — I overstated "those crops are also distorted." Zooming the classical vs input coin crops at native res (matched box; classical applies only vertical displacement) shows the coins remain visibly ROUND — content shifts up slightly but any figure distortion is at most a few-% vertical scale, not visible ellipticity. The measured +4.9pp regression is therefore a TEXT effect (displacement extrapolated across figure gaps warps the surrounding text lines), NOT visible coin destruction. Figure-crop fidelity under a full-page warp is real but SMALL here and still not WER-measurable — it needs per-region QA once Stage 04 masks exist, not a claim of gross distortion.]
- **Split alone** is a large win over the Gate-1 whole-spread baseline (mean WER 44.6%->20.9%; en_coins 83.1%->21.7% — facing-page de-interleaving), independent of dewarp.

> Framing (pre-committed before measuring): N=3 GT spreads, moderate handheld curl. A neutral/negative dewarp delta would have been a valid honest result (dewarping a flat page only adds interpolation), not a broken stage. CER is the less noisy signal at this N and avoids the hyphen-join WER artifact. Classical is the v0.1 floor; `fit_rms_px` is recorded (not thresholded — that would overfit 3 images) as a fit diagnostic, though on this testset it did not separate figure from text pages (see the en_coins finding).


## Gate 2 dewarp A/B — 2026-07-03, tesseract 5.4.0.20240606, dewarp=uvdoc (UVDoc neural grid unwarp)

OCR path identical across arms (grayscale + probe-upscale); only page geometry differs. Δdewarp = split+dewarp − split.

| image | lang | whole WER | split WER | split+dewarp WER | Δdewarp WER | whole CER | split CER | split+dewarp CER | Δdewarp CER | dewarp |
|---|---|---|---|---|---|---|---|---|---|---|
| en_coins_01 | eng | 83.1% | 21.7% | 12.0% | -9.7 pp | 65.4% | 15.0% | 6.7% | -8.4 pp | left.png:uvdoc/0px/rms0; right.png:uvdoc/0px/rms0 |
| bg_01 | bul | 12.7% | 9.6% | 3.7% | -5.9 pp | 8.9% | 5.9% | 1.5% | -4.4 pp | left.png:uvdoc/0px/rms0; right.png:uvdoc/0px/rms0 |
| bg_02 | bul | 38.1% | 31.5% | 1.7% | -29.8 pp | 28.9% | 27.4% | 0.3% | -27.1 pp | left.png:uvdoc/0px/rms0; right.png:uvdoc/0px/rms0 |
| **mean** | — | 44.6% | 20.9% | 5.8% | -15.1 pp | 34.4% | 16.1% | 2.8% | -13.3 pp | — |

Findings (per-image; the mean is carried by one image so read the rows, not the mean):
- **UVDoc improves ALL THREE pages, including the figure page.** en_coins split->dewarp WER 21.7%->12.0% (CER 15.0%->8.x%), bg_01 9.6%->3.7%, bg_02 31.5%->1.7%. Unlike the classical arm (which REGRESSED en_coins to 26.6% by extrapolating a text-baseline polynomial across the figure gaps), UVDoc applies a globally-coherent LEARNED full-page geometric rectification (perspective + curl), so figure-heavy layouts are flattened consistently rather than distorted. This revises the earlier classical-run framing: en_coins did NOT require layout awareness — it required a better (learned, coherent) warp.
- **bg_02 (strong curl) is near-perfect after UVDoc** (WER 1.7%, CER <1%), edging out the classical arm's 2.5%.
- **Caveat WER cannot see:** UVDoc still WARPS the figures (it bends them to flatten the page). WER improved because TEXT improved; it does not certify figure-crop fidelity. For a photo of a curved page a coherent flattening is plausibly correct for the coins too, but that needs visual QA / Stage-04 region handling to confirm — it is not measurable here.
- **Split alone** already beats the Gate-1 whole-spread baseline (mean WER 44.6%->20.9%; en_coins 83.1%->21.7% — facing-page de-interleaving); UVDoc adds a further large gain on top.

> Same N=3 humility as the classical run: 3 GT spreads, mean still carried by bg_02 — read the rows. UVDoc is the config default and wins on this evidence; revisit as the GT set grows. Full-res is preserved: the grid is predicted at 488x712 but grid_sample runs on the full-resolution page (Stage 06 patch crops come from this output).


## Gate 3 layout A/B — 2026-07-03, tesseract 5.4.0.20240606, layout=auto

Same recognized words reordered two ways (whole = Tesseract native order; layout = Stage 04 blocks in XY-Cut reading order) — isolates READING ORDER from recognition. Split+dewarp (UVDoc auto) identical across arms. Δ = layout − whole. All blocks kept incl. header/page-number (GT includes them).

| image | lang | whole WER | layout WER | ΔWER | whole CER | layout CER | ΔCER | arm | blocks | orphans |
|---|---|---|---|---|---|---|---|---|---|---|
| en_coins_01 | eng | 12.0% | 12.0% | +0.0 pp | 6.7% | 6.7% | +0.0 pp | doclayout | 25 | 1.1% |
| bg_01 | bul | 3.7% | 3.5% | -0.1 pp | 1.5% | 1.4% | -0.0 pp | doclayout | 13 | 0.7% |
| bg_02 | bul | 1.7% | 1.7% | +0.0 pp | 0.3% | 0.3% | +0.0 pp | doclayout | 7 | 0.0% |
| **mean** | — | 5.8% | 5.8% | -0.0 pp | 2.8% | 2.8% | -0.0 pp | — | — | — |

Findings (per-image; read the rows, not the mean — N=3 GT):
- **Reading order is NEUTRAL (non-regression) on all three GT pages:** en_coins_01 Δ0.0pp, bg_01 -0.1pp, bg_02 0.0pp. Stage 04's explicit XY-Cut order matches Tesseract's native order on these pages — it does not scramble the clean single-column controls, and it neither helps nor hurts the figure page.
- **Why NEUTRAL, not a win — and this is the real finding:** none of the GT pages is reading-order-hard AFTER Stage 02 split. Stage 02 already removed the cross-gutter facing-page interleave (the Gate 1 scramble); within each single half-page these GT pages are single-column-stacked, so Tesseract's own psm-3 order is already correct. There is NO post-split GT page where Tesseract's order fails, so a reading-order WIN cannot be demonstrated on the current GT. That is a GT-COVERAGE limit, not a stage weakness — the win case is multi-column/sidebar, which has no GT.
- **A real bug was found and fixed via this A/B** (recorded for mechanism honesty): the first cut REGRESSED en_coins_01 (+10.2pp, then +1.0pp after an intra-block-order fix). Root cause traced by diffing the two linearizations: DocLayout-YOLO does not box the italic footnote line, so its 8 words become ORPHAN singleton cells; the XY-Cut tie-break base case sorted them y-PRIMARY, and jittery OCR-box tops (2704-2717px on a ~24px line) scrambled same-line words (`Eastern Exchange` -> `Exchange Eastern`). Fixed by grouping the tie-break into reading ROWS by vertical OVERLAP (size-relative, so a line of jittery words groups but two tall stacked blocks do not — a fixed row-tolerance instead regressed bg_01 +7.5pp by collapsing stacked blocks). After the fix all GT pages are neutral.
- **Detection quality (debug overlays) is excellent** on every page including the no-GT complex ones: figures, captions, running headers, page numbers, titles and sidebars are all correctly boxed and typed (see testset/debug/*_04layout.png). Orphan rate 0-1.1% — detection covers nearly all text.
- **Multi-column (UNPROVEN, qualitative only):** it_geo_01 left reads headers -> diagram -> heading -> main column (full) -> right sidebar LAST — a standard, plausibly-correct two-column linearization (XY-Cut split the main column from the sidebar at their ~37px gutter; the overlay's crossing arrow is a centroid-connector artifact, not a scramble). But with NO GT this is NOT certified — it is the gate's open question.

Verdict: **PASS on the measurable scope** (detection proven; reading order non-regressive on all GT; overlays visibly correct), with the headline **multi-column reading-order IMPROVEMENT UNPROVEN** — no GT page exercises a post-split order failure, so no win can be shown yet.

> N=3 GT spreads, none multi-column. Proves figure/caption/footnote + header/page-number ordering on one single-column page (en_coins_01) + non-regression on two clean single-column pages (bg_01, bg_02). Multi-column order is exercised only qualitatively (testset/debug/*_04layout.png: it_geo_*, en_coins_02) and stays UNPROVEN until multi-column reading-order GT is hand-typed. See docs/GATE3_SPEC.md.


## Gate 3 block-order eval — 2026-07-03, tesseract 5.4.0.20240606, image=it_geo_04

Stage 04 block structure graded DIRECTLY against the per-subpage block-order GT
(`gt/it_geo_04.blocks.json`) by `tools/layout_order_eval.py`: segmentation, type,
caption<->figure grouping, and linear order. This is the sequence-order + grouping
metric the Gate-3 headline was blocked on. Owner priority (GT `primary_invariants`):
segmentation / type / grouping OUTRANK exact order — tau is secondary. Split+dewarp
= UVDoc auto (Gate-2 path). **N=1 spread — read the rows, not a mean.**

Matching: FIGURE GT blocks by reading-order rank within the subpage (no GT bbox;
in-figure labels don't OCR); TEXT GT blocks by anchor-token overlap on routed OCR
text (greedy, threshold 0.5). `tau (Tess-native)` ranks each block by the median
TSV index of its routed words — Tesseract's implicit order — graded the same way,
so improvement-over-baseline is measured, not asserted.

| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | grouping | det blocks | misses |
|---|---|---|---|---|---|---|---|
| left.png  | 4/5 (80%)  | 4/4 (100%) | +1.00 | +1.00 (n=3) | B8->B5: assoc, 1 figure | 10 | B6L |
| right.png | 4/4 (100%) | 3/4 (75%)  | +1.00 | +0.33 (n=4) | B7->B6R: assoc, caption MISTYPED, 1 figure | 9 | — |

Aggregate: **segmentation 8/9** GT blocks matched, **type 7/8** correct, **order
tau=+1.00** on both subpages. Grouping 2/2 captions associate to their partner
figure — but **0/2 on a >=2-figure subpage**, so grouping is NOT yet discriminated.

Findings (per-subpage; N=1):
- **Reading-order CORRECTNESS is proven on a genuine multi-column spread:** Stage
  04's XY-Cut order is fully concordant with GT on both subpages (tau=+1.00),
  including the right subpage's 3 columns (gutter-side caption B7 -> middle prose
  column B11 -> right prose column B12, read left-to-right column-major). This
  RETIRES the "multi-column reading order UNPROVEN" flag **for reading order
  specifically** — at N=1 with sparse anchors (4 blocks/subpage).
- **Improvement over Tesseract is limited to FIGURE placement, not text-column
  linearization — stated honestly.** Right-subpage Tesseract-native tau is +0.33
  vs Stage 04's +1.00, but the entire deficit is the figure block B6R (native
  median TSV=286, landing mid-stream because the panorama's stray in-figure labels
  OCR late). Over the TEXT blocks alone (B7=43 < B11=128 < B12=337) Tesseract's
  native column order is ALSO correct. So on this spread Stage 04 beats Tesseract
  only by placing the figure correctly (Tesseract has no figure concept); it does
  NOT out-linearize Tesseract on the prose columns, which Tesseract already reads
  in order. This refines — does not contradict — the layout_ab "neutral" finding.
- **Grouping is NOT yet proven — the metric passes are TRIVIAL here.** Each subpage
  has exactly ONE detected figure (B6L, the left fragment of the cross-gutter Fig.
  21 panorama, was pushed wholly onto the right subpage by the Stage-02 gutter
  split — right `ro2` figure spans x=0..2071 of 2099), so "caption's nearest figure
  == partner" has no wrong alternative to pick. Association is POSSIBLE, not
  DISCRIMINATED. The discriminating case (>=2 figures sharing one column, caption
  must pick the right one) is the owed follow-up fixture.
- **B7 (Fig. 21 caption) is mistyped paragraph -> grouping breaks in PRACTICE.**
  The geometric nearest-figure test passes, but the planned Gate-4 reflow floats
  caption-with-figure keyed on caption TYPE; a caption typed 'paragraph' won't be
  recognised as the caption to float, so the Fig. 21 panorama would lose its
  caption at reconstruction. Consequential, not cosmetic.
- **Segmentation miss B6L is a Stage-02 split artifact, not a Stage-04 failure**
  (the whole panorama went to the right subpage; see above). Extra detected prose
  blocks (10 left / 9 right vs 5 / 4 anchored GT blocks) are the body split into
  more paragraphs than GT anchors — GT anchors are sparse first-words, so this is
  not over-segmentation against GT.

Verdict: **Reading-order correctness on a genuine multi-column spread is PROVEN**
(tau=+1.00 both subpages, N=1, sparse anchors); segmentation 8/9 and type 7/8.
**Grouping is NOT closed** — the fixture has one figure per region so the pairing
test is undiscriminated, and B7's caption->paragraph type error would break the
Gate-4 float in practice. Improvement over Tesseract is figure-placement only on
this spread, not prose-column linearization.

> OWED to fully close the Gate-3 grouping headline: (1) a fixture with >=2 figures
> sharing one column (discriminate caption->figure pairing); (2) fix or account for
> the B7 caption->paragraph type error. Reading-order correctness itself no longer
> needs more GT at this altitude. See docs/GATE3_SPEC.md.


## Gate 3 caption-typing diagnosis (B7) — 2026-07-03, DocLayout-YOLO raw dets on it_geo_04

Owed item (2) above RESOLVED as **account-for, not code-fix** — by dumping the raw
pre-NMS DocLayout-YOLO detections per subpage (not inferring from the routed
block). The type miss (B7, Fig. 21 caption typed `paragraph`) is a **genuine model
miss, not an NMS suppression bug**:

- **B7 (right subpage):** its region (tall narrow gutter-side column,
  x=203 y=1870 w=430 h=940, w≈430 vs body columns ≈588) is detected ONLY as
  `plain text` conf **0.90**. **No `figure_caption` box appears on right.png at any
  confidence down to 0.10** — nothing was suppressed. The only Stage-04 lever is a
  geometric re-type, which at N=1 is overfitting → NOT done.
- **B8 (left subpage), for contrast:** correctly typed, but its box carries BOTH
  `figure_caption` 0.49 AND `plain text` 0.47; class-agnostic NMS keeps the caption
  by a **0.02 conf margin**. A class-aware NMS tiebreak (specific label beats
  co-located generic on overlap) would harden B8 — captured as a follow-up with the
  conf evidence, NOT built (B8 passes today; refinements go on failing pages, and
  en_coins_01 carries the same dual-label and is the regression risk).

**Fix pushed to Gate 4 (documented in GATE3_SPEC.md "Known limitation"):** the
Gate-4 caption↔figure float must NOT key solely on the detector `caption` type
(else B7's panorama loses its caption at reflow). It must also accept a *geometric*
caption signal — a text block **narrow relative to body columns and vertically
adjacent to a figure** (B7 is *tall*, so narrowness+adjacency, not shortness, is the
signal). The block-order eval already groups B7→B6R correctly by nearest-figure
geometry (type-independent), so the needed geometry is proven present. No code
change this pass; RESULTS + SPEC + memory updated. Grouping DISCRIMINATION (owed
item 1) remains blocked on an owner-supplied ≥2-figure fixture.


## Gate 3 grouping-metric fix — 2026-07-03, edge-gap pairing (synthetic ≥2-figure discrimination)

Owed item (1) — grouping DISCRIMINATION — advanced via a **synthetic** ≥2-figure
exercise (owner chose "synthesize now, maybe a real page later"; a fake image
does NOT go in the append-only real-image testset, so this is a detector-free
unit exercise of the pure grouping metric). The synthesis EXPOSED a real bug in
the grouping rule:

- `grouping_eval` paired each caption to its **nearest-CENTER-distance** figure.
  Probed with two figures in one column — a caption directly under a TALL figure's
  bottom edge (edge gap 10px) plus a SHORT neighbor figure — center distance picks
  the SHORT neighbor (center dist 120 < 530) and reports the correct attachment as
  a MISS. Unsound for unequal-height figures, and grouping is the owner's #1
  invariant.
- **Fix: pair by EDGE GAP** (box-to-box minimum distance; 0 if overlapping) —
  `_box_gap`, a better proxy than center for "which figure is this caption against."
  The tall-figure case now pairs correctly (10px < 50px). **This is NOT a fully
  sound rule** — edge-gap fixes the unequal-HEIGHT failure but does NOT encode the
  caption-above/below convention: stacked figures with ASYMMETRIC spacing (a caption
  nearer the NEXT figure's top edge than its OWN figure's bottom) still mispair
  (`gap=5` to Fig2 below beats `gap=10` to Fig1 above). No pure nearest-distance
  rule resolves above/below; a convention-aware rule is DEFERRED until a real
  >=2-figure fixture exists to tune against (same discipline as the NMS near-miss —
  the distinction from NMS is that center-distance was the *wrong heuristic* while
  a convention rule has *no data to tune* and NMS carries *en_coins_01 blast radius*).
- **Non-regression: it_geo_04 grade is byte-identical** (seg 8/9, type 7/8,
  tau +1.00/+1.00, grouping 2/2 assoc) — each it_geo_04 subpage has ONE figure, so
  edge gap == center (any-distance is trivially that figure). 66 unit tests green
  (was 63): `test_grouping_uses_edge_gap_not_center_for_unequal_height_figures`
  (the fix's regression test), `test_two_figure_subpage_discriminates_both_captions_end_to_end`
  (driver-level match+group on a 2-figure/2-caption synthetic subpage — both
  captions discriminate, `discriminated==2`), and
  `test_edge_gap_does_not_encode_caption_above_below_known_limit` (pins the
  asymmetric-spacing mispair so the boundary is explicit).

**What this proves and does NOT.** The grouping metric now *discriminates* on a
≥2-figure column (a wrong figure is present and it must be rejected) and its
pairing rule is *improved* (edge-gap, not center) — proven on synthetic data (the
metric CODE). It is NOT a fully sound rule (asymmetric-spacing above/below still
mispairs, pinned above) and it does NOT prove the DETECTOR keeps ≥2 real figures +
their captions separate on a photographed page. Both — a convention-aware rule and
detector-on-real grouping — still need the owner's real ≥2-figure fixture. B7
caption TYPE (item 2) remains account-for/Gate-4.

## Gate 3 block-order eval — 2026-07-03, tesseract 5.4.0.20240606, image=it_geo_06

Stage 04 block structure graded DIRECTLY against the per-subpage block-order GT (`gt/it_geo_06.blocks.json`): segmentation, type, caption<->figure grouping, and linear order. Owner priority: segmentation/type/grouping OUTRANK exact order (tau is secondary). Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.

| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | grouping | det blocks | misses |
|---|---|---|---|---|---|---|---|
| left.png | 7/8 (88%) | 3/7 (43%) | +0.14 | +1.00 (n=4) | C25->F25:assoc/type!; C26->F26:MISS/type!; C27->F27:MISS/type!; C28->F28:MISS/type! | 9 | F26 |
| right.png | 5/6 (83%) | 3/5 (60%) | +1.00 | +1.00 (n=4) | C29->F29:assoc/type!/1fig; C30->F30:MISS/type!/1fig | 8 | F30 |

**Segmentation** 12/14 GT blocks matched. **Type** 6/12 matched blocks correctly typed. **Grouping** 2/6 captions associate to their partner figure (0/6 also typed 'caption'); but only 1/6 on a subpage with >=2 figures (the rest are single-figure: association POSSIBLE, not discriminated).

**What it_geo_06 proves — grouping headline now DISCRIMINATED on a real page (the
owed fixture), and it measures a real DETECTOR gap.** This is the first fixture
with **≥2 figures sharing one column** (LEFT: 4 figs + a 4-caption stack; RIGHT:
2 figs + 2 caps), so a caption's nearest figure *can* be wrong — grouping is
genuinely discriminated, not merely "possible" as on single-figure it_geo_04.
Result on the current DocLayout-YOLO detector: **grouping fails, and the failure
is upstream of the edge-gap pairing rule** — (1) contiguous stacked figures MERGE
(LEFT cliffs F25/F27/F28 → one block; RIGHT F29+F30 → one block), cascading the
figure rank-match so F26/F30 go unmatched; (2) **every caption is typed
`paragraph`, not `caption` (0/6)** — the same tall-gutter-column miss class as B7.
So the blocker for real-page grouping is **figure under-segmentation + caption
mistyping**, not the geometric pairing rule. The fixture also encodes the
**number-keyed-pairing trap**: C26 (2nd in the stack) sits nearest the LEFT cliff
column but belongs to the top-right F26 — nearest-figure geometry *must* mispair
it, proving Gate-4 caption pairing has to be **textual** (read "Figura NN"), the
deferred convention-aware rule. tau is high where segmentation survives (+1.00 on
RIGHT, +1.00 Tess-native both) and drops on LEFT (+0.14) purely from the merge
scrambling figure ranks — order is secondary here per owner priority. Net:
retires "grouping discrimination UNPROVEN on a real page" → now PROVEN that it
fails, with the cause localized to the detector; motivates the Gate-4 "Figura NN"
parser (types + pairs by number in one step).

## Gate 3 block-order eval — 2026-07-03, tesseract 5.4.0.20240606, image=it_geo_05

Stage 04 block structure graded DIRECTLY against the per-subpage block-order GT (`gt/it_geo_05.blocks.json`): segmentation, type, caption<->figure grouping, and linear order. Owner priority: segmentation/type/grouping OUTRANK exact order (tau is secondary). Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.

| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | grouping | det blocks | misses |
|---|---|---|---|---|---|---|---|
| left.png | 1/2 (50%) | 1/1 (100%) | n/a | n/a (n=1) | C2->F2:MISS/type!/1fig | 3 | C2 |
| right.png | 5/5 (100%) | 5/5 (100%) | +1.00 | +1.00 (n=4) | C3->F3:assoc/1fig | 7 | — |

**Segmentation** 6/7 GT blocks matched. **Type** 6/6 matched blocks correctly typed. **Grouping** 1/2 captions associate to their partner figure (1/2 also typed 'caption'); but only 0/2 on a subpage with >=2 figures (the rest are single-figure: association POSSIBLE, not discriminated).

## Gate 3 block-order eval — 2026-07-03, tesseract 5.4.0.20240606, image=it_geo_07

Stage 04 block structure graded DIRECTLY against the per-subpage block-order GT (`gt/it_geo_07.blocks.json`): segmentation, type, caption<->figure grouping, and linear order. Owner priority: segmentation/type/grouping OUTRANK exact order (tau is secondary). Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.

| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | grouping | det blocks | misses |
|---|---|---|---|---|---|---|---|
| left.png | 15/17 (88%) | 14/15 (93%) | +0.87 | +0.51 (n=13) | C31->D1:assoc/type! | 20 | D5, T5right |
| right.png | 13/13 (100%) | 13/13 (100%) | +1.00 | +0.38 (n=13) | — | 16 | — |

**Segmentation** 28/30 GT blocks matched. **Type** 27/28 matched blocks correctly typed. **Grouping** 1/1 captions associate to their partner figure (0/1 also typed 'caption'); but only 1/1 on a subpage with >=2 figures (the rest are single-figure: association POSSIBLE, not discriminated).

## Gate-4 "Figura NN" caption parser — 2026-07-03, tesseract 5.4.0.20240606

New pure module `pipeline/caption_parser.py` + a **parser arm** in
`tools/layout_order_eval.py` (shown ALONGSIDE the detector-only numbers, so the
gain is measured not asserted). The parser re-types a `paragraph`/`other` block
as `caption` iff its OCR text STARTS with a figure keyword + number (`Figura NN`,
optional directional prefix `In questa pagina:` / `Sopra:` / `A lato:`); it never
demotes a block and never touches `figure` blocks. Motivation: the DocLayout-YOLO
detector types real captions as `paragraph` (0/6 on it_geo_06), which breaks the
Gate-4 caption↔figure float (keyed on caption TYPE). Empirically grounded first:
the routed OCR text was dumped for all four fixtures before a regex was written.

**Caption typing (detector → +parser), over the graded caption/matched blocks:**

| fixture | captions typed `caption` | type acc over matched blocks | promoted | false positives |
|---|---|---|---|---|
| it_geo_06 | 0/6 → **6/6** | 6/12 → **12/12** | 6 | 0 |
| it_geo_07 | 0/1 → **1/1** | 27/28 → **28/28** | 1 | 0 |
| it_geo_04 | 1/2 → **2/2** | 7/8 → **8/8** | 1 | 0 |
| it_geo_05 | 1/2 → 1/2 | 6/6 → 6/6 | 0 | 0 |

- **Robust typing win, zero regressions — provable, not just observed.** On every
  fixture `n_promoted` EQUALS the type-accuracy delta (06 +6, 07 +1, 04 +1, 05 +0).
  Since a promotion can only land on a `paragraph`/`other` block, promoting a GT
  non-caption would LOWER accuracy and promoting an unmatched block would make
  `n_promoted` exceed the delta; equality on all four means every promotion
  provably landed on a real matched GT caption — no hidden false positive is
  arithmetically possible. Every fixture reaches N/N type accuracy;
  the parser promotes exactly the mistyped-paragraph captions and NO body prose.
  The start-anchoring guard was verified against the real non-caption text that
  mentions a figure mid-sentence — it_geo_06 right `...ricoprirla (fig. 28). La
  loro base...` and it_geo_05 right `...tettonica piuttosto intensa (fig. 4)...`
  are correctly NOT promoted; the it_geo_07 `N)`-prefixed schema-step paragraphs
  (`1) Triassico...`) have no keyword and are ignored. it_geo_05 with 0 promotions
  holding at 6/6 is the clean non-regression control.
- **it_geo_05 C2 stays unrecovered (1/2)** — it is a caption embedded INSIDE the
  Fig.2 map's figure bbox (swallowed by the detector), and the parser deliberately
  never re-types figure blocks. Correct honest behavior, not a parser miss.

**Number extraction is OCR-fragile even when the keyword is clean:** on it_geo_07
the keyword read `Figura` but the number `31` OCR'd as `3`. Typing does not depend
on the number; pairing does — which is why the pairing claim is gated below.

**Pairing by number — figure-side blind on the current detector (honest limit).**
`pair_by_number` (caption N ↔ figure N) needs each FIGURE's number too; the only
textual source is the in-photo corner label (`25/26/27/28`) routed into the
figure block. What was verified on ALL four fixtures: every detected figure block
is EMPTY text — no figure-number signal reaches the figure blocks via center-
routing — so figure numbers recovered = 0 and number-keyed pairs recovered = 0/N
on each. (A stray corner digit could in principle have OCR'd and routed into
another column or dropped as an orphan — not separately checked — but on it_geo_06
it could not be attributed to F26 anyway while the three cliff figures are merged
into one detector box.) The C26→F26 discrimination that it_geo_06 was built to
test is therefore NOT textually solvable on this fixture: a figure-OCR /
detector-under-segmentation limit, not a parser gap. **This is the owner's #1
priority (grouping > order) and it remains UNMET on the real page** — Task #4
delivers the prerequisite (typed + numbered captions) and localizes the remaining
blocker to figure under-segmentation + corner-label OCR (the next lever).
The it_geo_06 GT's `document_order_gate4` reflow target (which this parser
ultimately feeds) is therefore left DEFERRED — ungradeable until the figure side
is separable — not silently skipped. The pairing LOGIC is proven
by unit test with synthetic figure numbers (defeats the geometric trap:
C26→F26 regardless of geometry) and correctly yields `{}` when figure numbers are
`None` (the real case). So the parser delivers the caption side (typed + numbered,
ready for Gate-4 reflow) and honestly reports the figure side as blocked upstream.

Tests: `pipeline/tests/test_caption_parser.py` (13) — real OCR strings, the
mid-sentence non-regression guards, multilingual keyword table (Italian validated;
en/de/bg provided but NOT fixture-validated), `figurano`/`figurative` false-match
guard, number-garble tolerance, and the pairing trap. Full suite 79 green.

---

## Stage 04 figure separation (Phase A) — 2026-07-03, DocLayout-YOLO + seam split

Built `split_merged_figures` in `stage04_layout` (see `docs/FIGURE_SEPARATION_SCOPE.md`):
under-segmented `figure` detections are cut at interior **full-width page-background
gutters** (a seam = a run of rows each ≥ `fig_seam_bg_frac` background, ≥
`fig_seam_min_frac` of the box tall; sub-boxes tightened to their non-seam extent).
Runs between NMS and reading-order in `dets_to_blocks`; NMS re-runs afterward to
reconcile a sub-box against the detector's partial-figure duplicate. Page-background
color is **sampled per subpage** from the outer margins (median HSV, dropping
near-black dewarp pad + saturated photo bleed) — not hard-coded cream. Phase A =
horizontal seams only; the right L-shape (H-then-V + caption ejection) is Phase B.

**it_geo_06 (the grouping fixture) — `fig_split` OFF vs ON, real detector:**

| subpage | figure boxes | seg-recall | tau (Stage04) | grouping (geometric arm) |
|---|---|---|---|---|
| left  OFF | 3 (F26 unmatched) | 7/8 (88%) | +0.14 | C25→F25 assoc; C26/C27/C28 MISS |
| left  ON  | **4** (F25/F27/F28/F26) | **8/8 (100%)** | **+1.00** | C25→F25 MISS; rest MISS |
| right OFF | 1 (F30 unmatched, 1fig) | 5/6 (83%) | +1.00 | C29→F29 assoc/1fig; C30→F30 MISS/1fig |
| right ON  | **2** (F29/F30) | **6/6 (100%)** | +0.87 | C29→F29 MISS; C30→F30 assoc (now ≥2-fig, DISCRIMINATED) |

Split sub-boxes hug the GT bands tightly (left: y271–1049 / 1091–1926 / 1973–2809 vs
GT 262–1052 / 1052–1902 / 1902–2812). **seg-recall improved on BOTH subpages** (F26,
F30 now match by rank); **tau jumped +0.14→+1.00** on the left (splitting the tall
box also unscrambled the text-block order — a bonus). No new params leak into the
forbidden OCR-threshold class (these are layout-geometry heuristics like the XY-cut
gaps).

**Regression guard — single-figure fixtures (it_geo_04 / 05 / 07):** figure-box count
is **identical OFF==ON** on every subpage (04: 1/1, 1/1; 05: 1/1, 1/1; 07: 4/4, 4/4).
Zero false-splits — the over-split guard (full-span seam + sampled-margin color)
holds; a single photo has no full-width cream band inside it, so its dets are
byte-identical and order/type/tau cannot move.

**Honest annotation (grouping row is NOT cleanly evaluated post-split).** The eval's
geometric grouping arm matches GT→detected figures by **reading-order RANK**. The
split perturbs it_geo_06's figure order — F26 (top-right plate) moves from last
(column-major) to ro=3, because splitting the tall box removes the vertical
continuity XY-cut used to keep the columns separate, exposing a spurious full-width
H-gap at y≈1049–1091 that groups F25+F26 into one top band. So on this ≥2-figure
page the rank match assigns 3-of-4 GT figure IDs to the wrong detected box, and two
pairs flip **assoc→MISS** (C25, C29) as the "nearest" tall box disappears. This is a
**cosmetic artifact on a row that is MISS-by-design** (the C26→F27 edge-gap trap this
fixture was built around): figure spatial order is owner-SECONDARY, and nothing
load-bearing consumes it — **tau excludes figures**, **Gate-4 reflow is number-grouped
(`document_order_gate4`)**, and **`pair_by_number` matches by number, not rank**. The
number-keyed grouping path (the real one) is **unchanged at 0/6** and still owed to
**#2 (corner-label OCR)** — spike showed 2/5 clean, feasible-but-not-free. Two
principled follow-ups (own commits, not this one): move the eval's figure matching
rank→**bbox-overlap** now that per-figure boxes + approximate GT bboxes exist (changes
the grading contract — owner call), and XY-Cut++ axis selection (prefer the larger
gap: the 50px V-gap beats the 42px H-gap here) to restore column-major order (its own
full regression pass).

## Stage 04 figure separation (#2 corner-label OCR) — 2026-07-03, `pipeline.figure_label`, image=it_geo_06

**What this delivers.** `pipeline/figure_label.py` recovers a figure's in-photo
CORNER-LABEL number (the small white "25" printed bottom-right of each plate) from
the figure's PIXELS — the number Stage 05 never emits as routed text — so
`caption_parser.pair_by_number` can pair caption N to figure N by the printed number.
This is the ONE route that defeats the C26→F26 trap (geometry provably mispairs C26,
which sits nearest the LEFT cliff column but partners the TOP-RIGHT plate F26).

**Method (glyph-geometry, the allowed heuristic class — NOT hard-coded OCR-confidence
thresholds, which live in Stage 06).** Crop the bottom-right region → upscale → white
top-hat on HSV Value (bright glyphs pop as solid blobs from dark OR textured bg) →
kill high-saturation pixels (coloured foliage/rock) → connected-components filtered by
digit size/aspect/fill → group adjacent similar-height CCs at one baseline → pick the
bottom-right cluster shaped like a 1–2-digit number → paint only its pixels → Tesseract
digit-whitelist OCR across PSM 7/8/10/13.

**Measured on it_geo_06 (N=1, six figures, one page) — on the REAL `split_merged_figures`
boxes, not GT extents:**

| figure | bg | localizes | read | correct? |
|---|---|---|---|---|
| F25 | cliff on teal water | yes | **25** | ✓ (eyeball-verified) |
| F26 | plate on near-black | yes | **26** | ✓ (eyeball-verified) |
| F27 | foliage cliff | no | None | — (0 wrong) |
| F28 | foliage cliff | no | None | — (0 wrong) |
| F29 | rock landscape | no | None | — (0 wrong) |
| F30 | rock close-up | no | None | — (0 wrong) |

**Net: 2/6 recovered, 0 wrong.** Moves `pair_by_number` **0 → 2** (C25→F25, C26→F26).
This is NOT the §7-aspired 0→6: four texture-swamped labels return None (real text
detector — EAST/MSER/CNN — needed; out of scope at N=1). The two reads and their
physical figure identity were **manually eyeball-verified** against the source photo
(the y272 box shows "25" on the water; the y253 box shows "26" on the black plate) —
this manual check is load-bearing because GT figures carry no gradable bbox.

**Conservatism is the invariant ("0 wrong").** `pair_by_number` attributes by NUMBER,
so one wrong read on a mispairing-trap fixture is worse than a miss. Acceptance rule:
a 2-digit value wins on ≥2 PSM votes only if no OTHER 2-digit value competes (so the
frequent "25"→"2" truncation cannot veto the full read — the exact real-box F25 case,
which OCR'd `['25','2','25','2']`); a lone 1-digit needs ≥3 PSM votes with no competitor
(the F28 texture fragment "3" stays None). Pinned by `pipeline/tests/test_figure_label.py`
(15 tests). **Non-regression:** on the single-figure pages it_geo_04/05/07 the reader
fabricates **0** numbers across all 12 figure boxes (`nonreg_check`), so no phantom
number can collide with those pages' caption numbers.

**HONEST framing — number-on-box defeats TWO defects, but the automated eval
under-reports it to 1/6.** In production `pair_by_number` reads "25"/"26" off the boxes
and pairs C25/C26 order-independently, defeating BOTH (a) the C26 geometry trap AND
(b) a real Stage-04 reading-order deviation: Stage 04 here emits the figures
**top-band-major** (F25, F26-plate, F27, F28), NOT the §6 **column-major** (F25, F27,
F28, F26) — the top-right plate lands 2nd because splitting the tall cliff box exposed
a full-width H-gap that XY-Cut cuts before descending the left column. The
`layout_order_eval` pairing arm rank-matches figures (GT figures have no gradable
bbox), so the physical-26 box — Stage-04's 2nd figure — is relabeled GT figure #2
("F27"), and the correct "26" read is scored a mispair: the metric shows **1/6, not
the true 2/6**. This is an eval-indirection limitation, not a `figure_label` defect,
and it was NOT laundered — the Stage-04 order deviation is a genuine §6 miss stated
plainly here. **Follow-up (Task #3, own commit):** switch `match_subpage` figure
matching rank→bbox-overlap against the GT's existing (overlay-only) figure bboxes;
that makes the 2/6 automated AND non-tautological (position-matched, still catches a
wrong read — unlike matching by the recovered number, which would be circular).

## Gate 3 eval — 2026-07-06, figure matching → bbox-overlap + tau over text-only, images=it_geo_04/05/06/07

**Closes the Task-#3 follow-up named at the end of the corner-label section above.**
Two entangled changes to `tools/layout_order_eval.py`, shipped together because the
first exposes a metric asymmetry the second must resolve:

**(1) Figures match GT figures by BBOX-OVERLAP, not reading-order rank.** A GT
figure that carries a bbox claims the detected figure it overlaps most (global
greedy by symmetric IoU, floor `FIG_IOU_MIN = 0.2`); a bbox-carrying figure that
overlaps nothing is an honest MISS (no rank fallback — that reintroduces the bug).
GT figures WITHOUT a bbox (it_geo_04, authored before figure bboxes) keep the rank
path, unchanged. Coordinate spaces were verified equal before writing: GT figure
bboxes and Stage-04 block bboxes coincide to IoU 0.92–1.00 on it_geo_06's clean
figures; every wrong (opposite-column / non-overlapping) pairing is ~0, so 0.2
clears them with a wide margin yet tolerates GT-bbox truncation (the clipped cliff
bottom F30 at IoU 0.63). Symmetric IoU, not coverage-of-smaller, so a partial-figure
fragment can't masquerade as the whole figure. This is the **non-circular** fix:
figures match by POSITION against the GT bboxes, independent of the recovered
corner-label number, so a WRONG read is still caught.

**(2) Tau (both arms) is now over TEXT blocks only.** The Tesseract-NATIVE arm ranks
blocks by the median TSV index of their routed words. Photos carry no words and were
already absent — but text-bearing figures (diagrams/maps with embedded labels, e.g.
it_geo_04's B6R map, it_geo_07's diagrams) DO get routed words and leaked into the
native arm, where their `native_key` is just where scattered internal labels fell in
the raster scan — noise, not a reading-order claim. That leak (not a real order
deficit) is what had pinned it_geo_04-right native at +0.33. Before change (1),
rank-matching forced figures concordant so the asymmetry was dormant; position-honest
matching would otherwise inject figure-placement deviations into a TEXT-order metric.
Excluding figures by TYPE from BOTH arms makes the layout-vs-native comparison
like-for-like for the first time and keeps tau measuring text reading order. Figure
order is owner-SECONDARY; nothing load-bearing consumes it.

**Measured (tool output for all four fixtures; text-block matches are byte-identical
to the prior grade on every subpage, so every delta is a figure-matching or
figure-exclusion effect only):**

| fixture / subpage | tau Stage04 | tau native | Δ vs prior | note |
|---|---|---|---|---|
| it_geo_04 left  | +1.00 | +1.00 (n=3) | native +1.00 (was +1.00) | byte-identical; bbox-less → rank |
| it_geo_04 right | +1.00 | **+1.00 (n=3)** | **native +0.33 → +1.00** | B6R map's TSV leak removed; text order was always a tie (matches prior prose) |
| it_geo_05 left  | n/a   | n/a (n=0)   | — | single figure only, no text pair |
| it_geo_05 right | +1.00 | +1.00 (n=4) | unchanged | — |
| it_geo_06 left  | **+1.00** | +1.00 (n=4) | layout stays +1.00 | text fully concordant; F26-plate order deviation no longer drags tau |
| it_geo_06 right | **+1.00** | +1.00 (n=4) | **layout +0.87 → +1.00** | figure-discordance removed |
| it_geo_07 left  | **+0.96** | **+0.45 (n=11)** | **layout +0.87→+0.96, native +0.51→+0.45** | like-for-like; win margin widens |
| it_geo_07 right | +1.00 | **+0.33 (n=9)** | native +0.38 → +0.33 | diagram-label TSV removed from native |

**Headline 1 — it_geo_07 multi-column reading-order proof, SHARPENED (not new).**
Previously recorded as "+0.87 / +1.00 (L/R) vs Tesseract-native +0.51 / +0.38." It is
now **"+0.96 / +1.00 vs +0.45 / +0.33"** — same conclusion (Stage 04's column-major
linearization beats native by a wide margin), but for the first time both arms are
text-only, so the comparison is like-for-like and the margin is honest, not inflated
by figures on the Stage-04 side that native structurally couldn't order.

**Headline 2 — grouping C31→D1 downgraded assoc → MISS, and this is the metric getting
MORE correct.** it_geo_07 left has 5 GT diagrams but 4 detected boxes; D1 (top,
`[80,880,940,240]`) is genuinely undetected (IoU 0.000 vs every det box). Old
rank-matching assumed the missing figure is *last*, shifting D1→D2's box … D4→D5's box
and dropping D5 — so C31's nearest figure was the box wrongly labelled D1 and scored a
spurious "assoc." Bbox-overlap matches D2–D5 to their own boxes and flags D1 as the
true miss, so the geometric arm now correctly CANNOT confirm C31→D1 (its partner wasn't
detected). Owner ranks grouping > order: the honest count drop is the point.

**The corner-label win, now correctly reported: `pair_by_number` 1/6 → 2/6.** On
it_geo_06 left, Stage 04 emits the figures top-band-major (F25, F26-plate 2nd, F27,
F28), not §6 column-major. Rank matching relabelled the physical-26 box as GT figure
#2 and scored `figure_label`'s correct "26" read a mispair (reported 1/6). Bbox-overlap
matches the plate box to GT F26 at IoU 1.000, so C25→F25 and C26→F26 are both credited:
**2/6, position-verified, non-tautological.** (The geometric nearest-figure arm also
moved to 2/6 — C28→F28, C30→F30 — but those are incidental geometry coincidences on
single-partner sub-columns, NOT the number-keyed win; the four texture-swamped labels
still return None → 0 wrong, unchanged.) Non-regression: it_geo_04/05 figure matches
byte-identical; full suite 103 green.

Tests: `tools/tests/test_layout_order_eval.py` +4 (`_bbox_iou` values; bbox-overlap
beats ro-rank on the out-of-order plate shape; a bbox-carrying no-overlap figure is an
honest miss with no rank shift; a fragment can't steal the whole-figure match). The
kendall_tau `1/3` unit fixture is retained as a pure partial-concordance case with an
updated comment (it was the it_geo_04-right native value *when* the B6R figure leaked
in; that grade is now +1.00 over its 3 text blocks).

## Stage 06 (uncertainty) — 2026-07-06, adaptive keep/flag/patch decision

The load-bearing stage: because OCR output BECOMES the visible re-typeset document,
every low-confidence word must be surfaced (flag), imaged (patch), or knowingly
emitted (best_guess). Built `pipeline/stage06_uncertainty.py` reading
`05_ocr/ocr.json`, writing `06_uncertain/resolved.json` (each `Word.decision` set,
+ a per-page patch manifest), `meta.json`, `debug/06_uncertain.png`, and (patch
mode) `06_uncertain/patches/`.

**The adaptive threshold (CLAUDE.md: never a single global cutoff).**
`threshold = clip(percentile(conf, flag_rate*100), conf_floor, conf_ceiling)`,
pooled over both subpages of the spread (spread ≈ document; `--threshold` injects a
true whole-job value). `flag_rate` (0.10) is a TARGET that BENDS: in a clean doc the
ceiling bites (flag fewer), in a garbage doc the floor bites (flag more) — the
operating point moves with the confidence distribution between the two rails, so it
is adaptive, not one hard-coded gate. `uncertain := conf < threshold OR
second-engine-disagrees` (the disagreement term is a wired seam — EasyOCR is deferred
at Stage 05, so it is always False and a warning makes the gap visible). Mode is a
thin policy layer over that one decision: `best_guess`→all KEEP, `flag`→FLAG,
`patch`→PATCH.

**Rails anchored to REAL testset conf histograms, not invented** (config
`uncertainty.conf_floor=45`, `conf_ceiling=75`). Per-word conf over the two OCR'd
docs: bg_01 p10=92/p50=96 (bad tail <65), en_coins_01 p10=82/p50=96 (tail <65). The
clean bulk sits ≥82, so `conf_ceiling=75` lands between bulk and tail — a clean doc
flags only its genuine low-conf tail, never good words. `conf_floor=45` is the
minimum threshold for a garbage doc and is a THEORETICAL rail: both testset docs are
clean (raw p10 ≫ 45), so only the ceiling bites here; the floor is untested until a
genuinely garbled page lands.

**Measured (both clean docs → ceiling bites, effective rate below the 10% target):**

| doc | scored words | raw p10 | applied thr | flagged (total) | effective rate (scored) |
|---|---|---|---|---|---|
| bg_01 | 759 | 91.96 | 75 (ceiling) | 30 | 3.43% |
| en_coins_01 | 738 | 81.81 | 75 (ceiling) | 60 | 7.45% |

The raw + clamped threshold and effective rate are recorded in `meta.json` — that
record is the proof the threshold adapted. "Effective rate" is scored-word-only
(non-KEEP among the words that fed the percentile); it shares the percentile's
denominator, so conf≤0 words — flagged unconditionally at any threshold, thus not a
measure of the threshold's action — are excluded from both. It is therefore a hair
below the total-flagged count (which does include those conf≤0 words).

**Note on the honest limit of this proof:** both testset docs are clean, so the raw
p10 is ≫ the ceiling and the threshold pins to 75 on both — i.e. on the REAL data
"adaptive" is currently indistinguishable from a fixed 75 cutoff. The percentile
machinery that makes it adaptive is exercised only by the synthetic unit tests
(clean→ceiling, garbage→floor, mid→honours target). Real-data adaptivity (a doc with
p10 inside the (45,75) band) and any `conf_floor` exercise are OWED until a
mid-degraded page lands in the testset.

**Patch-mode ship-gate — coordinate contract verified on REAL pixels.** Patch mode is
the first real exercise of Stage 05's promise that word bboxes live in 1x full-res
dewarp coords (both GT pages had run scale=1, so the map-back was unit-tested only).
Cut 60 crops from en_coins_01's `03_dewarp` full-res image and eyeballed a labelled
contact sheet (crop pixels vs recorded OCR text): every crop tightly frames its
labelled word — the coord map-back is correct. Better, the flagged words are genuine
recognition failures the crop exposes: `'Chapmarked'`→pixels "Chopmarked",
`'Light'`→"Eight", `'111'`→"III" (roman numeral), `'36.24).'`→"36.2a).", plus conf-0
accented/footnote/quote-wrapped tokens. Caveat: both docs ran scale=1 (word height
≥20px), so the 2× upscale coord map-back still isn't exercised on real small-text
pixels (a Stage 05 caveat inherited here).

**Scope kept lean** (like the other v0.1 stages): Stage 06 only assigns the per-word
decision + cuts patch crops. De-hyphenation on reflow and running-header /
page-number stripping are Stage 07 (`reconstruct`), not here.

Tests: `pipeline/tests/test_stage06_uncertainty.py` (12) — the rails biting in both
pathological tails (clean→ceiling→flag fewer; garbage→floor→flag more; mid honours
target), small-sample fallback to the floor, empty/conf≤0 eligibility (excluded from
the percentile yet still decided uncertain), mode policy layer, config resolution.
Full suite **115 green**.

Follow-ups (own commits, not this pass): a true whole-job (multi-spread) threshold
pass feeding `--threshold`; the EasyOCR cross-engine disagreement trigger when the
second engine lands; `conf_floor` re-tuning once a genuinely garbled page is in the
testset; and the 2×-upscale patch-coord exercise on a real small-text page.

## Multi-view curvature Phase 0 — 2026-07-11, make-or-break gate on the N=1 skew set

Ran the two gated Phase-0 measurements from `docs/plans/multiview-curvature.md` on the
existing skew set (`temp/zoomset_raw/skew/example 3`, "A New World" p.797 — the ONE
dense-single-column strong-gutter-curl page; examples 1/2 are mostly-photo regression
guards, not validation). Baseline frame = **151056**, the most *face-on* of the 4
angles (least gutter foreshortening — advisor: Phase-1's win must beat the best single
view, not just the sharpest). Ingest via the real pipeline path
(`normalize.load_upright_bgr`); OCR path identical across arms (grayscale +
probe-upscale, same as `tools/dewarp_ab`). Gutter/spine is on the LEFT. Scratch probes:
`temp/skew_phase0/skew_0a.py`, `skew_0b.py`. **N=1 — feasibility/sizing only, not an
OCR-gain validation** (that needs the data-gap set below).

### 0a — does Stage 03 UVDoc already solve it (on the best single view)? → NO.

Raw face-on page-crop vs UVDoc-dewarped crop, same OCR, words in 4 x-bands (same band
edges as 0b so the two tie together; gutter/spine on the LEFT):

| x-band | region | RAW words / conf | DEWARP words / conf |
|---|---|---|---|
| [0.00–0.12] | innermost gutter | 9 / 35.0  | 33 / **28.1** |
| [0.12–0.24] | outer gutter     | 28 / 48.2 | 49 / 53.3 |
| [0.24–0.50] | inner flat       | 118 / 68.3 | 112 / **80.9** |
| [0.50–1.00] | outer flat       | 114 / 78.7 | 117 / **88.5** |

UVDoc flattens geometry excellently: both flat bands jump (+12.6, +9.8 conf) and are
visually crisp. But the **innermost gutter band [0–.12] gets *worse* (35.0→28.1)** while
its word count balloons 9→33 — dewarp now finds boxes in the spine smear but they are
spurious/garbled. The dewarped gutter is a faint, foreshortened gray ghost
(`temp/skew_phase0/gutter_dewarp.png`); OCR there is garbage in BOTH arms (e.g. dewarp
reads `bine or Every / wees, 100, but / smd make` for "…ght. Every line…/ …too, but…/ …and
make…"). The word-count-up / conf-down signature means the innermost strip is **degraded
text + shadow**, not blank margin. UVDoc *straightens* the gutter but cannot *synthesise*
the resolution/contrast the single oblique view lost.

**Verdict:** on the best single view, a real, gutter-specific residual gap survives dewarp
→ the effort is **not moot** (do NOT STOP). The dead zone is **narrow** — the innermost
~1 word/line (<12% page width). Its two components split cleanly by band and matter for
what can fix them: the innermost [0–.12] is **foreshortening** smear (geometric — only a
different viewpoint has those pixels; contrast tricks can't reconstruct them); the outer
gutter [.12–.24] is real text at conf ~48–53, plausibly partly spine **shadow** (a cheap
contrast/CLAHE lever *for that band only*).

### #1 — does another ANGLE recover what the face-on view loses? → YES (existence proof).

The make-or-break question the plan bets on: is the lost gutter text actually *present* in
another view? Cropped the same top gutter lines from the face-on anchor (151056) vs the
most-oblique frame (151105) and OCR'd each (`temp/skew_phase0/compare_gutter.py`,
`cmp_*.png`):

| frame | top-gutter OCR (line-starts) |
|---|---|
| face-on 151056  | `and 98 = lots of line…` — line-starts **lost/garbled** |
| oblique 151105  | `Lines in the sang are … That's right … a line, UME passes too … come back here…` |

In 151105 the camera sits left and the page's **top-left tilts toward the lens**, so
"**Lines** in the sand around us / '**What** are you doing?' / '**I** draw seconds.' /
'**Seconds?**' / '**That's right.** Every line is time…" are **crisp and fully legible** —
every one a faint foreshortened smear in the face-on frame. The trade-off: in that same
oblique frame the *outer margin* ("A New World", "lots of lines with gaps…") recedes and
shrinks. So **different viewpoints favour different parts of the page**; the face-on frame
is best *overall* but is *not* best at the gutter.

**This flips an earlier hypothesis** (that the oblique frames might simply be
worse-everywhere, making multi-view moot on this set): the pixels say the opposite. It is
an **existence proof only** — N=1 page, one gutter region, one angle-pair: the *premise*
(the lost gutter text exists in another view) is **verified**; the *solution* (fusing it
yields net OCR gain) is **not** — that still needs the data-gap set. (Whether the oblique
advantage is more pixels-per-character or partly a focus/lighting accident of that frame is
not isolable at N=1 and does not matter for an existence proof.)

### 0b — can we register the angle set to fuse the gutter? → NOT with feature matching.

Registered the other 3 angles onto the face-on anchor with a single global ORB homography
fit on page-region correspondences, residual bucketed by x (long-side 2000px):

| angle vs anchor | inliers (% of page matches) | gutter inliers (x<0.24) | flat median resid |
|---|---|---|---|
| 151058 (mild)    | 320 / 584 (55%) | **0** (pre-RANSAC raw: 7 + 17) | 1.33–2.02px |
| 151100 (more)    | 25 / 265 (9%)   | **0** (raw: 0 + 11)            | 1.58px |
| 151105 (oblique) | 9 / 198 (5%)    | **0** (raw: 0 + 4)             | ~1.0px |

Zero RANSAC inliers land in the gutter band for all 3 pairs; the global homography fits the
flat region fine (median 1.3–2.0px). **Reconciling this with #1** (the oblique gutter is
crisp, so it is *not* feature-poor in absolute terms): the 0 inliers are an artefact of
registering **to the face-on anchor**, whose gutter is smear — there are no anchor-side
keypoints for the oblique frame's real gutter keypoints to match *to*, and the page's
non-planarity gets any stray gutter match rejected as an outlier against the flat-region
homography. So the precise claim is **"the gutter is unregisterable-by-features to a
face-on anchor,"** not "the pixels aren't there." Two more findings: the innermost band
[0–.12] has ~0 *raw* matches even on the anchor side (7/0/0), and inlier robustness
**collapses with angle** (55%→9%→5%) — the more-oblique views that carry the gutter payload
are the hardest to register.

**Verdict:** the recoverable gutter pixels demonstrably exist (#1) but a global ORB
homography cannot fuse them — Phase 1's naive mechanism ("ORB-register the set →
per-region pick the least-foreshortened view → blend") is **not** a cheap build. It needs
intensity-based / optical-flow registration seeded from the flat region, or a
developable-surface geometric model — i.e. it lands in the Phase-2 research bucket.

### Combined Phase-0 conclusion (holds the effort at SCOPE)

The effort's *premise is now demonstrated, not assumed*: on the one strong-curl page, gutter
text the best single view foreshortens into mush is legibly present in another angle (#1),
and UVDoc alone cannot recover it (0a). But Phase 0 still does **not** greenlight Phase 1 as
a quick build — the pixels exist yet feature registration cannot fuse them (0b). Verdict and
next-actions are unchanged from scope; this finding enriches the *why*, not the *what-next*.
Cheapest honest next steps, in order: (1) the still-owed **data-gap ask** — 3–5 more
paperback-style strong-curl dense-text pages, each multi-angle, before any OCR-gain claim
can be validated; (2) a cheap **shadow/contrast spike** targeting the *outer* gutter band
[.12–.24] only (the innermost word is foreshortening, not shadow — preprocessing can't
reach it); (3) if multi-view is pursued, budget for non-feature (ECC/optical-flow) or
geometric registration from the start — ORB will not align a gutter to a face-on anchor.
Examples 1/2 remain untouched regression guards. Nothing was canonised into `testset/` (N=1;
that stays the curated append-only data-gap deliverable).

---

## Multi-view curvature Phase 0 — extended to N>1 — 2026-07-11

The owner delivered the data-gap set (`temp/zoomset_raw/curl/`, 7 usable multi-angle sets,
folder 4 empty). This re-runs the Phase-0 gate on **N>1** to test whether the premise and the
gap **generalise** beyond the one skew page. **Important framing:** N>1 here buys *gap
generality* (0a) and *premise generality* (#1) — the go/no-go evidence to **greenlight** the
Phase-1 build. It is **NOT** the fusion OCR-gain measurement; that still needs the build (0b
showed no working registration). Do not read "solution validated" into this section.

**Honest clean N = 3 single-page strong-curl pages** (skew p.797 + curl set 3 "A New World"
p.785 + curl set 5 "Dépôt Kurt" p.827) — all single-page obliques with one unambiguous left
gutter, same geometry as the N=1 harness. The spreads (sets 1/2/6/7/8) have **two** gutters +
a central spine occlusion + need the Stage-02 split, so they are visual-consistency notes
only, not folded into the measurement.

*Curl geometry, so the frame labels don't read as a contradiction:* near a gutter the page
curls so its inner text runs **near-vertical / edge-on**. A camera **tilted toward the
gutter** sees that spine text more **face-on** (more pixels/char) than a camera square over
the page's flat middle — which instead foreshortens the gutter into a smear. So "the oblique
frame reads the gutter better" is geometry, not a mislabel.

### Gate first — is the angle spread real, or an auto-capture burst? → REAL.

Before measuring, confirmed the within-set frames are deliberately re-angled, not a static
hand-held burst (which would measure noise). ORB frame-to-frame registration (`orb_homography`,
half-res ×2 for full-res px):

| set | f1→f0 disp | f2→f0 disp | inlier trend |
|---|---|---|---|
| 1 (mild)   | ~336px | ~676px (→f3 ~926px) | 514→75→7 |
| 2 (strong) | ~394px | ~694px | 278→49 |
| 3 (strong) | ~83px  | ~581px | 151→7 |
| 5 (strong) | ~223px | ~607px | 83→7 |

Displacements of 80–900px are far beyond hand-shake (a few px) = genuine viewpoint change.
Inliers collapse as angle widens (set1 514→75→7), reproducing 0b's "robustness collapses with
angle." Gate passes numerically **and** by eye.

### #1 premise generality — the complementary-halves proof (the spine of this section)

On curl set 3 (p.785), the two extreme frames of the same page, de-contaminated (facing-page
sliver cut at the spine-shadow valley *before* any processing):

- **Oblique f0** reads the **left gutter line-STARTS** crisply ("*It changes its face as the
  year progresses*", "*and in spring by a dusting of pollen*") but foreshortens the **right
  line-ends** (flat-right OCR conf 65.4 / 52.8).
- **Face-on f2** reads the **right ends** crisply (flat-right conf 94.1 / 89.8) but now curls
  the **left gutter starts** away ("*ace as the year*", "*dusting of pollen*").

**Neither single frame reads the whole line** — each owns the half nearest its camera. This
is the multi-view premise made visible on a **second** page (after the N=1 skew existence
proof), and it is a *picture*, robust to any band-conf noise. **Set 5 is directionally
consistent, not a clean split:** by eye its oblique frame likewise reads the left gutter
starts that the face-on frame curls away, but its two frames differ ~2× in crop width
(oblique 1142px vs face-on 2370px — steep foreshortening, *not* a crop bug: the oblique
gutter text is intact), so set 5's *cross-frame* band numbers are muddied and are **not**
quoted as a complementary split — its face-on frame even wins the innermost-band conf. So the
clean complementary-halves proof is **set 3**; set 5 corroborates the premise directionally.
It also **reframes 0a**: there is no single "best
frame" that is face-on across the full width, so single-frame flattening (UVDoc, which only
un-warps one frame) structurally cannot recover the half that frame foreshortens — *that* is
the not-moot proof, cleaner than any statistic. (It also kills the tempting "just pick the
most face-on frame" deflation — no such frame exists.) The **cross-frame word-count** f0-vs-f2
is deliberately **not** quoted as a statistic: different scale/position/legible-half make it
not apples-to-apples — quantifying it rigorously *is* the fusion measurement, which needs the
build.

### 0a generality — does UVDoc alone recover the gutter on the best single frame? → NOT reliably.

De-contaminated (facing page removed from the *input* before dewarp), the only
apples-to-apples comparison is **RAW-faceon vs UVDoc-faceon** (same frame, same input, scale
controlled). Per x-band mean OCR conf:

| page (face-on frame) | innermost [0–.12] | outer gutter [.12–.24] | flat [.24–.5] |
|---|---|---|---|
| set 3 | 59.4 → **80.9** (helps) | 85.5 → 91.2 (helps) | 94.1 → 91.6 |
| set 5 | 63.9 → **34.3** (hurts) | 48.6 → **71.0** (helps) | 91.1 → 85.1 |

UVDoc **reliably lifts the outer gutter band** on both pages, but the **innermost band is
page-dependent** — it helps set 3 (+21) and hurts set 5 (−30). **Correction to the N=1
finding:** the earlier "UVDoc always mangles the innermost gutter" (skew page, conf 35→28 +
spurious boxes) **did not survive de-contamination** — it was partly the facing-page sliver
warping under the grid, not the target gutter. The honest, generalised 0a: *UVDoc does not
**reliably** recover the innermost gutter* (one page it degrades) → a residual gutter gap
remains on at least some pages → **not moot** — but the effect is weaker and less universal
than N=1 implied. The stronger not-moot argument is the complementary-halves geometry above,
which does not depend on this noisy band.

### Combined N>1 conclusion → GREENLIGHTS the Phase-1 build (0b still makes it research)

Both Phase-0 questions now hold at N=3: the **premise generalises** (complementary halves
cleanly on set 3, directionally on set 5 — the lost gutter text lives in another angle) and
the **gap generalises** (no single frame + UVDoc recovers the whole gutter across the 3
pages). That is exactly the go/no-go evidence to
**greenlight the Phase-1 multi-view build** — which the original N=1 gate could not do. It
does **not** change 0b's verdict: a global ORB homography still can't fuse the angles
(gutter unregisterable-by-features to a face-on anchor), so Phase 1 remains **research, not a
quick build** — intensity/optical-flow or developable-surface registration from the start.

**Next, in order:** (1) if the build is greenlit, curate a `testset/skewset_*` fixture
(append-only) — and if the production capture mode is spreads, prefer **strong-curl spreads**
(the central gutter is where two inner margins curl hardest) plus **variety**: 3–5 different
books, a curl-severity range, and the priority non-Latin scripts (Bulgarian Cyrillic,
Italian, German), since gutter OCR degradation is script-dependent; (2) the cheap
outer-gutter-band [.12–.24] contrast/CLAHE spike still applies. Nothing canonised into
`testset/` yet (the curl set stays scratch until a build is greenlit). Scratch probes:
`temp/skew_phase0/{viewpoint_diversity,curl_0a,curl_0a_clean}.py`.

---

## Outer-gutter CLAHE spike — 2026-07-17 — VERDICT: NEGATIVE (multi-view keeps the whole gutter gap)

The cheap preprocessing spike owed by `docs/plans/multiview-curvature.md` (First next
actions #4): does contrast/CLAHE recover the **outer gutter band [.12–.24]**, which Phase 0
described as "real text at conf ~48–53, plausibly partly spine **shadow** (a cheap
contrast/CLAHE lever *for that band only*)"? If yes, it would shrink the multi-view case for
free — narrowing Phase 1 to the innermost [0–.12] foreshortening band. **It does not.**

Same N=3 clean single-page strong-curl pages as the Phase-0 N>1 extension (skew p.797 +
curl set 3 p.785 + curl set 5 p.827), same de-contamination (facing-page sliver cut at the
spine valley before dewarp). Scratch probes: `temp/gutter_clahe/{dump_bands,clahe_ab}.py`,
GT in `temp/gutter_clahe/gt_bands.json`.

### Method — why the go/no-go is recall, not conf

**Baseline is UVDoc, not RAW.** RESULTS already shows UVDoc alone lifts the outer band
(set3 85.5→91.2, set5 48.6→71.0); measuring against RAW would bank Stage 03's win as
CLAHE's. The only question is whether CLAHE adds anything **on top of Stage 03**.

**CLAHE is applied globally** to the gray that feeds Tesseract, at native res before the
probe-upscale (the production-plausible Stage-05 preprocessing point). Global, not
band-local: CLAHE is already tile-adaptive, and a band-local application creates seams and
is not shippable. That makes the **flat bands a free regression guard**.

**Settings fixed a priori** at the conservative default (clipLimit 2.0, tile 8×8) — no
tuning on N=3. The sweep below shows every page × every setting so variance is visible.

**The probe-upscale scale is pinned** from the baseline arm and reused by the CLAHE arm, so
"CLAHE helped" can't be confounded with "the arms ran at different resolutions".

**Metric.** Screen = per-band word count + mean conf (Phase-0 continuity). **Go/no-go =
token recall against hand-keyed outer-band GT**, because mean conf cannot answer this
question — CLAHE raises conf on garbage as readily as on real text. GT was keyed by eye off
full-res strips with the band edges drawn (declared coverage: ~30–37 text lines/page, not
full-page); recall is scored box-independently inside a generous [0–.35] window, since CLAHE
can split/merge tokens near an edge. CLAHE moves **zero pixels**, so both arms share
identical geometry and one keying is valid for both.

### Result — at the pre-registered setting (clipLimit 2.0, tile 8×8)

| page | outer conf base→CLAHE | Δconf | outer **recall** base→CLAHE | **Δrecall** | flat guard [.24–.5] / [.5–1] |
|---|---|---|---|---|---|
| skew  | 67.6 → 66.3 | −1.3 | 0.533 → 0.533 | **+0.000** | 79.7→90.2 (+10.5), 77.2→89.8 (+12.6) |
| curl3 | 91.2 → 92.1 | +0.9 | 0.975 → 0.975 | **+0.000** | 91.6→93.6 (+2.0), 94.8→93.1 (−1.7) |
| curl5 | 71.0 → 73.9 | +2.9 | 0.500 → 0.519 | **+0.019** | 85.1→81.3 (−3.8), 87.8→88.5 (+0.7) |

**CLAHE recovers 0, 0, and 1 gutter tokens across the three pages.** The spike is negative.

**This is a true null, not a dead gauge** — the first thing to ask of any negative. Three
things say the needle *can* move: curl3 scores 0.975 (the GT keying + scorer reach ceiling on
legible text), recall ranges 0.33–0.64 across the sweep below, and it drops **sharply** when
CLAHE over-amplifies (curl5 4.0/8 → 0.333). The metric responds to CLAHE in **both
directions**, so +0.000 at the pre-registered setting is a measured zero. skew/curl5 at ~0.50
is real residual degradation that CLAHE does not touch, not a scoring artefact.

**The null is also conservative** — two things bias this measurement *toward* CLAHE and it
still lost. The recall window [0–.35] deliberately includes the smear band, so had CLAHE
turned any smear-garbage into a real GT-matching word, that would have scored as a gain. And
hand-keying error hits both arms symmetrically (one keying, identical geometry), so it can
only wash out a real delta — never manufacture a null.

**curl5 is the case for using recall and not conf:** conf rose **+2.9 while recall moved by
one token**. Token-level, the baseline reads `Anglada's` / `brought` / `You see,` where CLAHE
reads `nglads` / `rought` / `Y ou see,` — *more confident, less correct*. A conf-only spike
would have reported a win that does not exist.

### Why the premise was wrong (the pixels, not the statistic)

Phase 0 inferred "plausibly partly spine shadow" from the band's low conf (48–53). Looking at
the actual band pixels kills that inference: on curl3 and curl5 the outer band is **crisp,
high-contrast, black-on-white text** — there is no shadow in it to remove. Its depressed mean
conf is a **mixture artefact**: the band is mostly clean text plus a few *smear-tail
fragments* whose centres happen to land past x=.12 (`aving`, `flea`, `sonal`, `ried.`), and
those fragments drag the mean down. They are foreshortening damage, which is geometric —
contrast cannot reconstruct pixels the lens never resolved. The skew page differs: it is
**uniformly faint everywhere**, gutter and flat alike, which is a global exposure problem,
not a gutter one.

So the band's low conf never was a shadow signal. **The [0–.12] / [.12–.24] split that Phase 0
drew — "innermost = foreshortening, outer = shadow" — does not survive contact with the
pixels. Both gutter bands are foreshortening; only the severity differs.**

### Sweep — variance across settings (NOT a tuning result)

| setting | Δrecall skew | Δrecall curl3 | Δrecall curl5 | worst flat-guard hit |
|---|---|---|---|---|
| 1.0 / 8  | +0.111 | +0.000 | +0.037 | −2.5 |
| **2.0 / 8** (pre-registered) | **+0.000** | **+0.000** | **+0.019** | −3.8 |
| 3.0 / 8  | +0.044 | +0.000 | −0.019 | −9.0 |
| 4.0 / 8  | −0.089 | −0.025 | −0.167 | −16.1 |
| 2.0 / 16 | +0.000 | +0.000 | +0.074 | −1.7 |
| 4.0 / 16 | +0.044 | −0.025 | −0.093 | −21.6 |

No setting is consistently positive; the largest single gain (skew 1.0/8, +0.111 = 5 tokens
of 45) comes from the *mildest* setting and is **not** reproduced on the other two pages —
crowning it would be exactly the "tune on N=3" error. Everything at clipLimit ≥3.0 is
actively **destructive** (curl5 4.0/8: recall 0.500→0.333, flat conf −13.4/−16.1). Conf and
recall are decorrelated throughout the sweep (skew 4.0/16: conf **+5.2**, recall +0.044).

### Verdict

**The outer-gutter CLAHE lever does not exist at the insertion point the plan scoped** —
i.e. CLAHE applied *post-dewarp*, on pixels UVDoc has already resampled, as a cheap Stage-05
preprocessing step. That bound is deliberate and worth reading precisely: this result does
**not** say all contrast preprocessing is dead (the illumination lead below is the
counter-example), and it does not test CLAHE *before* dewarp — a different mechanism
(feeding UVDoc's grid prediction), outside what the plan scoped as a cheap post-processing
lever, and not worth chasing given the band-model correction above.

Multi-view Phase 1 therefore **keeps the whole gutter gap [0–.24]** — nothing is descoped,
and the Phase-1 budget is unchanged. This is a real (negative) result, and it was cheap: it
closes the plan's open question rather than leaving it as a maybe.

### Lead, explicitly NOT a claim — global illumination normalization

The one large effect found is **not** the one the spike hunted: gentle CLAHE lifts the
**flat-band** conf of the globally-dim skew page by **+10.5 / +12.6**, bringing it from 79.7/77.2
up to the 90ish of the other pages, while being neutral-to-negative on the already-bright
pages (curl5 flat −3.8). That is illumination normalization, not gutter recovery — the
Stage 00/03/05 preprocessing item already scoped in [max-quality-fusion](plans/max-quality-fusion.md)
("glare is single-image illumination normalization, not fusion"), not this effort.

**It is quoted as conf-only and is NOT validated as an accuracy win** — GT here covers the
outer gutter band only, so there is no accuracy number behind the flat bands. This very
spike just demonstrated that conf moves independently of accuracy (curl5: +2.9 conf, +1
token), so treating a flat-band conf lift as a win would repeat the exact error the spike
was designed to catch. Worth a separate spike **because it can be done right**: the real
`testset/` has ground truth, so a clean-page CLAHE non-regression + gain measurement is
directly runnable there — which is also the precondition a shippable Stage-05 preprocessor
would owe anyway, since it would touch every page, not just gutters.

---

## 2026-07-18 — Stage 00 orientation cascade (no-regression check)

`tools/normalize` rewritten from "exif_transpose-then-OSD-rescue" into a
confidence-gated priority cascade (capture-hint / text-baseline stubs → OSD →
EXIF **mirror-only**, pure-rotation tag distrusted → landscape prior). Motivated
by real-capture Finding 1 (`docs/notes/2026-07-18-real-capture-findings.md`):
figure-heavy German spreads (`de_01`/`de_02`) ingested sideways because OSD
starved (conf ~0.04–1.97) and the old fallback kept the spurious
`exif_transpose` rotation.

Gate 1 harness (whole-spread raw Tesseract, `--preprocess none`), the 3 text-GT
spreads — **identical to history → zero OCR regression**:

| image | lang | whole WER (pre) | whole WER (post) |
|---|---|---|---|
| en_coins_01 | eng | 83.1% | 83.1% |
| bg_01 | bul | 12.7% | 12.7% |
| bg_02 | bul | 38.1% | 38.1% |

Provable: for an orientation-6 spread with confident OSD, the old path was
`exif_transpose` (raw +90 CW) then OSD undoing it (−90) = the raw landscape
buffer; the cascade returns that same raw buffer directly. Only the OSD-can't-
decide case changes. End-to-end on the **original** (un-stripped) German
captures: Stage 04 recovers from `blocks=1` to 21 (de_01) / 47 (de_02) blocks;
all 15 `testset/gt/orientation.json` fixtures resolve upright
(`tools/tests/test_normalize.py`). de_* remain the guard for the figure-heavy
OSD-starve case.

## Gate 3 block-order eval — 2026-07-18, tesseract 5.4.0.20240606, image=de_01

Stage 04 block structure graded DIRECTLY against the per-subpage block-order GT (`gt/de_01.blocks.json`): segmentation, type, caption<->figure grouping, and linear order. Owner priority: segmentation/type/grouping OUTRANK exact order (tau is secondary). Tau is over TEXT blocks only (figures excluded from BOTH the Stage-04 and Tesseract-native arms, so the two arms compare the same block set); figures match by GT-bbox overlap. Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.

| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | grouping | det blocks | misses |
|---|---|---|---|---|---|---|---|
| left.png | 4/4 (100%) | 4/4 (100%) | +1.00 | +1.00 (n=2) | — | 7 | — |
| right.png | 8/8 (100%) | 8/8 (100%) | +1.00 | +1.00 (n=6) | — | 8 | — |

**Segmentation** 12/12 GT blocks matched. **Type** 12/12 matched blocks correctly typed. **Grouping** 0/0 captions associate to their partner figure (0/0 also typed 'caption'); but only 0/0 on a subpage with >=2 figures (the rest are single-figure: association POSSIBLE, not discriminated).

**Figura-NN parser arm** (`pipeline.caption_parser`, shown ALONGSIDE the detector-only numbers above — improvement is measured, not asserted). The parser re-types a paragraph/other block as `caption` iff its OCR text starts with a figure keyword+number (`Figura NN`, optional directional prefix); it never demotes a block or touches figures.
- **Caption typing:** detector 0/0 vs **parser 0/0** captions typed `caption` (0 paragraph blocks promoted). **Type accuracy over matched blocks:** detector 12/12 vs **parser 12/12**.
- **Pairing by number:** figure corner labels recovered from pixels = 0 → number-keyed C→F pairs credited = 0/0 (bbox-matched, manually verified). Figure numbers do NOT survive OCR here (figure blocks empty), so the number-keyed C→F pairing has no figure-side signal — the caption side is typed+numbered but pairing stays detector-under-segmentation-limited (honest scope, see caption_parser docstring).

### Finding 3 (symptom 2) — within-column reading order fix (Stage 04 v0.2.0), 2026-07-18

Real-capture Finding 3 symptom 2: on the German via-ferrata spread `de_01`, the
right-page instruction column was emitted **fully reversed** (Route → Zustieg →
Anreise instead of Anreise → Zustieg → Route). Root cause: both XY-cuts are
defeated (the top photo spans both columns → no vertical cut; the tall English
translation block bridges the mid-page → no horizontal cut), so every block
falls into the `_reading_rows` tie-break. There the tall English block
transitively swallowed the German column into one "row", which was then
**x-sorted** — and the German paragraphs' ragged left margins grow downward, so
x-sort emitted them bottom-to-top. Fix: `_reading_rows` now sub-clusters each row
into x-COLUMNS (`_separators` on the x-intervals) and reads each column
top-to-bottom, left-to-right across columns.

New block-order GT `testset/gt/de_01.blocks.json` (proposed-from-photo, NOT
owner-validated — order objectively fixed by the German text flow), graded by
`tools/layout_order_eval`:

| de_01 right.png | seg recall | type acc | tau (Stage04) | tau (Tess-native) |
|---|---|---|---|---|
| before | 8/8 | 8/8 | **+0.60** | +1.00 |
| after  | 8/8 | 8/8 | **+1.00** | +1.00 |

The German column goes from partially-reversed to correct. The Tesseract-native
order was already +1.00, so Stage 04's fallback had been **degrading an order
Tesseract got right** — the fix removes that self-inflicted regression. Left
subpage tau +1.00 unchanged (prose was already ordered; non-regression on the
same page). Non-regression: `it_geo_04..07` block-order taus **byte-identical**
before/after (those fixtures get clean cuts and never enter the changed
fallback); `split_eval` 15/15; full suite 218 green (incl. a new
`_reading_rows` bridged-column regression test).

Two honest caveats. (a) The fix rescues a column bridged by a *horizontally
disjoint* neighbour (de_01's English column at x≥1563 splits cleanly from German
x≤1542); a bridge that also overlaps the column in x still falls to the flat
x-sort — unfixed, no fixture yet. (b) **Latent testset bug (not Finding 3, for a
follow-up):** `it_geo_04..07` list their `.blocks.json` in the manifest `gt_file`
column, but `gate1_harness`/`dewarp_ab` read `gt_file` as verbatim *text* WER GT
with no `.txt` guard — so those rows compute a bogus WER against JSON. de_01 was
deliberately left with an empty `gt_file` to avoid joining that; the it_geo rows
still need either a `.txt`-guard in the harnesses or the `gt_file` column cleared.

Symptom 1 (icon sidebar OCRs to junk, lands early) is **deferred** — it is a
content-*typing* issue (in a climbing guide that difficulty/time/GPS panel is
high-value structured info, not junk to drop), so rendering it as a structured
info-box is a real feature and an owner call, not an ordering bug. Symptom 3 (a
Bulgarian paragraph swap) was the pre-split Taleb spread's cross-gutter scramble,
already resolved by Finding 2; `bg_01` reads cleanly post-split.


## Cross-engine disagreement trigger — 2026-07-18, EasyOCR 1.7.2 second opinion (bg_01)

Built the Stage 05 EasyOCR second opinion that sets `Word.engine_disagree` — the
CLAUDE.md non-negotiable *second, independent* uncertainty trigger, until now a
wired always-`False` seam. Measuring it on real Cyrillic **overturned the naive
design and reframed the feature**; recording both the finding and the reframing.

**Finding: a raw cross-engine token-diff has ~0 precision on Cyrillic.** The first
implementation flagged a Tesseract word whenever EasyOCR's line-region text
disagreed (token-sequence diff, region-conf gated, replace-opcodes only). On
`bg_01` it flagged **89/763 words (11.7%)** — of which 78 were high-confidence,
manifestly-correct Bulgarian words (`само`, `които`, `социалист`, `население`).
Precision ≈ 0; on a clean page the true number of confident Tesseract misreads is
~0. Direct cause (per-region alignment dumps):

- **Cyrillic↔Latin homoglyphs** dominate — EasyOCR (`[bg,en]`) freely emits Latin
  lookalikes for Cyrillic: `се`→`ce`, `а`→`a`, `е`→`e`, `и`→`h`. Tesseract-`bul`
  reads them correctly. Casefolding doesn't unify them, so `се`≠`ce`.
- **EasyOCR's own misreads** — `които`→`конто`, `социалист`→`соцналист` (и→н).
- **Tokenization boundaries** — `само за` (2 words) vs `самоза` (1); one `replace`
  opcode then flags *both* correct words.

The premise "disagreement ⇒ Tesseract may be wrong" is **asymmetric on Cyrillic**:
EasyOCR is the *noisier* reader there, so raw disagreement surfaces EasyOCR's
errors, not Tesseract's. And edit distance can't separate a real 1-char Tesseract
misread (`Chapmarked`→`Chopmarked`) from 1-char homoglyph noise (`се`→`ce`) — both
are single substitutions.

**Fix: a dictionary tiebreaker.** Flag a Tesseract word iff

    norm(T) ∉ lexicon   AND   EasyOCR nominated a norm(E) ∈ lexicon

i.e. flag only a Tesseract **non-word** that EasyOCR replaced with a **valid**
word. This single filter subsumes homoglyph-folding *and* join-tolerance (`се` is
a valid word → never flagged, whatever EasyOCR read), and its clean-page
null-behavior falls out for free (only non-dictionary words are even eligible).
Measured on `bg_01` with a **proxy lexicon = this page's own 382 ground-truth
tokens** (a smoke-test stand-in, NOT a production lexicon — see the caveat below):

| bg_01 (763 words) | raw token-diff | + dictionary gate (proxy) |
|---|---|---|
| words flagged `engine_disagree` | **89 (11.7%)** | **7 (0.9%)** |
| genuine Tesseract misreads among them | 2 | 2 |
| high-conf correct words wrongly flagged | 78 | 0 |

Net-vs-confidence impact (Stage 06, threshold 75): the 7 add only **2 net-new
flags (+0.26%)** over the confidence rule — `касалница`→`касапница` @92 and
`Делеагач`→`Дедеагач` @93, both confident misreads the confidence rule alone
keeps. The other 5 were already low-confidence.

**⚠️ These numbers are PROXY-OPTIMISTIC — pending re-measurement on a real
lexicon.** The proxy dict is bg_01's own ground truth, so *every* correct word on
the page is in it by construction. That is exactly why the homoglyph FPs collapse
(`се`, `само`, `които` are common words → in any real lexicon too, so **that part
generalizes** and is the solid result). But it also inflates the catches:

- Only `касапница` is **lexicon-robust** (a common noun any Bulgarian wordlist
  has). `Делеагач`→`дедеагач` fires **only because the proxy contains the place
  name** — a general/frequency wordlist won't have `дедеагач`, so EasyOCR's
  nomination fails the `E∈lex` test and **that catch is LOST**. So on a real
  lexicon expect ~1 net-new catch here, not 2.
- **The gate is structurally weakest on proper nouns** — which *dominate* this
  content (Гюмурджина, Балъкьой, Ортакьой, Караагач, Дедеагач) and are the
  *highest OCR-error-risk* tokens. The blind spot `norm(T)∉lex ∧ norm(E)∉lex`
  (both non-words → no flag; recall traded for precision, correct when raw
  precision ≈ 0) therefore lands HARD in this domain: a mangled place name whose
  correct form isn't in a plain wordlist is a silent miss.

**Reader-language finding (`langs`).** The whole homoglyph FP class
(`се`→`ce`, `а`→`a`, `и`→`h`) is an artifact of the EasyOCR reader `langs:[bg,en]`
— the English pack is what lets it emit Latin. Confirmed: a `[bg]`-only reader
emits **0 Latin characters** on bg_01. BUT `[bg]`-only does NOT remove the lexicon
dependency — its raw diff still flags ~9.8% (tokenization/segmentation drift like
`само за`↔`самоза` remains), and *under the dict gate the output is identical*
(`[bg]` and `[bg,en]` both give the same 4 flags on left.png, because the gate
already neutralizes the homoglyphs via `се∈lex`). So the reader choice is a wash
under the gate; config keeps `[bg,en]` (helps read genuinely-Latin foreign names).

**Honest reframing (owner-visible).** With the dictionary gate the trigger is
effectively an **"EasyOCR-nominated dictionary check"**, not a bare cross-engine
disagreement. It still earns EasyOCR its place — far more precise than a plain
spellcheck (which flags every proper noun / abbreviation); requiring an
independent engine to produce a *valid alternative* is what buys the precision.
But it IS a reframing of the raw non-negotiable, surfaced here rather than shipped
silently.

**OWNER DEPENDENCY — a per-language lexicon (with a caveat on WHAT KIND).** The
gate needs a lexicon, which does **not** ship in the repo — the same dependency
the Stage 08 de-hyphenation seam already waits on (`join_hyphen(..., dictionary)`
is always passed `None`). So the trigger is shipped **inert**, mirroring the repo's
seam pattern: the mechanism is built + unit-tested (15 tests), wired through
`config.engines.easyocr.lexicon` (`models/lexicons/<lang>.txt`, gitignored), and
Stage 05 does **not** even load EasyOCR when no lexicon is present (its pass would
flag nothing — wasted GPU). Supplying a lexicon activates BOTH this trigger and
de-hyphenation.

> **Not just any wordlist.** A plain frequency/dictionary wordlist activates the
> common-word precision win but, per the proxy analysis above, will NOT catch
> proper-noun misreads (names/places absent from a general lexicon) — precisely
> the high-error-risk tokens in this material. For real coverage the lexicon wants
> **gazetteer / proper-noun breadth** (place + person names for the corpus), not
> only common vocabulary. If only a plain wordlist is available, ship it — but
> expect proper-noun errors to remain silent misses, and re-measure the real
> flag numbers (the 89→7 / +2 above are proxy-optimistic).

Verified end-to-end on `bg_01`: with a proxy lexicon dropped into the seam the
live CLI produces the 7 flags above and Stage 06 reports the trigger LIVE; with
the lexicon removed it produces 0 and reports inert.

Full suite 158 green. Files: `pipeline/second_opinion.py` (+
`test_second_opinion.py`), `Word.engine_disagree`, Stage 05 wiring, Stage 06
OR-in + LIVE/inert reporting, and a Stage 08 test proving a disagreement-flagged
confident word clears through the SAME per-word `flag_visible`/edit path as a
confidence flag (no separate un-clearable marker).

### Addendum — 2026-07-18, honest re-measurement on a GENERAL lexicon + a bug fix

Followed up the "PROXY-OPTIMISTIC" caveat above: sourced a real, **non-GT-derived**
Bulgarian wordlist and re-measured `bg_01`. Lexicon = **FrequencyWords `bg_full`**
(hermitdave, MIT / OPUS-OpenSubtitles, CC) — 1.2M raw rows; the count≥1 tail is
subtitle noise (`безопстно`, `педставлението`, `коло-ните`), so a frequency cut
(≥5 → 332k words) trims it. Truth for TP/FP classification stays the page's GT
(this is **non-circular**: the lexicon is a general list, the GT is only the
grader).

**Bug found by the real lexicon (now fixed): a multi-token `replace` let a valid
EasyOCR word vouch for a wrong neighbor.** The proxy could never surface it (its
tiny 382-word vocab rarely produced multi-token replaces with an in-dict token).
On the general lexicon `bg_01` produced a **false flag on the correct word
`помашки`**:

```
TESS: помашки села      (both CORRECT — "Pomak villages")
EASY: помошки село       (both EasyOCR misreads)
one 2↔2 replace:  T[помашки, села] ↔ E[помошки, село]
old gate: any(e∈dict) → 'село'∈dict → True → flag T-nonwords → 'помашки' flagged ✗
```
`село` is the counterpart of `села`, **not** of `помашки` (whose true counterpart
`помошки` is itself garbage). The `any(e in dict)` slot test measured the wrong
thing. **Fix:** the tiebreaker now fires **only on 1↔1 replaces**, where "EasyOCR
nominated a valid word in place of *this exact* token" is actually defined. Skips
multi-token slots entirely (accepted recall loss on multi-token misreads — the
confidence trigger stays the net; no real multi-token TP was observed here — the
one dropped, `Иб5ит`, was footnote-punctuation mash). Regression-tested
(`test_multitoken_replace_does_not_let_a_valid_word_vouch_for_a_neighbor`).

**Honest numbers — general lexicon, after the fix** (stable across cutoffs ≥2…≥20,
so not a tuning artifact):

| bg_01 | proxy (GT-as-lexicon) | general freq lexicon (honest) |
|---|---|---|
| flags | 6 | **1** |
| TP (genuine misread, T≠GT) | — | **1** (`касалница`→`касапница`) |
| FP (correct word flagged) | — | **0** |
| precision | — | **1/1** |

The one surviving catch is **lexicon-robust**: `касапница` has **count 478** in
the frequency list (a solidly frequent common noun) — this **retracts** an
intermediate claim that it survived only via a hyphen-spelled artifact row (that
was a spot-check bug reading the file's last/lowest-frequency entry).

**⚠️ 1/1 is ONE flag on ONE page — the fix certifies the ALGORITHM, not the
lexicon.** A 330k-word lexicon still false-flags any rare-real-word or proper noun
whenever `norm(T)∉dict` and an aligned `norm(E)∈dict`; bg_01 is far too thin to
bound that rate. This is **not** an activation green-light.

**Sourcing answer (this was the actual question): a general frequency list alone
is INSUFFICIENT — now measured, not assumed.** Every place name in `bg_01` is
**absent** from `bg_full` at any frequency: `Дедеагач`, `Гюмурджина`,
`Дуганхисар` → `ABSENT`. Proper nouns dominate this corpus and are the
highest-error-risk tokens, so the blind spot lands hard exactly here. The
proxy's `Делеагач`→`Дедеагач` catch is **confirmed lost** on the general list.
Therefore:

- **GeoNames-BG (CC-BY) gazetteer overlay is now *measurably* justified** — it
  carries Bulgarian toponyms (the missing `Дедеагач`-class words) — rather than
  assumed. This is the delta the prior advisor said would decide the question.
- A **morphologically-complete base** (Hunspell `bg_BG` surface forms) is worth
  weighing against the frequency list for rare-valid-word coverage (would also
  have carried `помашки`, removing that word from the blind spot).

**Scope note / owner decision pending.** "Look into sourcing it" is answered:
the freq-list base is sourced and works, a real precision bug was found+fixed, and
proper-noun coverage measurably needs a gazetteer. The full build — a reproducible
4-language `tools/setup_lexicons.py` (mirroring `setup_tessdata`) + GeoNames
overlay + possible Hunspell base — is a real investment and is **held for owner
greenlight** rather than silently expanded into. The disagreement seam remains
inert (no lexicon committed; `models/` is gitignored) until that build lands.

Full suite **198 green** (17 in `test_second_opinion.py`, +2 for the 1↔1 fix).

### Addendum — 2026-07-18, owner greenlit the build: Hunspell lexicon shipped (runtime spylls)

Owner decision above resolved: **"build it — hunspell."** The lexicon
infrastructure is now built (`tools/setup_lexicons.py`), the gate consumes a real
Hunspell dictionary, and it was re-measured on bg_01 through the real code path.

**Mechanism — runtime spylls lookup, not offline expansion (empirically forced).**
The plan was to expand Hunspell to a flat wordlist. Verified on this box: no
`unmunch`/`hunspell` CLI, and `spylls` (pure-Python Hunspell, pip) exposes only
`.lookup()` (surface-form → valid?), **not** surface-form enumeration — it gives
stems + affix tables, i.e. the raw materials to *reimplement* unmunch (lossy,
over-generating, and German compounds are generative → not enumerable at all). So
we check validity at runtime instead: `HunspellLexicon.__contains__` (in
`second_opinion.py`) calls `spylls .lookup()`. Because it is a `__contains__`
drop-in for the old `set[str]`, **`find_disagreements` and its tests are unchanged**
— the gate still just does `tok in dictionary`. `spylls` is a lazy runtime dep
(imported only when a lexicon is configured); `config.yaml` lexicon paths now point
at `<lang>.dic`.

**`tools/setup_lexicons.py`** (mirrors `setup_tessdata`) downloads the four
LibreOffice Hunspell pairs — **SHA-pinned** `da8a7e7` — into gitignored
`models/lexicons/`, and for Bulgarian builds a **GeoNames** gazetteer overlay
(`bg.geo.txt`, CC-BY, 11 014 Cyrillic place-name tokens) unioned onto the Hunspell
base. Post-download sanity confirms morphology is live, incl. the inflected
`помашки`=True (bg) and `Häuser`=True (de).

**The Hunspell win, and the voucher guard it forced.** `помашки` (an inflected
plural the frequency list lacked) validates **morphologically without being
listed** — the whole reason for choosing Hunspell. But the real dictionary
introduced a new leak class: a **single valid letter** can vouch. Measured on
bg_01, EasyOCR's bare `к` (valid in Hunspell, never in a subtitle frequency list)
vouched to flag Tesseract's garble `кК.),`. Fix (deliberate, not deferred): the
voucher `e_tok` must be **≥2 chars**; regression-tested; all 17→18 gate tests green.

**Honest bg_01 re-measurement (real `load_lexicon` → `HunspellLexicon` path; GT
used only to classify TP/FP, non-circular):**

| lexicon | flags | TP | FP | precision |
|---|---|---|---|---|
| naive raw token-diff (no dict) | 89 | — | — | ≈ 0 |
| general frequency list (prior addendum) | 1 | 1 | 0 | 1.00 |
| **Hunspell bg_BG + GeoNames-BG (this build)** | **1** | **1** | **0** | **1.00** |

The one flag is the robust `касалница`→`касапница` л/п misread. The gate also
**correctly did NOT flag `караагач`** (Tesseract right; EasyOCR's `каразгач`
wrong — the dictionary protected the correct word), a clean demonstration the
freq-list measurement could not show.

⚠️ **Do not oversell: on this clean page Hunspell does NOT measurably beat the
frequency list** — both are 1 flag / 0 FP. The `помашки` over-flag was already
killed by the 1↔1 fix, not by Hunspell coverage, so nothing on bg_01 exercises the
coverage advantage. The Hunspell win is **principled** (inflected real words
validate → fewer over-flags *in principle*); one thin, clean page cannot
demonstrate it, same humility as before.

**Proper-noun coverage — partially closed, honestly.** The overlay closes the
*modern*-Bulgaria toponym gap (София/Пловдив/Хасково/Кърджали all present). But the
**Aegean-Thrace exonyms this refugee-history corpus is dense with are only
partially in GeoNames at all**: `Дедеагач` exists solely as a Cyrillic *altname*
under the **GR** dump (Alexandroupoli); `Гюмурджина` (Komotini) and `Дуганхисар`
are **absent from GeoNames entirely**, even as altnames. So `--geo-countries
BG,GR,TR` buys 1 of 3; the other 2 no gazetteer will supply. Default stays BG
(not silently widened); the knob makes the finding actionable.

**Reproducibility caveat.** LibreOffice dicts are SHA-pinned (bit-reproducible);
the GeoNames dumps are a **rolling, unversioned** file (GeoNames tags no releases),
so the overlay may drift between rebuilds. Noted in `setup_lexicons.py`.

**Activated path verified end-to-end (GPU).** Ran the real
`stage05_ocr jobs/bg_01/page_001 --lang bul` — never exercised before (the 254
tests only pass `set`/`None`; the measurement called `find_disagreements`
directly). Confirmed: `HunspellLexicon` loads, `run_second` flips True, live
EasyOCR runs, `meta.second_opinion.lexicon_words`=89 251 (`__len__`), warning
f-strings render, and exactly 1 `engine_disagree` (`касалница`) lands in ocr.json.

**Status.** The seam is now **activatable locally** (`python -m tools.setup_lexicons`)
and still **ships inert** (`models/` gitignored — a fresh clone has no lexicon →
`load_lexicon` returns None → gate flags nothing). Activating it also feeds the
Stage 08 de-hyphenation rule (same dependency). Full suite **255 green**
(18 in `test_second_opinion.py`).

---

## 2026-08-09 — Caption↔figure GROUPING lands in production (Stage 07 + Stage 08)

**The owner's #1 layout priority, finally moving real output.** `caption_parser`
(Task #4, 2026-07-03) and `figure_label` (Task #2, 2026-07-03) were both built
and measured — caption typing 0/6→6/6, `pair_by_number` 0→2 on it_geo_06 — but a
grep this session found neither module was imported by **any pipeline stage**:
only by `tools/layout_order_eval` and their own tests. Production grouping was
adjacency (`stage08_render`: a FIGURE followed immediately by a CAPTION), which
provably cannot express it_geo_06, where the four captions form a stack on the
far side of the subpage and their order does not track figure position. So every
measured win to date moved **zero** of the re-typeset document.

New `pipeline/figure_grouping.py` is the single decision point, called by **both**
Stage 07 (production) and the eval (measurement) — so the numbers below grade the
code the pipeline runs, not a parallel arm. Schema commit `66b84d6` added
`Block.caption_number / figure_number / figure_ref / pair_source / type_promoted`
(document schema 1.0→1.1, purely additive; `figure_ref` is a page-scoped
`BlockRef`, not a bare id, because it_geo_04's Fig.21 panorama is already split
across two DocPages by the gutter cut).

### The policy: number first, geometry guarded, ABSTAIN by default

The bar is **zero wrong pairs, not N pairs** — a caption printed under the wrong
photo is worse output than a caption standing alone (the same invariant
`figure_label` holds for its digit reads). Arms:

1. **Printed number** (authoritative) — caption "Figura 26" pairs to the figure
   whose in-photo corner label OCRs as 26, wherever it sits. This is what defeats
   the C26→F26 trap the it_geo_06 fixture was purpose-built around.
2. **Guarded geometry** (the ordinary book, which prints no corner labels) —
   requires ALL of: column overlap ≥0.50 of the narrower box, vertical gap ≤0.08
   of page height, mutual-nearest, an unambiguous runner-up (≥1.6× further), a
   non-empty caption, and **not nested inside the figure's box**; plus a
   **numbering-regime guard** — on a subpage where some figure number DID read, a
   caption that carries a printed number and found no numeric partner abstains
   rather than overrule the printed numbering.

Two guards were **forced by measurement, not designed up front**:

* **Containment (`_nest_frac`).** it_geo_06-right's L-shaped F29+F30 detection
  absorbed the C29 caption column (Phase B's caption ejection was never built), so
  C29's box sits **97% inside** the box the eval matches to GT F30, and the naive
  vertical gap scored that nesting as **0 = maximal adjacency** → `C29→F30`, a
  wrong pair. Reading containment as an ABSTAIN signal instead not only removed
  the wrong pair, it left C29's only remaining candidate as the figure genuinely
  above it → **C29→F29 and C30→F30, both correct**. A merge Phase B was supposed
  to fix is now survivable without fixing it.
* **Numbering-regime guard.** Probed directly: with it disabled and F25's label
  unreadable, C25 pairs geometrically to the top-right F26 plate — the exact
  mispairing the fixture traps. It is load-bearing, not defensive decoration.

### Measured — all five block-order fixtures, production code path

| fixture | pairs correct | **WRONG** | abstained | notes |
|---|---|---|---|---|
| it_geo_04 | 1/2 | **0** | 1 | B7→B6R by geometry (solo-case gap relaxation) |
| it_geo_05 | 0/2 | **0** | 1 | both captions are gutter-side columns |
| **it_geo_06** | **4/6** | **0** | 2 | 2 by number (incl. the C26 trap), 2 by geometry |
| it_geo_07 | 0/1 | **0** | 2 | GT partner D1 is undetected (IoU 0.000) |
| de_01 | 0/0 | **0** | 1 | no GT pairs |
| **total** | **5/11** | **0** | **7** | |

**it_geo_06 (the grouping fixture) goes 2/6 → 4/6 with zero wrong pairs.**
Caption typing is unchanged at 6/6 (type accuracy over matched blocks 8/14 →
**14/14**). The eval now also reports every emitted pair with a verdict, including
`UNGRADED` ones (a pair on a block the GT anchors no pair for) — 2 such pairs
exist on it_geo_07's diagram pages, surfaced rather than silently dropped.

### What abstains, and why it is not a defect

The 7 abstentions are 3 distinct causes, all honest:
* **it_geo_04-left / it_geo_05-right (2)** — the caption is a *gutter-side column*
  physically detached from its figure (x-overlap 0.04 and 0.00; gaps 1151px and
  1170px). No sound geometry recovers these; only the printed number can, and
  those figures carry no readable corner label. **Finding: in this Italian book
  the caption columns are not physically attached to their figures, so the number
  arm — not geometry — is the load-bearing one for this corpus.**
* **it_geo_06 C27/C28 (2)** — the numbering-regime guard, correctly declining to
  guess on the trap page.
* **it_geo_07 C31 + empty/edge cases (3)** — C31's GT partner D1 is genuinely
  undetected, so any pair would have been wrong.

### Verified on the production path, not just in the eval

Ran the real chain on `it_geo_06`: `run_all` 00→06 → `stage07_assemble` →
`stage08_render`. `document.json` (schema 1.1) carries `figure_ref`/`pair_source`
exactly as the eval measured (left: 2 by number; right: 2 by geometry), and the
rendered HTML puts **"Figura 25" inside Figure 25's `<figure>` and "Figura 26"
inside Figure 26's** — the trap defeated in the actual re-typeset output. 6
figures, 4 with grouped captions, 2 unpaired captions rendered standalone.

Two real bugs this run exposed, both fixed:
* **`_ocr_language` read `params.lang`; Stage 05 writes `params.language`** — so
  EVERY document assembled to date recorded `source_language="eng"` regardless of
  the OCR language. Pre-existing and independent of grouping, but it silently
  disabled the Italian caption keywords (0 captions promoted on the first real
  run). Now reads `language` with `lang` as fallback.
* **Unpaired captions emitted a bare `<figcaption>` outside any `<figure>`** —
  invalid HTML, and newly common because the pass deliberately abstains. Standalone
  captions now render as `<p class="caption">`.

### Honest limits

* **`document_order_gate4` is now PARTIALLY gradeable** (it was deferred as
  "ungradeable until figures are separable"). The rendered order on it_geo_06-left
  is F25,C25,F26,C26,F27,F28,C27,C28 against the GT's
  F25,C25,F26,C26,F27,C27,F28,C28 — the first four positions match exactly, and
  the whole residual gap is the two abstained captions. A document-order metric is
  still not written, and Stage 08 does not reorder ACROSS pages, so the
  cross-gutter half of that GT stays ungraded.
* **N is small and Italian.** The geometry knobs are fractions (not pixels) but are
  exercised on 5 spreads from 3 books; `geom_solo_max_gap_frac=0.25` in particular
  is justified by exactly one subpage (it_geo_04-right).
* **Unchanged open levers:** Phase B (right L-shape figure split + caption
  ejection) and a real digit text-detector for the 4 texture-swamped corner labels
  (F27/F28/F29/F30). Both would raise coverage above 4/6; neither is needed to make
  grouping *real*, which is what was missing.
* **Editor UI for correcting a wrong pair is deliberately NOT built.**
  `pair_source` is stored as provenance so a later pass can surface a geometric
  guess for review while leaving a number-keyed pair alone.

Full suite **284 green** (was 255): +25 `test_figure_grouping.py`, +4 render
grouping/non-regression tests.

### Follow-ups closed the same day (advisor review)

* **Editing must not unpair the document.** Grouping only means anything if it
  survives the editor, and `test_editor.py` predated these fields, so a green suite
  could not have detected a drop. Verified on the real path: the SPA PUTs the whole
  fetched document back (`JSON.stringify(state.doc)`), and a word edit in an
  unrelated block provably preserves `figure_ref`/`pair_source`/`caption_number`/
  `figure_number`/`type_promoted` through the HTTP round-trip. The editor fixture now
  carries a paired figure+caption so every editor test exercises a grouped document,
  and a pristine grouped document still reads as un-edited — an automatic caption
  promotion does not trip assemble's clobber guard (re-ran `stage07_assemble`
  WITHOUT `--force` over the grouped job: accepted, as intended).
* **Cost.** Grouping is the expensive part of assemble now: warm, a 2-subpage
  it_geo_06 spread takes **~12ms without** it and **~3–12s with** (high variance;
  Windows Tesseract process startup × 4 PSMs per localizing figure). Mitigated where
  it buys nothing — the number arm needs BOTH sides, so corner-label OCR is skipped
  entirely on a subpage where no caption carries a printed number (that subpage then
  records no `figure_number` provenance either, stated rather than hidden). Pages
  like it_geo_06, whose captions ARE numbered, still pay it. Worth revisiting before
  a long book runs through the server, which calls assemble in-process.

Suite **288 green**.

## 2026-08-09 — Figure separation Phase B: the L-shape split + caption ejection

Closes the output defect recorded in `docs/FIGURE_SEPARATION_SCOPE.md` §5 the same
day it was measured: on it_geo_06-right the detector's merged figure box swallowed
caption C29, so the rendered deliverable printed **Figura 29 twice** — once as
reflowed `<figcaption>` text, once as PIXELS baked into the Figura 30 `<figure>`
image. Pairing could never fix it; it is a crop-boundary problem.

Phase A cut figures only at full-**width** page-background seams. Phase B adds the
second axis (`_cut_figure(..., axis)`), runs **H-then-V at depth 2** — not general
recursion — and then **ejects** any sub-box that a non-figure detection covers by
`fig_eject_text_cover` (0.60).

### The two numbers that discriminate (it_geo_06-right, real pixels)

| measurement | Phase A | Phase B |
|---|---|---|
| **C29 caption's coverage BY a figure box** (the defect) | **0.967** | **0.000** |
| **F30 IoU vs GT** `636,1400 1072x800` (the metric) | **0.633** | **0.908** |
| F30's detected box | `154,1341 1554x842` | `640,1341 1068x842` |
| F29 IoU vs GT | 0.971 | 0.971 |

Both re-measured end-to-end in a **fresh job** (`phaseb_it06`, run_all → assemble →
render), not just in Stage 04 — `grouping_it06` was left alone so the human pairing
rulings from commit 90f1143 survive. At the document level, C29's `max coverage by a
figure` reads 0.967 in `grouping_it06` and 0.000 in `phaseb_it06`; the extracted F30
crops confirm it visually.

### Regression: 9 of 10 graded subpages byte-identical

`tools/layout_order_eval` over it_geo_04 / 05 / 06 / 07 / de_01, before vs after,
comparing seg-recall, type accuracy, tau, block count, misses and every pairing
counter: **identical on every subpage except it_geo_06-right.** Criterion 3.2 (zero
false-splits) holds, including on it_geo_06-**left**, which the Phase A scoping had
forgotten to list and which keeps all four figure boxes at IoU 0.974 / 0.928 / 0.919
/ 1.000.

### The false-split the guard exists to stop (measured, not hypothetical)

The first, unguarded implementation **did** false-split. On it_geo_05-left the single
full-page MAP `231,331 1806x2658` was sliced into two vertical strips and **GT F2
fell from IoU 1.000 to 0.702**. The eval reported this as an apparent *improvement*
(seg-recall 0.5 → 1.0) because one strip happened to contain enough of caption C2's
text to match its anchor — a reminder that a recall number can rise while the
segmentation gets worse.

Cause: **the two axes are not symmetric.** A stacked photo has no full-WIDTH cream
band inside it, which is what makes Phase A's full-span guard sound; but a diagram
drawn *on page background* legitimately has full-HEIGHT background columns. So the
V-cut carries an extra guard — **accepted only when it ejects a detector-confirmed
text column.** With it, it_geo_05 returns to identical. Residual and unfixed (no
fixture): a figure that both has an interior full-height background column and a text
detection overlapping one side would still be sliced.

### Honest cost: one pair lost, and it was right for the wrong reason

it_geo_06-right's recovered pairs go **4/6 → 3/6 (still 0 wrong)**: C30→F30 is no
longer emitted. The geometry arm requires a shared column, and C30 (`154,2239
439x581`) shares neither column nor y-band with the true F30 (`636,1400 1072x800`) —
the caption is printed "**A lato**" (*to the side*). The old pair existed **only
because the figure box was wrong** and accidentally overlapped C30's column; and the
figure it pointed at rendered the *other* caption's text. The arm now abstains, which
is correct. The legitimate route back is corner-label OCR for the number 30 (§7), not
loosening the column guard.

Suite **303 green** (was 288): +5 `test_stage04_layout.py` — the L-shape split with
ejection, the it_geo_05 false-split regression in miniature (a diagram on page
background must survive intact), the band-with-no-absorbed-text refusal, the
`fig_vsplit=False` escape hatch, and the all-sub-boxes-are-text abstain.


## Figure-inclusive reading order — a metric for what the harness could not see (2026-08-09)

`tools/layout_order_eval` graded reading order over **TEXT blocks only**, in both
the Stage-04 and the Tesseract-native arm. That exclusion is deliberate and stays
(native emits no order for an imageless region, so including figures would compare
unequal block sets) — but its cost was that **figure order went entirely ungraded**.
FIGURE_SEPARATION_SCOPE.md §6 recorded the gap and §10 recorded the consequence:
Phase B corrected it_geo_06-right's figure order to GT and **no number moved**.

**New: `tau+figures`** — a third, Stage-04-only Kendall-tau over text blocks PLUS the
figures whose match is **position-honest** (matched by GT-bbox overlap). Figures in
GT files authored before figure bboxes (it_geo_04, de_01) are matched by reading-order
RANK — i-th GT figure to i-th detected figure — so those pairs are concordant *by
construction*; grading order off them is circular, and they are **excluded**, with
`n_fig_graded` printed so an all-text `+1.00` cannot pass as a figure-order result.
The graded sequence is printed GT-vs-Stage-04 next to the scalar.

### The differential that proves it grades the historical defect (real pixels)

Same image, same GT, the V-cut toggled with the new `--set fig_vsplit=false`:

| it_geo_06 right.png | tau (Stage04, text-only) | **tau+figures** | Stage-04 sequence |
|---|---|---|---|
| V-split ON (shipped Phase B) | +1.00 | **+1.00** | `F29, C29, F30, C30, P1, P2` = GT ✓ |
| V-split OFF | +1.00 | **+0.87** | `F29, **F30, C29**, C30, P1, P2` |

The text-only arm is **identical** across the two runs; the new arm separates them,
and the recovered sequence is exactly the one §10 recorded by hand. Non-circular: the
figures are matched to GT bboxes, and left.png's **entire** subpage record is identical
between the runs — verified by diffing the two `--json-out` dumps whole, not by reading
the printed row (the V-cut only ever fired on the right subpage). The pairing arm moves 4/6 → 3/6 as
already recorded — the honest cost of the correct box, not a new regression.

### What the metric found on its first run (a genuinely new, unfixed defect)

**it_geo_06-left is `+0.86`, not `+1.00`** — figure order is WRONG there and nothing
had ever said so:

- GT (column-major): `F25, F27, F28, F26, C25, C26, C27, C28`
- Stage 04:          `F25, **F26**, F27, F28, C25, ...`

The top-right plate F26 (`x1611 y253`) is emitted **second** instead of last: XY-Cut
peels it early because it starts high on the page, rather than after the left column's
stack. This is precisely the "verify post-split order is column-major" check §6 asked
for and could not perform. **Not fixed here** — a metric commit should not also change
the thing it measures. Filed for the next figure-order pass.

### Full sweep (all five block-order fixtures)

| image | subpage | seg recall | tau (text) | **tau+figures** |
|---|---|---|---|---|
| it_geo_06 | left | 8/8 | +1.00 | **+0.86** (figs=4/n=8) — F26 misplaced, above |
| it_geo_06 | right | 6/6 | +1.00 | **+1.00** (figs=2/n=6) ✓ |
| it_geo_07 | left | 15/17 | +0.96 | **+0.94** (figs=4/n=15) — D3 before T2mid |
| it_geo_07 | right | 13/13 | +1.00 | **+1.00** (figs=4/n=13) ✓ identical to GT |
| it_geo_05 | left | 1/2 | n/a | **n/a** (<2 matched blocks — C2 is the known MISS) |
| it_geo_05 | right | 5/5 | +1.00 | **+1.00** (figs=1/n=5) |
| it_geo_04 | both | 4/5, 4/4 | +1.00 | **n/a** (no gradeable figure — GT has no figure bbox) |
| de_01 | both | 4/4, 8/8 | +1.00 | **n/a** (no gradeable figure — GT has no figure bbox) |

it_geo_07-right is the real workout — 4 diagrams interleaved with 9 text blocks,
ordered perfectly. it_geo_04/de_01 print `n/a` rather than the `+1.00` they would
have scored if rank-matched figures had been let in.

### Two honest limits, stated not fixed

- **The graded set is the MATCHED blocks**, so a figure the detector loses (or
  false-splits until it no longer overlaps its GT box) leaves the set entirely: a
  segmentation regression makes this metric **quieter, not red**. Read it beside seg
  recall — the same trap as the Phase B recall number that hid the it_geo_05 map
  false-split. Pinned by a test.
- **It grades Stage 04's per-subpage `reading_order`**, where the §10 defect lived and
  where its fix landed. It does **not** prove Stage 07 assemble carries that order into
  `document.json`; that end of the chain is still a by-hand check.

Suite **310 green** (was 303): +7 in `tools/tests/test_layout_order_eval.py` — the §10
defect and its fix in miniature (text-only tau reads +1.00 on the broken order while
the new arm does not), the circular-rank refusal, the goes-quiet-on-a-lost-figure
pin, the <2-blocks n/a, and two `--set` coercion tests. That last pair is load-bearing:
`--set fig_vsplit=False` stored as the string `"False"` is **truthy**, so the A/B above
would have silently compared a run against itself and reported "the metric is blind".

## Column-major reading order behind a spanner — the defect `tau+figures` found (2026-08-09)

The figure-order metric's first run flagged **it_geo_06-left at `+0.86`**: the
top-right plate F26 was emitted **second** instead of last. That was filed unfixed
because a metric commit should not change the thing it measures. Fixed here.

**Cause (traced on the real post-split boxes, not assumed).** Recursive XY-Cut is
axis-order sensitive, and `xy_cut_order` cuts horizontally first. The page is two
columns — `F25,F27,F28` at x203..1561 and `F26,C25..C28` at x1595..2109, gutter 34px
— but the running head ends at **y246** and F26 starts at **y253**. That 7px gap is
under `xy_gap_frac`, so the first H-cut banded `{header, header2, F26, F25}`
together; inside that band the full-width header spans both columns, so the V-cut
could not fire either, and the band fell to the `_reading_rows` tie-break, which
emitted F25 then F26. The globally-valid column gutter was **never consulted**.

**Fix.** A `_column_split` pre-pass at each XY-Cut node (knob `xy_column_first`),
consulted **before** the H-cut: find an x position splitting the node into a left
group, a right group, and a small set of **bridges** that cross it; emit
bridges → left → right (or left → right → bridges when the bridges sit below).

### The four guards, and the fixture that put each one there

The first draft carried only the bridge-fraction and gap guards. It fixed
it_geo_06-left **and gave the +0.14 straight back on two other subpages** — the
measurement below is why the shipped version is narrower, and each guard is pinned
by a unit test built from that subpage's real box geometry.

| guard | fixture that demanded it | what went wrong without it |
|---|---|---|
| `>= 1` bridge | — (blast-radius claim) | with no bridge the plain V-cut already finds the same partition, so the pre-pass would only be flipping H-first row-major into column-major on nodes with **no** spanner — a case no fixture covers |
| each column has a **common x-core** (`min(x2) > max(x)`) | **it_geo_06-right** | geometrically a twin of the left subpage (spanning F29 over two side-by-side groups) but its GT order is **row-major**; the right-hand group is not a column — body paragraphs P1/P2 and P3 are x-disjoint. Forcing column-major moved F30 behind C30: `+1.00 → +0.87` |
| columns y-overlap `xy_column_yov_frac` of the **longer** span | **it_geo_05-right** | against the *shorter* span, a 292px caption at the page foot (C3) posed as a column parallel to an 881px text run, and C3 lost its GT slot ahead of P1: `+1.00 → +0.87` |
| bridges all ABOVE or all BELOW the columns | — | a spanner in the middle abstains rather than guessing where the columns restart |

The x-core guard is the interesting one: it says a *column* is a set of boxes
sharing one horizontal extent, and a group that splits into its own columns is a
**region**, which reads row-major. That is what lets it_geo_06's two subpages —
same page, opposite GT conventions — both come out right.

### Measured: one subpage moves, nine do not

`--set xy_column_first=false` reproduces the pre-fix arm. Both arms run on all five
block-order fixtures; the **whole `--json-out` dump** is diffed, not the printed row
(it_geo_04 and de_01 print `n/a` for `tau+figures`, so the dump is the only thing
that would catch an order change there).

| image | dump diff old vs new |
|---|---|
| it_geo_04 | **identical** |
| it_geo_05 | **identical** |
| it_geo_06 | differs — left.png only (below); right.png byte-identical |
| it_geo_07 | **identical** |
| de_01 | **identical** |

| it_geo_06 left.png | seg recall | type acc | tau (text) | tau (native) | **tau+figures** | grouping |
|---|---|---|---|---|---|---|
| before | 8/8 | 4/8 | +1.00 | +1.00 | **+0.86** | 2/6 assoc, 3/6 pairs, 0 wrong |
| after | 8/8 | 4/8 | +1.00 | +1.00 | **+1.00** | 2/6 assoc, 3/6 pairs, 0 wrong |

- GT:       `F25, F27, F28, F26, C25, C26, C27, C28`
- Stage 04: `F25, F27, F28, F26, C25, C26, C27, C28` ✓ identical

Matching is by anchor tokens (text) and GT-bbox IoU (figures), **neither of which
depends on emitted order**, so segmentation, type and every pairing number are
required to be unchanged — and are. The only fields that moved in the dump are
`order_all` and the block *indices* inside `matched` (same GT ids, same physical
boxes, renumbered by the new order). Worth restating: `tau+figures` goes **quiet,
not red**, when a figure drops out of the matched set, so seg recall being pinned
at 8/8 is load-bearing here, not decorative.

### Carried into the document, not just Stage 04

The metric grades Stage 04's per-subpage `reading_order`. Assembled a **fresh** job
`figorder_it06` (no `--force`, so the human pairing rulings in `grouping_it06` and
`phaseb_it06` survive) and read `document.json` directly:

```
page_001__left   ro2 figure y272 (F25)  ro3 figure y1091 (F27)
                 ro4 figure y1973 (F28) ro5 figure y253  (F26)  <- last, as GT
page_001__right  ro2 F29, ro3 C29, ro4 F30, ro5 C30, ro6..8 P1,P2,P3  (unchanged)
```

So the Gate-4 reflow now emits the top-right plate after the cliff column in the
actual deliverable.

### Honest limits

- **The above/below guard passes on it_geo_06-left by 7 pixels** (header y2=246 vs
  F26 y=253). One fixture exercises it; that margin is not a safety margin.
- **Three of the four guards are calibrated, not derived.** Each was added because a
  named subpage regressed without it — 10 graded subpages total. A sixth fixture
  could plausibly need a fifth guard, or contradict one of these.
- **it_geo_06's two subpages carry opposite GT conventions** (left column-major,
  right row-major) and the GT header declares only "spatial column-major". The
  x-core rule reconciles them, but it is a *reconstruction* of the author's intent
  from geometry, not a rule the GT states.
- Suite **314 green** (was 310): +4 in `pipeline/tests/test_stage04_layout.py` — the
  fix with its knob-off counterpart (so the A/B is provably real, not a run against
  itself), the two abstain regressions above built from real box geometry, and the
  no-bridge / mid-page-spanner declines.

### The two callers the fixture sweep does not reach (measured after review)

`xy_cut_order` is not Stage 04's alone. `stage05_ocr` re-ranks the real blocks
together with **synthetic orphan-WORD blocks**, and `tools/layout_ab.py` orders
blocks plus orphan word singletons — box populations where `n` is much larger and
"column" means something else, and which every number above misses because both
arms of the sweep enter through `layout_page`. Advisor flagged it; measured rather
than assumed.

- **Stage 05, five real job pages** (`figorder_it06`, `bg_01`, `dw_en_coins_01`,
  `realtest_de1_fixed`, `realtest_bg`), knob on vs off: block order **identical on
  all five**, and `_column_split` fired on **0 nodes** — once word-sized orphan
  boxes join the population the guards decline, which is the intended behaviour
  rather than luck.
- **`tools/layout_ab.py`** (the Gate-3 WER A/B), both arms: report **identical**.
  That is an aggregate-WER claim, though, so the run was repeated with every
  `xy_cut_order` call instrumented — its input boxes and the sequence it emits:
  **60 calls, 4 pre-pass fires, and exactly one call emits a different sequence** —
  the it_geo_06-left node this commit exists for. (A second call differs only in its
  *input*, being the same reordered blocks arriving at the cell-ordering step.) The
  two other fires — it_geo_05-left and one 5-box node — emit the sequence the plain
  H/V cut already gave. WER is unchanged because F26 is a figure and carries no
  words, so a figure moving among word-bearing blocks cannot move a word metric:
  another instance of the harness being quiet about a real order change, the same
  gap `tau+figures` was built to close.

## Corner-label OCR #2 — caption↔figure pairing 3/6 → 4/6, still 0 wrong — 2026-08-09

Owner's #1 priority. `docs/FIGURE_SEPARATION_SCOPE.md` §7 named corner-label OCR as
the *only* route to caption↔figure grouping (geometry provably mispairs C26), and
Phase A/B finally supplied its precondition: a tight per-figure box to hunt the
label in. This entry is that follow-up.

**Headline, from `tools/layout_order_eval` on real pixels — the same
`pipeline.figure_grouping` pass Stage 07 runs, not an eval-only arm:**

| fixture | corner labels read | GT pairs recovered | WRONG pairs |
|---|---|---|---|
| it_geo_06 | **2 → 4** | **3/6 → 4/6** | 0 → **0** |
| it_geo_04 | 0 → 0 | 1/2 → 1/2 | 0 → 0 |
| it_geo_05 | 0 → 0 | 0/2 → 0/2 | 0 → 0 |
| it_geo_07 | 0 → 0 | 0/1 → 0/1 | 0 → 0 |
| de_01 | 0 → 0 | 0/0 → 0/0 | 0 → 0 |

On all four non-target fixtures the corner-label count, pairs, wrong pairs and
per-caption abstain reasons are unchanged from their pre-change baselines, each
re-measured by `git stash` rather than assumed. (That is the comparison actually
run — not a full report diff. It is decisive for these four because
`read_figure_numbers` returns `{}` on both sides there, so the grouping pass has
nothing to diverge on.) Beyond the count, the **provenance**
improved: all four it_geo_06 pairs now come from the printed number, where before
one (C29→F29) was a geometry guess. Verified carried into the deliverable — a
**fresh** job `cornerocr_it06` (no `--force`, so the human pairing rulings in
`grouping_it06`/`phaseb_it06` survive) has C25→F25, C26→F26 (the trap), C27→F27
and C29→F29 in `document.json`, each with `pair_source: number`.

### The old diagnosis was wrong, and wrong in the believable direction

`figure_label`'s docstring had recorded, since 2026-07-03, that the four
texture-swamped labels were a glyph-isolation limit needing "a real text detector
(EAST/MSER/CNN)". Two of the four were not that at all:

- **F27 was localized correctly the whole time.** The debug overlay's winning
  cluster sits exactly on the "27". What failed was the OCR *input*: the module
  painted the localizer's own CC mask, and its 7×7 CLOSE fused the two digits into
  one blob that read as nothing on all four PSMs. Re-cropping that same
  localization from the ORIGINAL pixels reads "27" on 4/4.
- **F29 was a filter rejection, and the filter was the wrong shape.** Its digits
  measured 50px against a 62px floor. That floor is `glyph_h_min_frac` × the
  *search region* height — i.e. it scales with the FIGURE box — while a printed
  corner label's cap-height is a constant of the BOOK. Measured across the six
  figures: 25, 26, 27, 30, 30, 37px = **0.83%–1.23% of page height**, tightly
  clustered, against a region-relative floor wandering over 0.62%–1.03%. F29 is
  simply the tallest figure, so it set itself the highest bar for an
  identically-sized label.

So: `read_corner_label` takes an optional `page_h` and switches to a page-relative
glyph band; and OCR input is re-cropped from the original figure pixels, upscaled
to a fixed `target_glyph_px`, and binarized there.

### Two negative results that shaped the change

- **A "best of both" hybrid is worse, and dangerously so.** Binarizing the re-crop
  but keeping only the components the localizer's mask already found sounds
  strictly safer. Measured: it clipped F29's "9" into a "3" and returned **23** —
  turning a clean miss into a plausible wrong number, the one failure this module
  exists to prevent. The mask is for localization only. Pinned by comment, not
  just memory.
- **The re-crop alone breaks the "0 wrong" invariant on it_geo_07.** Baseline read
  0 numbers there; with the re-crop it read **7** off a geological cross-section's
  brick hatching. it_geo_07's diagrams are ink on pale PAGE BACKGROUND, which
  inverts the module's founding premise (bright glyph, darker ground): the bright
  side of the threshold is the page, not a glyph. That is not cosmetic — a
  fabricated number puts the subpage into "numbered regime", which *suppresses*
  the geometry arm for every numbered caption on it.
  **The guard, and why it is a measurement rather than a knob:** the bright side's
  share of the re-crop separates the two classes with a wide gap — real labels
  **0.10–0.38**, label-free diagrams **0.82–0.86** — so `max_glyph_cover = 0.55`
  sits in open space, not on a boundary. Contrast would NOT have worked: F30's
  fg−bg delta is 61, inside the diagrams' 54–73.

### Honest limits

- **F28 and F30 still read `None`, deliberately.** F28's digits merge into bright
  rock speckle (best read is a lone "38", which the acceptance rule rejects); F30's
  light-grey digits on light rubble produce a top-hat mask that is pure noise, so
  no localization is possible at all. These two ARE the "needs a real text
  detector" cases the old note described — the note was just wrong about F27/F29
  being in the same club. 5/6 or 6/6 was not worth a fabricated number.
- **C28 and C30 therefore stay unpaired**, correctly: their captions carry printed
  numbers on a subpage that prints figure numbers, so the numbering-regime guard
  abstains rather than letting geometry overrule the printed numbering.
- **The page-relative band is calibrated on ONE book.** 0.4%–2.5% of page height is
  ~2× margin either side of a spread measured on six figures of a single fixture.
  A book printing conspicuously larger or smaller plate numbers would need it
  re-measured, and `max_glyph_cover` likewise rests on two fixtures (one with
  labels, one without).
- **`page_h` is optional and the fallback is the old, worse band.** Callers that do
  not pass it silently keep the figure-relative behaviour. `figure_grouping` passes
  it; anything new should too.
- Suite **314 → 318** (+4 in `pipeline/tests/test_figure_label.py`, counts measured
  by `--collect-only` on both sides, not inferred): the tall-figure band defect
  reproduced synthetically — same-size mark, taller figure, found only with
  `page_h` — plus its ceiling counterpart, and the polarity guard with an
  inverted-tone positive control. The band test also asserts the coordinate
  round-trip, since `_locate_label` now returns the box in the caller's own space.


## Corner-label OCR, round 3 — F28 recovered, F30 measured to a ceiling — 2026-08-10

Third pass over `pipeline/figure_label.py`, and the third time the previous note's
diagnosis was wrong. Round 1 called every textured photo hopeless; round 2
disproved that for F27/F29 and then wrote off **F28 and F30** as "the genuine
needs-a-real-text-detector cases". Neither of them is. They are not even the same
kind of failure, and the difference is the whole result.

**Headline: 4/6 → 5/6 numbers, pairs 4/6 → 5/6, still 0 WRONG.**

`python -m tools.layout_order_eval --image it_geo_06`:
`figure corner labels recovered from pixels = 5; 5/6 GT pairs recovered, 0 WRONG;
1 caption abstained` (C30, correctly). Segmentation 14/14, parser typing 6/6,
tau +1.00 / tau+figures +1.00 on both subpages — all unchanged.

### Why the old diagnosis kept being wrong, and how it was settled

Both prior errors came from reading the localizer's *output* instead of its
internals. So this round started by dumping **every connected component in the
corner region before any filter**, with the filter that rejected it, against a
hand-measured true label box. That one instrument split the two figures apart
immediately:

| | pre-filter CC on the true label? | verdict |
|---|---|---|
| F28 | yes — a single CC `(1280,778) 44x37`, **passes every filter** | localization arithmetic bug |
| F30 | **none at all** — the mask is blind there | not a localization problem either (see below) |

- **F28 was never texture.** The top-hat mask's CLOSE welds a speckle onto the
  digits, giving one CC of `44x37` where the label is `38x27`. Both the crop
  padding and the OCR upscale scale by `glyph_h`, so a 37px "glyph" mis-frames and
  **under-zooms by ~30% the very pixels being read** — which is how a
  human-legible "28" came out as "38". A local Otsu re-measure inside the box's
  neighbourhood (`_refine_box`) returns `39x29` against the hand-measured `38x27`.
- **F30 is a recognizer ceiling, and the "no localization is possible" claim was
  read off the wrong pixels.** The round-2 note inspected a debug zoom that showed
  mid-figure rubble, not the corner. MSER on the raw Value channel localizes the
  label fine (IoU 0.45 against the hand box). But **given the hand-measured
  perfect box**, a 432-read Tesseract knob sweep produces **no `30` even once** —
  10 digit reads in total, not one of them 2-digit — and EasyOCR returns nothing
  on 4/4 framings. A better detector cannot rescue what no recognizer can read.
  **This lead is closed, not open.** MSER was therefore dropped from the shipped
  code: it moved no number, and it costs a 141-candidate noise surface.

### What was built

A **second-opinion arm** that runs only after the strict rule returns `None`, so
it can turn a miss into a number but can never revisit one already accepted — the
four labels that already worked are byte-identical, by construction rather than by
measurement (and the ship gate checks it anyway).

1. `_refine_box` — local-Otsu re-measure of the located box (above).
2. A **re-crop sweep** (2 paddings x 3 upscales x 3 blurs x {global, adaptive}
   threshold = 36 hypotheses x 4 PSMs) pooled into one plurality vote, accepted
   only on a landslide (>=2 votes AND >=2x the runner-up). One fragile re-crop was
   the whole F28 failure; the point is that no single framing is load-bearing.
   The decisive knob is **despeckle** — all 48 sweep combinations that read "28"
   have it on, because the rock speckle around the digits was being read as a
   third glyph. On F28's refined box the sweep gives **"28" x78 vs a runner-up
   of 4**.
3. **Two independent recognizers must agree** (Tesseract sweep + EasyOCR).

### The agreement requirement is load-bearing, not ceremony

On F30 the Tesseract sweep returns a **confident, wholly fabricated `88`** — 6
votes, no runner-up at all — off bright rubble. The only thing between that and a
wrong caption pairing is EasyOCR declining to see a number there. Had the relaxed
arm shipped on Tesseract dominance alone, this change would have broken the "0
wrong" invariant on the very fixture it was built for.

### On the Tesseract-backbone rule (CLAUDE.md)

Bringing in EasyOCR does not breach it. The rule forbids a non-Tesseract engine
being the **sole text source** or the **confidence source**; a corner label is
neither — it is never rendered into the document and never reaches Stage 06's
thresholds, it is a grouping KEY deciding which caption floats with which photo.
EasyOCR is already a sanctioned second opinion in this repo (Stage 05, Cyrillic).
The dependency is **optional and non-fatal**: no package, no GPU, or a model that
fails to load all degrade to the previous behaviour — a miss, never a fabrication
— and the arm is **opt-in** (`second_opinion=False` by default; `figure_grouping`
turns it on).

### Ship gate — real crops, both settings, all four corner-label fixtures

`read_corner_label` run over every figure crop of it_geo_04/05/06/07 with the arm
off and on, asserting (1) no accepted number changes and (2) no fabrication on the
label-free fixtures:

| fixture | figures | prints labels | strict | +second opinion |
|---|---|---|---|---|
| it_geo_06 | 6 | yes | 25,26,27,29 (4) | 25,26,27,**28**,29 (5) |
| it_geo_07 | 8 | no | none | none |
| it_geo_04 | 2 | no | none | none |
| it_geo_05 | 2 | no | none | none |

`GATE PASSED: no changed number, no fabrication.`

### Honest limits

- **F30 stays `None` and should be left alone.** Recorded as a measured ceiling
  precisely so a future session does not spend a day re-attempting it with a
  better text detector. C30 therefore stays unpaired, correctly — its number is
  printed on a subpage that numbers its figures, so the geometry arm is suppressed
  rather than allowed to overrule the printed numbering. The route
  `FIGURE_SEPARATION_SCOPE.md` §9 left open for C30→F30 is now closed.
- **The polarity guard does NOT cover the new arm, and must not be trusted to.**
  `max_glyph_cover = 0.55` was calibrated on the strict arm's single top-hat
  re-crop, where real labels covered 0.10..0.38 and it_geo_07's ink-on-pale
  diagrams 0.82..0.86. Re-measured over the refined boxes and the 36 sweep
  variants that separation is **gone**: real labels 0.03..0.41, label-free
  it_geo_04/05 figures 0.00..0.34 — fully inside the label range, guard kills
  **0/36** variants there (it still kills 18/36 on it_geo_07). What keeps the
  relaxed arm honest on those fixtures is two-recognizer agreement, not the guard.
  Tightening 0.55 would cut real labels before it cut diagrams.
- **Cost.** The arm fires only on figures whose label localizes but does not read,
  and then costs a recognizer load plus up to 144 Tesseract calls for that one
  figure. Callers wanting the cheap path pass `second_opinion=False`.
- **Still N=1 on one book.** Five of six labels on a single spread. The sweep
  space, the despeckle fraction and the dominance multiple are all tuned against
  that one fixture; a second corner-label book is what would test them.
- Suite **318 → 338** (+20 in `pipeline/tests/test_figure_label.py`, both counts
  from a full `pytest -q` run, not inferred). The new tests pin the additive
  property (a strict read is never revisited), the F30 fabrication case (a lone
  confident Tesseract read is refused), the plurality rule's floor/dominance/tie
  behaviour including the real pre-despeckle `{'32':2,'22':2,'33':2,'93':2}` tally,
  the recognizer being absent or raising, and the F28 fused-speckle box reproduced
  synthetically.


## Caption printed inside a figure — it_geo_05-left C2 recovered — 2026-08-10

`FIGURE_SEPARATION_SCOPE.md` §5 recorded this as blocked on detection: *"with no
text detection there is no evidence to eject on... it needs the caption to be
detected in the first place."* **That premise was false**, and it is the second
§5-class note this session's measurements have overturned (see the corner-label
entry above). The pattern is the same both times: a claim about what the LAYOUT
DETECTOR emitted, read later as a claim about what the pipeline holds.

### What was actually wrong

On it_geo_05-left the whole page is one hand-drawn map, and caption C2 is printed
on the drawing's pale margin, inside the figure box. Measured:

- **Tesseract finds 60 words at conf ~96 in exactly that region** — 58% of the
  subpage's 103 words — reading as the caption verbatim.
- They are not orphans. `attach_words` routes a word to the smallest-area block
  containing its centre; the only block there is the figure, so the caption text
  was attached to the **FIGURE block** (64 words, mixed with map lettering
  `'T IE BELLUNO LE'`).
- `stage08_render` renders a figure from "the crop from the full-res page image at
  its bbox (**NOT its OCR words**)" — so the caption was dropped from the document
  as text while surviving inside the crop as pixels.

Nothing needed detecting. The words were in `document.json` the whole time, on the
wrong block.

The one genuinely missing piece is the small italic header, "In questa pagina: /
Figura 2", which the full-subpage psm-3 pass does not recognise at all — the first
line it finds is the bold body below. Re-OCR'ing just the cluster's region as a
uniform block (psm 6, 2x) recovers it on 4/4 settings.

### What was built

`pipeline/caption_eject.py`, hooked into Stage 05 immediately after `attach_words`:
cluster the words routed inside a figure into paragraphs, re-OCR each qualifying
cluster, and **eject only if a caption header parses** — number-first, exactly as
`figure_grouping` pairs. Density and alignment are floors that keep a subprocess
off obvious non-candidates, never an alternative route to acceptance. Ejecting is
destructive twice over (it takes text off a figure AND repaints that region of the
artwork), so the bar is the repo's usual one: abstain unless the printed header
says otherwise.

- **Words are MOVED, never created or dropped**, so Stage 05's asserted
  word-conservation invariant still covers the new path (verified 103 -> 103 on the
  real page, and testset-wide in the gate).
- The ejected block is re-ranked by the **same XY-Cut** Stage 04 uses, so it lands
  in geometric reading order — F2 then C2, as GT has it — not appended.
- Its bbox spans the region the **header was read from**, not just the words. This
  is load-bearing: the header sits above the first recognised line and has no word
  boxes, so a words-only bbox masks the caption body and leaves "In questa pagina:
  Figura 2" stranded on the artwork — the same defect again. Verified by rendering
  the crop both ways.
- **Stage 08 masks** any TEXT block contained in a figure's bbox out of the crop.
  Nested FIGURES are never masked (a sub-figure is artwork). The fill is sampled
  from the crop's own border rather than a fixed white, because these regions sit
  on a map's pale margin, not on page background.

### The gate — built BEFORE the fix, over the whole testset

The regression surface here is much wider than the corner-label work's: this
touches every figure block with words routed into it, and a figure legitimately
full of lettering (a topographic map, a geological section) must never be cut.

| | count |
|---|---|
| figure blocks across all 15 testset images | 50 |
| ... with a cluster dense enough to qualify | 6 |
| ... whose re-OCR parses a caption header | **1** |

The one hit is the defect. The five that abstain are de_02's topographic lettering
(29/16/8 words) and it_geo_02's geological-section labels (35/9 words) — real
artwork text that a density-or-alignment acceptance rule would have cut out of the
picture. Re-run with the production module: **1 ejection testset-wide, IoU 0.615
against GT C2, no word-conservation violation on any subpage.**

### Honest limits

- **The recovered header is evidence only — it is NOT added as words.** The
  ejected caption's rendered text therefore begins "La geografia nei dintorni..."
  and omits its own "In questa pagina: Figura 2" line. Adding those words would
  break Stage 05's conservation assert (they are not in `twords`), which is a
  schema/invariant question deserving its own commit. Today the whole caption is
  lost, so this is a strict improvement, but it is not the complete caption.
- **A consequence of that:** Stage 07's grouping reads a caption's number from its
  TEXT, and the ejected block's text no longer contains "Figura 2" — so this
  caption does not gain a `pair_by_number` partner from the ejection. On
  it_geo_05-left that costs nothing (the subpage has exactly one figure), but on a
  multi-figure page it would.
- **N=1.** One caption, one page, one book. The gate shows the *abstention* side is
  exercised 5 ways across three books, which is the half that carries the risk; the
  acceptance side rests on a single fixture.
- **This is a Stage 05 behaviour and `tools/layout_order_eval` does not grade it.**
  The eval has its own `_route_words` and never runs Stage 05, so it grades Stage
  04 block structure — the ejection deliberately does NOT appear as a Stage-04
  segmentation-recall gain, and no such claim is made here. The number above (IoU
  0.615 vs GT C2) was measured directly.
- Suite **338 -> 356** (+18 in `pipeline/tests/test_caption_eject.py`, both counts
  from full `pytest -q` runs). Tests pin the header parse against the real
  abstaining clusters, the anchoring (a "Figura 12" cross-reference deep in a
  paragraph must not eject a body paragraph), word conservation, the
  header-covering bbox, XY-Cut placement, the floors keeping the re-OCR off sparse
  lettering, and the masking rules including never masking a nested figure.

---

## Multi-view Phase 1 — STEP 1 gate + STEP 2 headroom — 2026-08-18

Phase 1 was greenlit on a **picture** (Phase 0's complementary-halves crops), never on a
number. Advisor-ordered, this session deliberately runs the two cheapest questions **before
writing any registration code**, because either can kill the build outright:

1. **Does UVDoc survive a steeply oblique frame at all?** The whole "dewarp each view, then
   register the rectified pages" route rests on it — UVDoc is trained on roughly frontal
   document photos, and the oblique frame is the one carrying the gutter text we want.
2. **How much is there to win?** OCR the dewarped **oblique** and the dewarped **face-on**
   and count GT tokens the oblique recovers that the face-on misses. A per-region
   "pick the best view" composite can never beat "best frame per region", so that count is
   the **ceiling** any fusion can harvest. Near zero → registration is unwarranted, and
   Phase 1 ends as a negative result the way the CLAHE spike did.

Same 3 pages, same de-contamination (facing-page sliver cut at the spine valley *before*
dewarp), same hand-keyed GT (`temp/gutter_clahe/gt_bands.json`) and the same
recall-is-the-verdict discipline as the CLAHE spike. Probe: `temp/mv_phase1/headroom.py`.

### STEP 1 — UVDoc on an oblique frame: PASSES (the route stays alive)

All 6 frames (3 pages × {face-on, oblique}) dewarped with `method=uvdoc`, **no** fallback to
classical, **zero** warnings. By eye the oblique rectifies to an upright, readable page —
`temp/mv_phase1/skew_oblique_thumb.png` shows the left line-starts (*"Lines in the sand
around us"*, *"The sea had made it!"*) crisp in exactly the region the face-on frame smears.
The route is not dead; the registration question is now worth asking.

### An incidental finding that had to be fixed first: the skew page now loads SIDEWAYS

The first run scored **recall 0.022 on BOTH arms** of the skew page. Cause is not the dewarp:
Tesseract **OSD errors out** on those two 4000×3000 frames (`method=osd_unavailable`), and
since the 2026-07-18 orientation cascade this phone's EXIF 6/8 is *deliberately distrusted*,
so the resolver keeps the raw landscape buffer and the page comes out rotated 90°. The CLAHE
spike ran 2026-07-17 — **before** that change — which is why its cached `skew_dw.png` is
upright. Pinned here through the cascade's own layer-1 escape hatch (`hint_rotate=90`).

**This is a real risk for the multi-view capture mode, not a fixture quirk.** The 2026-07-18
resolver was built around *landscape two-page spreads* (its fallback prior is literally "a
book spread should be landscape"); a single-page multi-angle capture is **portrait**, and
when OSD fails there is nothing left to catch it. Logged here rather than fixed, because the
multi-view ingest path is unbuilt and will need its own orientation contract anyway.

**Reproduction check (the reason to trust everything below):** with the hint, all three
face-on arms reproduce the CLAHE spike's baseline outer-band recall **exactly** — skew 0.533,
curl3 0.975, curl5 0.500 — and Phase 0's per-band confs to the decimal (curl3 80.9 / 91.2,
curl5 34.3 / 71.0).

### A scoring correction this measurement forced: the [0–.35] window is NOT cross-frame safe

The CLAHE spike scored recall inside a generous width-**fraction** window, and that was
correct there: CLAHE moves zero pixels, so both arms shared one geometry. Across two
*different photographs* it silently changes what is being measured — a tilted camera spends
more pixels on the near (gutter) side, so the same width fraction is a **different physical
slice** in each frame. The size of the artefact:

| page | oblique recall, window [0–.35] | oblique recall, **full page** |
|---|---|---|
| skew  | 0.044 | **0.933** |
| curl3 | 0.200 | **0.925** |
| curl5 | 0.704 | 0.630 |

The window said the skew oblique had recovered 2 of 45 GT words while the crop plainly shows
them; it was measuring geometry, not text. **Full-page recall is the headline** — it asks the
GT README's own question ("did OCR recover these real words") with zero geometry dependence.
The window numbers are kept only as continuity with the CLAHE row.

### STEP 2 — the headroom (full-page recall of the hand-keyed gutter GT)

| page | nGT | face-on | oblique | oblique-only | face-on-only | **union = ceiling** | **headroom** |
|---|---|---|---|---|---|---|---|
| skew  | 45 | 0.533 | 0.933 | **19** | 1  | **0.956** | **+0.422** |
| curl3 | 40 | 0.975 | 0.925 | 0  | 2  | 0.975 | +0.000 |
| curl5 | 54 | 0.574 | 0.630 | **14** | 11 | **0.833** | **+0.259** |

**curl3's +0.000 is a construction zero, not evidence against fusion:** it is the declared
no-headroom control (face-on already at 0.975), kept to hold N=3 honest. The two pages with
actual headroom to measure both show a large one. Do not read this as "1 of 3".

The oblique-only tokens are the distinctive gutter words, not filler — skew recovers
`incalculable`, `retreating`, `rushing,`, `spellbinding`, `Holding`; curl5 recovers
`discovered`, `safely;`, `mountain`, `years ago`.

**Two controls, because a token-alignment recall can be gamed by luck:**

- **Decoy recall** — each arm's OCR scored against the *other pages'* GT. It is the metric's
  noise floor, and it is **near-identical between the arms** (skew 0.170 face-on vs 0.160
  oblique; curl5 0.106 vs 0.082), so the *difference* between arms cannot be alignment luck.
  Note the floor is not negligible at full page (0.05–0.17) — a headroom smaller than ~0.15
  would not have been quotable.
- **Sequence length** — the oblique's OCR is not simply longer (skew 353 vs 277 tokens, curl5
  460 vs 490). On curl5 the winning arm has *fewer* tokens, so it is not winning by having
  more chances to align.

### Verdict: headroom is real → the registration work is warranted

Fusion can win up to **+0.42 / +0.26** gutter-token recall on the two pages that have room to
show it. That is the number Phase 0 could not produce, and it is far above the metric's noise
floor. Proceed to the registration measurement (gutter-local, per 0b — a page-wide inlier
count would pass on the flat middle and mean nothing).

### Honest limits

- **This cannot yet distinguish "fuse the views" from "just pick the oblique view".** The GT
  covers gutter words only, so an arm is never charged for what it loses on the far side. The
  oblique's far-side loss is visible only as conf ([.5–1] band: skew 51.6 vs face-on 77.2;
  curl5 65.5 vs 87.8; curl3 80.1 vs 94.8) — and this project treats conf as screen, never
  verdict. **A far-side GT band is now owed**, and it is what makes fusion's claim
  falsifiable rather than assumed.
- **N=2 effective** (curl3 is the control). Same single-page-oblique geometry throughout, all
  English. The `testset/skewset_*` fixture is still owed and deliberately not curated yet —
  nothing here is a shippable claim.
- The gutter GT was keyed from the *face-on* dewarp. That is what makes it a fair test of the
  oblique (the words were chosen without reference to it), but it also means GT coverage is
  bounded by which lines were legible enough to key at all.

### STEP 3 (re-scoped) — matched WORDS as the registration primitive — 2026-08-18

The plan's Phase 1 is a **pixel** composite: register the views, pick the sharpest source per
region, blend, hand the composite to Stage 03. 0b is what makes that research — ORB cannot
align an oblique frame's gutter to a face-on anchor.

The headroom probe above quietly undermines that framing. It aligned the **word streams** of
the two views well enough to produce every number in the table — a working cross-view
correspondence, obtained without ORB, on exactly the pages where ORB fails. So the route
changes: **fuse text, not pixels.** Pixel blending needs sub-character accuracy in the gutter
or it doubles glyphs; a word merge needs only enough geometry to put a word on the right
**line**. There is evidence for the second requirement and none for the first.

That reduces Phase 1's open question to one measurable thing: *can matched words alone pin a
transform that places an unmatched word on the correct line?*

**Design — a hold-out, so the transform is never scored on what it was fitted to.**
Correspondences are word pairs from the aligned OCR streams (tokens ≥3 chars). The transform
is **fitted only on non-gutter pairs** and **scored only on gutter pairs** — the gutter is
precisely where the face-on frame fails, so a transform that works only where both frames
read well is worthless; it has to **extrapolate**. Words both frames happened to read in the
gutter are the only honest ground truth for "where should this land".

**Bar, pre-registered:** median |Δy| < 0.5 × median word height. Line placement (Δy) is the
verdict; Δx is screen only — a word merge needs the right line, not the right column offset.

**Model choice is made blind.** Picking the best of three families by their gutter score is
selecting on the hold-out. Instead an inner validation slice is carved out of the fit set —
carved **spatially** (the band just outside the gutter, [.24–.40]), not at random, because
the task is extrapolation leftward, and a random k-fold only ever tests interpolation and
would happily crown a polynomial that flies apart past its last data point.

| page | word h | fit / held-out pairs | identity baseline | **selected model** | **median &#124;Δy&#124;** | bar | verdict |
|---|---|---|---|---|---|---|---|
| skew  | 71.0px | 43 / 16 | 32.6px (0.46 wh) | affine (RANSAC) | **5.2px** (0.07 wh) | 35.5px | **PASS** |
| curl3 | 44.0px | 102 / 64 | 45.2px (1.03 wh) | affine (RANSAC) | **5.4px** (0.12 wh) | 22.0px | **PASS** |
| curl5 | 44.0px | 79 / 24 | 59.0px (1.34 wh) | similarity (RANSAC) | **21.3px** (0.48 wh) | 22.0px | **PASS (marginal)** |

The identity baseline (oblique coordinates merely rescaled to the face-on canvas) sits at
0.46–1.34 word heights, so the transform is doing real work — this is not "the frames were
already aligned".

**The weak component is the model selector, not the capability.** On curl5 the blind selector
picks similarity at 21.3px — 97% of the bar — where affine scores 11.4px and the quadratic
4.6px. On skew it earns its keep in the other direction: it rejects the quadratic (inner
score 137px), which would indeed have blown up on the hold-out (29.4px vs affine's 5.2px).
A **fixed affine** model would have scored 5.2 / 5.4 / 11.4 — comfortably under bar on all
three — but that choice is **post-hoc on N=3** and does not count until it is pre-registered
on a fixture that has not been looked at. Recorded as the thing to pre-register, not as a
result.

**Verdict: the text route is viable.** Matched words pin the geometry to line accuracy, so
Phase 1 becomes *a word merge with provenance* rather than a pixel composite — which also
leaves the CLAUDE.md invariant intact, since every word keeps the box and confidence
Tesseract gave it **in the frame it was read in**. Design consequences, all with precedent in
this repo: choosing between two reads of the same word reuses the `second_opinion.py`
mechanism rather than a new confidence-as-truth path; each word carries a **source-frame**
field (Stage 06 patch mode has to know which dewarp to crop from).

**What the cheap route does NOT fix, stated now rather than as a later surprise:** nothing
merges pixels, so a **figure** crossing the gutter stays foreshortened, and so does any
region with no text to anchor on. That is the honest boundary of text fusion and the reason
Phase 2 (developable-surface unwrap) stays on the books.

**Still blocking a shippable win: the far-side GT band.** A merge that prefers the oblique's
reading is unfalsifiable while no arm is charged for what it loses on the far side — and the
conf screen says the oblique is worse there on all three pages. Keying that band is the next
step; it does not block building the merge, it blocks quoting a number as a win.

### STEP 4 — the word merge, measured on BOTH bands — 2026-08-18

The merge builds only from mechanisms this repo already ships: the difflib alignment
`second_opinion.find_disagreements` uses, the transform from STEP 3 (family chosen by the
blind inner-band procedure, so no GT is consulted and it is a runtime-legal choice), and the
`second_opinion` dictionary gate. Every kept word carries its **source frame**; the anchor is
always the face-on view. Probe: `temp/mv_phase1/merge.py`.

**Two metrics, and the reason for the second.** The verdict metric stays token recall scored
by difflib, for continuity with the CLAHE row. But the merge *inserts* tokens into the stream,
and difflib's matcher is a recursive longest-match, not an optimal LCS — junk between two GT
words can cost a match the document did not actually lose. So an order-free **bag** recall
(multiset intersection) is printed beside it. The pair is informative precisely where they
disagree: **sequence-only loss = the words are all still there but out of order; bag loss =
words genuinely replaced by something else.** The bag metric is a diagnostic, never the
verdict — it also rewards a junk-heavy arm for stumbling onto a GT token anywhere, which is
why its own decoy floor (0.21–0.35, much higher than the sequence metric's 0.05–0.17) is
printed with it.

#### Five policies, because the first one harvested almost nothing

| policy | how a contested slot is decided |
|---|---|
| v1 dict-gate | `second_opinion`'s rule verbatim: substitute only on a 1↔1 replace where the anchor read a non-word and the oblique nominated a valid one |
| v2 region/height | per-band winner by native median word height |
| v3 region/conf | per-band winner by mean OCR conf |
| v4 per-slot conf | the higher-confidence reading wins each slot outright |
| v5 slot + dict veto | v4, but a valid dictionary word is never traded for a non-word |

**v1 harvested a tenth of the ceiling, and the counter says why: `substituted=0`, blocked
173 / 92 / 312.** The 1↔1 restriction that is load-bearing for *flagging* is fatal for
*merging* — a smeared gutter line and a clean one do not tokenise into equal counts, so every
real substitution arrives as an n↔m block and is refused. Insert-only cannot reach the win
either: the face-on frame does emit words in the gutter (46 at conf 33 on skew), so the slot
is already occupied by garbage.

**Two geometric criteria were tried before conf, and both failed in instructive ways.** The
plan says "pick the least-foreshortened view", and a measurable fact should beat a model
output where one exists:
- **native word height is the wrong axis.** A curl at a vertical gutter compresses text
  *horizontally*; line height barely moves. It therefore called the face-on the better reader
  in skew's band [.12–.25] — the very band the gutter GT was keyed in, where the face-on
  scores 0.533 and the oblique 0.933.
- **per-character aspect (advance width / line height) is the right axis but is contaminated
  by the failure it should detect.** A smear is read as one or two garbage characters inside a
  *wide* box, so the ruined gutter scores a *higher* aspect than clean text (skew face 1.212
  vs oblique 0.476). It ranks backwards.

Mean conf orders all three pages correctly. Using it here is narrower than it looks — it
compares two reads of the *same* region rather than thresholding anything, the same use the
shipped disagreement trigger makes of a second reader — and its known hazard (conf rising on
garbage) is exactly what the far-side band exists to catch.

#### Results — v5, the policy proposed for the next fixture

| | GUTTER (the win) | | | FAR SIDE (the guard) | | |
|---|---|---|---|---|---|---|
| page | face-on | v5 | Δ | face-on | v5 | Δ |
| skew  | 0.533 | **0.778** | **+0.244** | 0.639 | 0.528 | −0.111 |
| curl3 | 0.975 | 0.950 | −0.025 | 0.800 | 0.778 | −0.022 |
| curl5 | 0.574 | **0.648** | **+0.074** | 0.688 | 0.672 | −0.017 |
| | *bag* | | | *bag* | | |
| skew  | 0.733 | **0.933** | **+0.200** | 0.694 | 0.694 | **0.000** |
| curl3 | 0.975 | 0.975 | 0.000 | 0.956 | 0.956 | **0.000** |
| curl5 | 0.722 | **0.815** | **+0.093** | 0.953 | 0.906 | −0.047 |

**What the two metrics together say.** The gutter win is real and survives both scorers. The
far-side story splits: on **skew and curl3 the bag metric is flat at zero**, so nothing was
lost — those sequence-metric drops are the merged words landing in the wrong reading order,
not missing. On **curl5 the bag drops 0.047**, which is genuine: three far-side words were
replaced by something else. Reading order is not a scoring detail in this project (the
deliverable is a re-typeset document), so the skew ordering drop is a real defect too — just a
different defect from word loss, and one that points at insertion placement rather than at
the selection rule.

**The veto earns its place.** Without it (v4) the gutter win is bigger — bag +0.223 skew,
+0.167 curl5 — but curl5's far side loses **0.141** of real words. The veto trades about a
third of curl5's gutter gain for two-thirds of its far-side damage. Given this project's
standing bar on the caption-pairing work (zero wrong beats one more right), the vetoed policy
is the right default.

**Harvest against the measured ceiling:** v5 takes 58% of skew's available headroom and 29% of
curl5's. Most of the remainder on curl5 is what the veto deliberately declines.

#### Limits — three, and the first is the one that matters

- **Five policies were compared on the same three pages that carry the GT.** "v5 is best" is
  therefore a hypothesis generated on N=3, not a validated choice — the same trap the STEP 3
  model selection was designed to avoid, and here it is unavoidable without another fixture.
  **Pre-register v5 and re-measure on a fixture that has not been looked at** before this is a
  result rather than a lead. The same applies to the 8-band grid and the ≥3-word minimum.
- **No precision metric on the gutter.** Recall counts real text recovered; junk the merge
  imports shows up only in the word counts and the decoy floor. The CLAHE row carried the same
  limitation, but the merge can *import* garbage in a way a contrast operator cannot.
- **Nothing here is wired into the pipeline.** This is a probe over cached dewarps. Stages 00–03
  have no multi-view capture mode, the schema has no source-frame field, and Stage 06's patch
  mode would need one to know which dewarp to crop from. The orientation resolver would also
  have to be fixed first (see the STEP 1 note) — it mis-orients these captures.

#### Follow-ups on the two soft spots above

**The ordering drop is NOT the line-clustering constant — hypothesis tested and rejected.**
The obvious suspect: `to_lines` clusters at 0.6 × median word height = 43px on skew, and the
selected transform's p90 line-placement error is 36px, so tolerance and error are the same
size and could plausibly be merging or splitting lines. Swept as a diagnosis (never to pick a
value — choosing a constant off these three pages is the selection-on-test trap):

| tolerance | skew gutter | skew far |
|---|---|---|
| 0.30 × wh (21px) | 0.800 | 0.417 |
| 0.45 × wh (32px) | 0.800 | 0.417 |
| **0.60 × wh (43px, current)** | 0.778 | **0.528** |
| 0.80 × wh (57px) | 0.689 | 0.528 |

Far-side ordering does not recover at any setting — it gets **worse** when tightened, and the
current value already sits at the top of the range. So skew's ordering loss has some other
cause (the selected transform there is a *similarity* with median |Δx| 63px, which is the next
thing to look at). Recorded as a rejected hypothesis so a later session does not "fix" the
constant. A GT-free tolerance derived from line pitch was tried in the same run and is **not
usable as written** — the pitch estimator returns 26px on a page with 71px words, which is not
a line spacing; it needs a real implementation before it can be proposed.

**The far-side guard is weaker than its zero reads.** That band was keyed where the face-on
frame is at its *best*, so the words most at risk from imported oblique junk — the ones the
face-on read only marginally — are underrepresented in it by construction. The flat 0.000 on
skew and curl3 should be read as "no loss among words the face-on read confidently", not as
"the guard passed". Keying a matched band of *marginal* far-side words is what would make the
guard as sharp as its name suggests.

## Multi-view fixture — the 2026-08-18 batch: three gates, four corrections, one fixture — 2026-08-18

Phase 1 ended not-shippable with the blocker named as **data**: five merge policies had been
compared on the same three pages that carry the GT, so "v5 is best" was an N=3 hypothesis.
The owner delivered **97 multi-angle phone captures** the same day
(`temp/zoomset_raw/batch_20260818/`, 344 MB, out of git). This row is what the data turned
out to be, and what had to be corrected before a single ground-truth token was worth keying.

**The pre-registration is committed first, on purpose** (`docs/plans/multiview-phase1-prereg.md`,
commit `5fe9fab`). Curating a new fixture and then scoring all five policies on it again would
reproduce the invalid thing at N=9. v5 is named as the one policy under test; the other four
will not be run on these pages.

### The batch

20 sets, 97 frames, all 4000×3000, grouped in `temp/mv_batch18/sets.py`. Three books:

| prefix | book | language | sets | frames |
|---|---|---|---|---|
| `it_ferr_*` | Italian via-ferrata atlas — a **new** book, not the `it_geo_*` geology one | ita | 8 | 24 |
| `de_ferr_*` | the German via-ferrata guide behind `de_*` | deu | 3 | 9 |
| `en_coin_*` | *Chopmarked Coins*, the book behind `en_coins_*` | eng | 9 | 64 |

Four English sets are multi-**scale** as well as multi-angle (a full spread then progressively
closer partial views). **No Bulgarian** — the original ask was Bulgarian / Italian / German, so
the **Cyrillic arm stays unvalidated**, in particular v5's dictionary veto on Cyrillic. Stated
as a limit on the claim, not as a gap to fill; the owner delivered this batch as sufficient.

### Gate A — orientation: a defect in shipped code, found by the fixture work

Two Italian sets have frames that disagree about which way is up:

| set | frame | OSD call | OSD conf | applied | the other frames |
|---|---|---|---|---|---|
| `it_ferr_b` | 134655 | 180° | **2.58** | 180° | 134657/134658 → 0° at conf 16.6 / 10.4 |
| `it_ferr_e` | 134731 | 180° | **3.09** | 180° | 134724/134729 → 180° at conf 0.24 / 1.59, below threshold, kept raw |

Both are one defect: **`DEFAULT_MIN_OSD_CONF = 2.0` trusts an OSD call at conf 2.6–3.1**, which
on a book spread is noise — and a **180° error is invisible to the cascade's layer-5 landscape
prior**, because a spread rotated 180° is still landscape. The prior separates portrait from
landscape and nothing else. `it_ferr_e` is the worst case by construction: a full-bleed
panorama with almost no text, so OSD has nothing to work with.

Two frames of one spread arriving 180° apart would have corrupted the word-stream alignment
**silently**, surfacing only as a bad number after the GT was already paid for. **Reported, not
patched** — `tools/normalize` is untouched this session; pinned fixture-side by per-set
majority (`temp/mv_batch18/orient.py`), which is defensible because every frame of a set
photographs one physical spread held one way up. That is an assumption about the *capture*, and
it is recorded as one.

### Gate B — ORB is the wrong instrument here, and that is finding 0b replicating

Phase 0 gated viewpoint diversity on ORB median displacement (80–900 px). On this batch that
gate would disqualify **exactly the sets the effort exists for**:

| book / curl | sets | ORB inliers between the extreme frames |
|---|---|---|
| Italian + German, mild curl | 11 | **36 – 701** (registers fine) |
| English *Chopmarked Coins*, strong curl | 9 | **3 – 13 on 7 of 9** (does not register at all) |

A median displacement computed from 3 inliers is noise, not diversity — `en_coin_b` reports
1246.9 px off 3 inliers, and the probe later crashed outright on a null homography mask, which
is the same failure with the politeness removed. **This is Phase 0's finding 0b reproducing on
new pages, outside its original set, for the first time**, and it separates cleanly by book and
curl severity rather than randomly. It is also precisely why the Phase 1 route became a text
merge. ORB is kept as a *screen* with inlier counts attached, never as an entry gate.

Replaced by the mechanism the merge actually uses: correspondences from the aligned OCR token
streams (`temp/mv_batch18/wordstream.py`), with a floor of ≥ 40 pairs and ≥ 12 of them in the
gutter — mirroring what STEP 3 actually fitted and held out (43/16, 102/64, 79/24).

### Gate C — specified, measured, withdrawn as a mis-specification

The gate asked whether Stage 02 puts the gutter at the same **fraction of the frame** in every
view. It cannot, and the data says so cleanly:

| set | split-x as a fraction of frame, per view |
|---|---|
| `it_ferr_a` | 0.634 → 0.545 → 0.478 |
| `it_ferr_d` | 0.626 → 0.545 → 0.460 |
| `en_coin_a` | 0.593 → 0.432 → 0.358 |
| `en_coin_e` | 0.633 → 0.543 → 0.459 |

Monotone with viewpoint — that is perspective behaving exactly as perspective does, not a
detector defect. A frame-relative bar is satisfiable only by frames that share a viewpoint,
which is the opposite of what this fixture is for; repairing it in a common frame would need
the transform, which needs the correspondences, which is downstream of what the gate was meant
to protect. Numbers kept in `temp/mv_batch18/gate_c.json`; the `0.3` entries look like a
search-range clamp rather than a detection and are not quoted as positions. What survives is a
by-eye check while keying GT: **does a frame's crop cut off text another frame retains?**
Stage 02 frame-stability across viewpoints is a **pipeline-integration** question, logged as
one.

### Correction 1 — capture order is not evidence about geometry

Every probe in this session initially assumed frame 0 is the face-on anchor. Found false by
eye and then confirmed: on `it_ferr_g`, frame 0 (134759, 177 valid tokens) is the **oblique**
view whose inner column is a smear, and 134801 (368) / 134804 (355) are the face-on ones that
read it. Since the merge is defined as *insert what the oblique recovered into the face-on
page*, getting this backwards inverts the measurement. The anchor is now the frame reading the
most dictionary-valid tokens (`temp/mv_batch18/anchors.py`) — a GT-free proxy, applied within
a set. **Every number produced before this correction is superseded by it.**

### Correction 2 — whole-page headroom collapses once the anchor is right

With the anchor picked by measured legibility, the second view contributes **fewer** new valid
tokens than it loses, on every set measured:

| set | valid tokens per frame | anchor | gain | loss | gain/loss |
|---|---|---|---|---|---|
| `it_ferr_g` | 177 / 368 / 355 | 134801 | 69 | 82 | 0.84 |
| `it_ferr_h` | 412 / 440 / 382 | 134815 | 86 | 114 | 0.75 |
| `de_ferr_a` | 63 / 81 / 115 | 134828 | 19 | 53 | 0.36 |
| `de_ferr_c` | 88 / 131 / 177 | 134917 | 16 | 62 | 0.26 |
| `en_coin_a` | 219 / 373 / 337 | 135006 | 132 | 168 | 0.79 |
| `en_coin_d` | 91 / 561 / 358 | 135049 | 145 | 348 | 0.42 |

**This is not a refutation of the premise — it is the wrong question**, and saying so is the
point of recording it. A whole-page count is dominated by the **far side**, where every Phase
0/1 measurement already says the oblique view is the worse reader. STEP 2's ceiling
(+0.422 / +0.259) was measured on the **gutter** band specifically. Had this number been taken
as the headroom, the fixture would have been abandoned on a measurement that was never testing
the claim.

### Where the premise actually lives: gutter-restricted headroom

Band defined to need **no page crop** — each frame's own OCR word boxes give a text extent
(2nd/98th percentile of x, the trick `gt_far.json` already uses for column edges); on a spread
the two inner margins meet in the middle, so the gutter is the middle ±0.10 of that extent.
Self-normalising per frame, so it survives the camera filling the frame differently — the
failure that made the CLAHE spike's width-fraction window not cross-frame safe.

| set | lang | curl | anchor | candidate | gutter gain | loss | anchor had | **net** | far gain | far loss |
|---|---|---|---|---|---|---|---|---|---|---|
| `en_coin_e` | eng | strong | 135113 | 135111 | 114 | 72 | 79 | **+42** | 162 | 234 |
| `en_coin_a` | eng | strong | 135006 | 135009 | 89 | 64 | 72 | **+25** | 125 | 175 |
| `it_ferr_g` | ita | strong | 134801 | 134804 | 40 | 31 | 66 | **+9** | 44 | 63 |
| `de_ferr_a` | deu | mild | 134828 | 134824 | 18 | 9 | 13 | **+9** | 7 | 51 |
| `en_coin_d` | eng | strong | 135049 | 135052 | 83 | 82 | 102 | +1 | 141 | 351 |
| `it_ferr_h` | ita | mild | 134815 | 134813 | 35 | 41 | 77 | −6 | 78 | 102 |
| `de_ferr_c` | deu | mild | 134917 | 134914 | 9 | 22 | 48 | −13 | 23 | 60 |
| `en_coin_c` | eng | strong | 135028 | 135030 | 56 | 90 | 103 | −34 | 101 | 248 |

> **Read this table with Correction 4 below.** This band pools **both** inner margins of the
> uncropped spread, which is not the band the GT is keyed in. Re-measured per-page on the hand
> crops, two of the four selected sets move — `skewset_en_02` from +25 to −2 and
> `skewset_de_01` from +9 to −6. The numbers here remain valid for what they measured (a
> whole-spread ranking used to choose which sets to crop) and are kept for that reason, but
> **the per-page table in Correction 4 is the one to trust.**

**Net-positive on 5 of 8, and the ordering is not random**: the largest net gains are all
**strong curl**, and the clearly negative ones are mild-curl or the set whose candidate is
simply a worse photograph. The `gain` column is the quantity STEP 2's ceiling measures (text
the other view recovers), so `it_ferr_g` offers 40 gutter tokens against an anchor that reads
66 — a 61% relative ceiling on the band that matters. The far-side columns show the oblique
losing heavily out there on every set, which is exactly what makes Claim A2's guard worth
having.

### Correction 3 — three automatic page-crop routes measured and rejected

The originals were prepared as single pages, hand-cut at the spine valley. Reproducing that
automatically on this batch failed three times, each for a different and instructive reason:

| route | result |
|---|---|
| `auto_page_crop` (Otsu + largest contour), inherited from the Phase 1 probes | returns the **whole 4:3 frame** on all 97 images (crop aspect 1.16–1.39 against a raw 1.333) — the originals were shot on a plain background, this batch is on a textured sofa |
| HSV paper segmentation (bright + desaturated), `temp/mv_batch18/pagefind.py` | isolates the book, but **not consistently across a set** — on a strongly curled spread the shadowed page stops being "bright paper", the component splits, and one frame yields the spread while the next yields a single page |
| OCR-word-box spine finder, `temp/mv_batch18/prep.py` | the reduced-scale scout OCR reads wildly different word counts per frame (77 / 652 / 479 on one set), so the spine is found in one view and missed in the next |

An inconsistent crop is worse than no crop: it silently makes the two views different physical
regions, which the merge would then read as a difference in what the cameras could *see*.
**Resolution: the selected sets' page crops are hand-specified and recorded in the fixture
manifest** — which is how the original three pages were prepared, and which takes automatic
multi-view page finding off the critical path and onto the pipeline-integration list, where
Stages 00–03 already owe a multi-view capture mode.

### Correction 4 (same day, on review) — the selection band was not the GT band

The four sets above were selected on a gutter band spanning **both** inner margins of the
uncropped spread (middle ±0.10 of the frame's text extent). The GT the next session is told to
key is **per-page**, on a single hand-cropped page, in text-column coordinates: gutter = the
inner .24 of *that page's* column width, far side = the mirror — `gt_far.json`'s definition.
Those are different regions, and on a spread they can cancel: the candidate's advantage may sit
on the left page's inner column while the anchor is the better reader of the right page's, and
a pooled band nets the two against each other.

Re-measured on the hand crops now recorded in `testset/skewset_manifest.json`
(`temp/mv_batch18/perpage.py`) — no GT needed, so it costs only OCR:

| fixture | page | anchor had | **gain** | loss | **net** | pooled net (superseded) | far net |
|---|---|---|---|---|---|---|---|
| `skewset_en_01` | p.12 left | 64 | **55** | 43 | **+12** | +42 | +19 |
| `skewset_en_02` | p.191 right | 79 | **57** | 59 | **−2** | +25 | +24 |
| `skewset_it_01` | p.62 left | 38 | **41** | 34 | **+7** | +9 | +16 |
| `skewset_de_01` | p.40 left | 29 | **7** | 13 | **−6** | +9 | −4 |

**Two of the four move, and the concern was justified.** `skewset_en_02`'s +25 was partly the
other margin — per-page it is a nearly symmetric exchange (gain 57, loss 59). `skewset_de_01`
collapses to **7 tokens of gain**: there is essentially nothing on that page for a merge to
recover, which is a sharper version of the thinness already flagged for the German book.

**What changes, and what deliberately does not.** No frames are swapped — all four remain
legitimate multi-view sets, and re-selecting now on numbers computed after the fixture was
built would be its own selection-on-test problem. What changes is the **declared role** of each:

- `skewset_en_01` (gain 55 vs an anchor reading 64, an 86% relative ceiling) and
  `skewset_it_01` (gain 41 vs 38, 108%) are the two **win cases**.
- `skewset_en_02` is retained as the **guard case**: a large, nearly symmetric exchange is
  exactly where a policy that swallows the oblique reading indiscriminately shows itself, which
  is what pre-registered prediction **A2** exists to catch.
- `skewset_de_01` is now the **declared no-headroom control** — the role curl3 plays in the
  original trio, and precisely what prediction **A3** was written for. A flat result there is
  the expected outcome, not a failure.

**Resolving one ambiguity in the pre-registration, by a rule that does not look at outcomes.**
A1 refers to "the headroom pages (triage proxy > 0)" without pinning whether the proxy means
*gain* or *net*. It means **gain** — the RESULTS text above already states that gain "is the
quantity STEP 2's ceiling measures", and A1 asks about pages where there is something to win,
not pages where a naive whole-band swap would win. Recorded here, before any scoring run, so
the reading cannot be chosen later to suit a result.

**And the fixture's missing measurement is now taken.** Gate B's floor (≥ 40 correspondences,
≥ 12 in the gutter) had only ever been computed under the superseded frame-0 anchor and the
rejected automatic crop. Re-measured on the selected frames and hand crops, all four pass —
326 / 260 / 94 / 120 pairs with 14 / 13 / 22 / 12 in the gutter — though `skewset_de_01` sits
exactly on the 12 floor, one more reason its result will be noisy. Claim B has a valid entry
measurement; the old `wordstream` block is kept for provenance only and marked superseded.

### The fixture

Selected under the rule fixed in the pre-registration (**at least one Italian and one German
set even if an English set ranks higher**, because replication across *books* is worth more
than a fourth page of the same paperback), then by gutter headroom:

| fixture id | set | language | book | curl | why |
|---|---|---|---|---|---|
| `skewset_en_01` | `en_coin_e` | eng | Chopmarked Coins | strong | **win case** — per-page gain 55 against an anchor reading 64 (86% relative ceiling), net +12 |
| `skewset_en_02` | `en_coin_a` | eng | Chopmarked Coins | strong | **guard case** — gain 57, loss 59, net −2: a large but symmetric exchange, where a policy that swallows the oblique indiscriminately shows itself (prediction A2) |
| `skewset_it_01` | `it_ferr_g` | ita | Italian ferrata atlas | strong | **win case** — the required Italian; gain 41 against an anchor reading 38 (108%), net +7 |
| `skewset_de_01` | `de_ferr_a` | deu | German ferrata guide | mild | **declared no-headroom control** — per-page gain is only 7 tokens (net −6); the role curl3 plays in the original trio, and what prediction A3 is written for |
| `skewset_orient_01` | `it_ferr_b` | ita | — | — | orientation fixture: OSD 180° at conf 2.58 accepted |
| `skewset_orient_02` | `it_ferr_e` | ita | — | — | orientation fixture: text-free panorama, OSD conf 0.24; also the "don't break a photo page" guard |

Anchor + candidate frame only per set, not whole bursts: `testset/` tracks ~64 MB of images
today and each frame is ~4 MB; these add 48 MB. **No frames were swapped after Correction 4** —
re-selecting on numbers computed once the fixture was already built would be its own
selection-on-test problem. What changed is each set's declared role, above.

### What this row does NOT claim

**No merge policy was run on these pages.** Claims A and B are pre-registered and unmeasured;
the ground truth is not yet keyed. Everything above is GT-free triage plus four corrections,
and the headroom numbers are a **dictionary proxy**, not the token recall the verdict metric
uses — they rank sets, they do not score arms. The next session's job is: key the gutter and
far-side bands on the four measurement fixtures in the band definition `gt_far.json` already
uses (text-column coordinates), then **one** scoring run — v5 plus the GT-free Claim B sweep —
reported against the pre-registered pass conditions, pass or fail.

## Multi-view Phase 1 — the pre-registered run: v5 does not replicate — 2026-08-18

**One scoring run, as pre-registered, and it is mostly a negative result.** The band ground
truth for all four page-pairs was hand-keyed and committed on its own (`acab013`,
`testset/gt/skewset_bands.json`) *before* the scorer was pointed at it; then v5 was scored
once, plus the GT-free Claim B sweep. Nothing else was run on these pages: **v1–v4 were never
computed**, which is the option `docs/plans/multiview-phase1-prereg.md` spent in advance.

Read this row with that file open. The short version: **A1 passes by one thousandth, and only
under one of the two readings of its own text; A2 passes cleanly; A3 passes on a page too small
to resolve it; B1 passes, B2 fails, and B3's answer turns out to sit one step upstream of where
the prediction looked.** And the fixture's guard case fired hard, in a place no pre-registered
prediction charges.

### Preparation and what it cost

Per set, anchor and candidate: orientation pinned → the hand-read page crop from
`testset/skewset_manifest.json` → UVDoc dewarp (`temp/mv_phase1b/prep.py`). **UVDoc held on all
eight frames, obliques included** — `method=uvdoc`, zero warnings — which is STEP 1's blocking
gate replicating on a new book and new viewpoints without being asked to.

Bands are `gt_far.json`'s definition reused verbatim, not re-derived: text-column coordinates
(edges = 2nd/98th percentile of the anchor's word boxes), `[.12–.24]` of the column width inward
from an edge, gutter on the spine side and far on the outer one. Geometry in
`temp/mv_phase1b/band_geometry.json`; the drawn thumbnails were checked by eye before keying,
because three of the four sets are the mirror of the original three and a side error would have
keyed the far band as the gutter.

GT size, which every delta below has to be read against:

| page | lang | gutter tokens | far tokens |
|---|---|---|---|
| `en_01` | eng | 91 | 115 |
| `en_02` | eng | 104 | 130 |
| `it_01` | ita | 77 | 60 |
| `de_01` | deu | **20** | 27 |

**Two keying decisions, both fixed in the GT file before a token was typed.**

*The anchor-primary rule.* The gutter GT is keyed on the frame that reads that band **worst** —
that is what makes the band interesting — so a word the anchor's photo renders illegible never
enters GT, and those are exactly the words a merge exists to recover. The rule adopted: key
anchor-primary (like-for-like with the original three), and anything only the candidate could
resolve goes in a separate `gutter_assisted` list the verdict never touches. Across four pages
that list holds **one token** — the place name *Pocòl*, which the anchor renders *Podòl*. So the
deflation this rule exists to expose is, on these pages, negligible.

*The band sits outside the smear, and was not moved.* The `[.12–.24]` ring is one band-width IN
from the column edge; the badly compressed text is in the innermost `[0–.12]` strip, which this
definition excludes — as it excluded it on the original three. On these pages the anchor is
therefore largely legible inside the ring. **The band was not widened to chase the smear**;
that would have destroyed the like-for-like replication the fixture exists for. It is recorded
as a stated limit on what A1 could ever show here, not repaired by moving the target.

### Claim A — v5, against the two single views

Gutter = the win (sequence recall, the pre-registered verdict metric). Far side = the guard
(bag recall, per A2). Order-free bag recall is printed beside the gutter as the diagnostic it
was built to be.

| page | role | n gut / far | GUTTER face-on | GUTTER v5 | **Δ seq** | Δ bag | FAR face-on | FAR v5 | **Δ bag** |
|---|---|---|---|---|---|---|---|---|---|
| `en_01` | win | 91 / 115 | 0.857 | 0.868 | **+0.011** | −0.011 | 0.887 | 0.939 | **+0.052** |
| `en_02` | guard | 104 / 130 | 0.865 | 0.365 | **−0.500** | −0.039 | 0.923 | 0.985 | **+0.062** |
| `it_01` | win | 77 / 60 | 0.831 | 0.922 | **+0.091** | +0.078 | 0.950 | 0.950 | **0.000** |
| `de_01` | control | 20 / 27 | 0.800 | 0.800 | **0.000** | 0.000 | 0.926 | 0.926 | **0.000** |

Decoy floors (each arm scored against the other pages' GT) run 0.004–0.134 against recalls of
0.365–0.985, so the metric is separating signal from noise everywhere except where noted below.

**A1 — "v5 raises gutter recall on pages that have headroom": PASS, by 0.001, under one reading
of two.** Mean gutter sequence Δ over the win cases `{en_01, it_01}` is **+0.0509** against a bar
of > +0.05 -- a margin of **+0.0009** -- and is strictly positive on 2 of 2. That is the addendum's bucketing, which was
pre-committed the same day *before* any scoring and is the more specific text, so it governs.

But A1's own body says "the headroom pages (**triage proxy > 0**)", and by that literal rule all
four pages qualify — `de_01`'s gain is 7 tokens, which is greater than zero. **Under the literal
reading the mean is −0.100 and A1 FAILS.** The verdict flips entirely on which sentence of the
pre-registration is read, and both numbers are reported here rather than the flattering one.

**And the margin is smaller than one hand-keyed word.** In tokens rather than ratios, the win
cases are `en_01` 78 → 79 of 91 (**one token**) and `it_01` 64 → 71 of 77 (seven tokens). One token
on `en_01` is worth 0.0055 of the win-case mean; A1 clears its bar by 0.0009, about a sixth of
that. Had that single word gone the other way the mean would be 0.0455 **and** "strictly positive
on a majority" would fail 1-of-2; had `it_01` scored six tokens instead of seven the mean would be
0.0445. The GT file's own keying rule calls edge words "a judgement call", and this row's verdict
turns on one of them. The same sentence written below for A3 applies here with more force: A1
passes exactly as pre-registered, **on a margin a fraction of the width of a single keying
decision**, and nothing finer than "the two win pages moved in the right direction" should be
read out of it.

**A2 — "the veto holds the far side": PASS, cleanly.** Mean far-side bag Δ is **+0.028** against
a bar of ≥ −0.05, and **no page loses anything at all** (worst case 0.000, bar 0.10). The far
side also improves on the *sequence* metric on all four pages (+0.060 / +0.092 / +0.066 /
+0.037), which A2 did not ask for. The dictionary veto is doing its job.

**A3 — "the no-headroom control stays flat": PASS, but unresolvable at this size.** `de_01`'s
gutter Δ is exactly 0.000, inside ±0.05. That page is figure-heavy with a single prose block, so
its gutter GT is **20 tokens** — one token is 0.05 of recall. A3's window is therefore exactly
one token wide here: the prediction cannot distinguish "flat" from "one word either way". It
passes as written and should not be quoted as evidence of anything finer.

A3 is also **vacuous under the literal reading that breaks A1**: it applies "on any page the
triage proxy calls zero-headroom", and under the literal gain > 0 rule no page is zero-headroom,
`de_01` included. The same ambiguity that flips A1 empties A3 of anything to apply to.

### The guard case fired, in a place no prediction charges

`en_02` is the set the pre-registration named in advance as "the set most likely to expose a
policy that swallows the oblique reading indiscriminately". It did:

* gutter **sequence** recall 0.865 → **0.365**, a loss of half the band;
* gutter **bag** recall 0.904 → 0.865, a loss of four points.

The two together bound what happened. v5 did **not** throw the words away — 86.5% of the band's
GT tokens are still somewhere in its output, but only 36.5% survive as an ordered subsequence.
What the pair licenses is precisely that: **the words are present and not recoverable in order**
— either genuinely mis-ordered, or interleaved with enough inserted tokens (80 insertions and 110
substitutions on this page) to derail the aligner, which `merge.py::matched_bag` flags as a real
alternative because the sequence scorer is difflib's recursive longest-match, not an optimal LCS.
Those two readings imply different repairs — geometry versus insertion policy — and **this run does
not distinguish them**. What it does establish is that the loss is not missing content. That is
the split the bag metric was printed for, doing the work it was added for: the verdict metric
alone would have reported a collapse without saying which kind.

**No pre-registered prediction charges this.** A1 excludes `en_02` by the addendum's bucketing;
A2 looks only at the far side, and only at bag recall. A policy can therefore wreck the reading
order of the very band the effort is about and still pass all three predictions. That is a hole
in the pre-registration, found by the fixture doing its job, and it is recorded as a defect of
the *predictions*, not explained away. Any future version of A1/A2 needs a term that charges
gutter order.

For the record the veto is not inert on that page: the oblique alone scores 0.308 sequence /
0.635 bag in that band, so v5's 0.365 / 0.865 is a large improvement **on the oblique** — and
still a rout compared with simply keeping the face-on frame.

**Verdict on shipping: v5 is not shippable on this evidence.** The pre-registration said "A1 or
A2 failing is a real negative result and will be reported as one". Neither failed outright, and
the outcome is arguably worse than a clean failure: a policy that wins about 0.05 on the pages
built to favour it, wins nothing on the control, and loses half the gutter's reading order on
the one page built to trap it. The word merge stays out of the pipeline.

### Claim B — the transform family (no GT involved)

Held-out |Δy|: fit on non-gutter correspondences, scored on gutter ones, so the model must
extrapolate into the band that matters. `merge.py`'s selector logic is reused verbatim with one
change — its inner band is hard-coded to `x < 0.40·W`, true of the original three pages and false
of three of these four, so the *side* is a parameter (`temp/mv_phase1b/score.py::_fit`).

| page | fit / held | selector | family it picked | fixed affine | bar (mwh/2) |
|---|---|---|---|---|---|
| `en_01` | 383 / 85 | 6.17 px | quadratic | 7.63 px | 14.0 px |
| `en_02` | 385 / 107 | 7.92 px | quadratic | **4.18 px** | 14.0 px |
| `it_01` | 175 / 48 | 9.31 px | quadratic | 14.04 px | 16.0 px |
| `de_01` | 88 / 24 | 6.28 px | affine | 6.28 px | 14.5 px |

**Deviation from the pre-registration, declared.** The prereg says Claim B "runs on **every** set
that passes gates A–C, not only the GT-keyed ones", because it needs no ground truth. It was run
on **four** — the GT-keyed sets only. Reason: Claim B is measured on the UVDoc-dewarped single
page, and no set outside these four has a valid page crop; all three automatic page-crop routes
were measured and rejected on this batch, and hand-reading crops for the remaining sets would
have competed with the GT budget this session was for. The consequence is stated rather than
buried: **B2's FAIL is a comparison of two four-set means**, and B1's "≥ 80% of sets" collapses to
a 4-of-4 bar. Widening Claim B's population is the cheapest outstanding item on this fixture,
since it costs hand crops and no keying.

**B1 — "fixed affine is under bar": PASS, 4/4.** Every set is under half a median word height.
With N=4, "≥ 80% of sets" is a 4-of-4 bar, and it is met.

**B2 — "fixed affine is no worse than the selector": FAIL.** Mean held-out |Δy| is **8.03 px for
affine against 7.42 px for the selector**, so the mean condition fails. The second half of B2
holds — affine loses by more than 2 px on exactly one set (`it_01`, +4.73) — but B2 required
both. **Per the pre-registration: the selector stays, and STEP 3's debt is recorded as
settled-negative.** The weak link named in STEP 3 is not closed; it is measured and kept.

Worth one sentence because it is the mechanism: affine is not uniformly worse. It is much
*better* on `en_02` (4.18 vs 7.92), where the selector chose quadratic on the non-gutter subset
and that choice extrapolated badly; it is much worse on `it_01` (14.04 vs 9.31), the page with
real curl. The selector's advantage is an average over disagreeing pages, not a consistent win.

**B3 — "scale change is where it breaks, if it breaks": measured, and the break is one step
earlier than the prediction assumed.** None of the four GT-keyed sets is multi-scale, so B3
cannot come out of the sweep above. It can still be measured, because a transform family can
only be compared where enough word correspondences exist to fit and hold one out — and that
needs no page crop and no GT. Gate B's own instrument, re-run on all four multi-scale sets with
the **corrected** anchors (`temp/mv_phase1b/b3.py`; the existing `wordstream.json` numbers could
not be quoted because they assume frame 0):

| | multi-scale (`en_coin_f/g/h/i`) | single-scale (`en_coin_a`–`e`) |
|---|---|---|
| sets with ANY frame pair clearing Gate B | **2 / 4** | 4 / 5 |
| best pair's correspondences | 60–180 | 174–287 |
| gutter correspondences on that best pair | 3, 20, 24, 3 | 1–74 |

So **the multi-scale failure is an alignment failure, not a transform-family failure**: on the
same book, the same curl and the same instrument, changing scale halves the fraction of sets
that can be fitted at all, and starves the gutter of correspondences in particular. B3 predicted
a scale finding rather than a family finding and got one — just upstream of the transform, at
the step that feeds it.

One caveat that keeps that table honest: it uses `wordstream.py`'s **automatic** page crop, the
route this fixture rejected for measurement, because Gate B was measured with it and the
comparison has to be like-for-like. On that route `en_coin_a` shows 11 gutter correspondences —
one under the floor — where the hand crop it actually entered the fixture with shows 13. The
floor is marginal and instrument-sensitive; the multi-scale gap above is much larger than that
sensitivity, which is why it is quotable.

### Limits, stated

* **The band excludes the worst of the smear** (see above). A1 was measured where the anchor is
  already largely legible, which caps how much any merge could have won. Not repaired, because
  repairing it would have voided the replication.
* **N=4, and one of the four is a 20-token control.** A1's headline rests on two pages, one of
  which moves by 0.011.
* **No Cyrillic.** The batch delivered English, Italian and German; v5's dictionary veto is
  untested on Cyrillic and no claim here extends to it.
* **The keying is one reader's judgement, by eye,** with band-membership calls at the edges.
  Recall is scored full-page, so a word keyed slightly off-band is still a real printed word the
  metric can fairly ask about — but the token counts, not the third decimal, are the resolution.
* **Exploratory, and labelled as such:** the gutter *bag* column and the far-side *sequence*
  numbers are diagnostics, not pre-registered verdicts. The `gutter_assisted` list (one token)
  was never folded into any score.

## Multi-view Phase 1 — Claim B on the widened population: the shortfall closed, B2 fails harder — 2026-08-18

The pre-registered run measured **Claim B on four sets** where
`docs/plans/multiview-phase1-prereg.md` promised "**every** set that passes gates
A–C, not only the GT-keyed ones". That row declared the deviation and named
widening as the cheapest outstanding item on the fixture, because it costs hand
page crops and **no ground truth**. This is that widening. Population: **11 sets**,
against 4. Verdict: **unchanged, and arrived at more decisively** — B1 passes
11/11, **B2 fails on both of its clauses** (at N=4 only one failed), so the blind
inner-band transform selector stays and STEP 3's debt stays settled-negative.

### The protocol was fixed in writing first, and then had to be amended

B2's failure at N=4 was already known, so every remaining choice here was
outcome-informed. **Addendum 2** of the pre-registration (committed before the
first widened fit) pinned the eligibility instrument, the frame-pair rule,
whether multi-scale sets enter B1/B2, that the widened population is
authoritative for the verdict — including replacing the selector if it now
passed — and that widening is not assumed to favour affine (B2's second clause
gets *harder* as N grows; B1's "≥ 80% of sets" becomes a real bar for the first
time, where at N=4 it was 4-of-4).

**Then the instrument it named disqualified itself.** Addendum 2 made the cheap
automatic-crop word-stream screen the eligibility rule, on the precedent that
Gate B was defined and reported on it. Re-run on all 20 sets with the corrected
anchors (`temp/mv_phase1c/screen.py`), it **fails two of the four sets the
scoring run itself measured and published** — `en_coin_a` and `de_ferr_a`, both
one short of the binding gutter floor of 12 — while over-counting 74 against 14
on `en_coin_e`. A rule that throws out the fixture's own published sets is not a
population rule. The **Amendment** replaced it with the version that removes
discretion rather than tuning it: **every Gate-A set is hand-cropped, and Gate B
is judged only on the hand crop.** A margin around the floor was rejected
explicitly — choosing its width after seeing which sets sit just under it is the
one thing the addendum exists to prevent.

That amendment was worth its cost. It moved sets in **both** directions:
`en_coin_g` fails the screen at 30/4 and passes the hand crop at 40/15, so the
screen-based rule would have silently dropped a measurable set as well as two
published ones.

### Population: 20 sets → 18 → 11

Gate A (orientation, unchanged from `gates.json`) rejects 2. The remaining 18
were hand-cropped — 4 already were, 14 read this session off a labelled 5% grid,
the same instrument and convention as `testset/skewset_manifest.json`'s
`page_crop`. Gate B (**≥ 40 correspondences, ≥ 12 of them in the spine-side
quarter**) then decides, on the hand crop only.

| set | lang | screen c/gut | hand c/gut | outcome |
|---|---|---|---|---|
| `it_ferr_a` | ita | 58 / 12 | 44 / **10** | out — gate B on the hand crop |
| `it_ferr_b` | ita | 156 / 52 | — | out — **gate A** (orientation) |
| `it_ferr_c` | ita | 100 / 44 | 93 / 27 | **in** |
| `it_ferr_d` | ita | 102 / 26 | 160 / 28 | **in** |
| `it_ferr_e` | ita | 0 / 0 | — | out — **gate A** (orientation) |
| `it_ferr_f` | ita | 285 / 83 | 308 / 49 | **in** |
| `it_ferr_g` | ita | 146 / 52 | 94 / 22 | **in** — carried over (`it_01`) |
| `it_ferr_h` | ita | 359 / 82 | 424 / 54 | **in** |
| `de_ferr_a` | deu | 85 / **11** | 120 / 12 | **in** — carried over (`de_01`) |
| `de_ferr_b` | deu | 105 / 85 | 107 / 35 | **in** |
| `de_ferr_c` | deu | 123 / 24 | 141 / 13 | **in** |
| `en_coin_a` | eng | 283 / **11** | 260 / 13 | **in** — carried over (`en_02`) |
| `en_coin_b` | eng | 174 / 27 | 272 / **2** | out — gate B on the hand crop |
| `en_coin_c` | eng | 198 / 1 | 172 / **3** | out — gate B on the hand crop |
| `en_coin_d` | eng | 245 / 37 | 259 / **1** | out — gate B on the hand crop |
| `en_coin_e` | eng | 287 / 74 | 326 / 14 | **in** — carried over (`en_01`) |
| `en_coin_f` | eng | 33 / 1 | 89 / **0** | out — gate B on the hand crop (multi-scale) |
| `en_coin_g` | eng | **30 / 4** | 40 / 15 | **in** (multi-scale) |
| `en_coin_h` | eng | 15 / 1 | 11 / **0** | out — gate B on the hand crop (multi-scale) |
| `en_coin_i` | eng | 18 / 3 | 24 / **3** | out — gate B on the hand crop (multi-scale) |

**The two columns barely agree.** Total correspondences track loosely; the
gutter count — the column that actually decides — does not. `de_ferr_b` goes
85 → 35, `en_coin_d` 37 → 1, `en_coin_g` 4 → 15. This is a result about the
instrument the gates were reported on, not a footnote: **a frame-relative
automatic crop cannot be trusted to say how many correspondences sit near the
spine.**

**Three crop boxes were wrong on the first read and were caught by a rendered
overlay before they became numbers**, which is why that check exists: on
`en_coin_f` and `en_coin_g` the candidate crop had taken the **facing** page (its
large left-hand text is the neighbour page, repeating the sliver the anchor shows
at its own edge), and on `en_coin_i` the spine had been read on the wrong side of
the target page entirely. All three would have fitted and produced plausible
numbers.

### Why the English single-scale exclusions are not a cropping error

`en_coin_b/c/d` fail with 172–272 total correspondences and **1–3** in the
spine-side quarter, which looks exactly like a crop that cut the gutter off. It
is not. Counting **words** (not correspondences) in that quarter of each dewarped
crop (`temp/mv_phase1c/diag_gutter.py`):

| set | anchor: words in the inner quarter | oblique: words there | oblique median conf |
|---|---|---|---|
| `en_coin_b` | 229 | 160 | **59.5** (anchor 93.5) |
| `en_coin_c` | 149 | 91 | 92.7 (anchor 90.8) |
| `en_coin_d` | 190 | 159 | **63.3** (anchor 89.8) |

Both frames read plenty of text there; almost none of it **aligns**. On two of the
three the oblique frame's spine-side confidence collapses to ~60 against ~90 on
the anchor — the smear producing boxes with wrong text, which is the phenomenon
the merge exists to attack, showing up here as a fittability failure instead. On
`en_coin_c` the confidence is high on both sides and the non-alignment is
unexplained; recorded as such rather than guessed at.

### B1, B2, B3 — as pre-registered

Held-out median |Δy|: fit on non-gutter correspondences, scored on the
spine-side ones, so the model must extrapolate. `score.py::_fit` is imported
**unmodified** from the four-set run.

**On Addendum 2's promised spine-side assertion — the obvious version of it is
worthless, and this row would rather say so than claim a protection it does not
have.** "The held-out band is on the spine side" **cannot fail**: `held` is
*defined* as the spine-side 24% of the span using the same `edge` variable the
check would read, so both branches agree by construction. That tautology was
written first, and the danger it was meant to cover is real and was measured
rather than imagined: re-running `it_ferr_h` with its side deliberately flipped
clears Gate B on 67 outer-quarter correspondences and reports **3.23 px against a
15.0 px bar** — a result indistinguishable from a true one. (A flipped
`de_ferr_b`, by contrast, happens to be caught by Gate B at 0 gutter
correspondences. That is luck, not a guard.)

What actually stands behind the sides here is therefore two things, neither of
them that assertion. First, the **rendered-overlay pass** over every crop box,
which is what caught the one genuine inversion (`en_coin_i`) and the two
facing-page crops. Second, a check that uses information from **outside** the
crop file: the screen measured which half of each spread carries more text, on
the *uncropped* anchor, before any of this existed — so where it detected a
gutter at all, its side is an independent witness, and `measure.py` now asserts
the hand-read side matches it. **Six of the seven newly measured sets have such a
witness and all six agree**; `en_coin_g` has none (the screen found no gutter on
that close-up), so its side rests on the overlay pass alone. Swapping the
tautology for the witness changed no number in the table below.

| set | fit / held | bar (mwh/2) | selector | affine | Δ (affine−selector) | family chosen |
|---|---|---|---|---|---|---|
| `de_ferr_a` (`de_01`) | 88 / 24 | 14.5 | 6.28 | 6.28 | +0.00 | affine |
| `en_coin_a` (`en_02`) | 385 / 107 | 14.0 | 7.92 | **4.18** | −3.75 | quadratic |
| `en_coin_e` (`en_01`) | 383 / 85 | 14.0 | 6.17 | 7.63 | +1.46 | quadratic |
| `it_ferr_g` (`it_01`) | 175 / 48 | 16.0 | 9.31 | 14.04 | **+4.72** | quadratic |
| `de_ferr_b` | 84 / 23 | 13.5 | 2.36 | 2.36 | +0.00 | affine |
| `de_ferr_c` | 117 / 24 | 15.0 | 2.50 | 2.50 | +0.00 | affine |
| `en_coin_g` (multi-scale) | 28 / 12 | 29.0 | 9.91 | 9.91 | +0.00 | affine |
| `it_ferr_c` | 70 / 23 | 18.0 | 6.53 | 9.58 | **+3.06** | quadratic |
| `it_ferr_d` | 129 / 31 | 17.5 | 1.83 | 3.20 | +1.38 | similarity |
| `it_ferr_f` | 228 / 80 | 15.5 | 3.33 | 6.22 | **+2.89** | quadratic |
| `it_ferr_h` | 323 / 101 | 15.0 | 3.67 | 3.56 | −0.11 | quadratic |

**B1 — "fixed affine is under bar": PASS, 11/11 (100%, needs ≥ 80%).** At N=4 this
was a 4-of-4 bar and said little. At N=11 it is a real bar and affine clears it
everywhere, including on the multi-scale set. **Affine is never disastrous** —
that is the honest reading of B1, and it did not weaken with more data.

**B2 — "fixed affine is no worse than the selector": FAIL, on both clauses.**
Mean held-out |Δy| is **6.32 px for affine against 5.44 px for the selector**, so
the mean condition fails. Affine loses by more than 2 px on **three** sets
(`it_ferr_g` +4.72, `it_ferr_c` +3.06, `it_ferr_f` +2.89) where at most one is
allowed, so the second condition fails too. At N=4 that second clause *held*
(exactly one set); widening broke it. **Per the pre-registration and Addendum 2
item 6: the selector stays, and STEP 3's debt remains settled-negative.**

**The mechanism, and it is not noise.** Four of the eleven sets are ties *by
construction* — the selector examined its inner band and chose affine itself, so
there is nothing to compare. The comparison lives on the other seven, and it
separates by **book**, not randomly: on all four Italian sets where the selector
picked a non-affine family it beat affine (three of them by more than 2 px), and
its single large defeat is `en_coin_a`, where it picked quadratic on the
non-gutter subset and that choice extrapolated badly into the gutter (7.92
against affine's 4.18). Curl earns the extra term; one flat English page punishes
it. The selector's advantage is still an average over disagreeing pages — but
with 11 sets it is an average over pages that disagree **by book**, which is a
better-understood average than the N=4 row could claim.

**B3 — "scale change is where it breaks, if it breaks": confirmed at the
hand-crop level.** Only **1 of the 4** multi-scale sets clears Gate B on its hand
crop, against **10 of 14** single-scale Gate-A sets. The earlier row measured
this with the automatic crop (2 of 4 against 4 of 5) and the hand crop reproduces
it. The single multi-scale set that entered (`en_coin_g`) is a **tie**: the
selector chose affine, so B3 contributes no evidence for or against the family —
the multi-scale finding remains an *alignment* finding, one step upstream of the
transform, exactly as the earlier row concluded. `en_coin_h` is the extreme case
and is recorded honestly in `crops.json`: under the pinned pair rule its anchor
and candidate are close-ups of **different pages** (p.242 and the facing p.243),
so their spine edges point opposite ways. It was cropped and measured anyway
rather than substituted, and Gate B rejected it at 11 correspondences — but the
rejection should not be read as Gate B adjudicating a fair comparison. A set
carries **one** spine edge, the anchor's, so for that candidate frame the crop
and the gutter count were computed against the wrong side: the measurement was
structurally meaningless before Gate B ever looked at it. Nothing downstream
depends on it, and the pair rule stays pinned.

### What this does to the four-set row

Nothing is retracted. The four-set numbers are reproduced exactly (they are
carried over, not recomputed) and are now a **subset** of an 11-set population
that reaches the same verdict by a wider margin. The one thing that changes is
how much the row is allowed to claim: B1 was a 4-of-4 formality and is now a
100%-of-11 result; B2's second clause passed at N=4 and fails at N=11. **The
widened population is the authoritative Claim B verdict**, per Addendum 2 item 6.

### Limits, stated

* **Still no Bulgarian, and no GT anywhere in this row.** Claim B needs none by
  construction; this says nothing about Claim A, about v5, or about Cyrillic.
* **The crops are one reader's judgement by eye**, at ~1–2% of frame width, with
  three first-pass errors caught by the overlay check and corrected. A crop that
  is 2% out moves the correspondence set slightly; it does not move a 6-vs-9 px
  comparison, but the gutter *counts* near the floor of 12 are exactly that
  sensitive — `it_ferr_a` (10) and `de_ferr_a` (12) are one reader's decision
  either way.
* **The population is what Gate B admits, and Gate B is measured after the
  dewarp**, so a set excluded here is excluded for fittability, never for having
  a bad transform. Seven of the eleven excluded/failing sets are English
  strong-curl coin pages; the surviving population is Italian-heavy (6 of 11),
  which is also where the selector's quadratic choice wins.
* **`en_coin_g` sits on the floor** (40 correspondences, 15 gutter, 28/12 split)
  and is the only multi-scale set in the population. Its numbers are a tie, so it
  cannot move B2 either way, but it does count toward B1's 11.
* Inputs, per-set outputs and the verdict computation are committed at
  `docs/data/multiview_claimB_widened.json`; the raw frames stay in
  `temp/zoomset_raw/batch_20260818/`, out of git, as the pre-registration fixed.

## Patch-mode PDF in one run, and what "searchable" actually survives — 2026-08-18

Two tracked gaps, closed together because one run answers both.

**Gap 1 — patch mode's PDF was never watched end to end.** Gate 5's own notes
recorded the boundary honestly: one run had produced real per-word crops in
`patch` mode, a *different* run had produced a downloadable PDF in the default
`flag` mode, and a patch-mode document's PDF was only ever *inferred* from the
two halves working separately. Since all three uncertainty modes are a
CLAUDE.md non-negotiable, the inference was not good enough.

**The run.** Two jobs, one live `uvicorn` (its PID recorded at launch and the
only PID killed afterwards), the same real image `testset/en_coins_01.jpg`
through the whole HTTP route each time — `POST /api/jobs?mode=…` → upload →
worker → `/assemble` → `/render` → `GET /render/pdf`. The **only** difference
between the arms is the mode the API was asked for, which is what makes the
image count below attributable rather than decorative.

| arm | words | words w/ patch crop | `<img class="patch">` | PDF bytes | embedded images |
|---|---|---|---|---|---|
| `patch` | 743 | 60 | 59 | 7,706,899 | **63** |
| `best_guess` | 743 | 0 | 0 | 7,252,222 | **4** |

The patch arm carries exactly **59 more embedded images**, matching its 59
rendered patch tags one for one; the 4 that both arms share are the figures.
A valid `%PDF` alone would have proved nothing — a patch-mode PDF with zero
patch images would look identical at that resolution.

**The 60-vs-59 is explained, not waved away.** All 60 crop files exist on disk.
The 60th word sits in a **running-header** block, and `strip_running_headers`
(on by default, a CLAUDE.md non-negotiable) drops that block from the render —
so its patch correctly never reaches the page. Accounting closes: 59 patch
images + 4 figures = 63.

**Gap 2 — "the PDF is inherently searchable" had never been measured.** The
same PDFs, plus Bulgarian `bg_01`, were scored by `tools/pdf_searchability.py`
(new): of the words Stage 08 was *asked to emit as text* (excluding stripped
header/page-number blocks, and excluding patch-replaced words, which SHOULD be
absent), how many does a reader's search find?

| document | words as text | pypdf verbatim | MuPDF verbatim |
|---|---|---|---|
| `en_coins_01` patch | 671 | 87.0% | **99.9%** |
| `en_coins_01` best_guess | 730 | 86.4% | **100.0%** |
| `bg_01` (Bulgarian, flag) | 742 | 99.6% | **99.9%** |

The two extractors disagree by 13 points on English, and the disagreement — not
either number — is the finding. Chromium's PDF output writes **one glyph per
`Tj` with an explicit `Td` displacement** (no run-level advances at all), so
every extractor must re-derive word boundaries from glyph geometry. pypdf's
threshold inserts a spurious space inside wide-glyph words (`Chapm arked`,
`M urphy`, `W hile`); MuPDF's does not. **The text layer is correct; one
extractor's word reconstruction is not.** This is written down mainly so a
future session that greps a rendered PDF with pypdf does not "discover" a
phantom OCR defect that no reader sees.

**Font embedding — the spec's owed follow-up is closed, with evidence.** The
old note said Chromium fell back to Times New Roman. It no longer does: the
only font in every PDF above is `AAAAAA+NotoSerif` (subset of the bundled
`pipeline/assets/fonts/NotoSerif.ttf`), whose cmap covers the Cyrillic block
**256/256**, and `bg_01` extracts 3,238 Cyrillic characters with 739/742 words
verbatim. Two caveats stated rather than implied: Chromium embeds Noto as a
**Type3** font (glyph procedures, no `/FontFile2` TrueType program), and an
A/B that re-rendered `bg_01` against a **static** `wght=400` instance of the
same family produced a byte-identical 73,173-byte PDF — same Type3 encoding,
same extraction. So the variable font is not what causes Type3, and swapping to
a static instance buys nothing in the PDF (it would only halve the standalone
HTML, at the cost of real bold). Bundled font left as is.

Inputs and outputs: `docs/data/patch_mode_pdf_20260818.json` (both arms' full
counts) and `docs/data/pdf_searchability_20260818.json` (per-extractor scores).
The two 7 MB PDFs stay out of git, under `temp/`, as the multi-view raw frames
do — a deliberate choice with a cost worth naming: these numbers are **auditable
but not re-derivable**, since the PDFs and their gitignored job folders are gone
once `temp/` is cleared. Re-deriving them means re-running the two arms, which
`tools/pdf_searchability.py` and the recipe above make cheap.

## Caption↔figure grouping DISCRIMINATED on a second book — side-set captions, and two false positives it exposed — 2026-08-18

The owner's last open grouping item was *"figure/caption grouping discrimination
→ needs a real page with two or more figures"*. It did not need a new capture.
`en_coins_01/02/03` — three spreads of *Chopmarked Coins*, in the testset since
2026-07-03 — carry **four subpages with two coin plates sharing one column, each
with its own caption**, which is precisely the discriminating shape `it_geo_06`
was built for, in a second book and a second language. Three block-order GT files
were authored for them (`testset/gt/en_coins_0{1,2,3}.blocks.json`; figure boxes
read off the dewarped pixels against a 100px coordinate grid, not copied from the
detector; proposed-by-Claude, NOT owner-validated, same standing as `de_01`).

### What the fixture found before any code changed

**Grouping recovered NOTHING on this book: 0 of 8 pairs, on 4 discriminating
subpages.** Every real caption abstained with *"no figure shares this caption's
column within the gap limit"*, and the reason is a layout the geometry arm could
not express:

> **the captions are SIDE-SET.** Each sits to the RIGHT of its coin plate,
> vertically inside that plate's band, with horizontal overlap of **exactly
> 0.00** and a gap of 11–36px. The arm required x-overlap ≥ 0.50 ("a caption
> belongs UNDER or OVER its figure"), so it rejected all ten captions in the book.

Worse, the pass was not merely silent — it emitted the **wrong** pairs. This
book's run-in `Description:` section labels are typed `caption` by
DocLayout-YOLO and sit 11–40px below a plate, *nearer to it than the real
caption is*, so on three subpages "Description:" was attached to a coin plate
while that plate's actual caption stood alone.

A third finding, on `en_coins_03`-right: **`figure_label` read the number 4 off a
photograph of an 1890 Honduras Peso.** No such number is printed anywhere on the
page — it is coin surface detail. That is a false positive against the
recognizer's stated "zero wrong reads" invariant, on the first non-Italian page
it has ever been run on. It mattered because a single recovered figure number put
the whole subpage into "this book prints figure numbers" mode, which suppressed
the geometry arm for both real captions.

### Three changes, each forced by one of those findings

1. **Side-set attachment shape** (`side_min_yov_frac` 0.50, `side_max_gap_frac`
   0.05 of page width). A caption may attach to a figure it sits BESIDE when its
   vertical span lies inside that figure's band and the horizontal gap is small.
   Candidate distance became `max(h_gap, v_gap)` so stacked and side-set
   candidates rank on one scale for the mutual-nearest and ambiguity tests.
   Sitting beside a figure is **weaker** evidence than sitting under it — a block
   beside a photo may belong to a neighbouring column — so the side-set shape
   additionally requires the block to declare itself a caption **in print** (a
   parsed `Fig. NN` header). Two independent signals for the weaker geometry.
   *This guard is load-bearing, not decoration:* `de_01`'s icon-sidebar Gehzeiten
   panel is typed `caption`, has y-overlap 1.00 with the page photo and sits 28px
   from it — geometrically indistinguishable from a real side-set caption, and it
   is not one. Without the print requirement the side-set rule pairs it.
2. **Caption-side numbering-regime guard.** Where any caption on a subpage carries
   a printed number, a block typed `caption` that carries none is not one of them
   and does not pair. This is what removes the three "Description:" pairs. It is a
   **deliberate reversal** of a documented behaviour (the old
   `test_geometry_still_runs_for_an_unnumbered_caption_on_a_numbered_page`); the
   cost is that a genuinely unnumbered caption on a page that numbers its others
   is now missed, and under the zero-wrong bar a miss beats a wrong pair.
3. **Figure-number plausibility** (`fig_number_window` = 3). A recovered corner
   label outside the span of the caption numbers on the SAME subpage is a
   misread, not a figure number — figures and captions on one printed page belong
   to one short run. This drops the coin's "4" (captions 104/105) while keeping
   the it_geo_06 trap defence intact: a label reading 26 beside a caption reading
   25 is a neighbouring figure and is kept, so C25 still abstains rather than
   grabbing the top-right F26 plate.

### Measured — all eight block-order fixtures, production code path

| fixture | pairs correct | **WRONG** | abstained | change |
|---|---|---|---|---|
| it_geo_04 | 1/2 | **0** | 1 | unchanged |
| it_geo_05 | 0/2 | **0** | 1 | unchanged |
| it_geo_06 | 5/6 | **0** | 1 | unchanged |
| it_geo_07 | 0/1 | **0** | 2 | unchanged |
| de_01 | 0/0 | **0** | 1 | unchanged |
| **en_coins_01** | **4/4** | **0** | 2 | was 0/4, plus 2 pairs on `Description:` labels |
| **en_coins_02** | **2/2** | **0** | 1 | was 0/2, plus 1 pair on a `Description:` label |
| **en_coins_03** | **2/2** | **0** | 0 | was 0/2 |
| **total** | **14/19** | **0** | **9** | was 6/19 |

**Non-regression is byte-identical**, not merely "similar": the full eval reports
for `it_geo_04`, `it_geo_05`, `it_geo_06`, `it_geo_07` and `de_01` diff clean
against their pre-change baselines — every tau, every segmentation count, every
abstain reason. All four English pairs on `en_coins_01`, both on `02`-right and
both on `03`-right come from the **geometry** arm; no figure number is recovered
anywhere in this book (correctly, now that the coin misread is filtered).

**The metric was sharpened, in the direction that can only hurt.** A pair whose
caption maps to a GT block the GT types as something OTHER than `caption` now
counts as **WRONG**, not "ungraded". Without this, the three "Description:" pairs
would have been scored as unadjudicated rather than as the defect they are.
Checked before adopting: `it_geo_07`-right's existing ungraded pair is anchored on
a block the GT does not list at all (`det3`), so it stays ungraded — the
sharpening flips nothing on the Italian fixtures.

### Verified on the production path, not just in the eval

Ran the real chain on `en_coins_01`: `run_all` 00→06 → `stage07_assemble` →
`stage08_render`. Assemble reports `captions=3 paired=2 (geometry) unpaired=1` on
each subpage, and the rendered HTML contains **four `<figure>` elements, each
carrying its own `Fig. 96/97/98/99` caption**, with the two `Description:` labels
emitted as standalone `<p class="caption">` — exactly the shape the eval graded.

### Honest limits

* **Side-set pairing does nothing for a book that sets captions beside its
  figures and prints no caption numbers.** That is the price of the print
  requirement, and it is a real gap, not a rounding error — but the alternative
  (a purely geometric side rule) demonstrably mispairs `de_01`'s icon sidebar.
* The `de_01` Gehzeiten pair would have been reported **ungraded**, not wrong,
  because that GT scopes the icon sidebar out — the metric could not have caught
  the regression. The print requirement is doing that work, not the metric.
* **Two GT-authoring compromises, both stated in the files.** `en_coins_02/03`
  grade only their RIGHT subpage (the facing pages carry one figure each and
  cannot discriminate). The identical `Description:` anchors on `en_coins_01`-left
  are distinguishable only by the eval's deterministic tie-break.
* **A new, unrelated defect this fixture surfaced and nobody has fixed:** on
  `en_coins_03`-right the chapter heading "Honduras" is emitted **last** instead
  of first (`tau +0.43`, `tau+figures +0.56`); every other block on that subpage
  is in exact GT order. Recorded, not patched.
* `en_coins_01`-left's single segmentation miss is its footnote line, which the
  detector does not find at all.
* **The caption-side numbering guard has an unmeasured cost.** It reverses an
  existing test: on a subpage where any caption is numbered, an *unnumbered*
  caption block no longer pairs at all. So a page mixing numbered figure captions
  with one genuinely unnumbered caption loses that one pair — a case that does
  not occur anywhere in this corpus (which is what the five byte-identical
  fixture reports prove), so the cost is **unmeasured, not absent**. It is priced
  deliberately: the guard is what stops a mistyped `Description:` label from
  claiming a plate, and a missed pair is an abstention while a wrong pair prints
  the wrong words under a photograph.

Suite **383 green** (was 376): +7 in `test_figure_grouping.py` covering the
side-set shape, its print requirement, the de_01 sidebar rejection, the detached
gutter-column rejection, both numbering-regime guards and the plausibility filter.

### Also this session: the raw capture drop folder was emptied into the testset

`1/` is the gitignored "raw capture drop folder (originals copied into testset/
with canonical ids)". Seven originals had never been copied across, including
**the entire 3-frame Bulgarian real-capture set** behind the 2026-07-18 Finding-2
cross-gutter descramble. All seven are now in `testset/` with manifest rows under
a new `frameset` category: `bg_taleb_01` (+ its two sibling frames) and the four
sibling frames of the `de_01`/`de_02` sets. They carry no ground truth and are
registered as real-capture samples, not graded fixtures.

## The icon sidebar becomes a picture, not noise — Finding 3 symptom 1, closed — 2026-08-18

The other open item the owner handed over was *"icon-sidebar junk text ordering →
your call"*. The 2026-07-18 note deferred it with the right reason attached: on a
climbing-guide page that star-rating / difficulty / walking-time / GPS pictogram
panel is **high-value structured information, not junk to drop** — so neither
rendering its OCR nor stripping it is acceptable.

**First correction to the premise.** The note describes "scattered noise blocks"
landing early in reading order. Re-measured today on `de_01`, the panel is not
what it was: on the eval's dewarp path it is **two** blocks (a 31-word `other`
column and a 30-word `caption` times-panel), and on the production path it is one
30-word block plus three slivers of 1, 3 and 5 words. Some of the original
symptom has aged out with the Stage-04 v0.2–v0.4 work. The remaining defect is
real, though: the panel's OCR is garbage
(`"2842 m (5 )N 4638379 LE 1.526074 46.38138"`) and it opens the page.

**Second correction, and the one that decided the design.** The facing fixture
`de_02` carries the same panel, and **its detector already types it `figure`** —
so on one page of this book the pipeline already does the right thing and renders
the pixels. The change is therefore a *normalization*, not an invention.

### The decision: an unreadable block is re-typed FIGURE

New `pipeline/unreadable_panel.py`, called by Stage 07 assemble. A block whose
text cannot be trusted is re-typed `FIGURE`, so Stage 08 renders the crop it
already renders for any figure. This is the block-level analogue of the per-word
`patch` mode CLAUDE.md mandates: where the recognizer fails, show the reader the
original pixels. **Nothing about ordering changes** — the note is explicit that
the panel's leftmost-first position is already correct, and this pass touches
typing only. The words stay on the block, so a user who disagrees re-types it in
the editor and gets the text back; `type_promoted` marks the change automatic so
the editor never mistakes it for a human edit.

**The test is adaptive, never a global cutoff** (CLAUDE.md's non-negotiable):
a block converts when its median word confidence falls below `conf_ratio` (0.75)
of **the job's own** median text-block confidence, and it carries at least
`min_words` (8) words. A uniformly poor scan drags the reference down with it and
nothing fires — only a block that is bad *relative to its own document* converts.

### Measured on the production path — 15 spreads, 326 assembled blocks

Ran the real chain (`run_all` 00→06 → `stage07_assemble`) on every testset
spread. **Exactly 4 blocks convert, and all 4 are unreadable junk:**

| spread | block | words | median conf | ratio to job reference | what it is |
|---|---|---|---|---|---|
| `de_02` | left #1 | 13 | 25.6 | 0.27 | garbled banner strip |
| `it_geo_05` | left #2 | 14 | 27.7 | 0.29 | stray glyphs off the watercolour map |
| **`de_02`** | left #3 | 37 | 59.0 | **0.63** | **the icon sidebar** |
| **`de_01`** | left #7 | 30 | 62.6 | **0.68** | **the icon sidebar (Gehzeiten panel)** |

Nothing fires on any Bulgarian, English or other Italian page. It fires on **both**
German spreads, so the rule is not tuned to a single page. The `min_words` floor
is where the sweep put it: at 5 it converts two more blocks, both still junk; at
**3 it starts converting real text** — the "English Version" headings, which OCR
at 32–41 because they are set in a coloured banner. The shipped floor keeps two
junk blocks of margin between it and the first false positive.

**Rendered output, `de_01`:** the Gehzeiten garbage is gone from the HTML text and
the left page now carries 3 figures (banner, panel, photo) instead of 2.

### Why the block-order eval cannot see this, and what that means

The decision needs word confidences, which exist only from Stage 05 onward, so
the pass lives in Stage 07 — while `tools/layout_order_eval` grades Stage 04.
`de_01`'s graded numbers are therefore untouched **by construction**, not by luck,
and the corpus sweep above is the measurement that stands in for them. Worth
naming because it cuts both ways: had this been done in Stage 04 it would have
broken `de_01`'s grading outright, since that GT carries no figure bboxes and
falls back to rank-matching figures — two extra figure blocks would have
re-labelled the page photo as the sidebar.

### Honest limits

* **Every converted block is a picture instead of searchable text.** That is a
  real loss, taken deliberately because the alternative on these pages is noise.
* **It does not clean up the whole sidebar.** On `de_01` the production detector
  fragments the panel, and the 1-, 3- and 5-word slivers left over
  (`"pas"`, `"Y 2842 m"`, `"1 [3 11.526074 N 46.38138"`) stay under `min_words`
  and still render as text. Lowering the floor to 5 would take the GPS sliver;
  it was not lowered, because that is one step from the first false positive.
* **The panel is still not structured information.** Rendering it as a picture is
  the honest fallback, not the feature the note imagines (parsing difficulty /
  duration / GPS into fields). That remains an owner modelling decision.
* A page-scoped id bug caught in testing is worth recording, because it was
  invisible to the unit tests until a real two-page job ran: `Block.id` is
  page-scoped, not document-unique, so keying the decision on the bare id turned
  block 7 of BOTH `de_01` pages into pictures — the icon panel on the left and
  the English translation column on the right. The decision is now keyed on
  `(page, id)`, with a regression test.
* **The seam with caption↔figure grouping is latent, not exercised.** Stage 07
  pairs captions first and runs this pass second, so a block can be paired as a
  caption and *then* converted to a picture. Nothing in the 326-block corpus is
  both — a convertible caption would need a printed `Fig. NN` *and* confidence
  under 0.75× reference *and* ≥ 8 words. Checked and pinned rather than assumed:
  the association is recorded **only on the caption** (`Block.figure_ref` →
  figure; the figure's `figure_number` is a number read off the photo, not a
  caption id), so clearing the caption side leaves nothing dangling, and Stage
  08's pair resolver drops the converted block on both counts — its figure
  renders uncaptioned instead of bound to a picture.

Suite **397 green** (was 383): +14 in `test_unreadable_panel.py`, most of them
about the pass staying silent — on ordinary text, on a uniformly bad scan, on
fragments, on headers/figures/tables, and on the page-scoped-id case.

## The hover gate gets real numbers, and the calibration screen gets a mode — 2026-08-19

First on-device session with a phone (Galaxy S23, SM-S911B) over a real book.
`SHARPNESS_THRESHOLD` / `STABILITY_THRESHOLD` had been placeholders since M3 —
40 and 6, guessed, because the on-device metric (variance-of-Laplacian over a
320×240 luma buffer) is not on `stage00_ingest.py`'s absolute scale and could
not be copied from the pipeline. They are now fitted from 1787 labelled frames.

**The instrumentation had to be fixed twice before it could produce data**, and
both failures were the same shape: the screen captured a photo and navigated to
review before the calibration button could be used.

* Round 1 suspended auto-capture *while* logging. Stopping a log re-armed it
  instantly — and a passing streak is 8 frames, about three tenths of a second
  — so the burst fired before the "saved N frames" line could be read, and a
  second recording could never be started. The manual shutter also stayed live
  during a recording, one thumb-width below a button promising nothing would be
  captured.
* Round 2 made arming a mode that persists, but it still started ON, so the
  screen was gone 0.23 s after it appeared. The mode now lives in
  `MainActivity`, starts **off**, and survives Discard → re-enter.
* Hoisting it introduced a staleness trap worth recording: the analyzer lambda
  and the `takePicture` callbacks are created once, so they capture the
  parameter's value at creation time. A shot started while armed would add
  itself to the burst after disarming, and the *next* finalize would hand off a
  photo taken minutes earlier as the current spread. Everything outside
  composition reads through `rememberUpdatedState`.

### The numbers

| recording | frames | sharpness (min / p50 / max) | stability (min / p50 / max) |
|---|---|---|---|
| 1 steady hold | 696 (23.2 s) | 492 / 1116 / 1147 | 0.4 / 1.1 / 13.2 |
| 2 deliberate motion | 633 (21.1 s) | 12 / 358 / 2166 | 2.2 / 14.1 / 67.8 |
| 3 realistic use | 458 (15.4 s) | 112 / 933 / 1232 | 1.1 / 7.2 / 34.1 |

Applied: **sharpness ≥ 400, stability ≤ 3.1**. Fires on 89% of steady frames
and produces **zero bursts** across the entire 21 s moving recording; every
looser stability value fired at least one false burst. The old placeholders
would have passed 97% of steady frames *and* 7.9% of moving ones.

**The fitted sharpness optimum (930.1) was deliberately overridden to 400.**
With stability pinned at 3.1, the sharpness threshold changes no outcome
anywhere between 0 and 930 — the metrics are correlated, since a moving frame
is also a blurry one, and stability is doing all the separation. That makes
930.1 unvalidated precision fitted to one book under one light: on a dimmer
page whose whole sharpness range sits lower it would stop the gate firing at
all, silently and undiagnosably. 400 sits below the steady recording's observed
minimum (491.6), so it rejects nothing a genuine hold produces, while the case
sharpness actually exists to catch — still but out of focus — fails visibly on
the review screen. That case appears in none of the three recordings and
remains unmeasured.

Raw logs committed as `docs/data/hover_calibration_20260819_{1_steady,2_moving,3_mixed}.csv`;
distributions and the fitter's own suggestion in
`docs/data/hover_calibration_20260819.json`, annotated with what was applied.

**Not yet closed.** Auto-capture still starts disarmed. The replay says one
burst per 15 s of realistic use, and whether that feels right or sluggish is
the one thing a replay cannot answer — it needs a confirmation run on the
device with the gate armed by hand. The default flips only after that.

### Addendum, same day: one still per hover was not enough — hysteresis

Owner feedback after the armed confirmation run: firing felt right, but *"a
single frame won't be enough in practice."* Correct, and worse than it looks.
`HoverGate.onFrame` called `reset()` the instant one frame failed, so with a
strict threshold a single marginal frame collapsed the whole burst. Replay on
the three logs: **one still per hover** in realistic use. Stage 01's own
docstring says it expects the opposite — *"handheld bursts give several near
duplicates; the sharpest wins"* — selecting on Stage 00's **full-resolution**
sharpness, which is strictly better evidence than the 320×240 analysis-frame
proxy the phone was using to throw the others away.

Two changes, both measured on the same three recordings:

* **Entry and hold are now different tests** (`stabilityThreshold` 3.1 to open,
  `holdStabilityThreshold` 6.0 to stay open). Realistic use goes from 1 still
  per hover to **4**, and the moving log still produces **zero** bursts —
  because the eight-consecutive-frame entry test is what prevents false
  captures, and strictness after that buys nothing. A grace-frames knob was
  prototyped and dropped: the sweep showed it inert (`/0` and `/3` both gave 4).
  Hold 8.0 gave 5 stills but the cap is 4, so it was unreachable — unmeasured
  risk for nothing.
* **The whole burst is uploaded**, best-guess first, instead of the phone
  keeping one. `pickSharpest` is kept, unused, with a note saying selection
  moved to Stage 01 — it stays correct for a future keep-one mode on a slow
  link.

`simulate_gate` in `tools/calibrate_hover.py` gained the same hysteresis, or
its replay would have kept reporting the old one-still-per-hover figure as if
it were current. Replay against the shipped constants: steady 15 bursts /
54 stills, **moving 0 / 0**, mixed 1 burst / 4 stills.

Costs, recorded rather than discovered later: about 4× the bytes per spread,
and `uploadSpread` retries the whole multipart request up to 4 times on an
`IOException`, so a flaky link multiplies that. Fine on a LAN.

## First real spreads reach the pipeline: one missing step upstream broke three of four — 2026-08-19

Four spreads were captured with the Android app and uploaded over Wi-Fi to the
desktop server (job `20260819-064025-6b4cc4ac`, mode `flag`). All four ran the
full seven stages and exited 0 — no crash, no stall, no lost page. That is the
first end-to-end proof of the Gate 5 path on real camera photos, and it is the
good news. Everything below is what the photos then found.

The originals are committed as `testset/zoomset_*` (16 images, four sets, no
GT) so every number here is reproducible without `jobs/`, which is gitignored.

### The control comes first

`zoomset_de_02` is the one spread whose gutter was found correctly. Both its
subpages OCR'd well — 293 words at mean conf 77.4 and 385 at 73.7, real German
running text. Stages 03–06 are therefore **not** the problem on real captures.
Everything that went wrong went wrong before them.

### Finding 1 (CRITICAL): no book-boundary crop — 1 of 4 gutters correct

The photos were shot with the book on the photographer's lap, so 40–55 % of
each frame is room: floor, desk, cables, a chair. Stage 02 searches the whole
frame for the spine and on three of four spreads preferred a stronger vertical
valley elsewhere — twice the book's own **outer edge**, once the clutter to the
left of the book.

| set | gutter_x / width | what it hit | result |
|---|---|---|---|
| `zoomset_de_01` | 2855 / 4080 (70 %) | book's right outer edge | left.png = whole spread (566 words), right.png = background (14 words) |
| `zoomset_de_02` | 1631 / 4080 (40 %) | **the spine** | both subpages good |
| `zoomset_en_01` | 1272 / 4080 (31 %) | clutter left of the book | left.png = background (8 words), right.png = whole spread |
| `zoomset_en_02` | 2705 / 4080 (66 %) | book's right outer edge | left.png = whole spread (319 words), right.png = background (4 words) |

Every one of them reported `confident: true` and `corroborated: true`. The
corroboration is between two cues (ink-ratio and spine-pinch) that agree with
each other on the wrong edge, so confidence here is not evidence.

The pipeline has no step that finds the book in the frame. Every fixture until
now was a tightly framed spread, so the gap never showed. Neither a better
valley metric nor a capture-side framing guide addresses it on its own: the
missing thing is a page/book-boundary crop between fuse and split.

### Finding 2 (HIGH): Stage 01 stitched 0 of 11 close-ups — starved of features, not blocked by clutter

Every close-up on every page was rejected by the `min_inliers = 25` gate.
Four never reached 25 *good matches* at all, so RANSAC never ran on them (16,
19, 21, 23 good). The other seven ran it and came back with 3, 4, 5, 9, 13, 21
and 21 inliers. Eleven close-ups, eleven rejections.

Two candidate causes were separated by measurement rather than argued:

- **Clutter** — the anchor for `zoomset_de_01` was cropped to the book by hand
  and the stitch re-run. With the shipped feature budget one close-up crossed
  the gate (21 → 27 inliers) and the other barely moved (9 → 11).
- **Feature budget** — raising ORB's `nfeatures` from 4000 to 20000, changing
  nothing else, took the whole batch from **0 of 11 to 4 of 11** stitched
  (`de_01_f02` 21→43, `de_02_f02` 13→31, `en_01_f03` 5→27, `en_02_f05` 21→46).
- **Both together** added almost nothing over the budget alone (`de_01_f02`
  43 → 46, `de_01_f01` 15 → 16).

So the clutter hurts the **split**, not the stitch. 4000 ORB features spread
over a 12 Mpx frame is simply too thin to describe a page. Not shipped — this
is a measurement on committed fixtures, and the gate constant wants re-deriving
alongside it (`min_inliers` currently gates two different quantities, the
good-match count *and* the RANSAC inlier count, with one number).

### Finding 3 (OPEN): more features is not the whole story either

Seven close-ups still fail at 20000 features, and one of them, `en_02_f02`, got
*worse* — 5 inliers at 4000 features, 3 at 20000. Five times the descriptors
bought it nothing but noise, which is not what "starved of features" predicts.

Where the surviving inliers sit was checked as a possible tell and **does not
separate the two groups**: three of the seven failures have their inliers
spread as widely across the frame as the four that pass (`de_01_f01` 0.72 of
the width and only 15 inliers, `en_01_f02` 0.80 and 17, `en_02_f03` 0.79 and
21). So "the agreement is local" is not what distinguishes a failed close-up
here, and the statistic is recorded only so nobody re-derives it.

What remains is the shape of the problem rather than a measurement of it: a
homography assumes the thing being matched is flat, and Stage 01 stitches
*before* Stage 03 flattens. Page curvature is the obvious suspect. It is a
hypothesis with a plausible mechanism and no evidence yet, and nothing in this
batch decides it.

### Finding 4: the OSD 180° blind spot, confirmed in the field

`zoomset_en_01`'s anchor was rotated 180° on an OSD call of confidence 2.49,
just over the `min_osd_conf = 2.0` gate, and the delivered page is upside down
(782 words at mean conf 33.4, reversed glyphs). This is the already-pinned
known defect firing on a real capture for the first time, not a new one, and
the fix already identified still applies: the phone knows its own orientation
and the capture-hint arm of `tools/normalize`'s cascade is still a stub.

Secondary, same area: 11 of the 16 frames could not be oriented from EXIF or
OSD with any confidence, and four close-ups came out portrait with an explicit
"a book spread should be landscape" warning.

### Finding 5 (LOW): a second full-spread frame is silently discarded

`zoomset_en_02` carried two full-spread frames (the app now uploads the whole
auto-capture burst). `partition_frames` chose the sharper as the anchor and
dropped the other without a warning — only *smaller-area* frames are eligible
to be stitched. That is the documented behaviour, and it is the right default
for a burst of near-duplicates, but it means additional full-page views of a
spread cannot contribute anything today.

### Addendum: how much does tighter framing actually buy? — 2026-08-19

"Fill the frame" is not measurable advice, so it was measured. Each of the four
`zoomset_*` anchors had its book box and true spine hand-read off a 5 % grid
(the `skewset_manifest.json` convention — no automatic page-crop route is
trusted on this batch), was then cropped to the book box grown by a margin on
every side, and `detect_gutter` was re-run on the crop with the shipped params.
`fill` is the book's width as a fraction of the crop's width; 1.00 means the
book runs edge to edge. Data: `docs/data/framing_fill_sweep_20260819.json`.

| set | fill as shot | correct as shot? | tightest fill still wrong | loosest fill still correct |
|---|---|---|---|---|
| `de_01` | 0.64 | no | 0.75 | **0.83** |
| `de_02` | 0.59 | **yes** | — | 0.59 (as shot) |
| `en_01` | 0.51 | no | 0.51 | 0.57 |
| `en_02` | 0.47 | no | 0.54 | 0.59 |

**All four split correctly once the book covers ≈ 0.83 of the frame width.
Three of four are already correct at ≈ 0.57.** As shot, at 0.47–0.64, one of
four was correct. So the instruction that follows from this is a number, not an
adjective: *the book should span at least four-fifths of the picture's width.*

`de_01` is the demanding one and it is worth knowing why: its true gutter is a
weak ink valley (the top photo spans the spine), so it never resolves by ink at
all — it goes through the `pinch` cue at every crop, including the tightest.
The worry that cropping the room away would starve that cue of the dark
background it assumes did **not** materialise here. Whether a *pale* background
hurts it is untested.

Caveat on the method: cropping in software changes framing only, not
perspective or resolution. That is the right proxy for a gutter finder, which
sees framing, and the wrong one for anything about sharpness, curvature or
dewarp.

### The one rotation nothing can contradict - 2026-08-19

Stage 00's orientation cascade trusted Tesseract OSD equally on all four
rotations. It should not: a wrong 90/270 changes the page's aspect ratio, so the
cascade's landscape prior catches it, but **a spread turned 180 degrees is still
landscape**, so the layer that exists to catch mis-orientation is blind to the
most likely error. OSD was unsupervised on exactly that branch, and OSD at
confidence 2.5 is noise - which is why the Android app's first real upload
(`zoomset_en_01`) came back upside down, 782 words at mean confidence 33.4.

Both populations were measured before choosing a number. Data:
`docs/data/stitch_and_orientation_20260819.json`.

| population | n | how it was obtained | confidence range |
|---|---|---|---|
| **wrong** 180 calls | 7 | OSD said 180 on a buffer the orientation GT records as already upright | 0.24 - **3.09** |
| **correct** 180 calls | 25 | every testset frame rotated 180 on purpose, so 180 is known-right | **8.40** - 32.70 |

The populations do not overlap. `DEFAULT_MIN_OSD_CONF_180 = 5.0` is the
geometric midpoint (5.09) of the 3.09/8.40 gap - the same ~1.6x safety ratio on
each side. 90/270 keeps the old 2.0 floor, which is what still lets the
multi-zoom close-ups (real 270-degree rotations at confidence 2.0-17.6) be
corrected.

**Rejected, and measured rather than argued:** flip-and-compare - re-run OSD on
the flipped buffer and accept the 180 only if it then reads 0 degrees more
confidently. It looked like the threshold-free answer and it has *no*
discriminating power. On 6 of the 7 wrong calls OSD repeats the same wrong
answer on the flipped buffer, and on three of those at **higher** confidence
(2.49 -> 6.82, 0.92 -> 2.03, 0.24 -> 4.68). OSD is self-consistent when it is
wrong; asking it twice buys nothing.

Non-regression is by construction: all 15 flat testset spreads read
`osd_rotate = 0`, and a floor cannot change what happens to a zero. The two
frames pinned in 2026-08 as known resolver defects (`skewset_orient_01_134655`,
`skewset_orient_02_134731`) now resolve net-0, so their `known_defect_*` keys
were **deleted** - which is what the fixture's own note instructed - rather than
the assertion loosened. `zoomset_en_01_f00`, the wild instance, was added.
**28 orientation fixtures, all net-0.** Suite 425.

**Honest limit.** This is a refusal, not a detector. A page that genuinely *is*
upside down but figure-heavy scores 0.95-2.23 (the `de_*` family, measured the
same way) and will now be missed - the same wrong output as before, from the
opposite cause. Only cascade layer 1, the capture hint, knows which way up the
phone was, and it remains unwired end to end: `hint_rotate` has no caller in
Stage 00, the server, or the app.

### The gate was the bug, not the feature budget - 2026-08-19

The 2026-08-19 arrival note recorded that Stage 01 stitched **0 of 11** real
close-ups because ORB was starved (4000 features over a 12 Mpx frame), and that
raising the budget to 20000 took it to 4 of 11. Both halves are wrong, and the
reason nobody could tell is that **the inlier count is produced by the matcher,
so it cannot referee a change to the matcher** - a bigger budget inflates it
whether or not the fit improved. Re-measured with a correctness signal that does
not come from the matcher: warp the close-up and take the normalized
cross-correlation of its pixels with the anchor's over the footprint. Verified
by eye on full-resolution checkerboard overlays - NCC >= 0.45 lines up across
every tile seam, NCC <= 0.28 does not. Data:
`docs/data/stitch_and_orientation_20260819.json`.

| claim in the arrival note | what re-measurement says |
|---|---|
| 0/11 register; ORB is starved | **5 of 11 were located CORRECTLY by the shipped settings** - 9, 12, 13, 21, 21 inliers - and thrown away, because `min_inliers` was 25. Every correct registration in the corpus scores *below* the gate meant to admit it. |
| 20000 features -> 4/11 | It finds the same five and adds a **false positive**: `en_01_f03` reaches 27 inliers on a warp that puts grass and sky where the anchor has text. Shipping the budget change alone would have blended wrong pixels into pages. **Not shipped**; `orb_features` stays 4000. |

One overloaded constant became five gates asking five different questions:
enough matches to fit at all (a *precondition* - the good-match count overlaps
completely between right and wrong registrations, 21-58 vs 16-36, so it must
never be a quality gate), RANSAC consensus (**25 -> 8**, sitting in the measured
3-7 / 9-21 gap), that consensus as a fraction of the evidence, photometric
agreement, and finally whether blending actually helps.

**And then the registrations turned out not to be worth having.** Blending the
five correct ones made OCR *worse* on every spread that had any:

| set | words | mean conf | words at conf >= 80 |
|---|---|---|---|
| `de_01` (2 blended) | 530 -> 450 | 84.3 -> 67.6 | **435 -> 257** |
| `de_02` (1 blended) | 322 -> 210 | 69.9 -> 67.6 | 183 -> 120 |
| `en_02` (2 blended) | 288 -> 197 | 73.0 -> 71.3 | 160 -> 102 |

Not a matcher problem. A close-up is nearer the page but handheld at longer
focal length, and it must be warped *down* into the anchor's coordinate frame to
be blended. Measured linear scale is 0.71-0.94, so there was almost no extra
resolution to bank, and resampling spends more than that: over the identical
footprint pixels **all five are softer than what they replace** (sharpness ratio
0.49-0.83). Hence a fifth gate, `min_sharpness_ratio` - a close-up must prove it
*improves* the region, not merely that it belongs there.

**Net on the zoomset: 0 of 11 blended, the same count as before - but by a
stated measurement instead of by accident, and Stage 01's output is now
byte-identical to the anchor rather than worse than it.**

Also fixed: close-ups were matched against a base that earlier stitches had
already repainted, so the outcome depended on the order the phone shot in
(`en_02_f05` fell from 21 inliers to 5 for that reason alone). Matching is now
against the pristine anchor, blending into a separate accumulator. The debug
overlay finally draws the footprints its docstring always promised - green
accepted, red refused - because a wrong registration is obvious in a picture and
invisible in a number.

**Where the close-ups' value actually is, and it is not as patches.** These
close-ups are whole-spread re-zooms, so each frame can be OCR'd on its own and
compared directly (words at confidence >= 80):

| set | anchor | close-ups |
|---|---|---|
| `de_01` | **435** | 221, 173 |
| `de_02` | 183 | **270**, **249** |
| `en_01` | **167** | 120, 0, 2 |
| `en_02` | **160** | 96, 3, 121, 7 |

On `de_02` the close-ups read **47 % more high-confidence text than the chosen
anchor**, and Stage 01 rejected the better one and blended the other *downward*
into the worse image. So a close-up is sometimes not a patch at all but a better
photograph of the whole page - and `partition_frames` cannot express that. It
ranks anchors by variance-of-Laplacian over the **whole frame**, and these
frames are 40-55 % room, so the score rewards cluttered backgrounds (chair
edges, cables) over legible text. **Reported, not fixed:** it changes which
pixels represent the page, and it needs the same book-boundary crop the gutter
split wants (see the framing addendum above).

**Left unsolved, mechanism now identified rather than suspected.** The six
close-ups that no setting registers (`en_01` f01-f03, `en_02` f02-f04) are all
oblique views of a strongly curved page - a cylinder seen near edge-on. A
homography assumes a plane and Stage 01 runs *before* Stage 03 flattens, so
those frames are outside the model rather than badly matched. That is capture
guidance or register-after-dewarp, not matcher tuning. SIFT was measured in the
same sweep: it registers one of the six (6/11 vs 5/11) at ~1.6x the time, and is
wired behind `feature_engine` rather than swapped in, because CLAUDE.md
documents ORB as this stage's tool.

**Caveat that applies to every number above:** the `zoomset_*` fixtures have no
ground truth. Word counts and confidences are *indicative*, not accuracy; they
are reported alongside the visual registration proof, not instead of it.
Suite 425.

## Finding 1 closed: the pipeline can now find the book in the frame — 2026-08-19

Stage 02 v0.3.0 + new `pipeline/book_boundary.py`. Evidence:
`docs/data/book_boundary_crop_20260819.json`. Both arms below run the same code;
"before" is `book_crop.enabled: false`, which is exactly the shipped v0.2.0
behaviour, so the comparison is like-for-like rather than a re-implementation.

**The gutter, which is the load-bearing metric.** Graded by `tools/split_eval`
against `testset/gt/gutter.json`, now including four newly hand-labelled rows for
the real captures (read off the anchors at 1.3x zoom with a ruler overlay, from
the left page's right edge and the right page's first content column —
independent of every cue the detector computes; the read bands are recorded in
the GT file's `_doc`).

| spread | before | after | GT | was | now |
|---|---|---|---|---|---|
| `zoomset_de_01` | 2855 | **1684** | 1675 | book's right outer edge | 9 px |
| `zoomset_de_02` | 1631 | **1626** | 1631 | already correct | 5 px |
| `zoomset_en_01` | 2807 | **1616** | 1615 | clutter left of the book | 1 px |
| `zoomset_en_02` | 2705 | **1623** | 1660 | book's right outer edge | 37 px |

**16/19 → 19/19** — read that as the *previous* detector graded against the
*now-complete* GT set, since the four `zoomset_*` rows were labelled in this same
commit; the harness itself only had 15 rows before today, and scored 15/15 on
them. The fifteen pre-existing spreads are untouched — not
"still passing", *untouched*: the crop refuses to fire on every one of them, so
they run the byte-identical path they ran before this module existed.

`zoomset_en_01`'s "before" column is 2807, not the 1272 published in the table
above. That is not a regression: the earlier number came from the pre-OSD-fix
anchor, which was delivered upside down. Same spread, different input.

**Two boxes, because one cannot do both jobs.** This was built the obvious way
first — one book box, used to aim the search *and* to cut the pages — and the
obvious way is wrong, by measurement in both directions:

- the bright-paper mask's own bbox padded 2 % **clips up to 32.8 %** of a
  hand-labelled book (`de_02`: its orange side strips and header are saturated,
  so a "low-saturation paper" mask simply does not see them);
- padding until nothing clips (20 %) grows that box to **80-99 % of the frame** —
  a crop that no longer crops;
- and going the other way, using a generous box to aim the search puts the gutter
  straight back onto the outer edge (**17/19**).

So the search box is percentile-trimmed and modest (thin bright leaks — a white
cable, a pale chair edge — carry almost no pixel mass, so the 2nd/98th
percentiles ignore what dragged the bbox to the frame border), and the emit box
is grown by GrabCut seeded from the same paper region, which crosses the coloured
page areas the mask misses. **Clipping of the six hand-labelled books: 0.0 %, all
six** (`testset/gt/book_box.json`, a deliberately diagnostic file — the gutter GT
stays the metric). Clipping first reaches zero at 4 % pad; 6 % ships.

**The abstain gate is justified by a harm, not just by a gap.** Emit-box area is
65-80 % on the four lap captures and 85-100 % on the fifteen that need nothing, so
the gate sits at the midpoint, 83 %. The narrow half of that gap is `de_01`/`de_02`
at 85 %/89 %, and cropping them is not merely unnecessary — cropping `de_02`
moves its gutter **from 7 px off ground truth to 96 px**, because the ink valley
turns "confident" on the cropped frame and outranks the spine-pinch cue that had
been right. A frame the book already fills has nothing to gain and that to lose.

**What it is worth downstream, from the real seven-stage run** (`pipeline.run_all`,
mode `flag`, both arms):

| set | before: left / right | after: left / right |
|---|---|---|
| `zoomset_de_01` | 410 / **0** | 192 / 195 |
| `zoomset_de_02` | 204 / 244 | 202 / 200 |
| `zoomset_en_01` | 426 / **0** | 66 / 292 |
| `zoomset_en_02` | 226 / **0** | 119 / 153 |

(words at conf >= 80). The claim those numbers support is **structural**: on three
of four spreads one subpage was background and one held the whole spread, and now
all four yield two real pages. They do **not** support a fine-grained accuracy
claim in either direction — whole-image OCR at psm 3 was measured to churn ±60
words in *both* directions under nothing but reframing, so the totals are noise at
this precision.

The one spread that was already correct, `zoomset_de_02`, is the control, and it
is a **wash**: OCR'd directly off the dewarped pages (which removes Stage 04's
block routing from the comparison) it goes 191 → 172 on the left and 216 → 220 on
the right. Its `right.png` did lose 544 columns — of *room*, not page: 2489 px
wide before, 1945 after, at no measured cost.

**Caveats, stated rather than buried.** n = 4 real captures and 6 labelled books,
one photographer, two books, one lighting setup, all lap shots; the thresholds
separate cleanly on that corpus and have been seen on no other. The paper mask
assumes the page is the brightest low-saturation thing in frame — a white desk or
a paper-covered table would break it, though the guards make the failure "no crop"
rather than "wrong crop". `partition_frames` still ranks anchors by sharpness over
the whole frame and so still rewards clutter; that item is untouched here, and
`book_boundary.py` is a plain module precisely so Stage 01 can import it.
Reproducibility: the four `zoomset_*` GT rows read from committed `testset/` JPEGs
(verified pixel-identical to the Stage 01 anchors), but the older `de_01`/`de_02`
rows still resolve through `ANCHOR_OVERRIDE` into gitignored `jobs/orient_fix_de*`,
so those two rows are not reproducible off this machine. Suite 437.

## Anchor choice: the window was not the problem — 2026-08-19

Two stage docstrings carried the same open item. `partition_frames` picks the
anchor as the sharpest full-spread frame, sharpness is variance-of-Laplacian over
the **whole** frame, and on a lap capture that is 40–55 % room — so the score
rewards a cluttered background over legible text. Both notes said the fix needed
the book-boundary crop, and the crop shipped this morning. This is that question,
asked before the change was written rather than after: **rank the candidates
inside the book box instead.** The answer is no, and the reason is structural.

`tools/anchor_choice_census.py` runs it over every committed fixture holding more
than one frame of the same spread — 13 sets, 34 frames, three families (the four
multi-zoom sets, the six multi-view pairs, and the three re-shoot triples in
`manifest.csv`). Ten of the thirteen contain an actual anchor race. Each set is
partitioned by `stage01_fuse.partition_frames` itself, imported unmodified, under
three scores, and each frame is OCR'd standalone (Tesseract psm 3, conf ≥ 80 word
count **and** mean confidence) so the picks can be graded against something other
than the metric being tested.

**The instrument had to be fixed before it said anything.** Loading these JPEGs
EXIF-transposed feeds Tesseract sideways pixels — their pure-rotation tags are
spurious, which Stage 00's docstring has said all along, and they differ *within*
a set (`skewset_en_02` is 8 and 6). On the EXIF load `zoomset_en_02_f01` reads 30
words against the 160 on record. The census loads through
`tools.normalize.load_upright_bgr`, the pipeline's own resolver, and then all
sixteen zoomset frames reproduce `stitch_and_orientation_20260819.json` **exactly**
(435/221/173, 183/270/249, 167/120/0/2, 134/160/96/3/121/7) — two independently
written harnesses agreeing frame-for-frame.

**Scoreboard, on the ten sets where a choice exists** (does the selector pick the
candidate that OCRs best?):

| ranking score | picks the OCR-best candidate |
|---|---|
| whole frame (shipped) | 7 / 10 |
| inside `find_book`'s emit box | 8 / 10 |
| inside the emit box, ungated | 6 / 10 |

The middle row is the tempting one and it is an artefact. Variance of Laplacian
rises when smooth pixels are removed, so a candidate whose crop applied is scored
on page-only pixels while a candidate that abstained is still carrying its room.
Every set the box could touch is a set that mixes the two. Score every candidate
on its own box regardless of the abstain gate — the comparison that is actually
fair, since the gate answers "should we CUT here", not "which photograph is
better" — and the single win reverses (`de_02`: the shipped pick goes from 669.9
to 859.6 and beats the challenger's 793.2) while `bg_taleb_01` breaks.

**The argument that does not depend on n=10.** On **6 of the 10** sets — all six
multi-view pairs — the crop abstains on *every* candidate. There the emit box IS
the frame, so the two scores are numerically identical and no windowing variant
can change the pick **by construction**, including on `skewset_de_01` and
`skewset_it_01`, two of the three sets where the shipped selector picks the worse
photograph. On a seventh, `zoomset_en_02`, the crop applies to both candidates, so
the comparison there is fair — and the pick does not move. That leaves the three
sets that mix a cropped candidate with an abstaining one as the *only* place any
windowing variant can act, and those are exactly the sets where its numbers are
not comparable across candidates. The window is not where the problem lives.

**What the corpus does say about the criterion.** The shipped selector picks a
measurably worse photograph on three sets:

| set | selector's pick (words @ conf ≥ 80 / mean conf) | best candidate | margin |
|---|---|---|---|
| `de_02` | `de_02` — 282 / 74.3 | `de_02_092054` — 356 / 85.5 | +74 words, +11.2 conf |
| `skewset_it_01` | `..._134804` — 569 / 70.6 | `..._134801` — 628 / 84.2 | +59 words, +13.6 conf |
| `skewset_de_01` | `..._134824` — 147 / 70.8 | `..._134828` — 205 / 73.0 | +58 words, +2.2 conf |

The word counts alone would not carry this: **±60 words in both directions is the
churn this same instrument was measured to show under nothing but reframing**
(RESULTS 2026-08-19, book-boundary row), and two of the three margins sit inside
it. That ±60 is a **floor**, not a matched estimate — it was measured on the same
underlying photograph reframed, whereas these are different shots of the same
spread, which is more variation, not less. Mean confidence is what separates them, and it is not a redundant
statistic — on `bg_taleb_01` and `de_01` the two disagree about which frame is
best, which is exactly why agreement means something on the other two. So: two
sets where the selector is wrong and both statistics say so by a wide margin, one
that is a coin flip. Sharpness is a focus measure, not a legibility measure, and
that is the honest open question — the **criterion**, not the window.

**Two traps recorded for whoever picks that up.**

*The area gate is load-bearing, and sharpness will argue against it.*
`zoomset_de_01_f01` scores 1329 against its own anchor's 564 — 2.4× sharper by
the selector's own metric — while covering 0.39 of the spread and reading 221
words against the anchor's 435. `fullspread_area_frac` is the only thing keeping
a third of a spread from being elected the whole page. Relaxing it needs a
**coverage** test, not a sharper score.

*The book box's abstain guards are load-bearing too.* On `bg_taleb_01` the paper
mask sees 0.1 % of the frame and `find_book` correctly refuses; the ungated arm
built from the same mask returns a box covering 0.2 % of the image and scores it
478 points lower than the frame it came from (146.6 vs 469.3). The box is only
meaningful where `find_book` was willing to act on it, which is precisely why the
fair version of this experiment cannot simply be shipped as the fair version.
`find_book` also costs 258–1375 ms on a 12 Mpx frame, so a per-candidate ranking
would pay that per frame.

**Two written claims are corrected by this run**, both in place with the
superseded text left visible. `stage01_fuse.py` said the zoomset close-ups are
"whole-spread re-zooms, so it is a fair comparison" and concluded a close-up is
sometimes "a better photograph of the whole page" that `partition_frames` cannot
elect; `zoomset_manifest.json` carried the same bullet. Looking at the pixels
settles it: `zoomset_de_02_f01` frames the right page plus a clipped strip of the
left, and `f02` is essentially the right page alone (0.337 of the anchor's
footprint on its own correct registration). They are **per-page zooms**, 270/249
vs 183 is not like-for-like, and electing one would delete the other page from the
job. The honest reading is stronger than the wrong one: a frame covering a third
of the spread out-reads the anchor covering all of it because the anchor is a
distant oblique shot and the close-up has roughly twice the pixels per text line.
The anchor is bad; the close-up is not eligible to replace it. What that argues
for is **per-page frame selection**, which has to know where the gutter is and
therefore cannot live in Stage 01 — it crosses the stage contract, so it is a
design decision rather than a tweak.

**Limits.** Ten sets and one photographer, and "OCR'd best" is a proxy for "is the better anchor" that ignores everything
downstream of Stage 01. No pipeline code changed: `partition_frames` is exactly
as it was, deliberately. Evidence:
`docs/data/anchor_choice_census_20260819.json`; re-run with
`python -m tools.anchor_choice_census --json <path>`.

## Anchor choice, downstream: the criterion is not the problem either — 2026-08-26

`tools/anchor_downstream_census.py --json docs/data/anchor_downstream_census_20260826.json`

The previous row closed "rank the anchor candidates inside the book box" as a
no-op and left one thing standing: on three sets the incumbent selector (sharpest
full-spread frame) keeps a photograph that OCRs measurably worse, so the
**criterion** — variance of Laplacian, a focus measure, not a legibility measure
— was named as the honest open question. This run says the criterion is not the
problem either, and the reason is that the evidence against it was collected in
the wrong place.

**The instrument was the flaw.** That finding was Tesseract on the *raw upright
frame* — the whole flat spread, room included, before the book crop, before the
gutter cut, before Stage 03 flattens the page. Its own Limits paragraph says so.
And the three disputed sets are exactly the ones where that matters:
`skewset_de_01` and `skewset_it_01` are the multi-**view** fixture (deliberately
oblique shots), in each the loser is the *sharper* frame, and what separates them
is mean confidence — which is precisely the defect Stage 03 exists to remove. The
third, `de_02`, is decided by a 669.9-vs-658.8 sharpness margin: **1.7 %**, a tie
in the selector's own units rather than an error it committed.

**Same question through the pipeline's own geometry.** Three arms per candidate —
`flat` (whole frame), `split` (book crop + gutter cut, subpages summed), `dewarp`
(the same subpages flattened first, UVDoc) — using `tools/dewarp_ab.py`'s
`split_halves`/`dewarp_halves`, i.e. the functions Stages 02 and 03 run, and the
*identical* Tesseract instrument as the flat census (config psm/oem, no upscale,
words at conf ≥ 80 + mean conf). Only the geometry differs between arms. The
`flat` arm reproduces `anchor_choice_census_20260819.json` frame-for-frame
(`bg_taleb_01` 371/72.9, `de_01` 348/84.3, `de_02` 282/74.3, …), which is the
self-check that the load path did not move under it.

**Pre-registered before the run** (in the module docstring, committed in the same
change): a set counts as an incumbent **error** only if a losing candidate leads
on **both** statistics — more than **60** words at conf ≥ 80, *and* higher mean
confidence. 60 is the reframing churn floor this instrument was already measured
to have. `skewset_orient_02` (0 words on both frames) is degenerate and excluded
from the verdict, measured and printed anyway.

**Result — errors by arm, over the 9 non-degenerate sets that have a real choice:**

| arm | incumbent errors | which |
|---|---|---|
| `flat` | 1/9 | `de_02` |
| `split` | 2/9 | `skewset_de_01`, `skewset_it_01` |
| `dewarp` | **0/9** | — |

The disputed sets, as the challenger's margin (words / mean conf) against the
incumbent's pick, arm by arm:

| set | flat | split | dewarp |
|---|---|---|---|
| `de_02` | **+74 / +11.2** | +36 / −0.3 | −11 / +3.4 |
| `skewset_it_01` | +59 / +13.6 | **+73 / +6.1** | **−55 / −1.7** |
| `skewset_de_01` | +58 / +2.2 | **+87 / +6.9** | +22 / +1.4 |

**The two sign reversals are the claim, not the table.** `skewset_it_01` and
`de_02` are the two sets the previous row called solid — *"both statistics say so
by a wide margin"* — and both **change direction** once the pages are flat.
`skewset_it_01`: the frame the selector keeps goes from 59 words behind to 55
ahead, exactly the predicted result if the flat penalty was obliquity rather than
legibility. `de_02`: +74 becomes −11, with the two statistics now pointing
opposite ways. A reversal does not care where the floor sits; the error counts
do, so read the reversals first. `skewset_de_01` lands inside the floor from both
directions.

**Why this row's flat arm says 1 and the previous row said 3.** That is the
floor, not the geometry: the previous census took a bare max with nothing under
it, and `skewset_de_01` (+58) and `skewset_it_01` (+59) sit one and two words
below the 60 declared here. On that same bare-max rule the sequence over these
nine sets is **flat 3 → crop+split 5 → dewarp 2**, so the shape of the result is
the same under either rule and the arms remain comparable to each other. Note the
bar is deliberately asymmetric — a 60-word floor on one statistic, any positive
value on the other — which makes errors *easier* to declare, so a null under it
is the conservative reading.

**Reported against the incumbent, not for it.** On 7 of the 9 sets the
incumbent's pick also wins the dewarp arm outright. On the other two a loser
leads on both statistics but below the pre-registered floor: `de_01` +43 / +8.4
(the largest surviving disagreement in the corpus) and `skewset_de_01`
+22 / +1.4. So the honest claim is *no error survives at the stated bar*, not
*the selector is perfect*.

**And `de_01` is not an anchor-selection signal — it is UVDoc having a bad day on
one frame.** Nothing about that set changes upstream; what changes is what the
dewarper does to each candidate:

| `de_01` candidate | flat | crop+split | +dewarp |
|---|---|---|---|
| `de_01` (the pick) | 348 / 84.3 | 346 / 85.9 | **328 / 73.2** |
| `de_01_091921` | 308 / 82.0 | 313 / 83.6 | 371 / 81.6 |
| `de_01_091915` | 274 / 87.5 | 233 / 88.4 | 337 / 79.0 |

The dewarper gains +58 and +104 words on the two losers and **loses 18 words and
12.7 confidence** on the winner — the only frame in the corpus that dewarp makes
worse. That is the whole of the +43. It is a per-frame dewarp instability worth
its own look (Stage 03, not Stage 01); chasing it with a better anchor criterion
would be aiming at the wrong stage.

**Two things visible here that the flat census could not see.** Stage 02 fails to
find a gutter on `bg_taleb_01_093629` (and on `skewset_orient_01_134655`) — a
frame that breaks the split is a bad anchor whatever it scores, and in both cases
the frame the selector *keeps* is the one that splits correctly. And splitting
alone is not what fixes this: the `split` arm has **more** incumbent errors than
the flat one. The flattening is doing the work.

**Limits.** Nine sets, one photographer, one dewarper (UVDoc), and the label
still stops at OCR of the dewarped subpages — layout, reading order and
everything downstream of Stage 05 are outside it. The 60-word floor was measured
on the *flat* instrument and applied to the dewarp arm; a learned dewarper's
output plausibly varies at least as much under reframing, not less, so a floor
that is too small would make errors *easier* to declare — and none were. Every
candidate's Stage 00 rotation agrees within its set (no orientation confound).
Running on the `skewset_*` pages spends no pre-registration: it merges no views,
keys no GT and scores none of v1–v5, the same grounds on which that plan's own
headroom triage read those frames.

**No pipeline code changed.** `partition_frames` and `fullspread_area_frac` are
imported and used exactly as they ship. Evidence:
`docs/data/anchor_downstream_census_20260826.json`; re-run with
`python -m tools.anchor_downstream_census --json <path>`.

## Per-page frame selection: the two sides really do disagree, and nothing available can act on it — 2026-08-26

Both halves of the anchor question are closed (RESULTS 2026-08-19 and the row
above). What they left open, and named as the bigger lever, is **per-page frame
selection**: today one photograph becomes both pages of a spread — Stage 01
elects the sharpest full-spread frame and Stage 02 cuts *that* frame in two — so
a capture that holds the left page flat and lets the right one curl into shadow
has no way to contribute only its good half. `tools/perpage_choice_probe.py`
asks whether choosing a different photograph per page is worth building, through
this pipeline's own geometry (book crop → gutter split → Stage 03 dewarp) and
with the census's Tesseract instrument, per side. Pre-registration is in the
tool's docstring, written before the run.

**1. It is a real operation, not a no-op.** On **3 of 7** scored sets the frame
that wins the left page is not the frame that wins the right one (`bg_taleb_01`,
`de_02`, `skewset_de_01`); on 3 the same frame wins both; on 1 (`zoomset_en_02`)
a side is a dead tie — 142 words each — and is counted with neither. This is
where the book-box census died (on 6 of 10 sets the crop abstained on every
candidate, so any windowing variant was a no-op *by construction*) and this
question survives that test: the sides genuinely disagree about which photograph
they prefer.

**2. And nothing clears the bar. 0 of 7.** The pre-registered rule is the
census's: a challenger must beat the incumbent's frame on BOTH statistics —
words at conf ≥ 80 by more than the 60-word reframing-churn floor, and mean
confidence — applied **per side**, unchanged. A side holds about half a spread's
words, so that floor is deliberately *stricter* here; halving it would have been
inventing a number.

| set | side | best challenger | Δ words | Δ mean conf |
|---|---|---|---|---|
| `skewset_de_01` | left | `…_134828` | **+37** | +11.8 |
| `de_02` | left | `de_02_092054` | +22 | +1.1 |
| `bg_taleb_01` | left | `…_093636` | +14 | **−2.3** (fails on conf) |
| `zoomset_en_02` | right | `…_f00` | 0 (tie) | +10.0 |

The largest thing on the table is +37 words on one page of one set. **Add the
column up carefully**: only two sets have a challenger ahead on both statistics
at all, so choosing each page's best frame **with the answer key in hand** buys
**+37 and +22 — 59 words** across ~4,400. The other two lines are not gains to
be summed: `bg_taleb_01`'s +14 words comes with 2.3 points *less* confidence, and
`zoomset_en_02`'s is a tie. And 59 words is what an ORACLE collects, not a
selector.

**3. No cheap rule gets near even the oracle.** Three statistics a Stage 02
selector could actually decide on were logged per side per candidate, on the flat
half and on the dewarped half, and scored against the OCR winner over the 15
side races that have an unambiguous one. **Chance is 6.8**, not zero:

| statistic | agrees with OCR |
|---|---|
| ink density (flat) | 11 / 15 |
| variance of Laplacian (dewarped) | 10 / 15 |
| variance of Laplacian (flat) — *the incumbent's own criterion* | 9 / 15 |
| median glyph height (dewarped) | 8 / 15 |
| median glyph height (flat) | 7 / 15 |

Eleven of fifteen against an expectation of 6.8 demonstrates nothing at this
corpus size. And the failure is not spread evenly — **the two best statistics
both pick the wrong frame on the race with the most to win.** On
`skewset_de_01`'s left page (+37 words, +11.8 confidence) the *loser* is the
sharper image (608 vs 568) and the inkier one (0.097 vs 0.092); only median glyph
height gets it right, and glyph height is the worst-ranked proxy overall, at
chance. A selector built on any of these would not have collected the +37.

**4. The close-up arm is closed on coverage, as predicted, but now with the
number.** A close-up can only be a page source if it covers a page. Bar stated in
advance: ≥ 0.98 of the page's box. Measured over all 11 real close-ups, using
Stage 01's own registration at shipped parameters: **0 eligible.** Six never
register at all (oblique views of a curved page — a homography cannot fit them),
and the five that do cover **0.80, 0.64, 0.64, 0.54, 0.48** of the best page they
touch. So `zoomset_de_02_f02`, the frame Stage 01's docstring calls "essentially
the right page alone", covers 64 % of that page. The standing lead — *a close-up
is sometimes a better photograph of the page than the anchor is* — remains true
about the pixels and is dead as a feature, for want of a candidate that contains
a whole page.

**The one case that shows what the feature would be for.** `skewset_de_01` is
two oblique views of the same spread, and they trade sides cleanly: one reads
173/62 words on left/right, the other 136/105. Best single frame: 241. Per-page
oracle: 278. That is exactly the shape the feature exists to exploit, it is the
multi-view capture mode, and it is one set.

**A harness fidelity correction, found by the self-check.** This probe follows the
shipped stage and widens the cut to `pinch_margin_frac` when the gutter comes
from the Layer-2 spine-pinch cue; `tools/dewarp_ab.split_halves`, which the
downstream census used, always cuts with the narrower `margin_frac`. Every frame
whose gutter came from the ink cue reproduces the census exactly (that is the
self-check working); every pinch frame reads higher here. The consequence for the
row above: `de_01`'s "+43 words / +8.4 confidence, the largest surviving
disagreement in the corpus" is **+10 / +0.8** once the split uses the margin the
pipeline actually applies. (Both confidences are the same statistic computed the
same way — the word-count-weighted mean over a frame's subpages, as the census's
`_combine` does — over different pixels, which is the point. The wider cut lifts
that frame from 73.2 to 85.5, so the narrow one was clipping text off a curved
page, which is exactly what `pinch_margin_frac` exists to prevent.) The direction is unchanged and the census's verdict
(no incumbent error at the stated bar) is unchanged — but the size of the one
lead it reported is mostly an artefact of a harness cutting narrower than the
stage. `de_01` was quarantined from this row's headline in advance for exactly
the reason the census gave (its disagreement is a Stage 03 dewarp instability,
not an anchor-selection signal); its numbers are measured and printed.

**What this does not say.** It does not say the sides never differ — they differ
on 3 of 7. It says that on this corpus no per-page difference is large enough to
clear a floor this instrument has been measured to need, and that none of the
cheap criteria a Stage 02 selector could use ranks frames the way OCR does. One
criterion certainly *would* reach the oracle: OCR each candidate's dewarped side
and keep the better one. That is the metric itself, so it cannot lose — at the
cost of a dewarp and an OCR pass per candidate per side (roughly two to three
times Stage 03 + a probe Tesseract run per spread), to collect 59 words.

**Where the stage boundary actually is, since the next person will ask.** The
question was posed as one that crosses the stage contract, and it does, but by
less than it looks — worth recording so this is not re-derived:

* **Full-spread candidates need no registration at all.** Each candidate splits
  on its own, and the halves correspond BY NAME: left is left. The homography
  machinery Stage 01 owns is needed only for the close-up arm, which coverage
  has now closed.
* **Everything below Stage 02 is already per-subpage** and reads the pages
  manifest for `name` only (Stage 03 does; Stages 04-06 chain from its output).
  So two pages coming from two different photographs is invisible downstream.
* **The one real contract cost is `SubPage.box`.** It is documented as ORIGINAL
  spread coordinates and two tests in `pipeline/tests/test_stage02_split.py`
  assert it by rebuilding each page from the anchor with that box. The moment
  left and right come from different frames the box needs a `source_frame`
  beside it — a `page_model` change, its own commit per CLAUDE.md.

That is the whole bill. The feature is cheap to build; what it lacks is a
criterion to drive it.

**Limits.** Seven scored sets, one photographer, one dewarper, and 15 decided
side races — small enough that 11/15 and 6.8 are the same number. The label stops
at Tesseract on the dewarped subpages: layout, reading order and everything below
Stage 05 are outside it. Three cheap statistics were tried, not the space of
them. `de_01` is quarantined and `skewset_orient_02` degenerate (0 words on both
frames), both measured and printed. Running on the `skewset_*` pages spends no
pre-registration: nothing here merges views, keys GT or scores v1–v5.

**No pipeline code changed.** `partition_frames`, `find_book`, `detect_gutter`,
`cut_pages` and Stage 03 are imported and run as they ship, and the OCR
instrument is imported from the downstream census rather than copied. Evidence:
`docs/data/perpage_choice_probe_20260826.json`; re-run with
`python -m tools.perpage_choice_probe --json <path>`, or re-derive the verdicts
from the stored measurement without touching a pixel with
`python -m tools.perpage_choice_probe --rescore <path>`.

## Per-page frame selection SHIPPED as an option, off by default — 2026-08-26

The row above measured per-page frame selection and found it null: the two sides
really do prefer different photographs (3 of 7 sets), nothing clears the bar
(0 of 7), and no cheap statistic ranks frames the way OCR does (best 11 of 15
side races against 6.8 by coin flip, and wrong on the one race with headroom).
The recommendation was to stop; the owner's call was to build it as an option.
This row records what was built, what was deliberately NOT built, and what it
does on real pixels.

**What ships.** `pipeline/page_source.py` + Stage 02 v0.4.0. With
`per_page_source.mode: ocr` (config.yaml, or `--per-page-source ocr`), `left.png`
and `right.png` may be cut from **different** full-spread photographs of the same
spread. Candidates are Stage 01's `fullspread_frames`; each is cut by the shipped
Stage 02 geometry on its own; each side's candidates are then dewarped (Stage 03,
in memory) and OCR'd, and the side is taken from whichever frame reads best. The
default is `off`, which runs nothing extra and leaves Stage 02's output
byte-identical to v0.3.0's.

**One criterion, and no sharpness knob — because of the measurement, not despite
it.** The row above scored five cheap statistics a Stage 02 selector could decide
on. None is a result at n=15, and on `skewset_de_01`'s left page — the one race
with real headroom — the *loser* is both the sharper image (608 vs 568) and the
inkier one. Offering `mode: sharp` would therefore be shipping a selector
measured to pick the wrong photograph on the only case worth winning. `resolve_params`
rejects it by name with that reason. The only criterion offered is the metric
itself (dewarp + OCR each candidate's side), which cannot lose because it IS what
the bar is written in, and costs a dewarp + a Tesseract pass per candidate per
side. That cost is why the default is off.

**The bar is a validity boundary, not conservatism.** `min_word_gain` defaults to
60 — the reframing-churn floor (RESULTS 2026-08-19), the measured amount this
instrument's word count moves when the framing changes at all. Below it a
word-count difference is not measuring anything, so a lower default would be
choosing between photographs on noise. A challenger must also read at higher mean
confidence, so "more words" cannot be bought with junk. Applied **per side**,
unrescaled, for the reason the probe gave: halving it would be inventing a number.

**On real pixels, end to end.** `skewset_de_01` (the two oblique frames that trade
sides — the shape the feature exists for) through Stage 00 → 01 → 02 with the mode
on, then Stage 03:

| side | anchor `frame_00` | challenger `frame_01` | decision |
|---|---|---|---|
| left | 144 words @conf≥80, mean 81.0 | **173**, mean **91.9** | keep anchor (+29 < 60) |
| right | **95**, mean **69.3** | 59, mean 63.4 | keep anchor (−36) |

So the trade is reproduced by the shipped selector — the challenger is the better
left page and the worse right page — and at the shipped bar **nothing swaps**.
That is the honest expectation, not a validation: an inert option that costs 8.8 s
of probe per spread is not the same virtue as an inert gate that costs nothing.
(The margin here is +29 where the probe measured +37 on the same set. Same
direction, same winner; the difference is the ingest path — the probe reads the
raw upright JPEGs, the stage reads Stage 00's normalized PNGs.)

Dropping `min_word_gain` to 20 on that same page makes it fire, which is how the
swap path was exercised on real pixels rather than only on a stub: `left.png` then
comes from `frame_01.png`, carries **its own** gutter (2056, not the anchor's
2115) and its own book crop, and its `box` addresses `frame_01.png`'s pixels
exactly. Stage 03 runs on the mixed output unchanged.

**The schema cost, which is smaller than the earlier framing suggested.**
`SubPage` gains `source` (the photograph these pixels came from, page-dir
relative), plus per-side `gutter_x` / `book_crop`. `SubPage.box` is now documented
as coordinates *of `source`* — with the mode off that is always
`01_fuse/anchor.png` and the old "ORIGINAL spread coordinates" wording holds
verbatim. `SubPage` lives in `stage02_split.py`, not `page_model.py`, so this is a
stage-local change and does not touch the shared schema. Nothing below Stage 02
needed changing: Stage 03 reads the manifest for `name` only.

**The one silent-failure path, closed.** `test_stage02_split.py` rebuilt each
subpage from `anchor.png` using only `box`. Once two sides can come from different
frames that assertion would crop the *wrong* image and still pass, because two
photographs of one spread look nearly the same. It now rebuilds from
`page["source"]`, and a new test cuts a mixed spread and requires both that each
box addresses its own frame AND that the same box on the anchor is a *different*
picture — so the assertion has teeth.

**The stage-boundary exception, written down.** With the mode on, Stage 02 reads
the candidate frames out of `00_ingest/` (named by `01_fuse/fuse.json`), which
CLAUDE.md's "reads ONLY the previous stage's artifacts" does not cover. The rule's
purpose holds: `00_ingest` is upstream, is never written here, and the speculative
dewarp+OCR is entirely in memory and writes no artifacts. The alternative — Stage
01 duplicating every candidate into `01_fuse/` — costs ~100 MB of 12 Mpx PNG per
spread to avoid a read that is already safe. Recorded in CLAUDE.md beside the
editable-document exception.

**Every no-op path names itself.** A selector that silently does nothing is
indistinguishable from a broken one, so `split.json`'s `per_page_source` block
carries every candidate's reading of every side, the margin of the race that was
lost, and a `note` saying which no-op path was taken (single-page anchor, only one
frame, no eligible challenger, Tesseract missing, candidates dropped by
`max_candidates`) — each also as a `meta.warnings` line. A candidate that does not
split confidently is excluded with a reason, carrying the probe's pre-registered
eligibility rule into production. Close-ups are not candidates at all: measured
page coverage 0.80 / 0.64 / 0.64 / 0.54 / 0.48 against a 0.98 bar.

**Also, the probe no longer restates the geometry it licensed.**
`tools/perpage_choice_probe.split_with_boxes` now delegates to
`page_source.split_geometry` — that function is its former body, moved — so the
thing that ships and the thing that was measured cannot drift apart.

**Limits.** Unchanged from the row above, plus: the selection criterion has been
verified to run, to reproduce the measured left/right trade, and to swap pixels
correctly when the bar allows it — it has NOT been shown to improve any output,
because at the shipped bar it changes nothing on this corpus. Suite 466 green.
Evidence for both arms of the end-to-end run (shipped bar, and the lowered bar
that exercises the swap): `docs/data/perpage_source_e2e_20260826.json`.

**Activation, both documented entry points.** `run_all` passes the whole config
through to Stage 02, so setting `per_page_source.mode: ocr` in `config.yaml`
fires on the full-pipeline command as well as on `stage02_split` alone; both now
also take a one-run `--per-page-source` override. Note that `mode: on` is
REFUSED rather than read as `ocr` — YAML turns a bare `off` into a boolean with
exactly one possible meaning (accepted), but guessing the other direction would
silently switch on a ~9 s dewarp-and-OCR probe per spread.

## The two captions that were really pairing failures — an arm that looks at no distance at all — 2026-08-26

Five caption↔figure pairs in the corpus were missing. **Two of them were pairing
failures.** The other three were something else, and saying so is half the result:

| missing pair | why it is missing | whose problem |
|---|---|---|
| `it_geo_05` C2 | the caption is printed *inside* the map, so the detector emits no caption block | segmentation |
| `it_geo_06` C30 | its figure's printed corner label cannot be read | closed 2026-08-10 as a measured recognizer ceiling |
| `it_geo_07` C31 | its ground-truth partner D1 is not detected *at the shipped floor* — it is boxed at 0.247, see "The picture under the floor" (2026-08-26); with D1 back the pair is still not claimed, but now because C31 is mistyped and in another column | segmentation |
| **`it_geo_04` B8** | "A lato: Figura 20" | **pairing** |
| **`it_geo_05` C3** | "Sopra: Figura 3" | **pairing** |

Reported as "5 misses" this looks like a pairing pass that recovers 74% of the
pairs. Three of the five are cases where the pairing pass is handed no block to
pair, or a number no recognizer can read. It was owed two.

### Why loosening the proximity rule was the wrong lever

The probe (`M:\claud_projects\temp\bookscan_grouping`, dumped into
`docs/data/figure_grouping_sole_20260826.json`) read the geometry the pass
actually saw on real pixels:

| case | figures on the subpage | column overlap | vertical gap | sideways gap |
|---|---|---|---|---|
| `it_geo_04`-left B8 → B5 | 1 | 0.04 | **0.384** of page height | 0 |
| `it_geo_05`-right C3 → F3 | 1 | **0.00** | **0.390** of page height | 0.028 of page width |

Arm 2 wants a column overlap of 0.50 and a gap of 0.08 (0.25 on a solo page), or —
for the side-set shape — a vertical overlap of 0.50. **Both cases fail every one
of those in both shapes, and not marginally.** This book sets its captions in a
narrow side column, often most of a page away from the plate they describe: the
distance between a caption and its own figure is simply not smaller than the
distance to somebody else's. Widening the limits far enough to reach these two
would take them past the separations the `it_geo_06` trap is built out of — the
caption stack whose order does not track figure position — so the pairs would be
bought by re-opening the exact wrong-photo failure the guards exist to prevent.

### What is actually present is uniqueness

Both subpages print **one figure** and **one block that says in print it is that
figure's caption**. So a third arm pairs them on that alone, consulting no
geometry whatsoever: exactly one figure block on the subpage, still unpaired;
exactly one eligible caption left; and that caption carries a parsed `Figura NN`
header. Two independent signals again, neither of them a distance.

It runs **last**, after the geometry arm. That is not cosmetic: a caption arm 2
can already place keeps its proximity-backed provenance, and every pair that
existed before this change still comes from the arm it came from before.

`PairSource` gained `sole_figure` in its own commit rather than filing these
under `geometry` — telling a reviewer the pass measured a distance it never
looked at would be a lie in the provenance field, which exists precisely so the
editor can re-check the weaker inferences.

### Measured — every block-order fixture, production code path

| fixture | correct | **WRONG** | abstained | arms (number/geometry/sole) | change |
|---|---|---|---|---|---|
| **it_geo_04** | **2/2** | **0** | 0 | 0/1/**1** | was 1/2 |
| **it_geo_05** | **1/2** | **0** | 0 | 0/0/**1** | was 0/2 |
| it_geo_06 | 5/6 | 0 | 1 | 5/0/0 | unchanged |
| it_geo_07 | 0/1 | 0 | 2 | 0/1/0 | unchanged |
| de_01 | 0/0 | 0 | 1 | 0/0/0 | unchanged |
| en_coins_01 | 4/4 | 0 | 2 | 0/4/0 | unchanged |
| en_coins_02 | 2/2 | 0 | 1 | 0/2/0 | unchanged |
| en_coins_03 | 2/2 | 0 | 0 | 0/2/0 | unchanged |
| **total** | **16/19** | **0** | **7** | 5/10/**2** | was 14/19, 9 abstained |

**Annotated 2026-08-26** — with sub-threshold figure rescue on by default ("The picture under the floor" below) this total reads **15/19, 0 wrong, 8 abstained**. The lost pair is `it_geo_04` B8, and it was never discriminated: the `sole_figure` arm claimed it because the page had exactly one detected figure. The page has two; the second was under the confidence floor. Fewer pairs, same zero wrong, one more honest abstention.

**Non-regression is field-by-field identical, not "similar".** Every graded field
of all eight fixtures was diffed against a baseline captured before the change —
every match, miss, type verdict, tau, pair and abstain reason. Six fixtures are
identical outright; on the two that moved, the *other* subpage is identical too
and the only changed fields are the two new pairs and the two abstentions they
replace. `it_geo_05` still shows 1/2 because its second pair is the segmentation
case in the table above.

### The guard the metric cannot enforce, pinned as an assertion instead

A wrong pair on `de_01`'s icon sidebar would score **ungraded, not wrong** — that
ground truth scopes the panel out — so "0 wrong" is no evidence at all that this
arm is safe there. And the sidebar is the case uniqueness alone would claim: it is
the only block of its kind beside the only photo on its half of the spread, with a
vertical overlap of 1.00 and a 28px gap. What refuses it is the print
requirement — it carries no `Figura NN` header. That refusal is now a unit test
with the real coordinates in it, not something left to a metric that cannot see it.

Checked while writing that test: the unreadable-panel pass (which re-types the
sidebar as a picture) runs **after** grouping in Stage 07, so the panel really does
still reach the pairing pass as a caption-eligible block. The print requirement is
load-bearing today, not a historical artefact.

### One existing test reversed, deliberately

`test_side_set_does_not_reach_a_detached_gutter_caption_column` was written as
"`it_geo_05`-right in miniature" and asserted **no pair** — which was the right
answer when abstaining was the only safe one, and is the wrong answer now, since
the real fixture's ground truth pairs C3 to F3. Its purpose (the side-set rule must
not reach across a page) is still needed, so it keeps its assertion and gains a
**decoy second figure** that removes the uniqueness, leaving the gap limit as the
only thing that can reject the pair. The solo version is a separate test.

### Verified on the production path, not only in the eval

`run_all` 00→06 then `stage07_assemble` on `it_geo_05`: the right subpage reports
`captions=1 paired=1 (sole_figure)`, and `document.json` block 6 carries
`caption_number=3`, `figure_ref` → block 2, `pair_source=sole_figure`.

### Honest limits

* **The way this arm can be wrong has a name, and nothing in this corpus has that
  shape:** a spread whose single figure on one page belongs to the *facing* page's
  caption, while this page's caption describes the figure over there. The arm would
  mispair it and no available signal would catch it. Real books do print "A lato"
  captions that point across the gutter — this corpus's two do not.
* **N=2.** The arm fires on exactly two subpages in the whole corpus. Both are the
  same Italian series, which is also the only book here that sets captions in a
  side column. It has not been shown to do anything on a second book.
* **It does nothing for a book that prints no caption numbers**, the same price the
  side-set shape already pays.
* **`it_geo_05` C2 was left unclosed on purpose, and here is what stands in the
  way.** Stage 05's caption ejection *does* recover the block in production (the
  run logs `ejected caption (Figura 2) printed inside figure ...: 60 words`), so
  the pair is closer than the "segmentation miss" label suggests. Two things stop
  it: that subpage carries **two** figure blocks, so uniqueness does not apply; and
  the ejected block's words do not include the re-OCR'd `Figura 2` header (that
  header is evidence only, never added as words), so it carries no printed number.
  The obvious fix — pair a caption to the figure it was *ejected from* — was
  considered and **not taken**: this module's `_nest_frac` rule exists because of a
  measured case where a figure box swallowed a *neighbouring* column's caption, and
  it records containment as an ABSTAIN signal, never an attachment signal. Turning
  containment into the strongest attachment signal would contradict that finding,
  and needs evidence that the ejection gate's strictness (1 acceptance in 50 figure
  blocks) makes containment trustworthy — evidence nobody has gathered. It is an
  open lead with a stated blocker, not an oversight.

Suite **474 green** (was 466): +8 in `test_figure_grouping.py` covering both real
layouts, the `de_01` refusal, the two-figure and two-caption declines, the
numbering-regime precedence, the geometry-keeps-its-provenance ordering, and the
stamp on the editable block. Evidence:
`docs/data/figure_grouping_sole_20260826.json`.

### Addendum, same day — two claims above were unmeasured, and one of them was wrong

**"Fires on exactly two subpages" is now measured, and it holds.** The row above
asserted that from the eight graded fixtures, but the eval only ever looks at
subpages that carry ground truth — and this corpus deliberately leaves some
facing pages ungraded *because they carry one figure each*, which is precisely
this arm's trigger. So the claim was made about pages nothing had checked. All 15
curated testset spreads (30 subpages) were then run through the real chain
(`run_all` 00→06 → `stage07_assemble`) and every subpage's pairing arm read off:

| arm | subpages |
|---|---|
| **sole_figure** | **2** — `it_geo_04`-left, `it_geo_05`-right |
| number | 2 (`it_geo_06`, both subpages) |
| geometry | 8 |
| no pair emitted | the rest |

The two ungraded English facing pages the metric could not see (`en_coins_02`-left,
`en_coins_03`-left) do pair — by **geometry**, not by this arm: that book sets its
caption right beside its plate, so proximity reaches it and the weaker arm never
runs. The arm still has not been shown to do anything on a second book, and now
that is a measurement rather than an assumption.

**"The subpage prints exactly one figure" is not what the code tests, and
`it_geo_04`-left is the proof.** The code tests *one figure **block***, i.e. one
Stage-04 detection. That page prints **two** figures — the Fig.21 panorama spans
the gutter and its left fragment `B6L` is a segmentation miss (visible in the
eval's own `misses` list). **The headline case fires because a figure was not
found, not because the page holds one.** The pair it makes is still correct.

The same gap runs the other way on `it_geo_05`-left, which prints one figure and
still gets no pair from this arm: the detector also emits a **21×671px sliver** at
the page edge, and that sliver counts as a second figure block.

So detector noise can both manufacture this trigger and destroy it. It is
tolerable only because the arm's *other* signal is a printed one — but a page that
merges several plates into one box (the documented under-segmentation failure this
repo has a whole scope document for) and prints a single numbered caption **would**
be paired to the merged box. Nothing in this corpus has that shape. A
minimum-area floor on what counts as a figure block is the obvious guard and was
deliberately not added: nothing has measured where that floor belongs. Both the
module docstring and the code comment now say "figure block" and carry these two
cases by name.

**The rendered page was checked, and it corrects the `it_geo_05` C2 limit above.**
`stage08_render` on the same job: the "Sopra: Figura 3" caption comes out inside a
`<figure>` with its photograph, so the pair reaches the reader and not just
`document.json`.

On the left page the ejected `Figura 2` caption *also* renders inside the right
figure — via Stage 08's **adjacency fallback**, which groups a caption carrying no
`figure_ref` with the figure block immediately before it. That is worth stating
plainly because it qualifies the whole "abstaining is safer than a wrong pair"
premise: an abstention does **not** mean the caption stands alone in the output. It
means the pairing decision falls back to the weakest rule there is. Here that rule
happens to land on the correct figure (the 21px sliver sorts before the map, so the
map is what precedes the caption), so the rendered output for `it_geo_05` is right
on both pages — but by adjacency, not by anything this pass decided.

## The sole-figure arm's missing size floor: the guard was for the wrong thing — 2026-08-26

The arm added earlier today shipped with a hole named in its own docstring: it
counts *figure blocks*, not printed figures, and *"a minimum-area floor on what
counts as a figure block is the obvious guard and is deliberately NOT added here:
nothing has measured where that floor would sit."* This measures it. The floor
now exists — and almost nothing the previous row said about **why** it was needed
survived contact with the measurement.

### Three corrections, in order of how much they change

**1. The block that motivated the guard is not a figure block.** The previous row
reported that `it_geo_05`-left "prints one figure and the arm declines: a
21x671px sliver figure block at the page edge counts as a second figure". It does
not. Stage 04 emits **three** blocks on that subpage and none of them is the
sliver (`04_layout/layout.json`: two headers and the 1806x2658 map). The sliver
is an orphan junk-text region that Stage 05 assembles from unrouted words and
that Stage 07's `unreadable_panel` pass re-types FIGURE — **after** the per-page
loop has already called `group_figures`. It carries `type_promoted=True`, which
is how the census tells the two apart. The pairing arm never saw it.

**2. `it_geo_05`-left has exactly one thing wrong with it, and it is not this.**
With the sliver out of the picture the subpage the arm sees is: one figure block
(the map), one caption block (the one Stage 05 ejects from inside the map), and
no printed number — because the ejection recovers the caption's 60 words *without*
its header line, "In questa pagina: Figura 2". `caption_number` is None, so the
arm's second requirement fails. **Recovering that number is sufficient to make
the pair**; nothing else on that page is in the way. That is a small, separate,
measurable follow-up, and it is now the only blocker there.

**3. There is no detector-noise population at all.** The census
(`tools/sole_floor_census.py`, all 15 curated spreads, 30 subpages, **50 figure
blocks**, production path `run_all 00-06` + `stage07_assemble`) labels every
figure block real/noise by IoU >= 0.2 against the GT figure bboxes that six
fixtures carry. Noise: **zero**. Every figure block the arm counts on this corpus
is real ink.

### So what does break the count? Over-segmentation

`it_geo_02`-right prints ONE photograph — the Cadini di Misurina — and the
detector emits it as **two** boxes: a 1202x81px sky strip sitting on top of the
1202x628px body. One picture, two figure blocks, and the uniqueness arm declines
on a page where the answer is not in doubt. That is the real defect, and it is
the mirror image of the under-segmentation this repo already has a scope document
for.

### The statistic the docstring proposed is measurably the wrong one

The obvious floor is on AREA. On this corpus area **inverts** the two
populations:

| block | what it is | area frac | min(w,h) frac |
|---|---|---|---|
| `it_geo_02`-right 1202x81 | sky strip of one photograph | **0.0167** | 0.0270 |
| `de_02`-right 231x175 | a WHOLE printed pictogram | **0.0092** | 0.0630 |

A fragment can cover more of the page than a whole small figure does, so no area
threshold orders them correctly. Minimum dimension does: 0.0270 against 0.0630.
This is a measured inversion on real blocks, not an argument from principle.

### The floor, and what it does

`sole_min_fig_frac = 0.04` — a figure block thinner than 4% of the page in its
narrower dimension does not count toward "this subpage holds exactly one figure".
It sits in the middle of the empty gap between the strip (0.0270) and the
smallest whole figure in the corpus (0.0630): 1.5x above one, 1.6x below the
other. It is applied **inside `_sole_figure_pair` only** — it changes no
detection, nothing arm 2 can pair to, no segmentation recall, no order metric.

Swept over all 30 subpages by re-running Stage 07's real pairing pass with each
floor injected (`docs/data/sole_floor_census_20260826.json`):

| floor | pairs | by sole-figure | changed vs floor 0 | what falls below the floor |
|---|---|---|---|---|
| 0 (off) | 20 | 2 | — | — |
| 0.02 | 20 | 2 | 0 | — |
| 0.026 | 20 | 2 | 0 | `de_02`-right 1257x56 route banner |
| **0.04 (shipped)** | **21** | **3** | **1** — `it_geo_02`-right gains "Figura 1" | + the 1202x81 sky strip |
| 0.055 | 21 | 3 | 1 (same) | + `it_geo_02`-left 1712x163 legend row |
| 0.065 | 21 | 3 | 1 (same) | + **two whole pictograms** (231x175, 233x179) |
| 0.08 | 21 | 3 | 1 (same) | + a **GT-confirmed figure** (829x222) |

**Exactly one subpage in thirty changes, and zero wrong pairs appear.** The eight
block-order fixtures re-graded identically: 16/19 pairs, 0 wrong, per-fixture
counts the same as the row above. The rendered HTML for `it_geo_05` is
byte-identical with the floor off and on (`document.json` too) — checked, not
assumed.

**The change is visible in the deliverable, not just in the provenance field.**
Re-rendering `it_geo_02` both ways: with the floor off, the "In questa pagina:
Figura 1" caption comes out as a loose `<p class="caption">` standing on its own —
Stage 08's adjacency fallback does not reach it, because the caption sits in the
far-left column and the block before it in reading order is not the photograph.
With the floor on it comes out inside a `<figure>` with its picture. This is one
of the cases where abstaining really did leave the caption alone on the page.

**Read the bottom two rows of that table carefully: they are a limit, not a
reassurance.** At 0.065 the floor deletes two whole pictograms from the count and
at 0.08 a ground-truth figure, and *nothing changes* — because neither subpage has
an eligible printed-number caption for the arm to act on. So "no wrong pair even
at 0.08" is not evidence that 0.08 is safe; it is evidence that this corpus cannot
exercise the harm at all. 0.04 is placed by the block geometry, not by the sweep
being flat.

### Limits, stated

* **The one gain is on an ungraded page.** `it_geo_02` has no block GT, so the
  recovered pair was verified by looking at the pixels (one photograph, split).
  The metric cannot see it either way.
* **The floor is a thinness test, not a fragment detector.** `it_geo_02`-left's
  1712x163px legend row is the same kind of fragment and survives at 0.04. It
  changes nothing either way, which is why the floor was not pushed up to catch
  it: the gap above it is 1.16x wide and that is not a place to put a threshold.
* **It removes nothing from the document.** A block below the floor keeps
  `type=figure`, so Stage 08 still renders the `it_geo_05` sliver as a picture
  (its PNG header decodes to 21x671). This changes a COUNT, not a page.
* **Under-segmentation is still unguarded and no size floor can guard it** — a
  merged box is large. See `docs/FIGURE_SEPARATION_SCOPE.md`.
* **N=1 for the benefit.** One page in the corpus has the over-segmented shape.

Suite 477 green.

## The words that were on the page and not in the document — 2026-08-26

The corpus's segmentation headline was **106/112 GT blocks matched** over the eight
block-order fixtures. Six misses. This pass asked one question of each — *does that
block's text reach the shipped document at all?* — and the answer split them three
ways, only one of which is a defect in the pipeline.

| miss | what the harness says | what the shipped pipeline does | class |
|---|---|---|---|
| `it_geo_05` C2 | caption not detected | **is** a caption block, via Stage 05's `caption_eject` | harness blind spot |
| `en_coins_01` FN1 | footnote not detected | **is** a block, via Stage 05's orphan-word rescue | harness blind spot |
| `en_coins_03` P2 | paragraph not detected | **is** detected — block #10 scores 0.875 for it | matcher artifact |
| `it_geo_04` B6L | figure fragment lost | Stage 02 cuts the panorama, but the surviving fragment IS detected, at 0.229 — **superseded**, see "The picture under the floor" below | ~~upstream~~ under the floor |
| `it_geo_07` T5right | paragraph not matched | detected at **exactly** its GT box — the OCR read 8 of ~25 words | **real: text lost** |
| `it_geo_07` D1 | figure not detected | detected at **0.247**, 0.003 under the floor — **superseded**, see "The picture under the floor" below | ~~real loss~~ under the floor |

### Correction 1 — the harness grades Stage 04, and two shipped mechanisms live in Stage 05

`tools/layout_order_eval` stops after `stage04_layout` and routes page-level OCR
words into the detected boxes. But **caption ejection** (`pipeline/caption_eject.py`,
shipped 2026-08-10) and **orphan-word rescue** (`attach_words`, shipped with Stage 05)
both run *after* that, in Stage 05, and both create blocks. So the harness cannot
see them.

Concretely, `jobs/floor_it_geo_05/page_001/05_ocr/ocr.json` block #6 is
`type=caption`, 60 words, conf 91.7, reading as C2 verbatim — while the eval reports
C2 as a miss and the 2026-08-26 pairing row above states "*the caption is printed
inside the map, so the detector emits no caption block*". That sentence is true of
**Stage 04** and false of the **deliverable**. Same for `en_coins_01` FN1: production
`ocr.json` carries it as an 8-word block at the page foot, five of five anchor
tokens present, built out of orphan words.

**So 106/112 understates the shipped pipeline, and every figure the eval prints is
measured on a block set two mechanisms younger than the one that ships.** Closing
that is its own piece of work — it would move every number in the corpus, for
reasons unrelated to anything measured here — and it is deliberately NOT bundled
into this change. What is recorded here is that the gap exists and how wide it is
on these two cases.

### Correction 2 — `en_coins_03` P2 is the greedy matcher, not the detector

**Superseded 2026-08-26** — fixed in "The heading that ate the paragraph" below.

`match_subpage` assigns each detected block to at most one GT block, greedily by
anchor-token overlap. On `en_coins_03`-right, detected block #10 scores **0.875**
for P2 — and is claimed first by **H1**, a short heading anchor whose every token
also appears in that paragraph. P2 then has nothing left to match. The text is in
the document; the miss is an artifact of one-to-one assignment meeting a short
anchor. Not fixed here — recorded, because "segmentation recall" currently counts it.

### Correction 3 — `it_geo_07` D1 is the corpus's one genuinely lost figure

**Superseded 2026-08-26 — this section's central claim is wrong.** D1 is not
undetected: at `conf_thresh` 0.02 the detector boxes it at confidence **0.247**,
IoU 0.386 against its GT box, three thousandths under the shipped 0.25 floor. The
observation below that the detector "read everything around the picture and not
the picture" is false; it read the picture too, and the floor discarded it. See
"The picture under the floor" below.

The GT calls it a thin cross-section diagram in the far-left column. The detector
emits figure boxes for D2/D3/D4/D5 at y1204/1482/1926/2377 and **nothing** in D1's
band — IoU 0.000 against all four. The crop confirms a real drawing is there (pink
strata, `DPR`, a sea-level line). The detector even found the diagram's *furniture*:
blocks #2 and #3 are its scale bars (`0.5 cm = 200m`, `0.5 cm = 5 Km`) and #6 is its
own label `7 Piana tidale`. It read everything around the picture and not the
picture. Open, and the honest next figure-side task.

## Starved blocks: text that is on the page, readable, and absent from the document

`it_geo_07`-left block #22 is the paragraph the GT calls `T5right`. Stage 04 boxed it
at `1527,2464 501x223` — **exactly** its GT box. The subpage OCR pass returned:

    8 words, conf 77.5:  "In questo cont, esto acino Bellunese de el"

The pixels are sharp enough to read by eye. Re-reading that block's own crop as one
uniform block (`--psm 6`) returns:

    21 words, conf 90.1:  "In questo contesto nel Bacino Bellunese si depone la
                           Formazione di Igne (IGN), che include le peliti
                           anossiche del Toarciano."

Because OCR output IS the visible document here, those were words a reader simply
lost — and the loss was invisible to every metric in the repo, because the block
matched nothing and dropped out of the graded set rather than scoring badly.

**It is not a page-level parameter.** Re-running the whole subpage and counting words
whose centre lands in that block: psm 3 gives 8, psm 4 gives 21, psm 6 gives 31,
psm 11 gives 25, psm 12 gives 25 — and every one but psm 3 is garbled or duplicated,
because a three-column page with figures between the columns is exactly what "uniform
block" is wrong for. The win is the PAIR: this block's crop, read as one block. A
per-block pass, not a different page-level setting.

### The rule: a comparison against the block's own score, never a cutoff

`pipeline/block_reocr.py` re-reads every non-figure block and keeps the re-read only
when it is better on **both** counts at once — **more words AND mean confidence no
lower than the page pass gave that same block**. No fixed confidence floor appears
anywhere in the module: Stage 05 emits raw confidence and every threshold is Stage
06's (CLAUDE.md).

Two consequences, stated rather than glossed:

* **It rescues starvation, not garbling.** On `de_01`-left #1 the re-read returns 149
  words at conf 93.3 against the page pass's 165 at 71.4 — clearly the better read,
  and this rule **rejects** it because the count fell. That is a scope choice.
* **A block the page pass read as EMPTY accepts any re-read**, since its conf is 0.0.
  Three of the four such accepts are real (a caption reading "Piattaforma di Trento
  (in annegamento)" at conf 96.3, two page numbers); the fourth is two junk tokens at
  conf 33.3. That is not silent — a low-confidence word is precisely what Stage 06's
  flag/patch machinery acts on, whereas a block holding no words at all is invisible
  to it.

**Padding was measured, not assumed.** All 163 text blocks were re-read at pad 0 and
pad 12. Padding manufactures two accepts that pad 0 does not (both junk bleeding in
from a neighbour) and rescues nothing extra. The `it_geo_05` caption header looked
like it might be a bbox-tightness artifact — the detected caption starts 68px below
the GT box — and it is not: it recovers at pad 0 too. Shipped at **pad 0**.

**The crop goes to Tesseract in COLOUR**, which is a deliberate divergence from the
page pass's grayscale, and it is load-bearing rather than incidental:

| `it_geo_05`-left #6, re-read | words | conf | opens |
|---|---|---|---|
| grayscale (page-pass path) | 67 | 90.9 | mangled: `n questa pagina: Foa 2 pag` |
| **colour (shipped)** | **66** | **92.6** | **`In questa pagina: Figura 2`** |

Grayscale falls *below* that block's own page-pass confidence (91.7) and the rescue
is refused — taking the caption header with it. Over the corpus: colour rescues 4
GT-graded blocks, grayscale 2, neither regresses anything.

### Measured against ground truth, not against its own opinion

Graded on the block-order GT **anchors** over all eight fixtures, comparing the
shipped `ocr.json` before and after. Each GT text block scores the best anchor-token
overlap over the subpage's blocks — deliberately without the one-to-one greedy
assignment, so this measures text recovery and not the matcher (Correction 2).

| | value |
|---|---|
| GT text blocks graded | 80 |
| mean anchor recall | **0.9254 to 0.9468** (+0.0214) |
| blocks improved / regressed | **4 / 0** |
| blocks at or above the harness's 0.5 match bar | 78 to 79 |

| block | before | after |
|---|---|---|
| `it_geo_07`-left T5right (paragraph) | 0.400 | **0.900** |
| `en_coins_03`-right H2 (heading) | 0.500 | **1.000** |
| `de_01`-left P2 (paragraph) | 0.625 | **1.000** |
| `it_geo_05`-left C2 (caption) | 0.667 | **1.000** |

**15 rescues fire across the eight fixtures**, listed with before/after counts and
confidences in each page's `05_ocr/meta.json` under `params.block_reocr.rescued`
(and as `note:` lines, the same channel `caption_eject` uses).

**Non-regression is block-by-block, not "similar".** Of **195 blocks** across the
eight fixtures, **180 are byte-identical** to the pre-change `ocr.json`, **15 changed
— exactly the 15 rescued** — and **0 changed unexpectedly**. Block counts per subpage
are unchanged everywhere.

### The coordinate contract, verified on pixels

A rescued word's box is in *crop* coordinates and must be mapped back — divide by
the page scale, then add the crop origin — or Stage 06's patch mode crops the wrong
pixels while the text still looks right. Verified the way the per-page-source work
was: every one of the 58 rescued words on `it_geo_07`-left was cropped from the
full-res dewarp at its **stored** box and OCR'd alone. **45 read back as the same
token**; all 13 that did not are 1-3 character tokens (`i`, `|`, `;`, `0.5`) or a
case difference (`peliti` read back `Peliti`), i.e. single-glyph psm-8 noise, not
displacement. Every multi-letter word in the rescued paragraph and caption read back
exactly.

### It reaches the deliverable

Re-running Stage 06 then Stage 07 on `it_geo_05`: caption C2 now carries
`figure_ref -> page_001__left block 5` with `pair_source=sole_figure`. It was
**unpaired** before. The GT's own pairs list says `C2 -> F2`, so this is a correct
pair the pipeline could not previously make — `caption_parser` needs the printed
`Figura N` header to number a caption, and the header is exactly the line the
subpage pass was missing. This also closes `caption_eject`'s stated limit, that its
re-OCR'd header was "used as evidence only and deliberately NOT added as words".

**The harness cannot see that pair either** (Correction 1), so the 16/19 figure in
the row above does not move. The pair is in `document.json`; the number is measured
at Stage 04.

### Cost, and why no cheap gate was added

| | Stage 05, rescue off | rescue on |
|---|---|---|
| `it_geo_07` (41 blocks) | 15.3s | 24.8s |
| `en_coins_03` (23 blocks) | 9.9s | 21.4s |

Stage 05 is already the largest per-page stage (13.6s of ~27s on `it_geo_07`), so
this is roughly **+35% on the whole per-page pipeline**. The obvious lever is a cheap
precondition so only suspicious blocks are re-read. Read off the census, there isn't
one worth placing:

| word-density gate (words per 1000 px² of block) | blocks re-read | rescues lost |
|---|---|---|
| <= 0.05 | 7/163 | 10 of 15 |
| <= 0.10 | 15/163 | 7 of 15 |
| <= 0.20 | 61/163 | 5 of 15 |
| <= 0.238 | 105/163 | 0 of 15 |

The tightest gate that keeps every rescue still re-reads **105 of 163 blocks** — a 36%
saving — and 0.238 is the rescued blocks' own maximum, i.e. a threshold fitted with
zero margin, sitting on top of healthy blocks like `en_coins_03` #7 at 0.232. A knob
placed there would break on the first page that starves a denser block. Not added.

### Limits, stated

* **The rule was fitted and graded on the same 163 blocks.** There is no held-out set.
* **The gain is concentrated.** Of 15 rescues, 4 move a GT-graded block; the rest are
  headers (stripped by default), page numbers, or single tokens. One of the four —
  `it_geo_07` T5right — is the whole reason to build this.
* **`total_words` changed meaning.** It was the subpage pass's recognized count; it is
  now the words actually in the page's blocks. Stage 05's word-conservation assert is
  amended to match (recognized minus dropped plus added) and is unchanged when
  nothing is rescued.
* **This is the only pass in Stage 05 that may REPLACE words rather than move them.**
  Ejection and orphan slotting both preserve the original invariant; this does not.
* **Nothing here touches the two real losses' causes.** `it_geo_07` D1 is still
  undetected and `it_geo_04` B6L is still cut by the gutter. T5right was the third
  real one, and it is closed.

Suite 493 green (was 477).

### Addendum, same day — three things the checks above did not cover

**The headline metric is recall-only, and the row above read as if it were not.**
`anchor_score` is `|anchor ∩ block| / |anchor|` — the denominator is the *anchor's*
tokens, so adding tokens to a block can never lower it. "4 up / 0 down" therefore
proves no rescue destroyed text a GT anchor names; it is blind by construction to
junk a rescue *adds*, and to the 11 rescues on blocks carrying no GT anchor at all.

The missing half, measured as a set difference over the same files: across the 15
rescued blocks, **60 normalized tokens are present before and absent after; 33 of
them are 3+ characters.** Read one by one they are overwhelmingly the *garbled forms
the re-read repaired* — `acino`→`Bacino`, `cont`+`esto`→`contesto`, `ikm`→`KM`,
`licat`→`Licato`, `chap`→`Chopmarked`, `chaopmarked`→`Chopmarked`, `peg`→`Peso`,
`chir`→`China and`. The clearest single case, `en_coins_03`-left #5:

    before: ... Dala (IKM# 7). Licat Collection. Ex-F. M. Rose. Fig. 79, Chap;
            Coins — A History ... IF Chopmarks by I. M. Rose. Photography b Todd
            Pollock, reprinted with permission Michael Chou.
    after:  ... Dala (KM# 7). Licato Collection. Ex-I. M. Rose. Fig. 79, Chopmarked
            Coins — A History ... Fig. 133, Chopmarks by F. M. Rose. Photography by:
            Todd Pollock, reprinted with permission from Michae...

**Two genuine regressions inside net-better blocks, named rather than netted out:**
that caption swaps the two initials (`Ex-F. M. Rose` / `by I. M. Rose` becomes
`Ex-I.` / `by F.`), and the `en_coins_03`-left header trades `Chaopmarked`→`Chopmarked`
for `Hawai'i`→`Hawai 't`. The header is stripped by default; the caption is not, and
it is the honest price of this rule. Nothing similar appears in the paragraph
rescues, where every lost token is a fragment of a word the re-read spells whole.

**Pairing was verified on all eight fixtures, not two.** Three rescues land on
`caption` blocks, and the repo's bar is zero wrong pairs — which the eval cannot
check here, because its pairing arm runs on Stage-04 text this change does not
touch. So Stage 06 → Stage 07 `--force` was re-run on every fixture and the pair
sets diffed field by field: **identical on seven, and on `it_geo_05` exactly the one
new C2 → F2 pair**. In particular `en_coins_03`, whose captions print two numbers
each (`Fig. 103 ... Fig. 79 ...`) and whose pairing rides on the caption-numbering
guard, is unchanged at 3 pairs from the same arm — even though its #5 caption text
moved substantially.

**Cyrillic is now exercised.** All eight GT fixtures are `ita`/`deu`/`eng`, so the
pass had never touched a Bulgarian page. Run over `bg_01`/`bg_02`/`bg_03` (33
blocks): **2 rescues, both small, both upward** — a footnote block 17→18 words
(72.9→74.5), reading `!) Вж. за това най-автентични подробности в съчинението ми
"Гръцките жестокости", София 1913 год.`, and a page-number header 1→2 (32.7→50.0).
`bg_02` and `bg_03` fire nothing. The empty-block arm did not run wild on Cyrillic,
which was the thing worth checking before Gate 5.

**Two limits to add to the list above:**

* **The `/scale` map-back on rescued boxes is unit-test-only on real pixels.** All 16
  graded subpages ran at `scale=1.0`, so the divide-by-2 branch has never been
  exercised on real small-text pixels — the same caveat Stage 05 already carries for
  `_word_box`, now inherited by the rescue.
* **`total_words` has no consumer outside Stage 05.** Grepped: the only readers are
  Stage 05's own two progress lines, so the meaning change reaches nothing else.

## The heading that ate the paragraph — 2026-08-26

The same-day census of the corpus's six segmentation misses classified
`en_coins_03` P2 as "the greedy matcher, not the detector … Not fixed here —
recorded, because segmentation recall currently counts it". This closes it.

### What was wrong

`match_subpage` scores a GT block against a detected block with `anchor_score`,
which is **recall of the anchor**: the fraction of the anchor's own tokens present
in the block. Its denominator is the anchor's length, so a **one-token anchor
scores a perfect 1.0 against every block on the page that contains that token**.

`en_coins_03`-right's first GT block is the heading `H1`, and its anchor is the
single word **`Honduras`** — the country the page is about. It ties at 1.0 against
six of the twelve detected blocks: its own heading, the running header, both
figure captions, and both body paragraphs. The greedy loop sorted candidates with
`cand.sort(reverse=True)` over `(score, gt_id, det_idx)`, so among a six-way tie
it took the **highest detected index** — block #10, the body paragraph `P2`.
One-to-one assignment then left P2 with nothing, and the eval reported it as a
segmentation miss although its text was in the document, in one block, correctly
typed.

The damage was not confined to the recall number. `H1` was then graded against a
*paragraph* block, so its type counted wrong; and it sat at reading-order position
10 instead of 1, which dragged the subpage's Kendall-tau from perfect to +0.429.
One arbitrary tie-break moved three of the four headline figures on that subpage.

### The fix: break ties with the other direction of the overlap

`anchor_precision(anchor, block)` is the fraction of the **block's** distinct
tokens the anchor accounts for. Candidates now sort by `(-recall, -precision,
gt_id, det_idx)`. For `H1` that separates the six-way tie at once: its own heading
block is precision 1.0 (the block is nothing but the anchor), the paragraph that
merely mentions Honduras is 0.08.

Precision is deliberately **only** a tie-break and never part of the accept test.
GT anchors are the first 6–12 words of a block, so a correct match against a long
paragraph has low precision *by construction* — used as a threshold it would
reject exactly the matches this metric exists to make. Both halves are pinned by
unit tests: the heading case, and a low-precision true match that must still beat
a short high-precision rival on recall.

The final tie-break is now stated (`gt_id`, then `det_idx`, both ascending)
instead of falling out of a bare `reverse=True`, so the number cannot move on an
unrelated re-run.

### Measured: 14 graded subpages re-run, one moved

Every fixture was graded before and after, with the matched sets diffed block by
block (`base_*.json` / `fix_*.json`).

| subpage | seg recall | type acc | tau | tau incl. figures |
|---|---|---|---|---|
| `en_coins_03`-right | 9/10 -> **10/10** | 5/9 -> **7/10** | +0.429 -> **+1.000** | +0.556 -> **+1.000** |
| the other 13 | unchanged | unchanged | unchanged | unchanged |

The other thirteen subpages produced **byte-identical matched sets**, so nothing
was traded for this. Corpus segmentation recall **106/112 -> 107/112**; type
accuracy **86/106 -> 88/107**. No caption<->figure pair changed anywhere.

`H1` moved from det #10 to det #1 (its own heading block, now typed correctly) and
`P2` from unmatched to det #10 (typed correctly) — the two type gains.

### Greedy vs optimal, measured rather than assumed

Greedy assignment can be beaten by a global one even with a good tie-break, so
that was checked rather than argued: the same eval run was wrapped to compute, on
the identical inputs, a `scipy.optimize.linear_sum_assignment` over the same
eligibility rule (recall >= `MATCH_TAU`) maximizing total recall with precision as
a secondary weight. **14 subpages compared, 0 disagreements.** Greed costs nothing
on this corpus once the tie-break is specified, so the simpler code stays.

### Limits, stated

* **The fix is graded on the page that motivated it.** One subpage in fourteen has
  a one-token anchor; the other thirteen prove only non-regression.
* **A short anchor can still lose outright, not just on a tie.** If `H1`'s own
  block had not been detected, `H1` would score 1.0 against P2's block while P2
  scores 0.875 — that is not a tie, and precision never gets consulted. Fixing
  *that* means changing the score itself, which would move every number in the
  corpus; it is not done here and no case in the corpus exercises it.
* **This changes the harness, not the pipeline.** No page renders differently. It
  changes what the eval says was on the page.
* **The larger harness gap is still open**: the eval stops after Stage 04 and
  cannot see `caption_eject`, orphan-word rescue, or `block_reocr`, all of which
  create blocks in Stage 05. Two of the six misses in that census are exactly
  that, and closing it remains its own piece of work.

Suite 496 green (was 493).

## The picture under the floor — 2026-08-26

The same-day census called `it_geo_07` D1 "the corpus's one genuinely lost
figure … the detector emits figure boxes for D2/D3/D4/D5 and **nothing** in D1's
band — IoU 0.000 against all four", and closed with "It read everything around the
picture and not the picture." That is true of the **shipped block set** and false
of the **detector**, and this row corrects it.

### Correction A — D1 is not undetected. It is 0.003 under the floor.

Re-run at `conf_thresh` 0.02, DocLayout-YOLO puts a `figure` box over D1 at
confidence **0.247**, IoU **0.386** against its GT bbox. The shipped floor is
0.250. The picture was never invisible; it lost by three thousandths.

### Correction B — `it_geo_04` B6L is reachable by a Stage 04 change after all

The same census row classified B6L as "upstream, out of scope — Stage 02 cuts the
cross-gutter panorama; **no Stage 04 change reaches it**". Wrong on both halves:
the detector boxes the Lagazuoi Piccolo photo at **0.229**, unclaimed by anything
the page emitted, and the change below recovers it. Its fragment is cut by the
gutter, but the fragment that survives is a picture the page was dropping.

### The rule: three gates, each in a measured gap

Nudging the floor to 0.24 would be a threshold fitted to one box with no margin,
so the admission test is not confidence alone. `tools/subthreshold_figure_census`
measures every `figure` detection down to 0.02 on all 14 graded subpages. Of 22
sub-threshold boxes, 14 already lie under an accepted block. The 8 that do not
separate cleanly:

| conf | what it is (verified on the pixels) | covered | text-covered | verdict |
|---|---|---|---|---|
| 0.247 | `it_geo_07` D1, the cross-section diagram | 0.000 | 0.074 | **picture** |
| 0.230 | D1's two printed scale bars | 0.000 | **1.000** | text |
| 0.229 | `it_geo_04` B6L, the Lagazuoi Piccolo photo | 0.000 | 0.044 | **picture** |
| 0.047 | the table the book is lying on | 0.000 | 0.000 | junk |
| 0.035 | a whole column of `it_geo_04` (photo + text) | 0.110 | 0.150 | blob |
| 0.023 | `de_01`'s decorative page-number glyph | 0.000 | 1.000 | text |
| 0.022 | a running-header text strip | 0.000 | 1.000 | text |
| 0.022 | a near-duplicate of the B6L box | 0.000 | 0.044 | dup |

`pipeline/stage04_layout.rescue_unclaimed_figures` (Stage 04 v0.5.0, config
`fig_rescue`, **off by default**) admits a sub-threshold figure box only if:

* **nothing already claims it** — coverage by the blocks the page actually emitted
  at most 0.20. Both admitted boxes score 0.000; the nearest rejected one, 0.640.
* **confidence above the junk cluster** — floor 0.10, sitting 2.1x above the
  highest junk box (0.047) and 2.3x below the lowest real one (0.229). Deliberately
  not 0.24, which would be fitted to D1 with no margin at all.
* **not something the model also boxed as text** — the three printed things score
  1.000 text coverage, the two photographs 0.074 and 0.044. A 13x gap.

Admitted boxes are fed back through `dets_to_blocks`, so they go through NMS,
figure-splitting and XY-cut like any other detection; nothing is appended after
ordering.

### The third gate is load-bearing, and the first build of it was wrong

Without the text gate the scale-bar box is admitted, the figure-splitter carves it
into two 15px strips, one lands nearer to caption C31 than D1 does, and an honest
unpaired caption becomes a **wrong** caption↔figure pair — measured, `wrong 0 → 1`.

Then the gate itself failed the same way for a subtler reason. The census measured
text coverage over every non-figure box down to 0.02; the code built its text set
from the pass floored at the **rescue** confidence, 0.10. A printed scale bar is
faint — the detector's own text box over it scores under 0.10 — so at that floor
its coverage read 0.000 instead of the measured 1.000 and it was admitted anyway,
`wrong 0 → 1` a second time. **A gate must be applied to the population it was
measured on.** The pass now runs at 0.02 (`fig_rescue_text_conf`), rescue
candidates are filtered at 0.10, the text set at 0.02, and a unit test pins it by
raising the text floor and asserting the bug comes back.

Verified separately on all 16 half-pages: one forward pass at 0.02, filtered at
0.25, is byte-identical to detecting at 0.25 — the accepted path is untouched and
only the discarded tail is new.

### Measured: 14 graded subpages, rescue off vs on

| subpage | seg recall | type acc | order incl. figures | pairs |
|---|---|---|---|---|
| `it_geo_07`-left | 15/17 -> **16/17** | 14/15 -> **15/16** | +0.943 -> **+0.950** | 0/1 wrong 0 -> 0/1 wrong 0 |
| `it_geo_04`-left | 4/5 -> **5/5** | 4/4 -> **5/5** | n/a (no GT fig bboxes) | 1/1 wrong 0 -> **0/1** wrong 0 |
| the other 12 | unchanged | unchanged | unchanged | unchanged |

Corpus: segmentation **107/112 -> 109/112**, type **88/107 -> 90/109**, figures
graded in the order metric **24 -> 25**, caption↔figure **16/19 wrong 0 -> 15/19
wrong 0**, abstentions **7 -> 8**. Both recovered blocks are typed `figure`
correctly. Nothing else on any subpage moved.

### The one trade, stated as a trade

`it_geo_04`-left loses a correct pair — and it is not a regression to fix. B8's
pair was produced by the `sole_figure` arm, which fires when a subpage has exactly
one detected figure and reads no geometry at all. The page has two figures; it was
under-segmented, and the pair was earned by the missing picture. With B6L back, the
geometric arm has to decide, and it abstains ("no figure shares this caption's
column within the gap limit"). The eval's own grouping check still says *"nearest
figure is the partner"* — the geometry is right, the shipped rule declines to claim
it. That is abstain-over-guess working as designed, and loosening the proximity
rule to recover it is the move measurement already refused (2026-08-26 pairing row,
overlap 0.04/0.00). **Do not re-attempt.**

The mirror-image effect on `it_geo_07`-left is the gain: with D1 matched, C31's
nearest figure becomes its true partner (`nearest_ok` false -> **true**). The pair
is still not claimed, for the pre-existing reason that C31 is mistyped `paragraph`
and sits in another column.

### Rendered end to end, because the eval never gets that far

`layout_order_eval` stops after Stage 04, so "the block is back" is not the same
claim as "the picture is in the document". Both spreads were run through the whole
pipeline (`run_all` -> assemble -> render) with the rescue on:

* `it_geo_07`-left assembles **five** figure blocks where it had four, D1 at reading
  order **6** — ahead of D2-D5, which is where the GT puts it. Cropping its box out
  of the rendered page asset shows the cross-section itself: pink strata, the
  sea-level line labelled *Livello del mare*, the `DPR` box, *Piana tidale*. It is a
  figure, not a strip, and it is placed correctly.
* `it_geo_04`-left assembles **two** figure blocks where it had one, the recovered
  box at reading order 4. Its crop is the Lagazuoi Piccolo photograph — sky, the
  peak, the `HKS` label, the red fault line — cleanly bounded. (It is the fragment
  on this side of the gutter; the panorama continuing onto the facing page is the
  pre-existing Stage 02 cut, untouched here.) Assemble reports the page's caption
  as `paired=0 unpaired=1`, which is the trade above showing up in the deliverable
  exactly as the eval predicted: an abstention, not a wrong pairing.

Two starved blocks on `it_geo_07`-left were re-read as usual (block 16: 0 -> 5
words; block 22: 8 -> 21), unaffected by the added figure.


### Limits, stated

* **One of the two recoveries is confirmed by measurement, the other by eye.**
  `it_geo_07` D1 has a GT bbox, so its IoU 0.386 is independent evidence. `it_geo_04`
  predates figure bboxes in GT, so B6L's recovery is confirmed by looking at the
  crop — a photograph of Lagazuoi Piccolo — and by the block being typed `figure`
  in the right place. It is not a second measurement.
* **On by default — owner's call, same day, and the reason is that it measured
  positive.** The repo's other off-by-default option (`per_page_source`) ships off
  because it measured *null*; that precedent does not transfer to a change that
  gains on every axis and loses on none. What ships off instead is the *excuse*:
  the gates below are measured on this corpus only, so a book whose junk
  detections are more confident needs them re-measured, not re-guessed.
* **The confidence gate is a corpus artifact.** 0.10 sits in a gap that is real on
  these 8 fixtures. A book whose junk detections are more confident, or whose faint
  pictures are less, would need it re-measured — not re-guessed.
* **Two boxes is a small sample for a three-gate rule.** Each gate is justified by
  a measured margin, but the population it separates is 2 pictures against 6
  non-pictures.
* **This does not fix the harness gap.** The eval still stops after Stage 04 and
  cannot see `caption_eject`, orphan-word rescue, or `block_reocr`; the corpus
  numbers above are Stage-04 numbers.

Suite 503 green (was 496) — the seven added tests are `covered_fraction`, the
five rescue gates, and the text-set-population regression test. Re-run green
with `fig_rescue` on by default.

## The harness measures the stage it stops at — closing that — 2026-08-26

`tools/layout_order_eval` stopped after Stage 04. Three mechanisms that CREATE or
REWRITE blocks run after it, in Stage 05, before anything reaches
`document.json`: orphan-word rescue (`attach_words`), caption ejection
(`caption_eject`, shipped 2026-08-10) and the starved-block re-read
(`block_reocr`, shipped 2026-08-26 above). So every figure the eval printed —
segmentation recall, type accuracy, tau, caption↔figure pairing — was measured on
a block set several mechanisms younger than the one that ships, and a block the
eval called a **miss** could already be in the deliverable. Two of the corpus's
six misses were exactly that ("The words that were on the page and not in the
document", above), and the repo carried a hand-written convention telling every
session to go open `05_ocr/ocr.json` before believing a miss — a workaround for a
broken measuring tape.

The eval now runs those three passes itself (`stage05_blocks`), in production
order, calling the same functions `stage05_ocr.run` calls, and grades the blocks
they leave behind. `--no-stage05` keeps the old arm for reproducing older rows.

**Wiring check first, numbers second.** The eval replicates production's
word-conservation assert verbatim (`attached == recognized − rescue-dropped +
rescue-added`) after the three passes. It is the cheapest available proof that
they are wired the way production wires them and not merely approximately: it
held on all 14 subpages. Nothing below would have been worth reading if it had
not.

### Before / after, 8 fixtures, 14 subpages

Both arms in `docs/data/harness_stage05_ab_20260826.json`.

| | Stage 04 alone (`--no-stage05`) | Stage 04 + 05 (**ships**) |
|---|---|---|
| segmentation recall | 109/112 (97%) | **112/112 (100%)** |
| type accuracy (detector) | 90/109 (83%) | 92/112 (82%) |
| type accuracy (parser arm) | 99/109 (91%) | 101/112 (90%) |
| caption↔figure pairs correct | 15/19 | **16/19** |
| pairs WRONG | 0 | **0** |

Per subpage, the blocks Stage 05 contributed to the graded set:

| subpage | seg before→after | det blocks | orphan | eject | re-read |
|---|---|---|---|---|---|
| `de_01`-left | 4/4 → 4/4 | 7→9 | 2 | 0 | 2 |
| `de_01`-right | 8/8 → 8/8 | 8→8 | 0 | 0 | 0 |
| `en_coins_01`-left | 11/12 → **12/12** | 13→14 | 1 | 0 | 0 |
| `en_coins_01`-right | 10/10 → 10/10 | 12→12 | 0 | 0 | 2 |
| `en_coins_02`-right | 8/8 → 8/8 | 10→10 | 0 | 0 | 1 |
| `en_coins_03`-right | 10/10 → 10/10 | 12→12 | 0 | 0 | 1 |
| `it_geo_04`-left | 5/5 → 5/5 | 11→14 | 3 | 0 | 0 |
| `it_geo_04`-right | 4/4 → 4/4 | 9→9 | 0 | 0 | 1 |
| `it_geo_05`-left | 1/2 → **2/2** | 3→7 | 3 | 1 | 1 |
| `it_geo_05`-right | 5/5 → 5/5 | 7→10 | 3 | 0 | 0 |
| `it_geo_06`-left | 8/8 → 8/8 | 10→10 | 0 | 0 | 1 |
| `it_geo_06`-right | 6/6 → 6/6 | 9→9 | 0 | 0 | 0 |
| `it_geo_07`-left | 16/17 → **17/17** | 21→23 | 2 | 0 | 3 |
| `it_geo_07`-right | 13/13 → 13/13 | 16→18 | 2 | 0 | 0 |

### The diff has three categories, not two

`match_subpage` is greedy and one-to-one, and this change adds small text-bearing
blocks to every subpage — precisely the surface of the heading-ate-the-paragraph
defect fixed two commits ago. So the diff is on **match identity** (the matched
block's bbox, which is stable across arms; detected *indices* shift), not on the
matched count:

* **gained** (unmatched → matched): **3**
* **lost** (matched → unmatched): **0**
* **moved** (same GT block, DIFFERENT detected block): **0**
* **type verdict flips on already-matched blocks**: **0**

The three gained are the three the earlier row predicted, and the mechanism
behind each is the one it named:

| GT block | recovered by | typed right? |
|---|---|---|
| `en_coins_01`-left FN1 (footnote) | orphan-word rescue | **no** — `other` |
| `it_geo_05`-left C2 (caption) | caption ejection | yes |
| `it_geo_07`-left T5right (paragraph) | starved-block re-read | yes |

**`it_geo_05`-left C2 also brings its pair with it.** Recovered as a real caption
block, it pairs to its map through the production grouping pass: 15/19 → 16/19
GT pairs, still **0 wrong**. That pair has been in the shipped `document.json`
since 2026-08-26 and no harness number could see it until now.

### What got WORSE, and why it is not a regression

**Type accuracy falls as a rate**, 83% → 82% (and 91% → 90% on the parser arm),
while rising as a count, 90 → 92. Both moves come from the same block:
`en_coins_01` FN1 is the corpus's only ground-truth `footnote`, and orphan-word
rescue emits synthetic blocks typed `other` **by construction** — it groups words
that landed inside no detected box, and it has no type to assign them. So
recovering it adds one to the denominator and nothing to the numerator.

That is the honest shape of this change: a block the pipeline genuinely ships,
whose type it genuinely gets wrong, was previously counted in neither column. The
old 83% was not better — it was measured over 109 blocks while the pipeline
shipped 112.

### Order: the column is a different quantity now

`attach_words` re-ranks real + synthetic blocks through the same XY-Cut Stage 04
uses whenever there are orphans, and renumbers gaplessly. So on the 6 subpages
with orphans the tau column no longer reports Stage 04's proposed order but the
order that ships. The report header and the column label both say so, and
`--no-stage05` is documented as not comparable — RESULTS.md is append-only and
its tables get read side by side.

Measured, the two happen to almost coincide: 12 of 14 subpages are +1.00 in both
arms. `it_geo_07`-left rises +0.964 → +0.970 (text) and +0.950 → +0.956
(text+figures) because T5right joins the graded set in the right place, and
`it_geo_05`-left goes from ungradeable to **+1.00** on `tau+figures` — with C2
recovered it finally has two blocks to order.

### Limits, stated

* **Segmentation recall is now at its ceiling on this corpus** (112/112). That is
  a real result, but it means this metric can no longer show an improvement here
  and can only ever go down — the next segmentation claim needs a harder fixture,
  not another run of this one.
* **The three gains were predicted, so they are a confirmation, not a discovery.**
  Two were named in the row above; the third is `block_reocr`'s own headline case.
  What is new is that the harness can now see them — and that nothing ELSE moved,
  which was not known.
* **One arm, one corpus.** The 0-lost/0-moved result says the greedy matcher
  survived adding ~1.5 blocks per subpage on THESE pages. A book with denser
  orphan text could still let a synthetic `other` block steal a paragraph's match.
* **This measures block structure, not text quality.** A rescued block that
  matches its GT anchor still counts as matched however garbled the rest of it is;
  word-level accuracy is `tools/gate1_harness`'s question, not this one.
* **The eval's OCR call was deliberately NOT unified with production's.**
  `tools.layout_ab.ocr_words` and `stage05_ocr.ocr_subpage` are byte-identical
  today (same oem/psm, same 20px/2× upscale probe), but swapping them would have
  perturbed the *before* arm too, on a commit whose whole value is a clean
  comparison of one thing. The duplication is noted, not fixed here.

One question this run raised and closed: `it_geo_05`-left's text-only tau reads
`None` in BOTH arms while `tau+figures` becomes +1.00. That is correct, not a
blind spot in the tau path — the subpage's ground truth is exactly two blocks,
F2 (figure) and C2 (caption), and text-only tau excludes figures, so it has one
graded block and cannot be scored. The recovered caption is in the tau path: it
matches, types correctly, and sits in the right place in `seq_det`.

Suite 511 green (was 503) — eight added tests. Six pin the new view: text comes
from the block's final words, `native_ranks` stay the page pass's TSV order, the
smallest-containing-box rule and the upscale division are unchanged, an
orphan-rescued block is matchable but typed `other`, and each arm names itself in
its own report. Two pin the OLD arm, which is otherwise reachable only through
`--no-stage05` and would break silently: `_route_words` routes by the page pass,
and the two arms are identical block-for-block on a subpage where no Stage 05
pass fires — so they may only ever differ BECAUSE of the three passes.

---

## The harness had its own copy of the OCR call — closing that — 2026-08-26

The row above closes with a deferral, stated in its own words:

> **The eval's OCR call was deliberately NOT unified with production's.**
> `tools.layout_ab.ocr_words` and `stage05_ocr.ocr_subpage` are byte-identical
> today (same oem/psm, same 20px/2× upscale probe), but swapping them would have
> perturbed the *before* arm too, on a commit whose whole value is a clean
> comparison of one thing. The duplication is noted, not fixed here.

That reasoning was right for that commit and does not survive it. This one does
nothing but the swap.

### What was actually duplicated

Three functions, living in `tools/layout_ab.py` as a byte-for-byte copy of
`pipeline/stage05_ocr.py`:

| copy in `tools/layout_ab.py` | original in `pipeline/stage05_ocr.py` |
|---|---|
| `ocr_words` | `ocr_subpage` — the Tesseract TSV call, `oem=1 psm=3`, probe at 1× then re-OCR at 2× when median word height < 20px |
| `_word_box` | `_word_box` — the `/scale` map-back from OCR space to 1× dewarp coords |
| `_center_in` | `_center_in` — the word-centre-inside-box test the routing rule is built on |

`tools/layout_order_eval.py` imported all three *from the copy*, so there were two
import sites and one duplicate implementation. Both now import from
`pipeline.stage05_ocr` directly; `ocr_words` is kept as an alias because that is
the name both harnesses have always called it by, and an alias is not a wrapper —
after this commit there is exactly one implementation of each.

Direction matters and is unchanged: `tools/` depends on `pipeline/`, never the
reverse. The harness grades the pipeline, so importing the thing it grades is the
correct arrow — a copy is what made it possible for the arrow to be wrong.

### Why this is worth a commit when it changes no number

Because a copy that agrees today can disagree tomorrow, and the disagreement
would not look like a bug. Anyone tuning the OCR call — a psm change, a different
upscale trigger, a new preprocessing step — edits the pipeline and not the two
harness copies of it. Every metric this repo reports on block structure would then
move, in a commit that touched no metric code, and the RESULTS row would read as a
finding about the pipeline. The `/scale` map-back is the sharpest case: it is the
coordinate contract Stage 06's patch crops depend on, and the harness silently
holding its own version of it is exactly the kind of drift that gets discovered
three rows later.

### The bar: identical, not better

Since the two were byte-identical, the correct result is **no movement at all**.
An improvement here would be evidence the refactor changed behaviour under cover
of a cleanup, and would have to be investigated rather than reported.

Re-ran `tools/layout_order_eval` over all 8 ground-truth spreads in **both** arms
(default and `--no-stage05`) and diffed every field against the committed baseline
`docs/data/harness_stage05_ab_20260826.json`, float tolerance 1e-9:

```
de_01 en_coins_01 en_coins_02 en_coins_03 it_geo_04 it_geo_05 it_geo_06 it_geo_07
  × {before, after}  ->  16 graded runs
=== 0 differences ===
```

Segmentation recall stays 112/112, pairs stay 16/19 with 0 wrong, every tau to
nine decimals. Nothing in this file's tables changes.

### Limits, stated

* **This is debt removal, not a measurement.** It makes no claim about OCR,
  layout, or ordering quality, and no row above becomes more or less true.
* **Identity is pinned by a test, not by discipline.**
  `test_the_evals_ocr_call_is_productions_not_a_copy` asserts all six references
  (two harnesses × three functions) *are* the Stage 05 objects. Without it,
  re-introducing a copy is a two-line edit that nothing catches.
* **Only these three functions were shared.** The harnesses still own their own
  routing and grading code, which is correct — that code is the measurement, and
  a harness that imported the pipeline's grader would be marking its own work.
* **The 0-difference result is over this corpus.** It is a very strong signal (16
  runs, every field, exact match) but it verifies the swap, not the OCR call.

Suite **512 green** (was 511) — one added test, the identity guard above.

### Addendum, same day: what "exactly one implementation" does and does not cover

The row above was pushed before the repo was swept for other Tesseract call
sites. Sweeping it afterwards (advisor) turns up several, so the claim needs its
scope said out loud rather than inferred.

It is true as written, for the three functions named: `grep -n "def _word_box\|
def _center_in"` across `pipeline/ tools/ server/` returns exactly one hit each,
in `pipeline/stage05_ocr.py`, and the only other `def ocr_*` in the repo is
`tools/dewarp_ab.ocr_text`, which returns a joined string with no boxes and no
`/scale` map-back — a different function, not a surviving copy.

What the row must NOT be read as saying is that the 20px/2× upscale rule now
lives in one place. It does not, and should not:

* `tools/gate1_harness.py` writes the rule inline as bare literals
  (`2.0 if 0 < med_h < 20 else 1.0`) and its docstring says why: *"This tool
  stays INDEPENDENT of `pipeline/` so it remains a regression check whenever OCR
  settings change (CLAUDE.md)."* An instrument that followed Stage 05's constants
  would move whenever the thing it measures moves, which is the one thing a
  regression check may not do. Its duplication is the feature.
* `tools/dewarp_ab.py` repeats the same literals and pins itself to *Gate 1*, not
  to Stage 05 — "exactly as the Gate 1 harness does, so absolute numbers stay
  comparable to Gate 1."

So the repo has **two** Tesseract instruments on purpose: the frozen Gate-1 one,
and the pipeline's own, which the block-order and layout-WER harnesses now share
with production instead of copying. The commit above collapsed a copy *within the
second group*. It did not, and must not, merge the two groups. A test pinning
`gate1_harness`'s literals to `UPSCALE_MEDIAN_PX` was considered and **rejected**
for exactly this reason: it would assert a coupling the file forbids in writing.


## The rescued blocks were all called "other" — one of them wasn't — 2026-08-26

**What was asked.** Stage 05 rescues words that fall outside every detected block
into synthetic blocks so nothing is dropped. Those blocks were typed `other` by
construction, nobody having looked at what they are. The task was to type them.

**What the census said, before any rule was written.** `tools/layout_order_eval`
now records every rescued block (bbox, word count, median word height, text) next
to the page's real blocks, so the question "what ARE these?" is answerable instead
of assumed. All 16 on the eight block-order GT subpages, read by hand —
`docs/data/rescued_type_census_20260826.json`:

| what it is | n | examples |
|---|---|---|
| OCR noise, 1–2 garbage tokens | 10 | `n,` `ME` `ei` `di i]` `orme` `ed bacri` `I nia pica ian na n PE aaa EEE EEE pa` |
| real words printed ON a figure | 5 | `CL 'INEAMENTO` / `PERIADR\A` (a map's title), `0.5 cm = 200m`, `lo 0.5 cm =5 Km` (scale bars), `Livello del` |
| body text the document should carry | **1** | `1 Spalding, Eastern Exchange Currency and Finance, (314).` — en_coins_01's footnote, an honest detector miss already recorded in that fixture's `known_detector_gap` |

So for 15 of 16, **`other` is the accurate label** and the premise of the task is
mostly false on this corpus. That reframes the work from "classify them" to "find
the one rung that is worth having, and abstain everywhere else".

**Two rules that suggest themselves, measured and NOT shipped.**

* *"Default them to `paragraph`."* `stage08_render._TAG` maps both `OTHER` and
  `PARAGRAPH` to a bare `<p>`, and no CSS separates `.other` from `.paragraph`. It
  would change **nothing** in the deliverable while asserting body-text status for
  15 blocks that are not body text.
* *"Run the caption parser over them."* `figure_grouping.PROMOTABLE` already
  contains `other`, so a rescued caption is ALREADY promoted at Stage 07. The rung
  would be dead code — and it fires on nothing in this corpus regardless.

**What shipped: one rung.** `pipeline/rescued_type.py` types a rescued block
`FOOTNOTE` only when all three definitional conditions hold — it sits BELOW the
body, INSIDE the horizontal span of a text column, and is SET SMALLER than that
column — and returns `OTHER` otherwise. `HEADER` and `PAGE_NUMBER` are
deliberately **unreachable**: both are stripped by default, so a wrong call there
does not mislabel text, it deletes it, and nothing in this corpus is a rescued
header or page number to buy that risk with. `FOOTNOTE` is safe in exactly the way
they are not — it renders, only smaller.

**The condition that carries the rule.** "Below the body" alone is 1 right / 1
wrong: `i: dad aan` (it_geo_07 right, y=2874) has the same shape as the footnote.
The column condition separates them — the footnote overlaps its column 1.00, the
stray overlaps no text column at all. A third guard matters too: it_geo_05 left is
a full-page figure with no text column, where "below the body" is vacuously true
for all three of its strays; requiring a real column to hang under rejects them.

Measured on the true positive: word height **24 against its column's 28** (ratio
0.86), 8 words, column overlap 1.00.

**Result — the eval, all eight images, every field.**

```
type accuracy   92/112  ->  93/112
```

A full-field diff of before/after (float tolerance 1e-9) returns exactly **one**
substantive difference across the whole corpus:

```
en_coins_01/subpages[0]/type_ok/FN1         False -> True
en_coins_01/subpages[0]/type_ok_parser/FN1  False -> True
(+ the derived type_acc on that one subpage: 0.667 -> 0.750)
```

Segmentation recall stays 112/112, pairs stay 16/19 with 0 wrong, every tau
identical to nine decimals. The rung fired **once**, on the one block that
deserved it, and abstained on the other 15.

### Limits, stated

* **One true positive, no second example.** The three conditions are definitional
  (what a footnote IS typographically) rather than fitted, which is the whole
  argument for trusting them past n=1. The *thresholds* attached to them are not,
  and are recorded above with their measured values so a later corpus can
  contradict them.
* **The metric is structurally blind to the failure mode.** The 15 noise/figure
  blocks match no GT anchor, so `type_ok` cannot see a wrong call on any of them.
  `92/112 -> 93/112` is evidence the rung fired once and correctly — it is **not**
  evidence that it is safe. That half was checked by reading all 16 blocks by eye,
  which is why the census is committed rather than summarized.
* **Five rescued blocks are still wrong, and typing is not their fix.** The map
  titles and scale-bar labels belong to the artwork; they are text that needs
  SEGMENTING onto its figure, not a label. They currently render as loose
  paragraphs in the reading flow. Untouched here, and a real open defect.
* **The prose that said otherwise is fixed in the same commit.**
  `tools/layout_order_eval` asserted in two places that "an orphan-rescued block is
  typed `other` by construction"; that stopped being true with this commit.

Suite **534 green** (was 512): +13 for the new module, +9 for the editor commit
immediately before it.

---

## The map's own title was reading as a paragraph — putting it back on the picture — 2026-08-28

Stage 04's figure box does not always reach the ink. On `it_geo_05`-left the box
starts 51px BELOW the handwritten annotation the map carries across its top
(`LINEAMENTO PERIADRIATICO`); on `it_geo_07`-right it starts 17px below the
cross-section's printed waterline label (`Livello del mare`). Those words fall
inside no block, so `attach_words` rescues them into synthetic `OTHER` blocks,
XY-Cut ranks them by position, and the re-typeset document opens the page with a
loose paragraph reading `CL 'INEAMENTO` — a fragment of a map's annotation,
standing in the reading flow as if it were prose. The 2026-08-26 rescued-block
census (`docs/data/rescued_type_census_20260826.json`) counted these and recorded
the verdict: they are text, but they belong to the artwork, and what they need is
SEGMENTING, not typing. `pipeline/figure_text.py` is that segmentation — the
stray is folded INTO the figure (box unioned, words moved onto the figure, where
Stage 08 draws pixels and ignores text), so no block is created and no word is
lost.

Evidence: `docs/data/figure_text_ab_20260828.json` (both arms in full, the
pre-registration, and the full-field diff) plus two crops of the real pixels.

### The A/B, and why it is a real one

ON = shipped default. OFF = the SAME code and the SAME config with one knob
disabled, `layout.figtext_max_gap_frac = -1.0`, which makes the vertical-gap gate
unsatisfiable so nothing can be absorbed. Not a `git stash`: stashing would also
revert the eval-tool changes and the two arms would dump different JSON schemas,
turning a clean comparison into a noisy one.

The alternate config lives outside the repo, which is a hazard worth naming: if
`yolo_ckpt` / `uvdoc_ckpt` / `tessdata_dir` resolved against the CONFIG file's
directory, the OFF arm would have found no checkpoint and silently fallen back to
the classical detector, and the whole comparison would be two different detectors
mistaken for a feature. They resolve against `REPO_ROOT`
(`stage04_layout.py:814`, `stage03_dewarp.py:347`, `gate1_harness.py:72`), and
the arms confirm it empirically: identical `real_blocks` COUNT on all 16
subpages, and byte-identical boxes everywhere except one box per absorption site
— the figure that grew.

`n_det_blocks` is NOT that check and must not be used as one: it counts the
SHIPPED set, after Stage 05 adds blocks, so it differs (5 vs 7, 17 vs 18) on
exactly the two absorbing subpages for the expected reason.

### What changed

Three absorptions, at two sites, across all 8 images / 16 subpages:

| site | words | figure box OFF -> ON | v-gap | h-inside | nearest text |
|---|---|---|---|---|---|
| `it_geo_05`-L `LINEAMENTO`   | 1 | (231,331,1806,2658) -> (231,280,1806,2709) | +3px  | 1.00 | +130px |
| `it_geo_05`-L `PERIADRIATICO`| 2 | (same figure, same growth)                  | -12px | 1.00 | +158px |
| `it_geo_07`-R `Livello del`  | 2 | (91,842,876,624) -> (91,825,876,641)        | -6px  | 1.00 |  +36px |

Six of the eight images are bit-identical between arms. The two documented
must-rejects both stayed rejected: `de_01`-left's garbage token `ME` (33px under
a figure but 18px from a paragraph) and `it_geo_07`-left's two scale bars (53px
and 150px from any figure — a legend for a whole column of stacked
cross-sections, not text clipped off one picture's edge).

Every accuracy column is unchanged in both arms: segmentation recall 112/112,
caption<->figure pairs **16/19 recovered, 0 wrong**, type accuracy identical.
**No order field moved** on either subpage — the two absorbed groups leave the
XY-Cut ranking rather than re-entering it, so `tau` and `order_all` are untouched
rather than perturbed-and-recovered.

### The positive evidence is PIXELS, because the metric cannot see it

None of the three absorbed blocks matches a GT anchor, so the accuracy columns
are structurally blind to a wrong call here — the same blindness `rescued_type`
paid for on 2026-08-26. A clean diff is evidence of no collateral damage, and of
nothing else. So both sites were cropped out of the real dewarped pages with the
two candidate figure tops drawn on them:

* `docs/data/figure_text_ab_20260828_map_title.png` — green = ON figure top
  (y=280), red = OFF (y=331). The red line runs straight THROUGH the middle of a
  handwritten `LINEAMENTO PERIADRIATICO` written across the map. That is why the
  words fell outside every block. Green sits above them.
* `docs/data/figure_text_ab_20260828_livello.png` — green y=825, red y=842. Red
  cuts through an italic `Livello del mare` printed on the cross-section at the
  waterline, with the blue sea directly beneath it.

Both are unambiguously part of the artwork, and in both the OFF box bisects the
words rather than missing them cleanly.

### What got WORSE, and why it still ships

**One caption<->figure pair that used to be emitted now abstains.** On
`it_geo_07`-right, the caption-typed block `det3` sits 4px below figure `D6` and
was paired to it by the geometry arm. Growing `D7` upward by 17px moved the
runner-up gap from 53px to 36px — inside the ambiguity band
`geom_ambiguity_ratio * max(best_gap, floor) = 1.60 * max(4, 30) = 48` — so
`figure_grouping` now abstains with "two figures are comparably close (4px vs
36px)". The pair was marginal in the OFF arm (53px against a 48px bar), not
comfortably held.

This subpage has no GT pair, so the eval grades neither arm. Reading the GT
settles it against BOTH of them: `it_geo_07`'s D6 is described as *"Stage 6
diagram ('Riempimento del Bacino di Belluno: fondale omogeneo dal Cansiglio al
Garda' **sub-label stays inside**)"*. That text is `det3`. It is not a caption at
all — it is D6's sub-label, and it belongs INSIDE D6. The OFF arm paired a
sub-label to a figure as if it were a caption; the ON arm stops doing that and
leaves it standing alone. Neither is the right output. Corpus pair totals are
unchanged (16/19, 0 wrong) and the standing bar prefers an abstention to a guess,
so this ships — recorded, not buried.

### Limits, stated

* **Three true positives on one corpus of four books, none of them GT-anchored.**
  The gates sit in measured gaps (accepted at +3/-12/-6px against a nearest
  rejected 33px; h-inside 1.00 x3 against a nearest rejected 0.69), but a book
  whose figure boxes are looser would need them re-measured.
* **A DETECTED block that belongs inside a figure is out of reach by
  construction.** `figure_text` only sees words that landed in NO block. D6's
  sub-label above has its own detection, so absorption cannot touch it even
  though the GT says explicitly that it belongs inside the figure. Same class of
  defect, different mechanism, still open — and now the reason `it_geo_07`-right
  looks odd, so the next reader does not rediscover it from scratch.
* **`it_geo_07`-left's two scale bars are still loose.** Deliberately: they are a
  legend for a column of stacked diagrams, and folding them into the topmost one
  would be a guess about which figure owns them. Known-wrong output recorded
  rather than a wrong pairing shipped — the same `0 wrong` bar `figure_grouping`
  holds.
* **The module's own docstring said "every other number is unchanged."** That is
  now contradicted by this measurement and is corrected in the same commit.

Suite **547 green** (was 534): +13 for the new module.

## The phone session that demoted auto-capture, and found the book detector blind — 2026-08-28

Second on-device session (Galaxy S23, SM-S911B, wireless adb; server on the
LAN at `0.0.0.0:8000`). The phone reached the server on the first try —
`curl` from the device to `/api/jobs` returned 200 before any UI was
exercised — so nothing below is a network-plumbing artefact.

### What is now confirmed on real hardware, for the first time

| Thing | Evidence |
|---|---|
| Job list + **resume** from the list | tapped an existing job, it re-targeted polling and rendered its state |
| **Progress display** | "7/7 stages" with per-stage ✓ against a live server |
| Manual capture → review → close-ups → upload → full pipeline | two pages, both `exit 0` through all seven stages |
| An **18-image page** (2 full shots + 16 close-ups) | `page_002`, ran clean |
| **Uncertainty mode chosen on the phone** | created a job as `patch`; server wrote `{"mode": "patch"}` |

### Finding 1 — the hover gate delivers ONE still on a phone, not four

The confirmation run that `autoArmed`'s default had been waiting on since
2026-08-19 finally happened, and it went the other way. Armed over a real
spread, the burst handed off **1 shot**. The device's own cache is the
evidence, not the UI: exactly one `auto_*.jpg` for the hover, so the burst
collapsed after the first still rather than losing async callbacks.

**The replay that produced "four stills per hover" could not have caught
this.** Calibration logging *deliberately suspends capture* — that is what
makes a 15 s recording possible at all — so the three recordings the hold
threshold was fitted on contain **no frame from just after a shutter fires**,
which is precisely the moment the hold test fails. The blind spot is
structural. Any future gate tuning has to log through a live capture or it
will keep re-deriving a number the device does not honour.

Owner's call, same session: **manual capture is the flow, auto-capture stays
as an opt-in toggle.** Shipped in `5a7f463` together with two UX defects the
device surfaced immediately — the close-up screen returned to review after
*every* shot (so capturing several cost a re-entry each), and there was no way
to take more than one whole-spread photograph. Both now stay put and append,
and Stage 01 gets the several full-spread frames its anchor choice wants.
They are still **not stitched**: blending close-ups was measured to make OCR
worse (RESULTS 2026-08-19) and 16 of 16 were correctly declined here
(3 inliers against a floor of 8).

### Finding 2 — the phone could not choose the uncertainty mode

`createJob` sent no `mode`, so every phone job was the server's `flag`
default and two of the three modes CLAUDE.md requires were unreachable from
the only client that exists — despite the server having persisted a per-job
mode since `ecc9993`. Fixed and verified on the device in `665791b`. The
existing test asserted only the request *path*, which passed happily
throughout the defect; it now asserts the query string.

### Finding 3 (the important one) — the book detector returns the whole frame

**Neither real capture split into pages.** Two different failures, one cause
upstream of both.

`page_001` — the ink-valley cue fired at `gutter_x = 2741` and **won
outright**, cutting through the middle of the right-hand page. `left.png`
came out holding *both* pages; `right.png` held margin and read **0 words**.
The other two cues had it right: `pinch_x = 1668`, `shadow_x = 1730`, and
cropping those columns out of the anchor confirms on pixels that the real
gutter is there (left page ends, right page's "Honduras" heading begins),
while 2741 is a **white channel inside the right page** between its
coin/caption column and its body text — a product of the figure layout.

`page_002` — no cue cleared its gate, so Stage 02 abstained and emitted
`single.png` (the whole spread as one page). Text quality was fine:
935 words, 860 at conf ≥ 60, mean 88.6.

**Both gates were within a few percent of going the other way, and both went
the wrong way.** `page_001`: ink `ratio` 0.525 against a 0.55 cutoff (fires,
wrongly); `pinch_depth` 0.106 against a 0.11 cutoff (silent, correctly
located). `page_002`: ratio 0.701, pinch depth 0.012. That says the cascade is
not robust on this corpus, not that one threshold is mistuned.

**Why the ink cue is wrong here, stated as a property of the book rather than
of the photograph:** it assumes the gutter is the emptiest vertical strip. On
a numismatic page — coin plates floating in white, captions in a side column —
there are several emptier strips than the gutter, and at least one of them is
*inside* a page.

**And why the crop that exists to prevent exactly this never ran.** Both
captures reported `book_crop_applied: false` with the reason "book fills
92%/100% of the frame — already tightly framed". That reason is **derived
from a failed detection, not from the framing**: `page_002` is a book on a
sofa with a wide margin of upholstery all round, and the debug overlay's emit
box runs along the frame edge. Measured on that exact photograph, the search
box's bright-paper test (`S < 0.25 and V > 0.55`):

| region | S | V | share passing the paper test |
|---|---|---|---|
| whole frame | — | — | **39.9 %** |
| the page itself | 0.140 | 0.534 | **56 %** |
| sofa (bottom left) | 0.256 | 0.524 | **22 %** |

The page is dim enough that its brightness sits *below* the 0.55 cutoff, and
the sofa is pale and desaturated enough to partly pass it. Page and background
are not separable by that rule on this shot, so the component spans the frame
and the box becomes the frame. The 83 % abstain gate then reads a detection
failure as tight framing — the gate is not wrong, its input is.

**Not a logic bug, a reporting one.** `corroborated: true` is documented as
scoped to the *pinch* cue ("for a pinch split: did shadow OR ink agree?") and
on `page_001` it is factually correct — shadow 1730 vs pinch 1668, inside the
122 px tolerance. The defect is that it is serialized into `split.json`
unqualified, so a reader takes it as endorsing whichever gutter shipped. The
larger half is that **nothing acts on two cues agreeing ~1000 px away from the
answer that shipped** — which is positive evidence against that answer, and is
also the shape of the 2026-08-19 "both flags true on the wrong edge" finding.

Fix deliberately **not attempted in this session**: Stage 02 carries 13+
non-regression fixtures and the bar here is a measured row, not a plausible
patch.

### One number NOT to quote

`page_001`'s 826 words / 677 at conf ≥ 60 / mean 79.8 is a **whole-spread**
figure — it came from an image containing both pages because the split was
wrong. It is **not** comparable to `zoomset_de_02`'s per-page 293/385, and it
is not evidence that OCR improved.

### Addendum, same day: the two resilience checks that had never been run

Goal 4 of `docs/DEVICE_SESSION.md` was the only completely untouched goal.
Both halves now pass.

**Upload over a dropped link — took the CLEAN branch.** Wi-Fi switched off on
the phone, upload tapped, Wi-Fi restored ~15 s later. The spread arrived as
**one** page holding **both** files, `exit 0`. The outcome that matters is
*which* branch fired, not that it worked: the known-and-accepted failure —
a response lost *after* the server already processed the request, which
retries into a genuine duplicate page — did **not** occur. One observation, so
this says the good path works, not that the duplicate path is unreachable.

**Server killed mid-page — reconcile rescues it.** Killed on *state*, never on
a timer: `reconcile.py` deliberately never re-enqueues a `failed` page, so
hitting the wrong moment would test nothing. Same result both times — these
are **runs 2 and 3; run 1 killed nothing and was invalid, see the scar below**:

| | page_002 | page_003 |
|---|---|---|
| state when killed | `running`, `exit_code: null` | `running`, `exit_code: null` |
| what the tree kill took | server + child pipeline pid | server + 2 children |
| re-enqueued after restart | 09:56:49 | 09:59:26 |
| final | `done`, exit 0 | `done`, exit 0 |

Two notes recorded rather than discovered later:

* **`worker.json` is overwritten by the recovering run**, so a completed page
  carries no trace of having been interrupted. The recovery is only visible
  live, or by noticing `started_at` is later than the upload. Fine today;
  worth knowing before anyone tries to audit a restart after the fact.
* **A second server launched against the same jobs root runs its startup
  reconciliation BEFORE the port-bind check.** Observed accidentally: the
  duplicate process re-enqueued a page the first server was actively running,
  then exited with `[Errno 10048]`. Harmless in this instance, but an
  accidental double-launch can duplicate work on an in-flight page. Not fixed.

And one methodological scar, since it nearly published a false pass: the first
run of this test reported success while **killing nothing**. PowerShell's
`Out-File -Encoding utf8` writes a BOM, the BOM rode along in the PID string,
and `taskkill` answered `The process "?39452" not found` — which the script
did not treat as fatal. The page then completed under the *original* server
and the state timeline looked exactly like a recovery. Read the PID with
`utf-8-sig`, and check that the process is actually gone.

## 2026-08-28 — the pale-background frames become fixtures, and the suite goes red

Phase 0 of `docs/plans/book-detector-pale-background.md`. No detector code was
touched; this row exists because the **baseline moved**, which is the thing a
later fix will be measured against.

`testset/paleset_01.jpg` and `testset/paleset_02.jpg` are the two real captures
of 2026-08-28 that did not split into pages. They are now committed, labelled
fixtures, and `tools/split_eval` is **19/21, exit 1** because of them.

| id | expect | got | method | ratio | pinch | clip | |
|---|---|---|---|---|---|---|---|
| `paleset_01` | 1680 | **2741** | ink | 0.53 | 0.11 | 0.0 % | FAIL — split inside the right page |
| `paleset_02` | 1778 | **none** | none | 0.70 | 0.01 | 0.0 % | FAIL — no gutter, `single.png` |

**All 19 pre-existing spreads keep their exact shipped answers**, and worst
clipping of a labelled book stays 0.0 %, so nothing regressed: the two new rows
are the whole of the difference between 19/19 and 19/21.

**Red on purpose.** The plan listed three ways to absorb two known-failing
fixtures — an expected-fail list, a second arm like `layout_order_eval
--no-stage05`, or simply letting the suite fail. The owner chose the third:
a real failure should not be parked somewhere it stops being visible. Do not
"fix" the suite by removing or excusing these rows.

### What was banked, and how it was labelled

- **Pixels.** Each committed JPEG decodes **byte-for-byte identical** to the
  Stage 01 anchor the failing job actually saw
  (`jobs/20260828-092505-15c41a76/page_00N/01_fuse/anchor.png`; Stage 00 applied
  no rotation to either), so these rows need no gitignored `jobs/` input — unlike
  `de_01`/`de_02`, which still reach into `jobs/orient_fix_de*`.
- **Ground truth.** A book box each in `gt/book_box.json` — the **first
  pale-background book-box labels**, taking that corpus from 6 spreads to 8 — and
  a gutter each in `gt/gutter.json`. Hand-read off the committed full-resolution
  JPEG with ruler overlays at 1:1 and 1.4–1.6× on every edge, then re-checked by
  drawing the labels back onto the frame. Independent of every quantity the
  detector computes, and read before any fix was attempted.
- **A corroboration, not a fit.** The labelled boxes cover 0.577 and 0.436 of
  their frames; the same day's throwaway background-first probe reported 0.561
  and 0.438. Two independent routes to the same box, within ~2 points of frame
  area.
- **A paired control, for free.** Both frames are the *same two pages* as
  `en_coins_03` (`Chopmarked Coins` pp.104–105), which is flat, well framed, and
  passes today. Content is held constant and only the surface changes.

Machine-readable inputs and outputs: `docs/data/paleset_fixture_20260828.json`.

### One line of the plan is now stale

Phase 0 was written as urgent because "the two failing frames exist only in
gitignored `jobs/`, one `git clean` from gone". `tools/archive_photos.py` (same
day, commit e048b34) already put all 31 of those captures in
`M:\claud_projects\bookscan_captures` with a manifest, so the pixels were never
at risk by the time this ran. What Phase 0 actually delivered is the other half:
committed, labelled fixtures, so an experiment is reproducible from the repo
alone.

### A trap these two labels set, measured rather than discovered later

The clipping metric divides by the **labelled box area**, so a hand label read to
±20 px is knife-edge against a bar of exactly 0.0 %. Measured with
`_clipped_fraction`: on `paleset_01` one pixel off the left or right edge costs
**0.033 %** (0.042 % top/bottom), on `paleset_02` **0.036 %** (0.052 %). A 20-px
inset all round therefore reports **~3 %** and prints as PAGE CONTENT LOST.

`paleset_01` is the sharp case: **its book runs off the left edge of the frame** —
the page reaches x=0 in a band around y=2620–2660 — so the label starts at x=0 and
any crop starting further right clips it (25 px in is already 1.4 %). The label was
*not* softened by inventing an inset, because the book really does leave the frame
there.

Both rows read 0.0 % today only because the detector abstains and emits the whole
frame; the trap springs the moment a fix makes the crop apply. So on those two rows:
a clip under ~2 % landing in an edge band is adjudicated by **whether the band
contains ink** — blank outer margin is label precision (report the number *and* the
adjudication), ink removed is a real failure at any size. The 19 pre-existing
spreads keep the plain 0.0 % bar; they never hit this because their emitted crops
are larger than their labels.

## 2026-08-28 — the book detector stops claiming things it did not measure

Phase 1 of `docs/plans/book-detector-pale-background.md`. **No accuracy change,
and that is the point:** `tools/split_eval` still reads **19/21, exit 1**, worst
clipping still **0.0 %**, and the table is identical to the previous commit row
for row — verified by running the eval at `HEAD`, applying the change, and
diffing. Suite 554 green. What changed is what the artifacts *say* when the
detector fails, because on 2026-08-28 they said three things that were not true.

Machine-readable inputs and outputs: `docs/data/phase1_honest_failure_20260828.json`.

### 1. The abstain reason is no longer a verdict about the photograph

Before: *"book fills 92 % of the frame (>= 83 %) — already tightly framed, not
cropping."* That sentence is a claim about the **shot**, inferred from a
detection that — by the act of abstaining — was never confirmed. On the two pale
captures it was wrong and it was actionable: it sent an operator to reframe a
correctly framed photograph. After:

> `reason`: detected region covers 92 % of the frame (>= 83 %) - cropping to it
> would discard almost nothing, so not cropping
>
> `evidence`: an edge was found inside the frame, but the region it encloses
> still covers almost all of it. This is NOT a finding that the shot is tightly
> framed: a mask that merged the book with its surroundings produces the same
> number, and no runtime test measured on this corpus tells the two apart
> (2026-08-28). If the pages came out wrong, check debug/02_split.png before
> reframing.

`paleset_02`, whose box is the entire frame, gets the stronger first clause —
*"the region IS the entire frame - no edge was found anywhere in it."* The
caveat rides in a new `BookBoundary.evidence` / `split.json.book_crop_evidence`,
appears in `meta.warnings`, and is drawn on `debug/02_split.png`, which is where
a human actually looks. The conclusive refusals (no mask at all, a mask that is
a speck) carry **no** evidence string — a caveat that appears everywhere means
nothing anywhere, and that is asserted in the tests.

### 2. A classifier was attempted first, and it failed — measured, not assumed

The plan asked for positive evidence that a book was found. Six candidates were
measured across all 21 fixtures. **Every one puts a pale capture inside the range
of `de_01`/`de_02`**, which abstain through the same 83 % gate and are
legitimately near-tight (their boxes overshoot the labelled book by only
1.26×/1.14×, against 1.59×/2.30× for the pale pair):

| signal | 13 flat | de_01 / de_02 | paleset_01 / 02 | separates? |
|---|---|---|---|---|
| component ÷ emit-box area | 0.69–0.95 | 0.39 / 0.32 | 0.59 / 0.81 | no — inverted |
| component growth on close | 1.26–3.34 | 1.57 / 2.92 | 1.40 / 2.37 | no |
| component fills own bbox | 0.69–0.95 | 0.57 / 0.59 | 0.65 / 0.82 | no |
| component covers frame ring | 0.10–0.82 | 0.00 / 0.00 | 0.06 / 0.63 | no |
| emit box ÷ search box | 1.00–1.01 | 1.32 / 1.66 | 1.15 / 1.04 | no |
| component ÷ raw mask area | 1.23–1.79 | 1.26 / 1.24 | 1.28 / 2.04 | no |

**Why, and it is not a missing threshold:** on a tightly framed scan the book
really does reach the frame border, so *"the box is the frame"* is the correct
answer and the failure's answer at the same time. Separating them needs the one
question none of these ask — **is there a background in this photograph at
all?** — which is precisely the precondition Phase 2's background-first detector
is built around. Until that exists, refusing to guess is the honest outcome, and
`evidence` says so instead of picking a side. **Do not re-attempt these six.**

### 3. The spine-pinch cue can now say "I could not measure anything"

`paleset_02` reported `pinch_depth: 0.012`, which reads as *"this book has no
pinch"*. It is not a small pinch; it is **no measurement**. The cue takes the
first and last bright row of each column, so it only sees a page outline when
there is background above and below the page.

**The plan's model of this was wrong, and the correction matters.** It said
"Otsu inverts on a pale background". Otsu does not invert: on `paleset_02` the
sofa still reads dark — only **8.9 %** of the pixels outside the labelled book
pass as bright. What breaks the cue is that scattered bright specks reach the top
and bottom edges of most columns, pinning the profile flat at the image height.

Mean column extent over the search band, as a fraction of image height, separates
cleanly on all 21 fixtures:

| | rows | value |
|---|---|---|
| outline visible → cue applies | `paleset_01` 0.798, `de_01` 0.823, `de_02` 0.829, `zoomset_de_01` 0.840 | **max 0.840** |
| profile pinned → no measurement | the other 17, incl. `paleset_02` **0.977** | **min 0.924** |

Gate at the midpoint, **0.88** — the rule this stage already uses for
`pinch_min_depth` and Stage 00 uses for its OSD 180° floor. Layer 2 is skipped
when the cue is inapplicable, so a meaningless number can never cut a page.

**Non-regression here is MEASURED, not structural**, unlike the other two items.
The only two spreads pinch decides (`de_01` 0.823, `de_02` 0.829) stay applicable
with room to spare, and every other row is decided by ink or by nothing — so no
shipped answer moves. But `zoomset_de_01` (extent 0.940, pinch depth 0.215) would
newly be refused the pinch cue *if ink ever stopped deciding there*. That is a
counterfactual, not a change on this corpus, and it is the correct call: its
search box is cropped inside the book, so there is no outline in those pixels.

### 4. Corroboration now says what it corroborates

`corroborated` → **`pinch_corroborated`**, which is the question it always asked
(does anything agree with the *pinch candidate*), computed whether or not pinch
decides. On `paleset_01` it read `true` for a column ~1000 px from the cut that
shipped. New **`corroborated_by`** lists the cues that agree with the column that
**actually shipped** — `[]` on `paleset_01`, `["ink","shadow"]` on `de_02`. New
**`band_x`** publishes the search band in original coordinates, because a cue
reported *on* that boundary is the band clipping its profile, not a page feature.
Note `pinch_corroborated` is meaningless when `pinch_applicable` is false, and
says so in the schema.

### 5. The dissent flag is weak, and it admits it

`other_cues_agree_elsewhere` fires when the two cues that did **not** decide agree
with each other and both disagree with the winner — the `paleset_01` shape, and
positive evidence against the shipped column. Measured over all 21 fixtures it
**fires 5 times, and 4 of those are correct splits**:

| id | shipped | 2nd cue | 3rd cue | band | correct? |
|---|---|---|---|---|---|
| `paleset_01` | ink 2741 | pinch 1668 | shadow 1730 | 1224–2856 | **no — true positive** |
| `en_coins_01` | ink 1960 | pinch 2799 | shadow 2799 | 1200–2800 | yes |
| `en_coins_02` | ink 1994 | pinch 2796 | shadow 2744 | 1200–2800 | yes |
| `en_coins_03` | ink 2024 | pinch 2791 | shadow 2799 | 1200–2800 | yes |
| `de_01` | pinch 1983 | ink 2703 | shadow 2790 | 1200–2800 | yes |

In **all four** false alarms both agreeing cues sit pinned at an *end of the
search band* — the artifact the plan's band-edge guard (Phase 2, C3) is for.
Rather than smuggle that guard into a phase that promised no accuracy change, the
warning states its own hit rate and prints the band, so a reader can dismiss a
band-edge case at a glance. **Nothing acts on the flag.** Acting on it is C1, and
the plan puts that deliberately last, after the crop works.

### Cost

`find_book` 318 ms and `detect_gutter` 82 ms on the 4080×3060 `paleset_01`
frame — unchanged. B1 adds **no computation**: it re-words a string from numbers
already in `find_book`'s diag. C2 adds one mean over the search band of an array
Layer 2 already builds: **0.003 ms**, 0.004 % of the resolver.

## 2026-08-28 — background-first detection: the detector half-works, the precondition does not exist

Phase 2 / A10 of `docs/plans/book-detector-pale-background.md`. **Nothing shipped
— this row is a measurement, and the decision is the owner's.** `tools/split_eval`
is untouched at 19/21, exit 1. Machine-readable inputs and outputs:
`docs/data/a10_background_first_20260828.json`.

The plan says the deliverable is not the detector but the **precondition** —
*"before trusting a background-first box, test whether there is a background at
all."* That was the right thing to name, and it is the thing that failed.

### The detector reproduces, and it splits the two failing frames in half

| frame | box found | labelled box | gutter after crop | want | clips labelled book |
|---|---|---|---|---|---|
| `paleset_02` | (312,498)-(3222,2436) | (340,495)-(3150,2430) | **1752** | 1778 ±200 | **0.00 %** |
| `paleset_01` | (702,414)-(4080,3060) | (0,400)-(3050,2760) | **3045** | 1680 ±200 | **20.85 %** |

`paleset_02` is an outright win — the box lands almost exactly on the hand label
and the row would flip from FAIL to OK. `paleset_01` would destroy a fifth of the
book.

**Why `paleset_01` fails, named rather than guessed:** its book **runs off the
left frame edge**, so the 2 % border strip the background model is fitted to
*contains page pixels*. Paper then reads as "background", the left page drops out
of the blob, and the blob leaks along a cable to the bottom-right corner. A
background-first method presumes the border is background; when it is not, it
does not degrade — **it inverts**. Same inversion the plan already identified for
tightly framed spreads, arrived at from a different direction.

### Reproducing the plan's throwaway probe — and one methodological correction

`paleset_02` reproduces (0.452 vs the plan's 0.438). `paleset_01` does not
(0.716 vs 0.561). Two bugs in the first attempt, both worth recording because
they are easy to repeat: normalising the Mahalanobis map by **its own max** lets
one outlier pixel squash the bulk of the distribution (1–5) into ~20 of 256
levels, so Otsu thresholds a histogram with all its mass in 20 bins; and adding
morphological close/open, which the plan's recipe does not have, moved
`paleset_02` from 0.452 to 0.845. Percentile-clip, no morphology, and it
reproduces.

**Area agreement is not box agreement.** The reproduced `paleset_01` blob covers
0.716 of frame against a labelled 0.577 — and it *misses the left page entirely*
while leaking to the bottom-right corner. So Phase 0's "the labels agree with the
background-first probe to within ~2 points of frame area" is **area-only
corroboration**, and should be read that way. The labels themselves remain
independent for the reasons Phase 0 gives separately: hand-read with rulers, off
the committed pixels, before any fix was attempted.

### One half of the precondition IS solved

The precondition has to answer two different questions, and they have different
mechanisms:

1. **Is the background model valid** — was it fitted to background, or to the book?
2. **Is there a background at all** — or is the border simply the page?

**Question 2 is answered by a single principled signal: how many frame sides the
candidate blob touches.** `paleset_01` = 2, `paleset_02` = 0, `zoomset_de_01` and
`zoomset_en_01` = 1, all other seventeen = 0. Two or more sides means the
candidate is not enclosed, or the border model was fitted to the book — exactly
the mechanism confirmed on `paleset_01`'s pixels. That is a real result and it is
not a fitted threshold.

### Question 1 has no cheap answer — eight families measured

| # | family | best signal | `paleset_02` | nearest flat row | verdict |
|---|---|---|---|---|---|
| 1 | paper-mask statistics (six) | — | — | — | closed in Phase 1 |
| 2 | Mahalanobis scalars | `inner_med` | 2.73 | 1.74–7.37 | inside the range |
| 3 | absolute ring homogeneity (Lab σ) | — | **19.52** | `it_geo_06` **19.81** | 0.29 gap on a 50-unit scale |
| 4 | blob compactness | fill | 0.91 | `bg_01` 0.87 (0.94 on the connectivity variant — *inverted*) | no gap |
| 5 | connectivity | ring coverage | 0.995 | 0.849–1.000 | inside; enclosure is degenerate at 1.000 for all 21 |
| 6 | text-ink veto | ink outside box | **63.75 %** on a box that clips **0.00 %** | — | fabric texture reads as glyphs |
| 7 | brightness polarity | ΔL fg−bg | 72 | `bg_01` 71, `bg_02` 71, `bg_03` 69 | no separation |
| 8 | border texture | Sobel median | 69.87 | `bg_01` 71.34, `it_geo_04` 69.81 | weave = page texture |

Family 3's `ring_p90` deserves a specific warning: Mahalanobis distance of the
ring **under the ring's own model** is self-normalising by construction, and duly
reads 2.14–3.11 across all 21 frames. It looks like a homogeneity measure and is
not one. Family 8 was predicted to fail by the plan's own A3/A6 ("upholstery is
smooth at both scales"); it is now measured rather than predicted.

**Why this is structural, not a missing threshold.** On a tightly framed scan the
border *is* the page, so a background-first method finds the **printed area**
instead of the book — and a printed area is also large, also rectangular, also
compact, also bordered by something darker, and (at the ring) also textured.
Every property that makes a book look like a book is shared by the thing this
method finds when it inverts.

### What an unguarded fallback would cost, measured

The existing guards refuse some bad boxes for free: `min_area_frac` 0.10 refuses
`en_coins_01/02/03` (0.026–0.028) — **including the plan's nominated "sharpest
test", `en_coins_03`, which therefore discriminates nothing** — and
`abstain_area_frac` 0.83 refuses `bg_02`, `bg_03`, `it_geo_04` (0.92–0.99).

**Seven of the thirteen flat fixtures survive both guards and would be cropped**,
losing this much of their text-like ink:

| `bg_01` | `it_geo_01` | `it_geo_02` | `it_geo_03` | `it_geo_05` | `it_geo_06` | `it_geo_07` |
|---|---|---|---|---|---|---|
| 17.6 % | 46.0 % | 92.5 % | 57.7 % | 39.1 % | 39.6 % | 69.6 % |

None of those seven has a labelled book box, so **`split_eval`'s clipping column
is blank for all of them** — an unguarded A10 could destroy page content on seven
fixtures and still print a green table. That is why this was checked directly per
row instead of being inferred from the harness.

### The archive cannot fix this, and that corrects a standing impression

Calibrating a precondition on one positive example is not calibration. The
obvious remedy — bank more pale-background fixtures, there are 31 in the archive —
**does not exist**. Those 31 files are **11 frames of `page_001` (a lap shot), 18
frames of `page_002` (the sofa shot), and 2 more frames of the lap scene** from
the same session's patch-mode run. Two scenes, one session, one book, one surface
each. Question 1 has exactly **one** usable positive, and `paleset_01`'s scene is
a *negative* for A10 itself.

**The route to n > 1 is new photographs of new surfaces, not the archive.**

### Cost, if it ever ships

Background-first is **23 ms** on the 4080×3060 `paleset_01` frame, against
`find_book`'s own 318 ms, and it would run only where the paper route already
abstained on area. Cost is not what stands in the way.

## 2026-08-28 — the operator draws the box, on the desktop

The escape hatch the pale-background investigation ended at, built. Owner's call
on both counts: do this **and** go shoot more fixtures, and draw the box **on the
computer, not the phone** ("it is easier"). `tools/split_eval` is unchanged at
**19/21, exit 1**, worst clipping **0.0 %** — nothing in `testset/` has a drawn
box, and the absent case is byte-identical by construction. Suite **569**
(was 554). Machine-readable: `docs/data/operator_book_box_20260828.json`.

### It works, and on exactly the frames that fail today

Feeding the eight hand-read boxes from `gt/book_box.json` in as if an operator
had drawn them — those were read with ruler overlays off the committed pixels,
which is what a careful drag approximates — splits **8 of 8**:

| | today, no box | with a drawn box | ground truth |
|---|---|---|---|
| `paleset_01` | **2741** (inside the right page) | **1699** | 1680 ±200 |
| `paleset_02` | **none** — one page | **1749** | 1778 ±200 |

The other six (`de_01`, `de_02`, four `zoomset_*`) stay correct.

### The drawn box is padded, and that is the whole safety property

Feeding the labels in straight makes "clips 0.00 %" true by construction, so the
real question is what a *drag* produces. A 4080 px frame shown ~1000 px wide is
~4 image pixels per screen pixel. Shrinking each label to simulate that:

| emit box is… | 1 % undersized | 2 % | 3 % | 5 % |
|---|---|---|---|---|
| the drag exactly | **1.95 %** of the book lost | 3.92 % | 5.90 % | **9.73 %** |
| the drag padded by `search_pad` | **0.00 %** | 0.00 % | 0.00 % | **0.00 %** |

All eight gutters stay correct in both rows; text is only lost past a ~14 %
undersized drag. So `book_boundary.user_box` pads the box outward and Stage 02
cuts the padded one — which is also what `find_book`'s existing
`_union(emit, search)` produces anyway. The module's own asymmetry decides it:
stray room inside the emit box is harmless, clipping cannot be undone.

**On the 0.08 pad — no overclaiming.** It was chosen by sweeping {0, 0.03, 0.06,
0.10} against these eight boxes and taking what worked; 0.06, 0.08 and 0.10 all
give 8/8. That it equals the existing `search_pad` is a consistency argument (one
pad concept, one value), not independent evidence. And record the **dead zone**:
`zoomset_de_01` passes at 0.00, **fails at 0.03**, passes at 0.06+ — the ink cue
has lost its valley there while the pinch cue is not yet applicable, a direct
consequence of the applicability gate shipped earlier the same day. A smaller pad
is *not* safer.

### The failure mode found by actually using it

Driving the tool in a browser, a drag ~400 px too wide **on the right only**
took `paleset_01`'s ink ratio from 0.44 to 0.56 and lost the split entirely. The
perturbation sweep had only tested *symmetric* error, so it had missed this.
Measured properly afterwards:

| extra width on **one** edge | 0 % | 5 % | 10 % | 15 % | 20 % | 30 % |
|---|---|---|---|---|---|---|
| spreads split correctly | 8/8 | 8/8 | **7/8** | 7/8 | **5/8** | 4/8 |

Symmetric error is far more forgiving — **±10 % is 8/8 with 0.00 % clipping**.
The mechanism is plain once seen: the spine is searched in the middle **30–70 %
of the drawn box**, so extra width on one side slides the book sideways inside it
until the spine leaves the band.

That is invisible to an operator, so the editor now **shades the 30–70 % band of
the box being drawn** and draws the last gutter it found as a line, and the
header says the mistake to avoid is *extra room on one side* rather than
sloppiness in general. A wrong box is now something you can see before you save
it.

### What ships, and the rules that keep a trusted box safe

`tools/book_box_editor` (stdlib HTTP server + a browser page, the
`pipeline/editor.py` pattern) writes `<page_dir>/book_box.json`. That file is
**user input, not a stage artifact** — the same kind of thing as `config.yaml` or
`--mode patch` — which is why it sits at the page-dir root rather than in a
numbered folder, and why it is a documented CLAUDE.md exception. A hand-drawn box
carries a human's confidence, so:

* a box whose `frame`/`frame_size` does not match the current anchor is
  **refused** with a stated reason and the detector runs instead — a box drawn
  before Stage 01 re-ran is a wrong crop nobody would question;
* a degenerate or sub-`min_area_frac` box is refused in the editor *before* it is
  written, and again in Stage 02;
* a corrupt `book_box.json` is treated as absent, never as an error — a
  convenience tool must not be able to stop a page processing;
* deleting the file restores the detector byte-for-byte;
* `split.json` gains `book_crop_source` (`detector` | `operator` |
  `operator-refused`), because `book_crop_applied: false` alone cannot tell a
  refused operator box from a page nobody ever drew on;
* a box covering the **whole frame** is a third outcome, not a crop: it is
  kept as the operator's answer (`book_crop_source: operator`) but reported
  `applied: false` with *"there is nothing to crop away"*, and the editor
  says so before writing anything. Recording it as an applied crop would be
  the same overstatement the abstain gate was fixed for earlier the same day.

The re-split button runs **Stage 02 only** — draw, re-split, look at the overlay.
Stages 03–06 stay a separate explicit run.

---

## 2026-08-29 — A vision model's book box, graded on the split it has to survive

`tools/vlm_box_eval.py` · data: `docs/data/vlm_box_split_20260829.json`

The experiment `docs/notes/2026-08-29-local-llm-available.md` deliberately did
not run. That note measured a local vision model (`qwen3.6:27b`, Ollama) against
`testset/gt/book_box.json` and got IoU 0.905/0.940 on the two pale frames the
detector fails on — then said, correctly, that IoU is not the load-bearing
metric, because RESULTS 2026-08-28 measured that **asymmetric** box error is what
breaks the split. So: feed the model's box through the SAME path a hand-drawn one
takes (`book_boundary.user_box` — validated, refused when degenerate, padded
`search_pad` outward), run the real `detect_gutter`, grade against
`testset/gt/gutter.json`.

**This is not a reproduction of the note's numbers, it is a stricter
re-measurement.** `localLLM/book_box_probe.py` parses the answer under *both*
coordinate orderings and reports whichever fits the label better — a selection
made using the ground truth. Here the ordering is fixed a priori to the model's
documented convention and never chosen per image. All 21 answers parsed under it.

### The bar, pre-registered before the first model call

A row counts as correct only if **all three passes** land within tolerance;
`paleset_01` must reach [1480, 1880] (shipped: 2741) and `paleset_02`
[1578, 1978] (shipped: no gutter at all); and the 19 rows correct today must stay
correct. Clipping was expected to read 0.0 % by construction. It did not — see
below, that is the finding.

### Result

| arm | what it is | gutters |
|---|---|---|
| A | the shipped detector | 19/21 |
| B | model box on **every** row | **21/21** |
| C | model box only where the detector abstains | **21/21** |

`paleset_01` 2741 → **1697** (target 1680 ± 200) and `paleset_02` none → **1749**
(target 1778 ± 200) — within 2 px of what a HAND-DRAWN box produced on the same
frames (1699 / 1749, RESULTS 2026-08-28). Zero gutter regressions in either arm.

**The unknown this run actually resolved was not the two pale rows.** The
detector abstains on **17 of the 21** graded rows — all 13 flat fixtures, both
`de_*`, both `paleset_*` — and abstain hands back the whole frame, which is
*why* those rows have been correct. So 15 currently-correct rows had never been
run through an applied crop before today. They all survived one. That also means
"where the detector abstains" is **not** a narrow trigger: arms B and C differ on
4 rows only, so C is not the safe subset it sounds like.

### The gutter column hides one thing: the crop is no longer clip-free

`user_box` pads 8 % outward and unions emit with search, so a crop from a
*hand-drawn* box measured 0.00 % clipping everywhere. A model box does not:

| row | clipped | in arm C? | what is in the lost band |
|---|---|---|---|
| `de_02` | **1.89 %** | **yes** — the detector abstains here | 62 px off the left: cloth, the shadow gap, the fanned closed-page block, and the outer sliver of a solid coloured side tab |
| `zoomset_en_02` | 1.19 % | no — the detector crops here, so C never takes the model's box | 26 px off the bottom: entirely the polka-dot tablecloth (median grey 41 vs page interior 155) — the label runs past the page |

So the shippable arm has **one** affected row, not two.

Adjudicated per `book_box.json`'s own instruction (a sub-2 % clip is a finding
plus an adjudication; a clip that removes **ink** is a real failure at any size).
Checked two ways: a connected-component pass found 22 letter-like blobs in
`de_02`'s lost band against 110 in the 62-px strip immediately inside it, and
looking at both regions at 3–4× showed those 22 are the coloured page tabs and
the fanned page-edge texture, not glyphs. **No readable content is lost.**

### And that is a finding about the METRIC, not only about the model

`split_eval`'s bar is `worst_clip == 0.0`, and until today nothing could produce
a small non-zero clip: the detector abstains and emits the whole frame (trivially
0.0 %), and a hand-drawn box measured 0.00 % because a human draws generously.
The bar has therefore **never had to tell "lost text" apart from "trimmed a
tab"** — and this run is the first case that separates them. It was resolved by
hand, correctly, in a way the harness cannot express.

Two readings, and choosing between them is an owner call, not something to settle
silently:

* the model's box needs a **guard against inward error** before it can be
  trusted; or
* the bar should grade **ink lost**, not labelled area lost, in which case this
  run already passes.

What is NOT in doubt: the box loses no readable content, and `worst_clip == 0.0`
as written would go red.

**Owner's objection, 2026-08-29 — the second reading is worse than it looks, and
the decision is POSTPONED.** "Grade ink lost" is not a safe generalisation of
this adjudication. The outer edge of a **photograph or an illustration** carries
no glyphs, so an ink-based bar would score a trimmed figure edge as a clean pass
while real content went missing. The band on `de_02` happened to be book
furniture (cloth, the fanned page-edge block, a coloured tab) — that was checked
directly and still holds for **that row** — but "no text in the band" was never
the same claim as "nothing of value in the band", and the write-up above leans on
it as if it were.

So the menu is not two options, it is at least three, and none is chosen yet:

* an **inward-only guard** on the box (no metric change at all); or
* grade **content lost** — ink *or* non-page imagery — which needs a definition
  the harness does not currently have; or
* keep `worst_clip == 0.0` and accept that a model box cannot pass it.

Do NOT implement an ink-only bar on the strength of the `de_02` adjudication.
The clipping question stays **open by the owner's decision**, not by oversight.

### The mechanism, and the threshold it hands the next step

The cause is in the per-edge table (positive = the box sits outside the book,
negative = it cuts in, as a fraction of book width/height):

| row | left | right | top | bottom | clipped after the 8 % pad |
|---|---|---|---|---|---|
| `paleset_01` | −0.13 | **+4.89** | −0.30 | −3.64 | 0.00 % |
| `paleset_02` | +0.18 | +1.46 | −2.27 | −2.07 | 0.00 % |
| `de_01` | −2.33 | +0.71 | −0.83 | +0.04 | 0.00 % |
| `zoomset_de_01` | +0.47 | +2.09 | +0.38 | +2.21 | 0.00 % |
| `zoomset_de_02` | −0.85 | −1.55 | +0.59 | +0.89 | 0.00 % |
| `zoomset_en_01` | +2.57 | **+15.03** | +0.05 | +0.88 | 0.00 % |
| `de_02` | **−8.90** | −3.54 | +0.31 | −0.49 | 1.89 % |
| `zoomset_en_02` | +0.40 | −1.65 | −1.83 | **−8.36** | 1.19 % |

Read it in two directions:

* **Outward excess was harmless.** The note feared `paleset_01`'s ~5-point
  one-edge excess; it split fine, and `zoomset_en_01` carried **+15.03 %** on one
  edge and still hit. That worry can be closed.
* **Inward error is the whole failure mode, and the pad has a measured ceiling.**
  −3.64 % survives the 8 % pad; −8.36 % and −8.90 % do not. **The pad stops
  covering somewhere between ~3.6 % and ~8.4 % of inward error** — that is the
  design constraint for whatever guard comes next, and it is the number to build
  against.

### The next move this points at

Stop the box cutting inward, rather than widening the pad: an **inward-only
guard** (refuse or expand an edge that sits inside the detector's own paper
mask), or a **union with the detector's mask**, which is available on every row
because the detector still runs. Both keep one pad concept with one value.

### What this does not license

- **Do not raise `search_pad` to rescue `de_02`.** That is fitting a pad to one
  example, and 0.08 has a recorded dead zone (`zoomset_de_01` passes at 0.00,
  fails at 0.03, passes at 0.06+). A smaller pad is not safer and a bigger one is
  not free.
- **All three passes returned byte-identical boxes on all 21 rows.** At
  temperature 0 the sampler is deterministic, so the pre-registered "all 3 must
  hit" bar was satisfied *trivially*: it measured determinism, not robustness.
  Robustness would need varied inputs, not repeated ones.
- **`split_eval` stays red at 19/21.** Nothing in the pipeline was changed. A
  passing experiment is a reason to build the fix, not to relabel the rows.
- **Two pale frames are two scenes, not two examples.** This says the box source
  is worth pursuing. It cannot say the pale-background defect is fixed, and it
  does not replace `docs/plans/pale-background-fixture-shoot.md` — which still
  needs the tightly-framed **negatives** most of all.

---

## 2026-08-29 — The vision model's box, shipped as a search window and nothing else

`tools/split_eval --vlm` · `pipeline/vlm_box.py`, `book_boundary.search_only`,
Stage 02 · model `qwen3.6:27b` on local Ollama

| arm | gutters correct | worst clip of a labelled book |
|---|---|---|
| detector alone (the shipped guard) | **19/21** | 0.0 % |
| detector + model-aimed search *(new, shipped)* | **21/21** | **0.0 %** |

`paleset_01` 2741 -> 1697 (target 1680), `paleset_02` none -> 1749 (target 1778).
Nineteen previously-correct rows unchanged or within tolerance. Same harness,
same labels, same tolerance as every prior row — nothing was invented alongside
the model.

### What changed relative to yesterday's experiment, and why it matters

Yesterday's arm C routed the model's box through `book_boundary.user_box`, the
path a **hand-drawn** box takes, which pads the box outward and then **cuts** to
it. That reached 21/21 too — but it also stopped the crop being clip-free
(`de_02` lost 1.89 % of the labelled book), which forced an adjudication by hand
and left an open owner decision about what the clipping bar should even measure.

This ships the win without the risk, by separating the two boxes the boundary has
always carried:

* **`search`** — where the spine is looked for — comes from the model's box.
* **`emit`** — which pixels become the page — is copied from the detector,
  untouched.

Every frame this fires on is one where the detector abstained, so `emit` is the
whole frame and **no crop happens at all**. The path therefore **cannot clip, by
construction** rather than by measurement, and the clipping column above is 0.0 %
for a structural reason. Running uncropped is not new behaviour either: 17 of the
21 graded spreads already do, and split correctly.

**So the postponed owner decision is not blocked, and not forced.** Whether a
model box should ever be allowed to *cut* — and whether the bar should grade lost
ink, lost imagery, or lost labelled area — remains open exactly as recorded on
2026-08-29. Nothing here depends on the answer. The known objection stands and is
recorded: an ink-only bar would pass a trimmed photograph edge.

### Where it fires, and where it does not

Last resort only: the detector must have abstained **and** no operator box may be
present. A successful detection wins; a human's drawn box wins. If Ollama is not
running, the answer is unreadable, or the box is a shape no book makes (degenerate,
outside the frame, under 5 % or over 99.5 % of the frame), Stage 02 does exactly
what it did before and says so in `split.json`. A missing local service must never
fail a scan.

Recorded per page in `02_split/split.json` as `book_crop_source:
"detector+vlm-search"` plus a `vlm_box` block carrying the model, the box, how the
answer was read, the time, and — on refusal — the reason. "Never asked" is
therefore distinguishable from "asked and gave nothing usable".

### What this still does not settle

**n = 2 scenes.** Both pale fixtures are one sofa and one lap, one session. This
result is a reason to keep the fallback, not evidence that it generalises to
surfaces it has not seen — `docs/plans/pale-background-fixture-shoot.md` is
unchanged and still needed, negatives included.

The model is deterministic at temperature 0 (three passes returned byte-identical
boxes on 2026-08-29), so nothing here measures robustness to a re-ask.

Suite: 588 passed.


---

## 2026-08-29 — Close-up stitching, measured on a whole real book: 6 of 317

**Question.** The Android app captures a full-spread anchor plus multi-zoom
close-ups per spread, and Stage 01 is supposed to register the close-ups onto the
anchor so the sharper pixels reach OCR. Does that happen on real captures?

**Population.** Every close-up in `jobs/20260829-084115-de3c20d3` — the owner's
own 25-spread book, shot handheld on 2026-08-29 and uploaded in one batch. 24 of
the 25 spreads carried close-ups (page_001 is a closed cover, one frame). Read
straight out of each page's `01_fuse/fuse.json`, which records every gate's input
per close-up, not just the verdict.

| | close-ups | share |
|---|---:|---:|
| **registered and blended** | **6** | **1.9 %** |
| rejected — too few inliers (needs 8) | 283 | 89.3 % |
| rejected — located, but softer than the anchor (do-no-harm gate) | 28 | 8.8 % |
| rejected — degenerate homography | 8 | 2.5 % |
| rejected — warped close-up disagrees photometrically | 3 | 0.9 % |
| **total** | **317** | |

Per page: 22 of 25 spreads used the sharpest single frame and merged nothing
(`method: "sharpest"`); 3 merged at least one close-up (`"sharpest+stitch"`).

The inlier counts of the rejected majority cluster at **3–7** against a threshold
of 8: 93 at five, 51 at six, 44 at four, 42 at three, 20 at seven.

### This replicates a recorded finding at 29× the sample size

`pipeline/stage01_fuse.py`'s docstring already states the diagnosis, measured on
the 11 close-ups in `testset/zoomset_*` (RESULTS 2026-08-19): the failure "is a
capture-guidance and/or dewarp-before-stitch problem, not a matcher problem", and
`min_inliers` had already been corrected once, from 25 down to 8, after that run
showed the old gate was throwing away five *correct* registrations. Nothing here
is new behaviour. What is new is the sample: 317 close-ups over two dozen
spreads, in place of 11 over four.

**Do not lower `min_inliers` again.** The cluster at 3–7 is the shape that tempts
it, and the 2026-08-19 run measured what happens: raising the budget to 20k
inliers-worth of matching adds a false positive, and a five-inlier homography is
noise rather than a weak-but-real fit. A false stitch paints wrong pixels onto
the page the OCR then reads, which is a worse failure than not stitching.

### The actionable half is the capture, not the code

Two operator-facing facts fall out:

* **The close-up taps currently buy nothing.** 311 of 317 extra photographs were
  discarded, and the anchor frame was used alone on 22 of 25 spreads. Whatever
  the close-ups cost in time and battery, they are not reaching the OCR.
* **The 28 "located but softer" rejections are the interesting sub-population**,
  because those *did* register — the matcher found them, and the do-no-harm gate
  refused them for being less sharp than the frame they would have replaced.
  That is a photography problem (phone too close to hold focus, motion blur,
  focus hunting between shots), and it is the only rejection family an operator
  can act on directly.

### What this does not say

It does not say multi-zoom capture is worthless — it says this capture technique
did not produce registrable close-ups. Nothing here measures what a close-up shot
differently would do, and no fixture exists for that; the 317 rejected frames are
one book, one session, one photographer.

It also does not touch `per_page_source` (off by default, RESULTS 2026-08-26),
which is the other route by which a close-up could reach a page. That route was
measured null on its own terms and is unaffected by this.

Recorded per page in `01_fuse/fuse.json`, and now surfaced per page in the
console ("close-ups used", with the rejection families counted).

---

## 2026-08-29 — The do-no-harm sharpness gate was measuring its own resampling

**Control experiment, on the owner's 25-spread book.** Stage 01 refuses to blend
a close-up that is not sharper than the anchor over the same pixels
(`min_sharpness_ratio: 1.0`, variance of Laplacian over an eroded footprint
mask). 28 close-ups on this book were refused by that gate, and the recorded
reading of the zoomset run was that the close-ups are simply blurry.

Push the **anchor's own pixels** through the identical warp — same homography,
same `warpPerspective`, same eroded mask — and score them the same way:

| | median | range |
|---|---|---|
| real close-up, warped into the anchor | **0.630** | 0.397–1.672 |
| the anchor itself, through the same warp | **0.506** | 0.414–0.653 |
| close-up ÷ control | **1.249** | — |

n = 34 located close-ups. **The close-up beats the control on 25 of 34.** A
perfect copy of the anchor scores 0.506 against a bar of 1.0, so no close-up can
ever pass that gate however sharp it is. The statistic is dominated by the
resampling the warp performs, not by the photograph's sharpness, and the earlier
"all five are BLURRIER than the anchor" reading is an artifact of the
measurement. Stage 01's docstring and the parameter comment now say so.

**The decision does not change, and now has a better reason.** A close-up warped
DOWN into the anchor has already lost the pixels it was taken for. Measured on
the same book with Tesseract (`deu`, same settings, over the identical region):

| arm | high-confidence words | vs the anchor |
|---|---|---|
| A — the anchor's own crop of the region | 6823 | — |
| B — the close-up as shot, native resolution | 5784 | 0.85× |
| C — the close-up warped into the anchor frame | 5252 | **0.77×** |

Median linear scale close-up→anchor is 1.304, so the resolution is real; the
anchor's coordinate frame is where it dies. **Caveat, stated because it matters:
arms A and B are not strictly comparable** — Stage 05 upscales by median word
height and this measurement did not, so B < A is "no evidence of a text win",
not a measured loss. Arm C versus A is like-for-like (same frame, same scale)
and is the one that carries the conclusion.

So `min_sharpness_ratio` stays at 1.0, blending stays off, and the resolution is
collected somewhere it survives — see the next row.

## 2026-08-29 — Figures re-cut from the captures that hold them (`figure_hires.py`)

**The owner's requirement:** "there are important pictures in the books - i want
them with the highest available detail". A figure is cropped from the dewarped
page, and the page is one photograph of a whole spread, so a picture gets
whatever pixels are left after the spread is divided up. The close-ups hold more.

**The move is to stop warping down.** Instead of folding a close-up into the
anchor, take the figure we want, find every capture that contains a piece of it,
and rebuild the figure at those captures' scale. The page keeps its resolution;
only the figure asset grows. Stitching still happens — in the picture's own
frame, where it pays, rather than in the anchor's, where it cannot.

**Why the matching works here and not in Stage 01.** Stage 01 registers a whole
close-up against a whole spread, and a spread is mostly text: repetitive,
self-similar, generous with matches that are individually plausible and
collectively contradictory (317 close-ups, 49 located, median 39 good matches to
5 inliers). A figure is locally unique. On `page_023`'s cover photograph, six
frames register against the figure crop that Stage 01 never located at all.

**Result over the whole 25-spread book, 125 figure blocks:**

| | |
|---|---|
| figures upgraded | **22 of 125 (18 %)** |
| linear resolution gain | median **1.35×**, range 1.16–1.86× |
| pixel gain | median **1.83×**, best 3.5× |
| contributing frames per figure | median 2, max 4 |
| cost | 205 s for the book (~8 s/spread), inside `stage07_assemble` |

**Gates, and the two the measurement moved.**

* `min_ncc: 0.60` per source, not the 0.50 an earlier single-source run
  suggested. With partial-coverage sources admitted, agreement is computed over
  each source's *own* footprint; every mis-registered source seen on this book
  scored 0.51–0.52 and every correct one 0.63 or better. At 0.50 two figures were
  rebuilt from the wrong part of the page.
* **Greedy source selection.** A source joins only if it brings ≥ 3 % of the
  figure that nothing already in the composite has. Painting every candidate was
  the actual bug: on `page_023` ten frames all repainted the same middle, so the
  last one applied won it with its own alignment error — and the sources with
  least to add are exactly the ones judged over the smallest footprint. 10 → 1.
* **ECC refinement** of each fit, because the crop is DEWARPED and the source is
  the raw photograph: RANSAC on sparse matches leaves a systematic residual no
  set of matches can remove. Both compositions of the correction are scored and
  the unrefined fit competes, so a refinement that helps nothing changes nothing.
  Worth +0.11 agreement on `page_009` right fig 11.
* `min_result_ncc: 0.80` on the finished picture, compared **coarsely** (128 px).
  At full resolution the number does not separate: correct composites scored
  0.70–0.79 and so did one showing the wrong part of the page, because the
  dewarp-vs-homography residual punishes fine texture. Shrunk past that, the
  question left is "is this the same picture, in the same place" — the 22
  shipped upgrades scored 0.825–0.980 and the two rejected as wrong scored 0.623
  and 0.759. **This is a backstop, not the main defence, and n = 6 with one
  labelled negative is thin** — `min_ncc` and greedy selection are what keep a
  wrong source out.

**Verification is by eye, on real pixels, with a checkerboard.** Side-by-side
comparison is misleading here and misled me twice: a sharper picture reveals text
the blurry crop hides, which reads as a framing change. Interleaving the two at
80 px tiles is unambiguous — features and caption text either run continuously
across tile boundaries or they do not. Four of the 22 were checked this way,
including the two lowest-scoring, and all four align.

**What this does not say.** It is one book, one photographer, one session. The
103 figures that were NOT upgraded mostly had no candidate frame at all: a
close-up must be *tighter* than the anchor to carry more resolution but *wider*
than the figure to contain it, and these close-ups were not aimed at the
pictures. That is the operator-facing half — **a close-up framed on a picture
would upgrade it**; these were framed on the page.

**Nothing can get worse.** A refusal means the page crop stays, which is exactly
what the pipeline did before. The upgrade is written as a separate asset with the
bbox it was cut for recorded on the block, and Stage 08 falls back to the page
crop if the block's bbox no longer matches — a high-resolution picture of a
figure's *old* outline would be a wrong picture, which is worse than a soft one.


## 2026-08-29 — A picture is now built at the scale of its SHARPEST source, not its widest

`pipeline/figure_hires.py` shipped earlier today rebuilding each FIGURE from the
captures that hold it. Asked to maximise the detail on a via-ferrata topo map
(`page_021__right` block 1 — route grades and critical-point notes, the kind of
picture the owner reads rather than looks at), three separate things were found to
be throwing resolution away. All three are fixed; none of them was a threshold.

**1. The canvas came from the widest source.** Eighteen frames match that topo
map. One holds a fifth of it at **3.16x**; a frame covering half at 1.86x set the
canvas and every sharper source was resampled DOWN into it. The old comment
defended this ("a frame holding a fifth must not decide the resolution of the
other four fifths") but the canvas is only a container — a region is as good as
the source that lands on it, and a smaller container cannot improve the rest, only
spoil the fifth. Canvas is now the sharpest accepted source.

**2. Paint order gave every overlap to the WIDEST source** — precisely the one
with least resolution to offer. Sources are now laid down sharpest-first, and each
paints only pixels no better source has claimed. (This also keeps the page_023
fix: a source that adds no new pixels can only add its own alignment error.)

**3. The pieces did not agree, and the seam showed.** A source is a photograph of
a CURVED page; the crop it must fill was flattened by Stage 03. One homography
cannot express the difference, so a globally well-fitted source still sits a few
pixels out in places — with sharpest-first painting the topo map came out with the
word "Arzalpenturm" torn in half at a seam. Each source is now bent onto the
flattened page by a smooth displacement field (phase correlation per tile,
confident tiles only, interpolated and smoothed) before it is laid down.

| | before | after |
|---|---|---|
| figures upgraded (163 searched, 151 large enough) | 22 | **24** |
| median linear scale | 1.35x | **1.42x** |
| best | 1.86x | **3.65x** |
| the topo map | 1.86x | **3.16x** (2.9x the pixels) |
| agreement with the page crop, topo map | 0.833 | **0.871** |
| figures lost | — | **0** |

14 of the 22 already-upgraded figures gained more than 5 % linear; none lost
anything. Mesh alignment adds one figure and removes none.

**One figure is unreconciled and is recorded rather than rounded away.** An
offline sweep over the same 151 figures upgrades 25; the shipped assemble run
upgraded 24. The one that differs (`page_022__left` block 5) upgrades
reproducibly when run on its own — six identical searches, one source at 1.29x
covering 1.00 with agreement 0.827 and 60 inliers — including through Stage 07's
own `_upgrade_figure` with the config's own parameters. So it is not a marginal
case flipping. The most plausible cause is that `figure_hires` keeps every frame
of a spread decoded until the spread ends (18 frames x ~12 Mpx here) and a decode
returned None under memory pressure, which `candidates` skips SILENTLY. Not
reproduced, not fixed, and the silent skip is the part worth fixing first. Cost: figure assets on
this book grow to 117 MB of PNG (16 MB if written as JPEG q92 — not done, the
asset is the lossless master).

**The relaxation the owner asked about is REFUSED, by measurement.** "Why can't
frames that hold part of the picture be stitched?" — they are, and always were
(`min_piece` admits a source holding a tenth). What was thrown away is the
COMPOSITE, when the sources together covered less than `min_coverage` = 0.90 —
32 of 163 figures on this book. Lowering it to 0.60 admits six more, and the first
one inspected (`page_013__left` block 7, union 0.607 from sources holding 0.40 and
0.28) is **visibly worse than the page crop it would replace**: the two sources
disagree, the feather smears the climber's arm and the rock beside it across a
wide band, and 39 % of the picture is still an upsample. It scored **0.889** on
the result gate while being damaged, so the gate does not catch this and must not
be asked to. An under-covered figure needs another PHOTOGRAPH, not another
threshold.

**One trap closed on the way.** `_result_agreement` compared the whole thumbnail
against the whole page crop. Wherever no source landed, the composite IS the page
crop resized, so that part of the correlation is the crop against itself — the
backstop lost its power exactly as coverage dropped, i.e. exactly where it was
about to be relied on. It is now computed only over pixels a source actually
covered.

**Verify by CHECKERBOARD, never side-by-side** (standing rule, and it was needed
again here: the first "misregistered" reading of the seam was correct, but only
the checkerboard could tell it from the sharper picture merely revealing text the
blurry one hid).


## 2026-08-29 — Enlarging the page works; pasting the close-ups into it does not

The owner's proposal for the text half: rather than shrink a close-up to fit the
anchor (which is where its resolution dies), **enlarge the anchor so the close-up
fits**. The physics is right and the first two measurements supported it. The
third refutes it, and the refutation is specific rather than a shrug.

**1. The registration failure was the DESCRIPTOR, not the task.** Stage 01 uses
ORB(4000) and located 6 of 317 close-ups on this book, the failures clustered at
3-7 inliers against a threshold of 8. Asking the identical question - whole
close-up onto whole anchor - with SIFT + ratio 0.75 + RANSAC 4px:

| matcher | registered (inliers >= 20 AND photometric agreement >= 0.45) |
|---|---|
| ORB 4000 (shipped) | **6 / 317** |
| SIFT | **227 / 317** |

Median scale of an accepted close-up 1.72x the anchor over ~17 % of the spread;
median agreement 0.73, which sits in the band Stage 01's own docstring calls
correct (0.50-0.77) and far above what it calls wrong (-0.23 to 0.28).

**2. The per-block alternative is not available.** Re-cutting individual TEXT
blocks would have needed no canvas change at all. Measured on 3 spreads: text
blocks match the wrong paragraph. Agreement against close-up frames comes back
0.04-0.36 where a correct match reads 0.6+, while the same blocks match the
full-spread frames at 0.7-0.9 but at scale 0.8-0.9 (no extra resolution). A
paragraph is not locally unique; a photograph is. So the only registration that
works is the whole-frame one, and the only way to spend it is a bigger canvas.

**3. And the bigger canvas does not survive its own control.** `page_013`,
stages 02-05, same Tesseract language on every arm:

| arm | words | high-confidence | mean conf |
|---|---|---|---|
| baseline (today's anchor, 1378x2142 per page) | 345 | 324 | 91.4 |
| **enlarged 1.58x, NO close-ups pasted** | 360 | **336** | 91.8 |
| enlarged 1.58x **with** close-ups | 431 | **270** | 88.8 |

The enlargement alone is harmless. Pasting the close-ups in costs **66
high-confidence words** against that control, and total words RISE while confident
words fall - the signature of a page that has become harder to read, not easier.
Looking at the pixels says why immediately: the text comes out **doubled**, two
copies of each line tens of pixels apart, at every boundary between sources.

**Why, measured, and it is not fixable by tuning.** For one well-registered
close-up (243 inliers, agreement 0.745) the leftover displacement between it and
the anchor over its own footprint is a median **6.5 px** and up to **59 px** at
anchor scale — and it is **not smooth**: neighbouring 128 px tiles disagree by a
median 5.3 px and a 95th percentile of **45 px**. A homography assumes a plane and
the page is a cylinder seen off-axis; over a 17 % footprint the model error is
already larger than an x-height. The same local-bend correction that fixed the
figure seams was tried at three resolutions (12 tiles, 48 tiles, none) and the
doubling is identical in all three, so it is the placement, not the correction.

This is the mechanism Stage 01's docstring already named for the six close-ups no
setting registers: *"outside the model rather than badly matched... fixing that
means capture guidance or registering after dewarp, not matcher tuning."* It
applies to the ones that DO register too. **Not shipped.** The route that could
work is registering AFTER Stage 03 flattens both images, which is a different and
larger piece of work; nothing here should be read as ruling it out.

**A larger effect found on the way, and it is free.** This book is German and
every job the console or the phone submits is read as **`eng`** — `server/worker.py`
passes `--mode` to `run_all` and never `--lang`, so `languages.default` in
config.yaml decides, and it is `eng`. Same page, same pixels, `deu` instead:

| language | words | high-confidence | mean conf |
|---|---|---|---|
| eng | 345 | 324 | 91.4 |
| **deu** | 345 | **335** | **94.2** |

+11 high-confidence words and +2.8 mean confidence for nothing, on the arm that
every other measurement here is a fraction of. The operator has no way to choose
a language today; that gap is worth more than the canvas was.

---

## 2026-08-29 — The operator can choose the language, and the sofa stops being a picture

Two shipped changes, both prompted by the owner reading the rendered PDF of
their own 25-spread book and listing ~15 defects. Ten of the fifteen have one
cause.

### The language gap from the previous row is closed

`server/worker.py` now passes `--lang` (`server/jobs.py`'s `job_lang`,
`PATCH /api/jobs/{id}`, and a picker in the console job view). A job with no
recorded language passes **no** `--lang` flag, which is deliberately not the
same as passing the config default: omitting it leaves the choice to Stage 05,
so jobs created before this setting are unchanged rather than retroactively
pinned to whatever config says today. The value is validated by shape, not
against `languages.supported` — Tesseract takes `deu+ita`, which that list does
not enumerate.

### Ten of the fifteen defects: the book was photographed on a sofa

The owner's PDF renders full-width photographs of upholstery, with Stage 05's
reading of the weave underneath them. **All of them come from the first four
spreads**, and neither branch of the vision-model book box shipped earlier the
same day can remove them:

| spread | what Stage 02 did | was the model asked? |
|---|---|---|
| 1, 3 | detector abstained; model found the book correctly | **yes** — but its box only *aims* the spine search, so nothing is cut |
| 2, 4 | detector said "cropped to detected book", keeping the **full frame height** | **no** — it is only asked when the detector abstains |

The trigger is `abstained`; this book's failure mode is *confidently wrong in
one axis*. 25 of 163 figures are full-width bands at a page edge; 16 of those
are fabric or the shadow behind it.

### `pipeline/figure_surface.py` — asked twice, and both must agree

A local vision model is asked whether a figure block is the surface the book is
lying on. Each single form of the question **discards real book content**, and
for the same reason: a guide to via ferratas is full of printed photographs of
rock, and a picture of a rough surface looks like a rough surface.

| arm | flagged | wrong |
|---|---|---|
| the crop alone | 24 | a real printed photo of an information board, + 6 slivers of real photos |
| the whole page, block outlined | 18 | a real tilted chapter banner |
| **both must agree** | **16** | **none** |

Non-regression on other books — 26 assembled jobs from the committed testset
(`floor_*`, `sole_*`, the real-capture jobs), clean backgrounds: **0 of 93
figures flagged**.

Cost 1.1 s per figure; the second question is skipped when the first says no, so
a clean book pays ~0.7 s per figure. **OFF by default** (`figure_surface.enabled`),
same contract as `vlm_box`: a missing Ollama, an unreadable answer, or a
disagreement all keep the block exactly as before.

**Nothing is deleted.** `Block.is_surface` is a flag; Stage 08 skips the block
and the editor can clear it. At one book of evidence, a wrongly-flagged chapter
banner the operator can restore is a different risk class from one that
vanished.

**This does not fix the crop, and must not be read as fixing the detector.**
Spreads 1–4 still have wrong margins and their dewarp still ran on a frame
containing fabric. Cutting to a model's box remains the owner's postponed
decision.

### The garbage text is NOT a dictionary problem — measured, and the rule is refused

The obvious cheap fix for the meaningless letters is "drop a text block with no
dictionary words". **Do not build it.** On the four affected spreads, the
zero-dictionary-word blocks with 4+ words are the guide's **route tables** —
`840 Hm 1450 Hm 1400 Hm`, `4 5td. 6% Std. 7 Std.` — which are the most valuable
data in a via-ferrata guide, correctly read. On the clean spreads the same rule
picks `Kletterhohenmeter/Zeit Climbing altitude diff./time`, which is real.

The geometric alternative was measured too and is also dead: **0 of 150** text
blocks on the affected spreads sit outside the paper band implied by the flagged
surface figures. The junk is *on* the paper — it is real content read badly,
because the dewarp ran on a frame containing fabric. That points back at the
crop, not at a text filter.

## 2026-08-29 — Multi-language OCR raises confidence and *lowers* accuracy (REFUSED as a page-level setting)

Books are multilingual; this via-ferrata guide is German with Italian and English
translation panels on the same page. Tesseract accepts `deu+ita`, and the job
language field already validates that shape, so offering it in the console picker
is a two-line change. **Measured first — and it must not be offered.**

One page's Stage 05 re-run three ways, everything else identical (same dewarp,
same layout blocks). High-confidence words (conf >= 70):

| page | `deu` | `deu+ita` | `deu+ita+eng` |
|---|---|---|---|
| `page_013` (German body text) | 332 | 336 | 340 |
| `page_005` (route tables + panels) | 499 | 528 | 535 |

By the metric that has driven every earlier language decision — the one that gave
`eng` 324 vs `deu` 335 — adding languages is a clear win: **+7.2 %** confident
words on `page_005`. **It is an illusion.** Diffing the text itself:

```
Berücksichtigung -> Beriicksichtigung      Überholende -> Uberholende
alpinverlag      -> alpinveriag            Via         -> Ya
2,0              -> 20                     Alpin),     -> Alpini,
```

Adding a language whose alphabet has no umlauts makes the non-umlaut reading
*plausible*, so Tesseract picks it **and scores it higher**, because it now fits a
lexicon. 3 of 13 changed words on `page_013` lost an umlaut or `ß`; `Via` — an
Italian word — got *worse* when Italian was added. Cost is also real: 11 s -> 18 s
-> 23 s per page.

This is the same trap as the outer-gutter CLAHE spike (2026-07-17): **confidence
rose while the text got worse.** Confident-word count is a valid metric only when
the alphabet is held constant; across language sets it is not comparable, and no
future language decision may be made on it alone without a text diff.

**Consequence for multilingual support:** a page-level language *list* is the
wrong shape. The right unit is the block — this book's foreign-language content is
physically separated into panels, which is also why 28 of them are currently
locked inside FIGURE blocks (12.2 % of the book's words). See
`docs/plans/panorama-and-next-steps.md`.

## 2026-08-29 — Reading the close-ups separately and merging the words: a wash

The owner's proposal: OCR each close-up on its own and union the words with the
anchor's, merging by lines and part-lines because a close-up does not span the
page width. Measured over 34 registered close-ups on the owner's book, aligning
Tesseract's own line groupings with `difflib` (coordinates cannot be the merge
key — leftover displacement is a large fraction of a word height, and a position
matcher inflated the same union to a false 1.403x):

```
anchor confident words over the same areas : 6155
close-ups alone                            : 6010
aligned as the same word                   : 4087
  close-up reads it well, anchor badly     :  122   <- the win
  anchor reads it well, close-up badly     :  133   <- keep the anchor
unpaired close-up tokens                   : 2118   <- suspect, not wins
```

A max-confidence merge gains **122 words, +2.0 %**, and loses 133 the other way.
**The gains are not text recovery.** Every example is the same string at higher
confidence — `Kostenlos@5 -> kostenlos@87`, `und@50 -> und@95`,
`urheberrechtlich@34 -> urheberrechtlich@89`. Nothing unreadable became readable.

**Bound on the conclusion:** these close-ups are framed on the *page*, median
1.30x linear. This says the union does not pay **at this framing**, not that it
never could. It is the same operator-side lever `figure_hires` found: a close-up
framed on a text block is untested.

The 2118 unpaired tokens are not a hidden win — they are border fragments
(a close-up cuts words at its edge and Tesseract reads the fragment confidently)
plus alignment failures. Counting them as rescues is exactly the error that
produced the 1.403x figure.

## 2026-08-29 — The de-hyphenation rule was inert, and the word normalizer was deleting umlauts

Verifying the German render surfaced two defects behind one symptom: **138 words
in the owner's book are split across a line break and left broken** — `Wolf- gang`,
`Weltge- schichte`, `Berücksich- tigung`.

### 1. The rule was implemented, tested, and never given a dictionary

`stage08_render.join_hyphen` has always implemented CLAUDE.md's rule correctly and
`load_lexicon`'s own docstring says it is "Shared with the Stage 08 de-hyphenation
seam". Stage 08 called `render_html(doc, job_dir, dictionary=None)`. The four
Hunspell dictionaries have been on disk since `tools/setup_lexicons.py` ran.

Now loaded, keyed on **the document's own `source_language`** — not the config
default, because a lexicon for the wrong language silently refuses every join.
Two supporting fixes the real data forced:

- the membership test normalizes the candidate. The second half of a broken word
  carries the line's punctuation (`Tourenvor-` + `schläge,`) and a trailing comma
  is in no lexicon. The emitted text keeps the punctuation; only the lookup drops it.
- a multi-language string takes the first code; a broken lexicon returns None
  rather than failing a render.

**54 of 138 join** (63 after fix 2 below). The 75 refusals are the rule working:
`An-|chtigkeit`, `Kletter-|stelgset.`, `Höhenkrank-|1eit` are OCR errors in one
half, and `GPX-|Track` is a real hyphen. Meta now states which case applies
instead of always claiming no dictionary is loaded.

### 2. `normalize_token` silently deleted the accented letters of 3 of the 4 target languages

```python
_NORM_RE = re.compile(r"[^0-9a-zA-Zа-яёА-ЯЁ]+")     # before
"Berücksichtigung" -> "bercksichtigung"             # in no German lexicon
"è" -> ""                                           # an Italian word, erased
```

Replaced with a script-agnostic `[\W_]+`, and `.casefold()` replaced by `.lower()`
— casefold maps ß to ss, so `Straße` became `strasse`, which the German Hunspell
**rejects** while accepting `straße`.

**Measured effect on shipped behaviour: none.** The disagreement gate is the only
consumer today and it runs for Bulgarian alone (`engines.easyocr.enabled_for:
[bul]`), whose alphabet was entirely inside the old class:

| fixture set | tokens | normalize differently |
|---|---|---|
| Bulgarian — **the gate actually runs here** | 5604 | **0 (0.00 %)** |
| German — gate inert | 2446 | 138 (5.64 %) |
| Italian — gate inert | 4147 | 106 (2.56 %) |

So this is a pure correction for the paths about to use it — Stage 08's
de-hyphenation, and the per-block language work in
`docs/plans/panorama-and-next-steps.md` — with a measured zero delta on the one
shipped path. It also means **the German and Italian rows of the disagreement
trigger were never measurable before**: every accented word was out-of-lexicon by
construction. If that gate is ever enabled beyond Bulgarian, it must be measured
fresh; no pre-2026-08-29 number about it applies to those languages.

## 2026-08-29 — Figures that are really text panels: 3 promoted, and the premise of the plan was wrong

**What was asked.** `docs/plans/panorama-and-next-steps.md` §3.1 ranked this
first: 12.2 % of the owner's book (1607 words in 28 picture blocks) renders as
**photographs of text** — the route tables, the hut information boxes, the
English and Italian panels. Not searchable, not correctable, not translatable.
The proposed fix was the mirror of `figure_surface`: ask a local vision model
twice whether a "figure" is really text, and promote the ones both answers agree
on.

### The premise was wrong, and the eye-check is what found it

Adjudicating every candidate crop by eye (18 real text panels, 32 pictures, 3
upholstery, 2 correct vetoes) and then tracing each one back through the
pipeline:

| where the block is a FIGURE | how many | who typed it that way |
|---|---|---|
| already at Stage 05 | **4** | Stage 04 — a box on a coloured background |
| only from Stage 07 | **14** | `unreadable_panel`, correctly |

The fourteen are text blocks the whole way through Stage 05. `unreadable_panel`
turns them into pictures because their OCR is not text a reader could use, and
it is **right**:

| block | what it is | words | median conf (floor 70.5) | OCR |
|---|---|---|---|---|
| `page_017__left` #7 | "English Version" panel | 68 | 19.2 | `Englist Version Crane a Of w wa Z SH Zu SO Saar Aatter` |
| `page_016__right` #8 | de/en/it glossary | 268 | 32.5 | `) Abılı see plan orm DL Bl \| pbstrigen m sm` |
| `page_018__left` #4 | English instructions | 29 | 29.3 | `I: Bands needet to fo up For begamers rape beizy reger` |
| `page_023__left` #2 | hut info box | 18 | 51.4 | `u "Rtugio Lunel- E58 m prnat Man Jam - Ende Sept.` |

So the 1607-word figure counted words that are **not recoverable text at all**,
and this was never "the cheapest fix in this list". Re-typing those blocks would
render noise — the exact trade `unreadable_panel` exists to refuse. The largest
single cause of the bad reading is **language**: the English panel and the
trilingual glossary are being read as `deu`. That belongs to the multilingual
work (§2 of the plan), not to typing.

### What shipped, and what it delivers

`pipeline/text_panel.py`, wired into **Stage 05** between caption ejection and
the starved-block re-read. That position is load-bearing: `block_reocr`'s
`SKIP_TYPES` is `{FIGURE}`, so a block promoted first is re-read from its own
crop for free, under that module's own measured acceptance rule, with no change
to it.

Over the 36 Stage 05 candidates of the owner's 25-spread book:

| | candidates | promoted | correct |
|---|---|---|---|
| shipped rule | 36 | **3** | **3 / 3** |

The three are both of the book's route tables (`page_003__left` #7, 328 words at
median conf 91.8; `page_004__left` #21, 268 at 92.3) and the four-country
difficulty table (`page_017__right` #10, 87 at 89.9) — 683 words of clean text
that were locked inside pictures.

### Three guards, each one earned by a measured failure

**1. Two text questions must agree.** Over a wider 21-block set measured through
the assembled document, the crop arm called 23 blocks text and the context arm
vetoed 2. Both vetoes were correct: a photographic banner with a table header
strip, and — exactly as `figure_surface`'s docstring predicted — a photograph of
a wooden information board.

**2. The surface question, as an *either*-arm veto.** Without it the pass
promotes the sofa. Blurred upholstery has regular horizontal striations and the
model calls it TEXT confidently in **both** arms, including one full-width band
on `page_004__right` carrying **534 words** of weave noise at median OCR
confidence 19.7. Offering `SURFACE` as a third answer to the text prompt does
**not** help — measured, it changes not one answer of 55, byte-identical
decisions. Asking `figure_surface`'s own question and refusing on either arm
catches 3 of 3 upholstery blocks and costs 0 of 18 real panels.

The asymmetry with `figure_surface` is deliberate and set by which way the
mistake hurts: to **flag** a block as surface (Stage 08 drops it) both arms must
agree, because a false positive deletes real content; to **promote** a figure to
text, neither arm may even suspect it, because abstaining costs only a picture
that stays a picture.

**3. The wording of the prompt is part of the measurement.** The questions were
first measured naming the book being scanned ("a printed mountaineering
guidebook") and then generalised, as they must be — this is a book scanner. The
generalisation **changed an answer**, and the answer it changed was wrong:

| prompt | photographed warning sign | route table | grade table |
|---|---|---|---|
| names the guidebook (as measured) | PICTURE | TEXT | TEXT |
| generalised to "a printed book" | **TEXT** | TEXT | TEXT |
| + "a PHOTOGRAPH of a sign … is still a PICTURE" | PICTURE | TEXT | TEXT |
| + also "printed as part of the page itself" | PICTURE | TEXT | **PICTURE** |

Every cell is 3–5 identical draws. So the model is **deterministic** here at
temperature 0, an apparent flip between two runs is a changed prompt rather than
sampling, and the first place to look is your own edit. **An edited prompt is an
unmeasured prompt** — re-measure after changing one word of these strings,
exactly as after changing a threshold. The shipped prompt is row 3; row 4's
extra clause looks harmless and loses a real 87-word table.

### The two passes divide the work, and that is the honest headline

`text_panel` asks *is this worth reading?*; `unreadable_panel` asks *can this be
read?*; only a block that passes both renders as text. Measured, not asserted:
under the un-corrected prompt the warning-sign photograph **was** promoted at
Stage 05 and `unreadable_panel` demoted it straight back to FIGURE at Stage 07
(median conf 33.9 against a floor of 70.5), while all three good promotions
stayed text.

**Honest limit: that net only catches false positives whose text is junk.** A
photograph carrying *readable* burned-in text — a sign shot close up, a
photographed page — would pass both passes and be deleted from the render. The
two-questions-must-agree rule, not the net, is the safety argument, and it must
not be "simplified" to one question.

**And promotion deletes pixels.** Stage 08 renders a PARAGRAPH from its words, so
a picture wrongly promoted is *gone from the PDF*, not merely mis-labelled. The
plan's claim that this was a lesser risk than flagging was wrong and is corrected
in place. It is recoverable — the block keeps its id, bbox, words and reading
order, `type_promoted` marks the change as automatic, and the editor re-types it
back — but that is a different thing from harmless.

### Settled by measurement, not inherited

* **`min_words` = 8.** Sweeping to 3 adds 15 candidates on this book and **zero**
  promotions, at the cost of 15 more model calls.
* **The promoted type is PARAGRAPH.** Stage 08 maps PARAGRAPH and TABLE to the
  same `<p>` with a different class, so telling them apart would cost a third
  model question and change nothing a reader sees.

**Off by default in the module, on in `config.yaml`** — same contract as
`vlm_box` and `figure_surface`: a missing Ollama, an unreadable answer or an
arm's objection all leave the block a figure and say so in `meta.json`.
`--no-text-panel` turns it off for a run. Cost is ~1 s per candidate when the
first question says "picture" (the rest are skipped) and ~4 s when all four run.

**Still n = 1 book.** Every count here is one 25-spread guide photographed on a
sofa; the adjudication is by eye, by one reader.

### Postscript, same day — the pass is turned OFF, because the render is worse than the photograph

Everything above grades the **classifier**. It holds up: re-running the decision
over all 36 candidates with the prompts exactly as they ship returns the *same 3
promotions*, all 3 genuinely panels of text, with the 534-word band of sofa weave
refused by the surface veto. That was checked because the 25-page run predates
the final prompt edit, and a changed prompt is an unmeasured prompt.

Then the 683 words were read as rendered, which had never been done.

| block | words | median conf | rendered text (start) |
|---|---|---|---|
| `page_003__left` #7 | 328 | 91.8 | `Tourenübersi B _ Ampezzaner Dolomiten ton ivieri/Gianni Aglio @ Bil Ferrata Maria …` |
| `page_004__left` #21 | 268 | 92.4 | `@ )! Via ferrata Bolver-Lugli @ 2? Sent. N. Gusella u. Ferrata del Velo …` |
| `page_017__right` #10 | 87 | 89.9 | `äÄ A x ! m A Österreich Deutschland I [\| 1eatien ] Frankreich A KI F F A/B leicht facile facile …` |

All three are **multi-column tables**, and Stage 08 renders a promoted block as
one `<p>`. So the columns collapse into a single run of words. In the
seven-column route table (route / seriousness / time / difficulty / metres /
ascent / page) every time is detached from its route — `… 7 Std. 9 Std. 2½ Std.
6½ Std. 5½ Std. …` in a row — and the page numbers are stranded. In the grade
table all four countries interleave. The photographs are perfectly legible; the
text is not. Promotion deletes pixels, so this is a **loss**, not a downgrade.

Median confidence ~90 on all three, which is why nothing saw it: `unreadable_panel`'s
floor is 70.5 and these sail over it. **Fourth time in this project a confidence
number rose while the text got worse** — the rule is *no accuracy claim without a
text diff*, and this row exists because the diff was run late rather than not at all.

`text_panel.enabled` is therefore **false** in `config.yaml`. The code, the guards
and the tests stay; the pass is opt-in, like `vlm_box` and `figure_surface`. What
must exist before it pays: **Stage 08 rendering a TABLE as a table** — these three
blocks are the fixture — and per-block language, since the grade table is German,
Italian and French at once. A single-column panel of running text would probably
win today; this book contains none, so that is a guess, recorded as one.

## 2026-08-31 — Stage 08 renders a TABLE as a table; the rows come from a block re-read, not from geometry

Yesterday's row turned `text_panel` off with a named blocker: *"Stage 08 able to
render a TABLE as a table — these three blocks are the fixture."* This is that
work. The headline is not the renderer, which is twenty lines; it is **where the
rows had to come from**, and the fact that the obvious place cannot supply them.

### The rows are not a function of the words. This is a proof, not a tuning failure

The first design was a gridder over the words already in `document.json`. It
cannot work, for three compounding reasons measured on `page_003__left` #7:

* **`Word.line_id` groups a CELL, not a row.** The route names are lines 0–35,
  the times 43–75, the heights 92–124. Grouping by line yields *columns* — which
  is exactly the defect being fixed.
* **The printed columns are staggered** against each other by roughly 0.7 of the
  row pitch (the route name sits low in its ruled cell, the numbers high), on top
  of a residual skew from dewarp. Neighbouring columns share no baseline, so
  clustering by y is clustering the wrong thing.
* **And the stagger ALIASES.** Sliding the name column by a whole row pitch
  scores a mean residual of **7.4 px against 8.1 px** for the correct
  correspondence. *The wrong answer fits better.* No threshold rescues that.

Deskewing is real and insufficient: a −0.050 slope (−2.86°, found by projection
peakiness) collapses three of the five columns to **within 1 px** of each other
where they had drifted 16 px, and leaves the name column exactly as ambiguous.
**Do not re-attempt this from geometry.**

### What does know the rows, and what it is bad at

Tesseract reading the block's own crop as one uniform block (`psm 6`) has the
ruled lines and the baselines. Its TSV lines span the whole table — **x 36–2344
of 2370**, against a page-pass line's 126–506 of 1185 — and each line is one
complete table row, *including two columns the page pass never read at all.*

But it must not be allowed near the text:

| | rows | cell text | mean conf |
|---|---|---|---|
| page pass (`psm 3`, whole subpage) | **wrong** (column-major) | **right** | 91.8 |
| block re-read (`psm 6`, this crop) | **right** | **wrong** | 70.6 |

The re-read turns `2,2 4½ Std.` into `, .`, `1250` into `[250`, the page number
`102` into `I Ly`. So `pipeline/table_grid.py` runs it as a **row oracle and
nothing else** and discards its text. Rows from the re-read, text from the page
pass; **the module never adds, drops or edits a word**, it only writes
`Word.table_row` / `Word.table_col`. Word conservation is therefore untouched by
construction and an abstain costs literally nothing.

`deu` instead of `eng` does **not** fix those cells — 68.5 mean confidence
against `eng`'s 70.6, and it introduces `Hım`/`Huım`. Written down so this item
is not deferred to the per-block-language work on an excuse that does not hold.

### Three things the measurement decided

1. **A cell finds its row by overlapping the oracle's WORDS, never by a y band.**
   One top/bottom band cannot follow a skewed row; done that way, two cells
   collide in one band low down the table. Word-to-word overlap is local, so the
   skew cancels itself.
2. **A same-slot collision counts only when the two cells came from different
   printed rows.** Most same-slot pairs are one printed line the page pass split
   in half and the oracle correctly kept whole. Counting those refused the main
   fixture at 16 % against a 15 % bar — i.e. the guard was rejecting the right
   answer for being right.
3. **Words inside a cell order by visual line, then left to right, at a
   0.9-word-height tolerance.** Document order puts the tail of a split line
   first (`ivieri/Gianni Aglio @ B10 Ferrata Giuseppe Ol`); a plain y-sort
   scrambles one line into `Std. 7%`; and at 0.6 the two halves of a single
   *skewed* line separate and the right-hand half sorts first.

**Acceptance is STRUCTURAL** — the re-read's lines must span materially more of
the block's width than the page pass's (0.30 → 0.97 on the fixture). That is why
this is a new module rather than a rule inside `block_reocr`, whose acceptance is
*more words AND no lower confidence*: the oracle read is worse on **both** while
being the right answer, so that module would correctly refuse it.

### Results

Over the corpus's **7** Stage-04 TABLE blocks — the population that ships today:

| block | words | result |
|---|---|---|
| `page_003__right` #11 | 73 | **12 × 2** |
| `page_004__right` #14 | 219 | **17 × 4** |
| `page_004__right` #16 | 48 | **7 × 2** |
| `page_005__left` #1 | 164 | **17 × 2** |
| `page_003__right` #23 | 8 | abstain — 1 column |
| `page_016__right` #14 | 24 | abstain — 1 column |
| `it_geo_07 page_001__left` #5 | 26 | abstain — 1 column |

**4 gridded, 3 abstained.** End to end through a real Stage 05 → 08 run on pages
003/004/005, three tables render with every route keeping its own time and
heights, and the per-word uncertainty highlight survives inside its cell.

**The three abstentions were then opened and looked at, and they are NOT all
right.** An earlier draft of this row claimed they were, on the strength of
having inspected one of them; that claim was wrong and is corrected here rather
than quietly dropped.

* `page_003__right` #23 — **correct**. Two lines of route names, 8 words, the
  rest of the table unread. Flagged in advance as one that should abstain.
* `page_016__right` #14 — **right outcome, wrong reason.** It is not a fragment:
  it is a full German/English/Italian glossary, roughly 90 rows by 3 columns. But
  the page pass read **24 junk words** of it (`| | = Sl a A = SI | a A 0rso x`),
  so there is nothing to grid and abstaining is correct. The defect is upstream —
  this block is not readable as read — and it is not this pass's to fix.
* `it_geo_07 page_001__left` #5 — **a genuine MISS, and the corpus's only
  non-owner-book table.** It is a real three-column geological chart
  (period / stage / Ma) whose words are read *well*. Cause, measured: the page
  pass splits `INFERIORE` across the printed column rule into fragments at
  x 1449–1475 and 1477–1518, which sit **in the gutter** — column 1 ends at 1446,
  so the whitespace gap is **3 px** and the x-projection sees one column.
  Two candidate fixes were swept over the whole population and **both change
  nothing, on every block**: `col_gap_mult` 1.0 → 0.35 (the gutter is not the
  issue at any threshold that is not also absurd), and excluding full-width
  "spanning header" cells from the column vote (the title row is not the issue
  either). Neither was kept — an unmeasured parameter that fixes nothing is not
  worth its comment. The route that could work is taking the **columns** from the
  oracle read too: it spans the table and reads all three columns, where the page
  pass bridges two of them. Not attempted; recorded as the next step.

### The `text_panel` fixture, reported separately because it does not ship today

Pre-registered before any render was read (and the pre-registration was amended,
in writing, when the OCR findings above landed):

| block | words | predicted | result |
|---|---|---|---|
| `page_003__left` #7 | 328 | win | **34 × 5** |
| `page_004__left` #21 | 264 | win | **32 × 5** |
| `page_017__right` #10 | 62 | **still lose** | **abstain** (span 0.79 vs 0.58) |

The prediction held on all three. The grade table refuses *itself*, on the
structural rule, without anyone tuning a threshold against it — and it was
forbidden in advance to tune one. Rows 3–18 of `page_003__left` #7 were checked
by eye against the photograph as (route, time, grade, height) tuples: `B10 | 2,3
| 8½ Std. | 1250 Hm`, `C4 | 3 Std. | 580 Hm`, and so on — all correct.

`text_panel` typed a promoted panel PARAGRAPH, deliberately, because *"Stage 08
maps PARAGRAPH and TABLE to the same `<p>`, so telling them apart would change
nothing a reader sees."* It changes everything a reader sees now, so a panel this
run promoted out of a figure is offered to the grid and re-typed **TABLE** only
if it actually grids. The guard is `type_promoted` AND `PARAGRAPH` — uniquely
`text_panel`'s mark inside Stage 05 — so a paragraph Stage 04 detected, or one a
human typed, is never touched. With `text_panel` off this is inert.

### The honest limit, and it is the same shape as last time

**A correct grid is necessary and NOT sufficient, and this row must not be read
as saying the route tables are now good.** The cell text is still wrong in the
cells whose entire value is the number: `2,2` → `22`, `1,3` → `13`, `4½` → `4Y`,
`5¾` → `5%`, `170` → `I70`, and the coloured route-dot bullets read as `0`/`o`
and occupy a whole column of their own. That is an OCR defect, not a layout one,
and `deu` does not fix it. Whether these two blocks now beat their photographs is
therefore **still the owner's call** — the pre-registration exists precisely so a
correctly-gridded table full of wrong numbers could not be scored as a win. What
changed is that the *structural* half of the blocker is gone and the failure is
now legible: you can see which number is wrong, in which row.

One renderer bug found on review and fixed: the table emitted
`range(max_row + 1)` rows. Stage 05 numbers densely, but the document is mutable
and the editor ships block **split** — the second half of a split table keeps
rows 17–33, and that would have prefixed it with seventeen empty rows. The cell
is stored on the *word* precisely so an edit cannot invalidate it, so the
renderer now iterates the row and column values actually present.

Inputs and per-block output: `docs/data/table_grid_census_20260831.json`,
`docs/data/table_grid_census_20260831.txt`. n = 2 books, one of them by one
reader's eye.

## 2026-08-31 — Per-block language: the LABEL ships, the re-read is REFUSED

**The plan said the fix was to re-read a foreign-language block in its own
language. Measured first, and that half is dead.** What ships instead is a label
(`Block.language`, `pipeline/block_lang.py`), whose single consumer is Stage 08's
de-hyphenation — and it is worth **16 broken words rejoined across the corpus,
0 lost**.

### Does a dictionary vote even find the foreign blocks? (yes)

`tools/block_lang_census.py` scores every text block's already-read words against
the four installed Hunspell dictionaries. On the owner's 25-spread via-ferrata
guide, 209 scorable text blocks: **153 stay on the page language, 42 vote English,
14 vote Italian**. The clean English route descriptions are unmistakable — a
99-word block scores **0.92 against English and 0.13 against German**.

Reproducibility note: this job is **not uniformly German**. 22 spreads were read
as `deu` and three (`page_003`, `page_004`, `page_017`) as `eng`, left over from
the day the language picker shipped. So the corpus contains gains in **both**
directions, which is a feature of the evidence and a fact anyone re-running these
numbers needs.

### The re-read: measured over all 36 nominated blocks, and refused

Every nominated block was re-read from its own crop — the same crop-and-read path
`block_reocr` ships — in the page language and in the voted language.

**On blocks that read WELL, the language is a wash.** Word counts come back
identical (101/101, 103/103, 87/87, 56/56, 45/45, 42/42, 32/32), confidence moves
under a point, and the text diff has fixes and regressions in the same breath:

| block | English fixes | English breaks |
|---|---|---|
| `page_024/right` #4 | `interestin` → `interesting`, `„Giro` → `Giro` | `Ferrata Roghel` → `Ferrara Roghe!`, `can` → `an` |
| `page_024/right` #6 | `yalley` → `valley` | `10\|` → `[0]`, `Fischleintal` → `fischleintal` |
| `page_020/right` #10 | — | `From` → `from`, `15` → `[5` |
| `page_019/right` #9 | `Rif,` → `Rif.` | `Ferrata` → `Ferrara` |
| `page_022/right` #8 | — | — (**byte-identical**, 99 words) |

**On blocks that read BADLY — the translation panels this work was aimed at — the
other language returns DIFFERENT garbage, not better garbage.** `page_018/left` #9
reads `Beside the technacz! 68- Kcules (1-6 and dam- Ding` under German and
`wana! 6 ficunes (A-€ ... dim- bag` under English; the German read is if anything
closer to the printed `technical 6 figures (1-6 ... damping`. `page_016/right` #14
returns 158 words of noise under German and 112 under English.

**So the premise in `docs/plans/panorama-and-next-steps.md` §2 — "the largest
single cause is language" for the fourteen unreadable panels — is wrong.** Those
panels are unreadable because of the pixels: a coloured banner, small type, and
the four bad-crop spreads whose dewarp ran on a frame containing sofa. No language
setting recovers them, and none of them is fixed today.

### What the label is actually for

Stage 08 joins a line-end hyphen only when the joined token is in the document's
dictionary (CLAUDE.md's rule). In a German document every English paragraph
therefore keeps its broken words, and they are in the shipped PDF: `rou- tes`,
`at- tractive`, `distinc- tive`, `lone- liness`, `inc- reased`.

Applying the shipped pass over the whole corpus — the owner's book plus all
fifteen single-language testset fixtures, 1032 blocks:

| | blocks | labelled | joins gained | joins lost |
|---|---|---|---|---|
| owner's book (25 spreads) | 708 | 17 | 15 | 0 |
| `de_01`, `de_02` (same guide) | 55 | 4 | 1 | 0 |
| the other 13 fixtures (bg, en, it) | 269 | **0** | 0 | 0 |
| **total** | **1032** | **21** | **16** | **0** |

Thirteen of fifteen fixtures label nothing at all. The two that do are the two
spreads of this same German guide, and all four labelled blocks really are
English.

### The union, which one measurement forced

De-hyphenating a labelled block against its own dictionary **alone** gains 16 and
**loses one**: `de_02`'s English paragraph names the `Rosen- garten`, a German
massif, which the German lexicon joins and the English one cannot. A book that
prints one language inside another is exactly a book full of the other's proper
nouns — Italian route names in German text, German mountains in English text — so
the block's language is the **extra** authority, not the only one. Shipped as a
union with the document's lexicon: 16 gained, 0 lost.

### Graded on the RENDER, not on the label

The numbers above are counted on `05_ocr/ocr.json`; the PDF is built from
`document.json`, with assemble in between. So the same six spreads were taken
through the shipped path end to end — Stage 05, 06, assemble, render — and
rendered **twice from one document**: once as Stage 05 labelled it, once with
every label stripped, which is exactly what the document looked like before this
pass existed. Everything else is identical (3921 words, 33 figures, 505 flagged
in both arms).

The label survives assemble — 12 labelled blocks reach `document.json` — and in
the rendered HTML:

* broken words in the **unlabelled** render: **38**
* broken words in the **labelled** render: **26**
* **joined only with the label (12): `Star- ting`, `at- tractive`, `be- ginning`,
  `belay- ing`, `dif- ficult`, `distinc- tive`, `expe- rienced`, `inc- reased`,
  `lone- liness`, `rou- tes`, `sec- tions`, `verti- cal`**
* **newly broken with the label: 0**

Twelve rather than the eight this subset predicts, because these six spreads were
all re-run as `deu` here; in the archived job `page_017` had been read as `eng`,
so its four English blocks were invisible to the vote. The 26 that remain broken
are words no installed dictionary contains at all (proper nouns, and garbled
tokens) — the conservative default, unchanged.

### The guards, each one a measured false positive

* **`min_len` 3 — the one that matters.** English Hunspell accepts a long tail of
  two-letter forms (`la ir at do av se vs fa is cr`), so a block of pure noise
  scores **0.61 against English on two-letter tokens alone**. At `min_len` 2 the
  junk block of `it_geo_05` (median confidence 24, text `I nia pica ian na n PE
  aaa EEE`) is nominated; at 3 it is not, and **no real paragraph is lost
  anywhere in the corpus**.
* **`min_distinct` 6** — three blocks of route heights (`840 Hm 1450 Hm 1400 Hm
  ...`) score Italian at **1.00** off one repeated token, `hm`.
* **`min_rate` 0.65** — real prose scores 0.70–0.91; a mixed German/English
  caption scores 0.33.
* **`min_margin` 0.25** — `Sehr gut versicherter Steig / Very good secured route`
  ties at **0.00** and is correctly refused: it has no single language.

### Honest limits

* **One consumer, deliberately.** The EasyOCR disagreement gate and Stage 06's
  threshold also key on a lexicon, and neither is wired to this. They are
  unmeasured here, and wiring them on the strength of this row would make the row
  unfalsifiable.
* **The label is not a translation and not a re-read.** Nothing about the block's
  text changes; word conservation is untouched and an abstain costs nothing.
* **16 words is 16 words.** This is a small, visible correctness win on a defect
  the owner can see in the PDF, not a fix for the book's big remaining problems
  (the four bad-crop spreads, the fourteen unreadable panels, the wrong numbers
  in the route tables).
* **n = 2 books**, one of them supplying 17 of the 21 labels.
* Loading all four Hunspell dictionaries costs **3.7 s** once per Stage 05 run.

Inputs and per-block output: `docs/data/block_lang_census_20260831.json` (the
vote over every text block), `docs/data/block_lang_reread_20260831.json` (both
readings of all 36 nominated blocks, with their text), and
`docs/data/block_lang_dehyphen_20260831.json` (every label and every join gained
or lost, per job) and `docs/data/block_lang_render_ab_20260831.json` (the two
renders' hyphen sets). The census tool is `tools/block_lang_census.py`; its
`--reread` and `--all-langs` arms are the refused experiment, kept runnable.

---

## 2026-08-31 — Panorama Phase 0: the plan's premise is refuted, and a different reorder passes

`docs/plans/panorama-and-next-steps.md` §1 Phase 0, the measurement that was to
decide a large build either way. Pre-registered in
`docs/data/panorama_phase0_prereg_20260831.md` **before any number existed**:
population, arms, statistic and gate all fixed in advance, because this document
already records four occasions where a number improved while the text got worse.

**Question.** Stitching close-ups into an enlarged spread was measured and refused
(RESULTS 2026-08-29): the text came out **doubled**, diagnosed as a homography
being a plane-to-plane map while a photographed page is a cylinder seen off-axis.
The plan's premise was a **reorder — flatten first, stitch second**. Does
registering onto flattened pixels remove the leftover displacement?

**Two things about the earlier run shaped this one, and both were found by
READING it rather than re-running it.** `temp/stitch2/superres.py` registered onto
the **anchor** and *already applied* `figure_hires._mesh_refine` — so "add the
local-bend correction" was never the open question; the **target** was. And its
published numbers (6.5 px median, 59 px max, 5.3 px / 45 px neighbour) come from
**one** close-up. They are context, not a baseline; every arm here is compared
against arm A on the same population.

### Method

All **317** close-ups of the owner's 25-spread guide (`20260829-084115-de3c20d3`)
— every frame `01_fuse/fuse.json` does not list as a full spread. The four sofa
spreads are tagged and reported apart. One matcher for every arm (SIFT at 0.5
scale, ratio 0.75, RANSAC 4 px — the one that registers 227/317 where shipped ORB
gets 6), one acceptance rule for every arm (inliers ≥ 20 **and** masked NCC ≥
0.45), scale recorded but never gated on. `figure_hires.candidates()` was
deliberately **not** reused: its figure-tuned gates would admit a different subset
per arm, which is the one thing a cross-arm comparison cannot survive.

Statistic: leftover displacement over the source's footprint, on 128 px tiles
admitted by `_mesh_refine`'s own rule, read again at a half-tile offset; plus
**dense optical flow** as an estimator that shares no machinery with the
correction. Arms on the flattened page are converted to anchor-equivalent pixels
by their own local scales, so the gate is applied in one unit.

### Result — non-sofa, 303 close-ups, anchor-equivalent pixels

| arm | source → target | correction | placed | resid med | neigh med | flow med | flow p95 |
|---|---|---|---|---|---|---|---|
| A | raw → anchor | homography | 216 | 4.13 | 2.33 | 4.88 | 72.5 |
| B | raw → anchor | + mesh, footprint scope | 216 | **1.55** | 1.08 | 2.02 | 63.4 |
| B0 | raw → anchor | + mesh, whole-page scope | 216 | 4.24 | 2.15 | 4.72 | 61.4 |
| C | raw → **flattened page** | homography | 172 | 3.66 | 2.63 | 4.31 | 29.5 |
| D | raw → **flattened page** | + mesh, footprint scope | 172 | **1.39** | 1.27 | **1.67** | 21.2 |
| E | **flattened close-up** → flattened page | homography | 154 | 6.76 | 4.61 | 9.63 | 52.4 |
| F | **flattened close-up** → flattened page | + mesh, footprint scope | 154 | 2.57 | 2.50 | 3.34 | 43.3 |

**The gate — median residual < 2 px AND neighbour disagreement < 5 px — is met by
D on the pre-registered statistic (1.39 / 1.27) and on the independent one
(1.67).** B meets it on the pre-registered statistic only (1.55) and fails on flow
(2.02); the gate is not moved to accommodate either.

On the **120 close-ups every arm placed** — the only strictly like-for-like set,
which also answers the objection that C/D dropped the 44 hard ones — the ordering
is unchanged: A 2.88, B **1.29**, B0 3.00, C 3.79, D **1.51**, E 6.48, F 2.57.
Here B beats D on the median and loses on the tail, on this same set: worst-
twentieth 54.9 px against D's 25.8.

### The headline is the refutation, not the pass

**E and F — the plan's actual premise, flatten BOTH — are worse than C and D on
every statistic, and place 62 fewer close-ups (154 vs 216).** A double loss.
UVDoc flattens a borderless close-up perfectly well (probed first, 0.2–0.5 s,
median displacement 4.3–6.2 % of the long side, visibly straighter text), but
flattening the source destroys features the matcher needs and adds a second
non-rigid deformation the correction then has to undo. The pre-registration fixed
in advance that only a failure including E/F speaks to the premise. It does.

**So: "flatten first, stitch second" is refused. "Flatten the TARGET only, then
register with a footprint-scope correction" survives** — a different and smaller
claim than the plan made.

### What the old failure actually was

**B0 (4.24) is indistinguishable from no correction at all (A, 4.13); B (1.55) is
a third of it.** The only difference between B0 and B is the area the correction
is estimated over — the whole enlarged page, which is what the failed run did,
versus the close-up's own footprint. Most of the old doubling was **correction
scope**, not the target. That is a retrospective diagnosis of a run that was never
repeated here.

### The control: this is not the machinery grading itself

`_mesh_refine` is phase correlation and so is the tile statistic, and on the
footprint scope the correction's own grid lands at **53–191 px** against a 128 px
measurement tile — so the pre-registration's claim that the tiles are "much finer"
than the correction holds in one axis and not the other. The corrected arms
therefore rest on the flow estimator and on a floor measurement.

Feeding the **target's own pixels**, resampled backwards into the close-up's frame,
through the identical arm (`--control`, arms Cc/Dc) reads
**0.09 anchor px** — 0.07 by flow, worst single close-up 0.79 px, over 42
close-ups on four spreads, where D reads **1.21 / 1.62** on those same 42. The
apparatus can read 14-20x below where D lands, so D's pass is a measurement and
not a resampling artefact. The control is interpolated twice where
a real close-up is interpolated once, so it is a **pessimistic** bound on the
floor, which is the useful direction. This check exists because the same trap has
already been sprung here once: the close-up sharpness gate compared photographs
against a bar the anchor's own pixels scored 0.506 against, so nothing could pass.

### The tail is where this is decided, and it does not pass

Doubling is a tail phenomenon. Quoted as a range because the two estimators
disagree by 2.6x, D's worst-twentieth is **8–21 anchor px** — about a word width.
Per close-up, out of D's 172:

* **110** have a median under 2 px, but only **16** have a worst-twentieth under
  5 px, and **72 — 42 %** have a worst-twentieth of **30 px or more**.
* B is worse (151 of 216, 70 %, at ≥ 30 px), F worse still (100 of 154, 65 %).
* **Against every non-sofa close-up shot, not just the placed ones, that is 16 of
  303 = 5 %** at a 5 px tail rule and 56 of 303 = **18 %** at 10 px. This is the
  number that says whether Phase 1 is worth building, and it **reorders the
  plan**: if only 5-18 % of the close-ups the operator actually takes are
  paintable, the capture loop (Phase 3, tighter framing) is the *precondition*
  rather than the follow-on. D's residual is flat across zoom (1.90 / 1.87 /
  2.19), so framing tighter does not cost placement.

So the median passes and the tail does not, on four close-ups in ten even in the
best arm. **A pass therefore licenses Phase 1 only under a design that paints hard
narrow seams and skips a source where its local error is large** — the design
`figure_hires` already converged on for pictures. It does not license painting
every registered source.

### Diagnostic and honest limits

* **Re-fitting per sub-window** brings the *uncorrected* arms to where the
  correction gets: A 4.59 → 3.05 → **1.60** at 1, 2 and 4 divisions per side, C
  5.26 → 3.32 → **1.89**. But only **148 of 211** (A) and **95 of 168** (C)
  windows answer at all at 4 divisions, so this is a second viable Phase 1 design,
  not a drop-in.
* **The half-tile offset changes nothing** (D 1.685 → 1.625; every arm within
  0.2 px), so the tile phase is not carrying the result.
* **Tile-answer coverage 0.94–0.98** on every arm — these are fields, not a global
  translation wearing a mesh's clothes.
* **Gutter-straddling slivers are tagged and drive nothing**: excluding all 19
  moves D from 1.73 to 1.77 flow-median.
* In text-sized units D's residual is **0.077 x-heights** (F 0.142, C 0.202).
* **The sofa spreads are worse under every arm** (D 3.66 anchor px) and D's pass
  does not cover them. Their flattened pages are geometrically wrong for the
  already-recorded crop reason.
* **All 21 non-sofa spreads contribute**; no single spread carries the result.
* **The tightest close-ups are the worst placed on the anchor arms and not on the
  flattened-page arms** (A: 5.81 / 3.60 / 7.23 flow-median for < 1.4x, 1.4–1.8x,
  ≥ 1.8x; D: 1.90 / 1.87 / 2.19). Decision-relevant for the plan's capture loop,
  which wants tighter framing.
* **This is a placement number, and placement is further from the deliverable than
  a confidence number is.** Nothing here says a composite page reads better. Per
  the pre-registration, a pass licenses **Phase 1 and Phase 2 and nothing else**,
  and Phase 2 is decided by more confident words **and** a text diff.

**Ties to the row it replaces.** The old figure (6.5 px median for one close-up)
is recorded **at anchor scale**, the same unit as arm A's population median of
4.13 px, and it sits between that median and A's 95th percentile of 33.3 - which
is what one close-up drawn from the upper half of this distribution should look
like. It is *not* to be reconciled by dividing by the 1.58x canvas; 6.5 / 1.58 =
4.11 lands on 4.13 by coincidence and would be a false confirmation. The old row
also reports the correction tried at three resolutions with the doubling
identical - consistent with B0 here, where whole-page scope scores what no
correction scores.

**Recommended next step, not started here:** re-run the exact `page_013`
comparison that produced 324 / 336 / 270 confident words, under D's placement with
a hard-seam sharpest-first paint. That is the cheapest link from this number to
the book - **but not on `page_013` alone.** Of its 6 placed close-ups, **0** have a
worst-twentieth under 5 px and **3** under 10 px, so a paint that correctly skips
the rest paints almost nothing and returns an uninterpretable null. Run it on
`page_021` as well (25 of 27 placed; 6 under 10 px, 13 under 20 px), which is the
only spread in the book with enough paintable sources to show a difference either
way. `page_024` is the negative control: 10 placed, **none** paintable.

Tool: `tools/panorama_phase0.py` (all seven arms plus the `--control` floor).
Data: `docs/data/panorama_phase0_20260831.json` (every close-up, every arm),
`docs/data/panorama_phase0_control_20260831.json`, pre-registration
`docs/data/panorama_phase0_prereg_20260831.md`.

---

## 2026-08-31 — Panorama Phase 2: the paint lands where the text isn't

`docs/plans/panorama-and-next-steps.md` §1 Phase 2, pre-registered in
`docs/data/panorama_phase2_prereg_20260831.md`, measured by
`tools/panorama_phase2.py`, data `docs/data/panorama_phase2_20260831.json`.

Phase 0 (yesterday) measured **placement** and passed. Phase 2 asks the question
that matters — **does a page assembled that way read better** — on the gate the
plan set: more confident words **and** a text diff.

**It returns NO VERDICT on that gate, and the reason is the result.** Of 40
close-ups that register onto their flattened subpage across the three spreads,
**5 are admitted** to the paint. **Four of the five land on a topographic map.**

### The structural finding

| subpage | registered | admitted | union | text under the paint |
|---|---|---|---|---|
| `page_021` right | 18 | **4** | 65.5 % | **1** confident word |
| `page_013` right | 3 | **1** | 80.2 % | 102 confident words |
| `page_021` left | 7 | 0 | — | (98 conf. words, nothing admitted) |
| `page_013` left | 3 | 0 | — | (185) |
| `page_024` left | 8 | 0 | — | (177) |
| `page_024` right | 1 | 0 | — | (364) |

`page_021` is the spread the plan named as primary **because** it has the most
well-placed close-ups. It does — and **149 of its right page's 170 words sit
inside FIGURE blocks**. Those close-ups are close-ups of the map. Where the
running text is, not one source is reliably placed: `page_021`-left runs
**56.6–108.2** anchor px of leftover displacement against a 10 px bar,
`page_024`-left **25.4–166.8**. The well-placed sources are not spread thinly
over the book; they are concentrated on one picture.

The pre-registered statistic needs a TEXT BLOCK **fully inside** the painted
union. At 65–80 % coverage no block qualifies, so the primary is undefined
everywhere — on `page_021`-right for the substantive reason above, on
`page_013`-right on a technicality. Both are reported as no-verdict rather than
patched after the fact.

### The one text subpage that did paint — count tied, text better

`page_013`-right, one source, 80.2 % of the page, word-granularity and therefore
**secondary and post-hoc**:

| arm | words in union | confidence >= 80 |
|---|---|---|
| E (enlarged 1.27x, unpainted) | 104 | **102** |
| P (painted) | 104 | **102** |

A dead tie — and the text diff is not a tie. P **rejoins two hyphen-broken
words** (`Schuttbänd` + `er` -> `Schuttbänder`, `mög` + `lichst` ->
`möglichst`) and recovers `Wandstelle`, `damit`, `überholende`; it loses
`wird.`, and two words off a figure (`Am Klettersteig`). The count cannot see
this **because the improvement is two words becoming one** — which is the §0
warning running the other way for once: here the number is blind to a real gain,
where four previous times it rose while the text got worse.

**The seam check the pre-registration promised** (run only because P lost words),
measuring each lost word's depth inside the painted region in units of its own
height: the four hyphen halves are **14–35 word-heights** deep, i.e. not seam
artifacts but the merge described above. Of the three genuine losses, **two are
within 3 word-heights of a seam** (`Klettersteig` 1.0, `»Wer` 2.9) and one is not
(`wird.`, 20.6). That is the evidence that would license a **word-aligned seam**
in Phase 1 — cut the paint boundary around word boxes, never through them.

### The control fires — the instrument can see the failure

Arm **X** paints the sources the rule *rejects*. Required to lose, and it does:

| subpage | words | confidence >= 80 | mean conf |
|---|---|---|---|
| `page_024`-left E | 200 | **172** | 86.5 |
| `page_024`-left X | **242** | **137** | 66.9 |
| `page_021`-left E | 126 | **98** | 80.9 |
| `page_021`-left X | 113 | **77** | 72.6 |

`page_024`-left reproduces the recorded doubling signature exactly — **total
words RISE while confident words FALL** (the 2026-08-29 run: 360 -> 431 total,
336 -> 270 confident). So a null here is a real null, not a blind instrument.
And the bar is not obviously loose: `page_024`-right's single source, at 10.28 px
just *over* it, does no damage at all (364 -> 365).

### The instrument was not reproducible, and it is now

Found while building, amended in the pre-registration **before any composite
existed** (§9). The same close-up registered three times with nothing changed
returns **9.76 / 10.25 / 14.34** px — `cv::theRNG()` feeds both RANSAC and
FLANN's randomised index and advances between calls. Over the whole population
the seed moves a source's residual by a median **34 %** of its own value, p90
**107 %**, max **188 %**.

> **9 of the 40 sources flip across the 10 px bar depending on the seed** —
> best-draw admits **14**, worst-draw admits **5**.

Admission is therefore the **worst of three seeded draws**. Best-of-three by
inliers was considered and refused on the evidence: the draw with the **most**
inliers (82) had the **worst** placement (14.34 px). **This is also a fact about
Phase 0** — every per-source number in `panorama_phase0_20260831.json` is one
draw. Its population medians over 317 sources are not materially at risk; no
individual row there is exact, and nothing should threshold one.

### What this licenses

* **Phase 1 is NOT licensed.** The pre-registered pass never happened. This is
  not a refusal of the panorama route either — the route was never given a fair
  text page to work on.
* **The precondition is the capture, not the code.** Phase 0 already suspected
  this ("a capture loop that frames tighter becomes the precondition rather than
  the follow-on"); Phase 2 makes it concrete and specific: on this book the
  operator shot close-ups **of the pictures**, and the pictures are where the
  paint is admissible. A capture loop (plan Phase 3) that covers the *text* at
  the same framing is what would produce a population this measurement could
  read. **Do not build Phase 1 first.**
* If Phase 1 is ever built, the seam must be **word-aligned** — measured above,
  not assumed.

### Honest limits

n = **1 book**, 3 spreads, 6 subpages, one operator. The single painted text
subpage rests on **one source** whose worst draw (9.59 anchor px) sits just
inside the bar; a fourth seed could put it outside. The tie-with-a-better-diff is
one page of one book and is **not** a claim that painting helps. `page_013`-right
is not comparable to the 2026-08-29 `324 / 336 / 270` row (that was `eng`, onto
the anchor, at 1.58x, painting every registered source) and no arithmetic
relating them is offered.
