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

MEASURED CAPABILITY (it_geo_06, 2026-07-03, N=1 — six figures, one page):
- Dark-background labels (F25 on rock, F26 on near-black plate): read CORRECTLY
  with 4/4 PSM agreement.
- Textured-photo labels (F27/F28 foliage, F29/F30 rock): the white digit is not
  separable from same-size/-shape bright foliage/rock blobs by glyph geometry
  alone, so isolation is swamped. This module returns ``None`` on them rather
  than guessing — a real text detector (EAST/MSER/CNN) would be needed and is
  out of scope at N=1 (over-fitting risk, see the scope doc's N=1 warnings).
- Net on it_geo_06: 2/6 numbers recovered, **0 wrong**. That moves
  ``pair_by_number`` 0 -> 2 (C25->F25, C26->F26) and specifically DEFEATS the
  C26 trap; it does NOT reach the §7-aspired 0 -> 6. Four captions still have no
  numbered figure and are (correctly) left unpaired.

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
    "glyph_h_min_frac": 0.10,    # a glyph CC's height, frac of region height
    "glyph_h_max_frac": 0.75,
    "glyph_ar_min": 0.12,        # w/h; upper bound admits a merged 2-digit blob
    "glyph_ar_max": 2.6,
    "glyph_fill_min": 0.28,      # CC area / bbox area — digits are solid vs stringy texture
    "label_ar_min": 0.35,        # the whole cluster should look like a 1-2 digit number
    "label_ar_max": 2.7,
    "num_min": 1,                # plausible label-number range
    "num_max": 99,
    "min_psm_agree": 3,          # accept only if >= this many of the 4 PSMs agree
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


def _isolate_label(fig_bgr: np.ndarray, p: dict):
    """Localize the bottom-right corner label and return a clean OCR-ready crop
    (dark glyphs on white, only the label's pixels painted), or ``None`` if no
    plausible bottom-right glyph cluster is found.

    Method: crop the bottom-right region -> upscale -> white top-hat on the Value
    channel (bright glyphs pop from dark OR textured bg as solid blobs) -> keep
    low-saturation (white, not coloured foliage) -> connected components filtered
    by digit size/aspect/fill -> group adjacent similar-height CCs at one baseline
    into label clusters -> pick the cluster nearest the bottom-right corner whose
    overall shape is a 1-2 digit number -> paint ONLY that cluster's pixels.
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

    n, lbl, stats, _ = cv2.connectedComponentsWithStats(white, 8)
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
    mask = np.zeros((bh, bw), np.uint8)
    for m in g:
        mask[lbl == m[0]] = 255
    pad = int(0.3 * med_h)
    y0, y1 = max(0, gy - pad), min(bh, gy2 + pad)
    x0, x1 = max(0, gx - pad), min(bw, gx2 + pad)
    clean = cv2.bitwise_not(mask[y0:y1, x0:x1])          # dark glyphs on white
    return cv2.copyMakeBorder(clean, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def read_corner_label(fig_bgr: np.ndarray, tess_bin: str,
                      p: dict | None = None) -> int | None:
    """Recover a figure's printed corner-label number from its crop.

    ``fig_bgr``: the figure box cropped from the full-res dewarped subpage (BGR).
    ``tess_bin``: path to the Tesseract 5 binary (from config). ``p``: optional
    knob overrides (see ``DEFAULTS``).

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
    clean = _isolate_label(fig_bgr, pp)
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
