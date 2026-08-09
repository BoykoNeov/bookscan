"""Recover a figure's in-photo CORNER-LABEL number — the small white "25"
printed in the bottom-right of each plate — so ``caption_parser.pair_by_number``
can group caption N to figure N by the printed number (owner's #1 priority; the
one route that defeats the C26->F26 trap, since geometry provably mispairs it —
see docs/FIGURE_SEPARATION_SCOPE.md §7).

WHY A SEPARATE MODULE (cv2 here, not in caption_parser):
- ``caption_parser`` is PURE text-in/dataclasses-out. The corner label is not
  routed OCR text — it is PIXELS inside the figure box that Stage 05's block
  routing never emits as words. Reading it needs image processing + a Tesseract
  call, so it lives here; ``caption_parser.figure_number`` stays the pure text
  gate and ``pair_by_number`` stays pure.

MEASURED CAPABILITY (it_geo_06, N=1 — six figures, one page). Updated 2026-08-10.
This module's history is three rounds of the SAME mistake — diagnosing a failure
from the localizer's *output* instead of its internals — so each correction is
recorded with what the wrong reading was, because the wrong reading is always the
plausible one:
- **5/6 numbers recovered, 0 wrong** (F25, F26, F27, F28, F29). Was 2/6, then 4/6.
- Round 1 (2026-07-03) called textured photos hopeless. Round 2 (2026-08-09)
  disproved that for **F27** (localized correctly all along; the painted-CC mask
  fused its two digits, and re-cropping from the original pixels reads "27" on
  4/4 PSMs) and **F29** (a filter rejection — 50px digits under a 62px floor the
  figure-relative band put there because F29 is a TALL figure; hence ``page_h``).
- Round 2 then wrote off F28 and F30 as needing "a real text detector
  (EAST/MSER/CNN)". **Both halves of that were wrong**, and differently:
  * **F28** was never a texture problem. The top-hat mask's CLOSE welded a
    speckle onto the digits, so one CC spanned 44x37 where the label is 38x27.
    Since the padding AND the OCR upscale both scale by ``glyph_h``, that
    inflated height mis-framed and under-zoomed the crop. Re-measuring the box
    with a local Otsu (``_refine_box``) gives 39x29, and from there a re-crop
    sweep reads "28" 78 times against a runner-up of 4. It is now recovered.
  * **F30** IS localizable — MSER lands on it (IoU 0.45), and the earlier note's
    "no localization is possible at all" came from inspecting a zoom that was
    mid-figure rubble rather than the corner. What F30 actually is, is a
    **recognizer ceiling**: given a HAND-MEASURED perfect box, a 432-read
    Tesseract knob sweep never once produces "30" (10 digit reads total, no
    2-digit read at all), and EasyOCR returns nothing on 4/4 framings. Do not
    re-attempt F30 with a better detector — the detector was never the problem.
- Net effect on grouping: ``pair_by_number`` recovers C25->F25, C26->F26 (the
  trap), C27->F27, C28->F28 and C29->F29 — 5/6 GT pairs, **0 wrong**, and every
  one of them comes from the printed number rather than the geometry arm. C30
  abstains correctly (its number is printed on a subpage that numbers its
  figures, so geometry is suppressed rather than allowed to overrule).

THE SECOND RECOGNIZER, AND WHY IT DOES NOT BREACH THE TESSERACT-BACKBONE RULE.
Recovering F28 needs a relaxed acceptance rule, and a relaxed rule needs a second
opinion to stay safe — so ``second_opinion=True`` brings EasyOCR in. CLAUDE.md
forbids a non-Tesseract engine being the SOLE TEXT SOURCE or the CONFIDENCE
SOURCE; neither applies here. A corner label is never rendered into the document
and never reaches Stage 06's thresholds — it is a grouping KEY, used only to
decide which caption floats with which photo. EasyOCR is already a sanctioned
second opinion in this repo (Stage 05, Cyrillic). The dependency is optional and
non-fatal: with no EasyOCR installed, no GPU, or a model that fails to load, this
module degrades to exactly its previous behaviour — a miss, never a fabrication.

CONSERVATISM IS THE INVARIANT: ``pair_by_number`` attributes by NUMBER, so a
single wrong read on a mispairing-trap fixture is worse than a miss. We accept a
number ONLY on strong multi-PSM agreement of a plausible 1-2 digit value; on any
doubt we return ``None``. This is the "0 wrong" guarantee the non-regression test
(single-figure pages it_geo_04/05/07 must yield no fabricated numbers) protects.

This module is imported by ``tools.layout_order_eval`` (the pairing-by-number
arm) now, and by Stage 07 reconstruct later (attach a figure's number so a
caption floats with its true partner). It does NO file I/O; the caller supplies
the figure crop (from the full-res dewarped subpage) and a Tesseract binary path.
"""
from __future__ import annotations

