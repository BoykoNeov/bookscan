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

MEASURED CAPABILITY (it_geo_06, N=1 — six figures, one page). Updated 2026-08-09;
the original 2026-07-03 reading of "textured photos are hopeless" was WRONG about
its own cause, which is worth recording because the wrong diagnosis is the
plausible one:
- **4/6 numbers recovered, 0 wrong** (F25, F26, F27, F29). Was 2/6.
- The two that had been written off as "texture swamps the glyph" were nothing of
  the kind. **F27's label was localized correctly all along** — the green box in
  the debug overlay sits exactly on the "27" — and it was the OCR *input* that
  failed: the painted-CC mask fused the two digits into one blob. Re-cropping the
  same localization from the original pixels reads "27" on 4/4 PSMs. **F29 was a
  filter rejection**: its 50px-tall digits fell under a 62px floor that the
  figure-relative glyph band happened to put there because F29 is a TALL figure.
- Still ``None``, and correctly so: **F28** (digits merge with bright rock
  speckle; best read is a 1-vote "38", which the acceptance rule rejects) and
  **F30** (light-grey digits on light rubble — the white top-hat mask there is
  pure noise, so no localization is possible). These two are the genuine
  "needs a real text detector (EAST/MSER/CNN)" cases; the other two were not.
- Net effect on grouping: ``pair_by_number`` recovers C25->F25, C26->F26 (the
  trap), C27->F27 and C29->F29 — 4/6 GT pairs, **0 wrong**, and every one of them
  now comes from the printed number rather than the geometry arm.

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
    "max_glyph_cover": 0.55,
}

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


def read_corner_label(fig_bgr: np.ndarray, tess_bin: str,
                      p: dict | None = None,
                      page_h: int | None = None) -> int | None:
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
    """
    if fig_bgr is None or fig_bgr.size == 0:
        return None
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
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
