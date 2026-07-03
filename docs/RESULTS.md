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