import subprocess
from collections import Counter

import cv2
import numpy as np

# Glyph-geometry heuristics (same allowed class as the Stage-04 figure-split
# knobs: pixel/shape geometry, NOT the adaptive OCR-confidence thresholds
# CLAUDE.md forbids hard-coding — those live in Stage 06). N=1-tuned on it_geo_06;
# kept relative (fractions of the search region, not absolute px) so they are not
# pixel-locked, but generalization is unproven until a 2nd corner-label fixture
# exists.
DEFAULTS = {
    # Bottom-right search region as a fraction of the FIGURE box. All six
    # it_geo_06 labels sit here. A merged/split box that includes page-bg gutter
    # below the photo would push the label out of "bottom 30%": the localizer
    # then finds no bottom-right glyph cluster and returns None (a miss, never a
    # fabricated number) — verified on the real split boxes, not GT extents.
    "corner_w_frac": 0.42,
    "corner_h_frac": 0.30,
    "min_region_px": 500,        # upscale so the shorter region side >= this
    "tophat_k_frac": 0.22,       # white top-hat kernel = this frac of region height
    "sat_max": 110,              # glyph must be low-saturation (white, not coloured)
    # Glyph height. Two bands, and WHICH ONE APPLIES MATTERS — see the measured
    # numbers below. The region-relative pair is the fallback used when the caller
    # cannot say how tall the page is.
    "glyph_h_min_frac": 0.10,    # a glyph CC's height, frac of region height
    "glyph_h_max_frac": 0.75,
    # PAGE-relative band, used instead whenever ``page_h`` is supplied. The corner
    # label is printed text, so its cap-height is a typographic constant of the
    # BOOK, not a property of the figure box it happens to sit in. Measured on
    # it_geo_06's six figures (3000px dewarped subpages): 25, 26, 27, 30, 30 and
    # 37px => 0.83%..1.23% of page height, tightly clustered. The region-relative
    # bound above, by contrast, lands anywhere from 0.62% to 1.03% of page height
    # depending on how tall the figure box is — and that is exactly how F29's
    # 50px-tall "29" came to be rejected by its own subpage's 62px floor while the
    # identically-sized labels on shorter figures passed. The band below is ~2x
    # margin either side of the measured spread.
    "glyph_h_page_min_frac": 0.004,
    "glyph_h_page_max_frac": 0.025,
    "glyph_ar_min": 0.12,        # w/h; upper bound admits a merged 2-digit blob
    "glyph_ar_max": 2.6,
    "glyph_fill_min": 0.28,      # CC area / bbox area — digits are solid vs stringy texture
    "label_ar_min": 0.35,        # the whole cluster should look like a 1-2 digit number
    "label_ar_max": 2.7,
    "num_min": 1,                # plausible label-number range
    "num_max": 99,
    "min_psm_agree": 3,          # accept only if >= this many of the 4 PSMs agree
    # OCR input geometry. The localizer's CC mask says WHERE the label is; the
    # pixels handed to Tesseract are then re-cropped from the ORIGINAL figure at a
    # fixed glyph size (see _extract_for_ocr for why the mask itself is not used).
    "recrop_pad_frac": 0.45,     # padding round the label box, frac of glyph height
    "target_glyph_px": 110,      # upscale the re-crop until a glyph is this tall
    # POLARITY GUARD. Everything here assumes a bright glyph on a darker ground,
    # so in a crop sized to the label box + padding the bright side must be the
    # MINORITY. Measured: the six real it_geo_06 labels cover 0.10..0.38 of their
    # re-crop, while it_geo_07's ink-on-page-background diagrams — which print no
    # label at all — cover 0.82..0.86, because there the bright side IS the page.
    # That inversion is what let a brick-hatching pattern read as "7".
    #
    # SCOPE, measured 2026-08-10 — this clean separation is a property of the
    # STRICT arm's single top-hat-derived re-crop and does NOT carry to the sweep
    # below. Over the refined boxes and 36 sweep variants, the real labels cover
    # 0.03..0.41 while it_geo_04/05's label-free figures cover 0.00..0.34 — fully
    # inside the label range, so the guard kills 0/36 variants there (it still
    # kills 18/36 on it_geo_07, whose ground really is the pale page). The guard
    # is therefore NOT what keeps the second-opinion arm honest on those fixtures;
    # two-recognizer agreement is. Do not treat 0.55 as a fabrication defense for
    # the relaxed path, and do not "tighten" it to try to make it one — it would
    # start cutting real labels first.
    "max_glyph_cover": 0.55,
    # ---- SECOND-OPINION ARM (below) ----------------------------------------
    # Box refinement. The coarse mask can fuse a neighbouring speckle into a digit
    # CC — it_geo_06 F28's 27px digits are reported as one 37px blob — and since
    # BOTH the padding and the OCR upscale key off glyph_h, an inflated height
    # mis-frames and under-zooms the crop. A local Otsu inside a slightly larger
    # neighbourhood separates them: F28 refines to 39x29 against a hand-measured
    # 38x27. The keep-band is deliberately generous (0.35..1.6 of the coarse
    # glyph_h) — it is re-MEASURING a box we already believe in, not re-finding it.
    "refine_pad_frac": 0.60,
    "refine_h_min_frac": 0.35,
    "refine_h_max_frac": 1.60,
    "refine_baseline_frac": 0.75,   # |CC centre - box centre| in y, frac of glyph_h
    "refine_span_frac": 1.60,       # ... and in x, frac of max(box_w, glyph_h)
    # Despeckle before OCR: drop components too short to be a glyph, as a fraction
    # of the target glyph size. THE decisive knob on F28 — every one of the 48
    # sweep combinations that read "28" has it on, because the rock speckle around
    # the digits is what Tesseract was otherwise reading as a third glyph.
    "sweep_despeckle_frac": 0.25,
    # A wrong number is worse than a miss, so the relaxed arm demands a landslide,
    # not a majority: >= min votes AND >= this multiple of the runner-up.
    "sweep_min_votes": 2,
    "sweep_dominance": 2.0,
    # Second-opinion recognizer (EasyOCR) agreement requirement.
    "second_min_agree": 3,          # of the 4 crop variants it is shown
    "second_min_conf": 0.80,
}

