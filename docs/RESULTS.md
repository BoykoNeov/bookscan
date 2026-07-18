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
Measured on `bg_01` with a proxy lexicon (382 normalized ground-truth tokens):

| bg_01 (763 words) | raw token-diff | + dictionary gate |
|---|---|---|
| words flagged `engine_disagree` | **89 (11.7%)** | **7 (0.9%)** |
| genuine Tesseract misreads among them | 2 | 2 |
| high-conf correct words wrongly flagged | 78 | 0 |

Net-vs-confidence impact (Stage 06, threshold 75): the 7 add only **2 net-new
flags (+0.26%)** over the confidence rule — `касалница`→`касапница` @92 and
`Делеагач`→`Дедеагач` @93, both **genuine confident misreads the confidence rule
alone keeps**. The other 5 were already low-confidence. This is exactly the job of
a disagreement trigger: surface confidently-wrong words, add negligible noise.
Blind spot (accepted, documented): `norm(T)∉lex ∧ norm(E)∉lex` is a MISS (both
non-words — a domain term, or a rare word absent from the lexicon); recall traded
for precision, correct when raw precision is ≈ 0.

**Honest reframing (owner-visible).** With the dictionary gate the trigger is
effectively an **"EasyOCR-nominated dictionary check"**, not a bare cross-engine
disagreement. It still earns EasyOCR its place — far more precise than a plain
spellcheck (which flags every proper noun / abbreviation); requiring an
independent engine to produce a *valid alternative* is what buys the precision.
But it IS a reframing of the raw non-negotiable, surfaced here rather than shipped
silently.

**OWNER DEPENDENCY — a per-language lexicon.** The gate needs a lexicon, which
does **not** ship in the repo — the same dependency the Stage 08 de-hyphenation
seam already waits on (`join_hyphen(..., dictionary)` is always passed `None`).
So the trigger is shipped **inert**, mirroring the repo's seam pattern: the
mechanism is built + unit-tested (13 tests), wired through
`config.engines.easyocr.lexicon` (`models/lexicons/<lang>.txt`, gitignored), and
Stage 05 does **not** even load EasyOCR when no lexicon is present (its pass would
flag nothing — wasted GPU). Supplying a lexicon activates BOTH this trigger and
de-hyphenation. Verified end-to-end on `bg_01`: with a proxy lexicon dropped into
the seam the live CLI produces the 7 flags above and Stage 06 reports the trigger
LIVE; with the lexicon removed it produces 0 and reports inert. The proxy was a
smoke-test stand-in (this page's own GT tokens), NOT a production lexicon.

Full suite 156 green. Files: `pipeline/second_opinion.py` (+
`test_second_opinion.py`), `Word.engine_disagree`, Stage 05 wiring, Stage 06
OR-in + LIVE/inert reporting, and a Stage 08 test proving a disagreement-flagged
confident word clears through the SAME per-word `flag_visible`/edit path as a
confidence flag (no separate un-clearable marker).
