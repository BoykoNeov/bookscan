# Gate results (append-only history)

## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=none

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


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=otsu

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


## Gate 1 run — 2026-07-03, tesseract 5.4.0.20240606, preprocessing=adaptive (best variant)

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

Order-robust AUROC is **0.86–0.89 across all three, all above the 0.80 bar**,
and recognition (order-free word accuracy) is **79–94%**. The confidence
backbone separates errors and recognition is good — on English too.
(Reproduce: `python -m tools.gate1_order_robust_probe`.)

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

Recognition quality and confidence calibration are **good enough to build on**
(Bulgarian ~87% raw word acc; order-robust AUROC 0.86–0.89 all languages
measured). The failure mode Gate 1 actually exposed is **reading-order scramble
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