# The relaxed arm's re-crop sweep: (pad_frac, target_glyph_px, blur_k, adaptive_k).
# One fragile re-crop is what made F28 unreadable; the point of a sweep is that no
# single framing/binarization choice is load-bearing. Measured on F28's refined
# box: "28" x78 against a runner-up x4.
_SWEEP = tuple((pf, t, b, a) for pf in (0.25, 0.45) for t in (80, 110, 160)
               for b in (0, 3, 5) for a in (0, 31))

_PSMS = (7, 8, 10, 13)          # single line / word / char / raw line


def _ocr_digits(img: np.ndarray, tess_bin: str, psm: int) -> str:
    """Run Tesseract on ``img`` restricted to digits; return the stripped text."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return ""
    proc = subprocess.run(
        [tess_bin, "stdin", "stdout", "--psm", str(psm),
         "-c", "tessedit_char_whitelist=0123456789"],
        input=buf.tobytes(), capture_output=True)
    return proc.stdout.decode("utf-8", "replace").strip().replace("\n", " ")


def _locate_label(fig_bgr: np.ndarray, p: dict, page_h: int | None = None):
    """Find the bottom-right corner label's BOX in ``fig_bgr``'s own coordinates.

    Returns ``(x, y, w, h, glyph_h)`` — the label cluster's bounding box and the
    median height of one glyph in it — or ``None`` when no plausible bottom-right
    glyph cluster is found.

    Method: crop the bottom-right region -> upscale -> white top-hat on the Value
    channel (bright glyphs pop from dark OR textured bg as solid blobs) -> keep
    low-saturation (white, not coloured foliage) -> connected components filtered
    by digit size/aspect/fill -> group adjacent similar-height CCs at one baseline
    into label clusters -> pick the cluster nearest the bottom-right corner whose
    overall shape is a 1-2 digit number.

    ``page_h`` (the subpage image height) switches the glyph-height filter to the
    page-relative band — see ``DEFAULTS``. Without it the region-relative band is
    used, which is size-of-figure dependent and misses labels on tall figures.
    """
    h, w = fig_bgr.shape[:2]
    rx0, ry0 = int(w * (1 - p["corner_w_frac"])), int(h * (1 - p["corner_h_frac"]))
    region = fig_bgr[ry0:h, rx0:w]
    rh, rw = region.shape[:2]
    if rh < 4 or rw < 4:
        return None
    scale = max(1, int(round(p["min_region_px"] / max(1, min(rh, rw)))))
    big = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    bh, bw = big.shape[:2]
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    _, sat, val = cv2.split(hsv)

    kh = max(15, int(p["tophat_k_frac"] * bh) | 1)      # odd
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kh, kh))
    tophat = cv2.morphologyEx(val, cv2.MORPH_TOPHAT, kern)
    _, white = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    white[sat > p["sat_max"]] = 0                        # kill bright-COLOURED texture
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

    n, _lbl, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    if page_h:
        hmin = p["glyph_h_page_min_frac"] * page_h * scale
        hmax = p["glyph_h_page_max_frac"] * page_h * scale
    else:
        hmin, hmax = p["glyph_h_min_frac"] * bh, p["glyph_h_max_frac"] * bh
    cand = []
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if not (hmin <= ch <= hmax):
            continue
        if not (p["glyph_ar_min"] <= cw / ch <= p["glyph_ar_max"]):
            continue
        if area / (cw * ch) < p["glyph_fill_min"]:
            continue
        cand.append((i, x, y, cw, ch, area))
    if not cand:
        return None

    # Group adjacent, similar-height CCs sharing a baseline into label clusters.
    cand.sort(key=lambda c: c[1])
    med_h = float(np.median([c[4] for c in cand]))
    groups, cur = [], [cand[0]]
    for c in cand[1:]:
        prev = cur[-1]
        px = prev[1] + prev[3]
        v_ok = abs((c[2] + c[4] / 2) - (prev[2] + prev[4] / 2)) < 0.6 * med_h
        h_ok = (c[1] - px) < 0.9 * med_h
        sim = 0.55 < c[4] / prev[4] < 1.8
        if v_ok and h_ok and sim:
            cur.append(c)
        else:
            groups.append(cur)
            cur = [c]
    groups.append(cur)
    groups = [g for g in groups if 1 <= len(g) <= 3]   # a label is 1-2 (rarely 3) digits
    if not groups:
        return None

    def score(g):
        gx2 = max(m[1] + m[3] for m in g)
        gy2 = max(m[2] + m[4] for m in g)
        gx = min(m[1] for m in g)
        gy = min(m[2] for m in g)
        lar = (gx2 - gx) / max(1, gy2 - gy)
        shape = 1.0 if p["label_ar_min"] <= lar <= p["label_ar_max"] else 0.2
        dist = ((bw - gx2) ** 2 + (bh - gy2) ** 2) ** 0.5   # to bottom-right corner
        return shape / (1.0 + dist)

    g = max(groups, key=score)
    gx = min(m[1] for m in g)
    gy = min(m[2] for m in g)
    gx2 = max(m[1] + m[3] for m in g)
    gy2 = max(m[2] + m[4] for m in g)
    glyph_h = float(np.median([m[4] for m in g])) / scale
    # Back to the caller's own (un-upscaled, un-cropped) coordinates.
    return (rx0 + gx / scale, ry0 + gy / scale,
            (gx2 - gx) / scale, (gy2 - gy) / scale, glyph_h)


def _extract_for_ocr(fig_bgr: np.ndarray, box, p: dict) -> np.ndarray | None:
    """Turn a located label box into the image Tesseract actually reads.

    The pixels come from the ORIGINAL figure crop, re-cropped round the box and
    upscaled until a glyph is ``target_glyph_px`` tall, then binarized THERE.

    WHY NOT JUST PAINT THE LOCALIZER'S MASK (which is what this module used to
    do): the mask is a by-product of a white top-hat sized for *finding* blobs,
    not for preserving stroke shape, and it is rendered at whatever upscale the
    search region happened to need. On it_geo_06's F27 that mask fused the "2" and
    the "7" into one blob that read as nothing on all four PSMs, while the very
    same localization re-cropped from the original pixels reads "27" on all four.

    A tempting middle road — binarize the re-crop but keep only the components the
    mask already found — was MEASURED and is worse: it clipped F29's "9" into a
    "3", i.e. it turned a clean miss into a plausible WRONG number (23), which is
    the one failure this module's whole design forbids. Keep the mask for
    localization only.
    """
    bx, by, bw_, bh_, glyph_h = box
    h, w = fig_bgr.shape[:2]
    pad = p["recrop_pad_frac"] * glyph_h
    x0, y0 = int(max(0, bx - pad)), int(max(0, by - pad))
    x1, y1 = int(min(w, bx + bw_ + pad)), int(min(h, by + bh_ + pad))
    crop = fig_bgr[y0:y1, x0:x1]
    if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
        return None
    s = p["target_glyph_px"] / max(1.0, glyph_h)
    big = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # The localizer only ever finds BRIGHT glyphs (white top-hat), so the label is
    # the white side of that threshold. If that side is most of the crop, the
    # premise is false — this is not light text on a dark ground but a dark-on-pale
    # drawing — and whatever Tesseract reads off it would be a fabrication.
    if th.size and float((th > 0).sum()) / th.size > p["max_glyph_cover"]:
        return None
    th = cv2.bitwise_not(th)          # invert for Tesseract's dark-on-light
    return cv2.copyMakeBorder(th, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)


def _isolate_label(fig_bgr: np.ndarray, p: dict, page_h: int | None = None):
    """Localize the corner label and return the OCR-ready image, or ``None``."""
    box = _locate_label(fig_bgr, p, page_h)
    if box is None:
        return None
    return _extract_for_ocr(fig_bgr, box, p)


# ---------------------------------------------------------------------------
# THE SECOND-OPINION ARM. Everything below runs ONLY when the strict arm above
# returned None, and it can only ever turn a miss into a number — it never
# revisits, and so never changes, a number the strict arm already accepted.
# That is why adding it cannot regress the four labels that already worked.
# ---------------------------------------------------------------------------

def _refine_box(fig_bgr: np.ndarray, box, p: dict):
    """Re-measure a located label box from the ORIGINAL pixels with a local Otsu.

    The coarse box comes from a white top-hat sized to *find* blobs across a whole
    corner region; where the ground is busy it can weld a neighbouring speckle onto
    a digit. Re-thresholding a small neighbourhood of the box alone separates them,
    because there the label and its immediate surround are the only two populations.

    Returns a box in the same 5-tuple form, or the input unchanged if the refined
    view finds nothing plausible (never a wilder box than it was given).
    """
    bx, by, bw_, bh_, glyph_h = box
    h, w = fig_bgr.shape[:2]
    pad = p["refine_pad_frac"] * glyph_h
    x0, y0 = int(max(0, bx - pad)), int(max(0, by - pad))
    x1, y1 = int(min(w, bx + bw_ + pad)), int(min(h, by + bh_ + pad))
    crop = fig_bgr[y0:y1, x0:x1]
    if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
        return box
    gray = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _lbl, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    cx, cy = (bx + bw_ / 2) - x0, (by + bh_ / 2) - y0
    keep = []
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if not (p["refine_h_min_frac"] * glyph_h <= ch <= p["refine_h_max_frac"] * glyph_h):
            continue
        if not (p["glyph_ar_min"] <= cw / ch <= p["glyph_ar_max"]):
            continue
        if area / (cw * ch) < p["glyph_fill_min"]:
            continue
        if abs((y + ch / 2) - cy) > p["refine_baseline_frac"] * glyph_h:
            continue
        if abs((x + cw / 2) - cx) > p["refine_span_frac"] * max(bw_, glyph_h):
            continue
        keep.append((x, y, cw, ch))
    if not keep:
        return box
    gx = min(k[0] for k in keep)
    gy = min(k[1] for k in keep)
    gx2 = max(k[0] + k[2] for k in keep)
    gy2 = max(k[1] + k[3] for k in keep)
    return (x0 + gx, y0 + gy, gx2 - gx, gy2 - gy,
            float(np.median([k[3] for k in keep])))


def _sweep_variant(fig_bgr: np.ndarray, box, p: dict,
                   pad_frac: float, target: int, blur: int, adaptive: int):
    """One (framing, binarization) hypothesis for the relaxed arm's OCR input.

    Same shape as ``_extract_for_ocr`` — including its polarity guard, which is the
    fabrication defense and is NOT relaxed here — plus a despeckle pass and the
    option of a local threshold. Returns ``None`` when the guard fires.
    """
    bx, by, bw_, bh_, glyph_h = box
    h, w = fig_bgr.shape[:2]
    pad = pad_frac * glyph_h
    x0, y0 = int(max(0, bx - pad)), int(max(0, by - pad))
    x1, y1 = int(min(w, bx + bw_ + pad)), int(min(h, by + bh_ + pad))
    crop = fig_bgr[y0:y1, x0:x1]
    if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
        return None
    s = target / max(1.0, glyph_h)
    big = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    if blur:
        gray = cv2.GaussianBlur(gray, (blur, blur), 0)
    if adaptive:
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, adaptive | 1, -8)
    else:
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if th.size and float((th > 0).sum()) / th.size > p["max_glyph_cover"]:
        return None
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    kept = np.zeros_like(th)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_HEIGHT] >= p["sweep_despeckle_frac"] * target:
            kept[lbl == i] = 255
    return cv2.copyMakeBorder(cv2.bitwise_not(kept), 30, 30, 30, 30,
                              cv2.BORDER_CONSTANT, value=255)


def _tess_plurality(fig_bgr: np.ndarray, box, tess_bin: str, p: dict) -> int | None:
    """Pool 2-digit reads over the whole re-crop sweep; accept only a landslide.

    The strict arm asks for a SOLE 2-digit reading, which one bad framing can veto.
    Here no single framing is load-bearing: we pool every hypothesis and require the
    winner to clear both an absolute vote floor and a multiple of the runner-up.
    """
    votes: Counter[str] = Counter()
    for pad_frac, target, blur, adaptive in _SWEEP:
        img = _sweep_variant(fig_bgr, box, p, pad_frac, target, blur, adaptive)
        if img is None:
            continue
        for psm in _PSMS:
            o = _ocr_digits(img, tess_bin, psm)
            if o.isdigit() and len(o) == 2 and p["num_min"] <= int(o) <= p["num_max"]:
                votes[o] += 1
    if not votes:
        return None
    val, cnt = votes.most_common(1)[0]
    runner = max((c for v, c in votes.items() if v != val), default=0)
    if cnt >= p["sweep_min_votes"] and cnt >= p["sweep_dominance"] * max(1, runner):
        return int(val)
    return None


_READER = None
_READER_FAILED = False


def _easyocr_reader():
    """Lazily build the second-opinion recognizer; ``None`` if unavailable.

    OPTIONAL AND NON-FATAL BY DESIGN. Without it this module falls back to exactly
    its previous behaviour (a miss, never a fabrication), so no caller acquires a
    hard dependency on a GPU, a model download, or the package being installed.
    """
    global _READER, _READER_FAILED
    if _READER is None and not _READER_FAILED:
        try:
            import easyocr
            _READER = easyocr.Reader(["en"], gpu=True, verbose=False)
        except Exception:
            _READER_FAILED = True
    return _READER


def close_reader() -> None:
    """Drop the second-opinion model and free its VRAM.

    The cache above is module-level, so without this it would live for the whole
    process — and Stage 05 holds its OWN EasyOCR reader (``second_opinion.
    EasyOCRSecondOpinion``, a different language set, hence a different model).
    Two models resident on one consumer card is exactly what CLAUDE.md's per-stage
    GPU hygiene rule exists to prevent, so whoever turns the arm on releases it
    when the pass is done (``figure_grouping.read_figure_numbers`` does).
    """
    global _READER
    _READER = None
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _second_opinion(fig_bgr: np.ndarray, box, p: dict) -> int | None:
    """Read the label with the second recognizer over several crop framings.

    Shown the raw (un-binarized) pixels, because its strength is precisely the case
    that defeats a threshold: digits touching, or sitting on a busy ground.
    Requires one value, on most framings, at high confidence.
    """
    reader = _easyocr_reader()
    if reader is None:
        return None
    bx, by, bw_, bh_, glyph_h = box
    h, w = fig_bgr.shape[:2]
    reads: list[tuple[str, float]] = []
    for pad_frac in (0.5, 1.0):
        pad = int(pad_frac * glyph_h)
        x0, y0 = int(max(0, bx - pad)), int(max(0, by - pad))
        x1, y1 = int(min(w, bx + bw_ + pad)), int(min(h, by + bh_ + pad))
        crop = fig_bgr[y0:y1, x0:x1]
        if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
            continue
        for s in (4, 8):
            big = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            try:
                found = reader.readtext(big, allowlist="0123456789")
            except Exception:
                return None
            for _bx, txt, conf in found:
                if txt.isdigit() and len(txt) == 2 and \
                        p["num_min"] <= int(txt) <= p["num_max"]:
                    reads.append((txt, float(conf)))
    if not reads:
        return None
    tally = Counter(t for t, _ in reads)
    val, cnt = tally.most_common(1)[0]
    if len(tally) > 1 or cnt < p["second_min_agree"]:
        return None                    # any competing value at all is doubt
    mean_conf = float(np.mean([c for t, c in reads if t == val]))
    return int(val) if mean_conf >= p["second_min_conf"] else None


def read_corner_label(fig_bgr: np.ndarray, tess_bin: str,
                      p: dict | None = None,
                      page_h: int | None = None,
                      second_opinion: bool = False) -> int | None:
    """Recover a figure's printed corner-label number from its crop.

    ``fig_bgr``: the figure box cropped from the full-res dewarped subpage (BGR).
    ``tess_bin``: path to the Tesseract 5 binary (from config). ``p``: optional
    knob overrides (see ``DEFAULTS``). ``page_h``: the height of the subpage the
    crop came from — optional, but supply it when you have it: the corner label is
    printed at a PAGE-relative size, and without ``page_h`` the glyph filter falls
    back to a figure-box-relative band that misses labels on tall figures.

    Returns the integer number ONLY when a plausible 1-2 digit label localizes in
    the bottom-right AND at least ``min_psm_agree`` of the PSM modes agree on it;
    otherwise ``None``. Never raises on unreadable input — a miss is ``None``, not
    an exception, and never a fabricated number (the "0 wrong" invariant).

    ``second_opinion``: when True, a label the strict rule above rejects gets a
    second look — the box is re-measured and TWO independent recognizers must agree
    (see the module docstring). Opt-in, because it costs a recognizer load and a
    ~144-call Tesseract sweep, and it fires only on figures that would otherwise be
    a miss. It can only turn ``None`` into a number; a number already accepted
    above is returned before this ever runs.
    """
    if fig_bgr is None or fig_bgr.size == 0:
        return None
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    strict = _read_strict(fig_bgr, tess_bin, pp, page_h)
    if strict is not None or not second_opinion:
        return strict
    box = _locate_label(fig_bgr, pp, page_h)
    if box is None:
        return None
    box = _refine_box(fig_bgr, box, pp)
    tess = _tess_plurality(fig_bgr, box, tess_bin, pp)
    if tess is None:
        return None
    # Both recognizers, or nothing. This is not ceremony: on it_geo_06's F30 the
    # sweep above returns a confident, wholly fabricated "88" (6 votes, no runner-up)
    # off bright rubble, and the only thing that stops it becoming a caption pairing
    # is the second recognizer declining to see a number there at all.
    return tess if _second_opinion(fig_bgr, box, pp) == tess else None


def _read_strict(fig_bgr: np.ndarray, tess_bin: str, pp: dict,
                 page_h: int | None) -> int | None:
    """The original, unchanged acceptance path — see ``read_corner_label``."""
    clean = _isolate_label(fig_bgr, pp, page_h)
    if clean is None:
        return None
    # Collect plausible reads across PSM modes, split by digit length. A 2-digit
    # label ("25") frequently truncates to its first digit ("2") on some PSMs; we
    # must not let that truncation veto the full read. So:
    #   * a 2-DIGIT value wins on >=2 votes PROVIDED no OTHER 2-digit value also
    #     read (texture rarely yields the SAME wrong 2-digit number twice, so a
    #     lone consistent 2-digit read is trustworthy; a competing one is doubt);
    #   * else a 1-DIGIT value is accepted ONLY on strong agreement (>=
    #     min_psm_agree) and with no competing digit — a lone weak "2" (the
    #     it_geo_06 F28 texture fragment) stays None.
    two: Counter[str] = Counter()
    one: Counter[str] = Counter()
    for psm in _PSMS:
        o = _ocr_digits(clean, tess_bin, psm)
        if not o.isdigit() or not (pp["num_min"] <= int(o) <= pp["num_max"]):
            continue
        if len(o) == 2:
            two[o] += 1
        elif len(o) == 1:
            one[o] += 1
    if two:
        val, cnt = two.most_common(1)[0]
        if cnt >= 2 and len(two) == 1:
            return int(val)
        return None                      # ambiguous 2-digit reads -> don't guess
    if one:
        val, cnt = one.most_common(1)[0]
        if cnt >= pp["min_psm_agree"] and len(one) == 1:
            return int(val)
    return None
