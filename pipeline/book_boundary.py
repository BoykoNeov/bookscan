"""Book-boundary crop — find the book in a cluttered capture.

Stage 02 searches for the spine across the WHOLE frame. That was fine while
every fixture was a tightly-framed spread, and it broke the moment real photos
arrived: the first Android uploads (``testset/zoomset_*``) were shot with the
book on the photographer's lap, so 40-55 % of each frame is room, and Stage 02
preferred a stronger vertical valley in the clutter on three of four spreads —
twice the book's own OUTER edge, once the floor beside it. Two of those spreads
came out of the pipeline as one subpage holding the whole spread and one
subpage holding background. See ``docs/RESULTS.md`` 2026-08-19.

This module is the missing step: locate the book, so the split can look for the
spine inside it instead of inside the room. It is deliberately NOT a stage — the
stage numbering is a published contract (CLAUDE.md) and inserting 02.5 would
renumber everything downstream. It is a plain module called at the head of
Stage 02, which keeps it importable by the Stage 01 anchor-choice work that
wants the same crop.

That anchor-choice item — ``partition_frames`` ranks anchors by sharpness over
the whole frame, so on these captures it rewards cluttered backgrounds — was
then measured with this module in hand and **the box does not fix it**: on 7 of
the 10 committed fixtures that contain an anchor choice the crop abstains on
every candidate, so the box is the frame and the ranking cannot move; the one
set it does flip is flipped by a scoring artefact (a cropped candidate is scored
on page-only pixels while an abstaining one keeps its room, and variance of
Laplacian rewards that). See ``tools/anchor_choice_census.py`` and
``docs/RESULTS.md`` 2026-08-19 "Anchor choice: the window was not the problem".
Also note ``find_book`` is not free to call per frame: 258-1375 ms on a 12 Mpx
capture (measured on three of the fixtures; the spread is GrabCut converging or
not), so a ranking that called it on every candidate would pay that per frame.

**Two boxes, not one, and that is the whole design.** The obvious approach —
one book box, used both to aim the search and to cut the pages — was built and
measured, and it cannot work, because the two jobs pull the box in opposite
directions:

  * The **search box** only has to put the spine inside the detector's own
    ``[0.30, 0.70]`` band. Nothing is discarded, so leaking into clutter or
    clipping a page edge costs nothing here.
  * The **emit box** decides which pixels become the page. Clipping it loses
    text irreversibly — the one failure Stage 02's own comments call real — so
    it has to CONTAIN the book, and stray room inside it is harmless.

A single box has to be tight enough for the first and generous enough for the
second, and on this corpus no setting is both. Measured: the bright-paper mask's
own bbox padded 2 % clips up to 32.8 % of a labelled book, and padding it until
nothing clips (20 %) grows it to 80-99 % of the frame — a crop that no longer
crops. Going the other way, the generous emit box used as the search box puts
the gutter back on the outer edge on ``zoomset_en_01``/``en_02`` (17/19 vs
19/19). So: two boxes, each slack in what it needs.

**How each is found.**

*Search box* — page paper is bright and nearly colourless while skin, wood
floor and dark chair are not, so ``S < 0.25 and V > 0.55`` isolates it well
enough to locate the book. The mask does leak along thin bright tendrils (a
white cable, a pale chair edge), which drags a plain bounding box outwards, so
the box is taken from the 2nd/98th percentiles of the component's pixel
coordinates instead of its extremes — leaks are low-mass and percentiles ignore
them — then padded 8 %. Measured 19/19 against ``testset/gt/gutter.json``.

*Emit box* — the same mask UNDER-covers the book wherever the page is saturated
(orange headers and side strips), which is exactly what made the naive crop eat
page content. GrabCut, seeded from the paper component (eroded = definitely
page, dilated = probably page, frame border = definitely background), grows the
region across those coloured areas because they are contiguous and
colour-coherent with what it was seeded on. Measured against six hand-labelled
book boxes (``testset/gt/book_box.json``): clipping reaches zero at 4 % pad and
stays there, so this ships at 6 % — 1.5x the measured threshold — with the box
still at 56-89 % of the frame.

**Abstain is a first-class outcome, and it is not just a safety net.** An
already-tight frame must come out BYTE-IDENTICAL to before, which is guaranteed
by construction rather than by tuning: emit-box area is 65-80 % on the four real
lap captures that need cropping and 85-100 % on the fifteen spreads that do not
(97-100 % for the 13 flat ones, 85 % and 89 % for the two moderately-framed
``de_01``/``de_02``), so the gate sits at the midpoint of that gap — the same
rule used for the pinch gate and the OSD 180 floor.

The gap is narrow, so the threshold also had to be justified by CONSEQUENCE, and
it is: cropping ``de_02`` at 89 % moves its gutter from 7 px off ground truth to
96 px, because the ink valley becomes "confident" on the cropped frame and
outranks the spine-pinch cue that had been right. Nothing is gained by cropping a
frame the book already fills, and that is what is lost. A degenerate mask (too
small, absurd aspect) abstains too. Every refusal carries its reason into
``meta.warnings`` and the overlay.

**Known limits, measured not assumed.**
  * n = 6 labelled spreads, one photographer, two books, one lighting setup.
    The thresholds separate cleanly on that corpus and have not been seen on
    another.
  * The paper mask assumes the page is the brightest low-saturation thing in
    frame. A white desk, a paper-covered table or a very dark page would break
    it; the abstain guards limit the damage to "no crop", not "wrong crop".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# Defaults are overridable via config.yaml ``book_crop:``. These are geometry
# heuristics measured on the fixtures named above, not the adaptive CONFIDENCE
# thresholds CLAUDE.md forbids hard-coding (those live in Stage 06).
DEFAULTS = {
    "enabled": True,
    # --- paper mask (locates the book) -------------------------------------
    "work_w": 680,          # mask working width, px
    "sat_max": 0.25,        # page is nearly colourless ...
    "val_min": 0.55,        # ... and bright
    "close_k": 15,          # join text/figure gaps within a page
    "open_k": 11,           # drop speckle
    "min_seed_frac": 0.03,  # paper component smaller than this -> abstain
    # --- search box (aims the gutter search) --------------------------------
    "trim_pct": 2.0,        # percentile trim, kills thin bright leaks
    "search_pad": 0.08,     # outward pad, fraction of the trimmed box
    # --- emit box (decides which pixels become the page) --------------------
    "grabcut": True,
    "gc_work_w": 480,       # GrabCut working width, px (cost scales ~quadratically)
    "gc_iters": 5,
    "gc_seed_dilate": 31,   # -> GC_PR_FGD
    "gc_seed_erode": 15,    # -> GC_FGD
    "emit_pad": 0.06,       # outward pad; clipping hits zero at 0.04 (n=6)
    "fallback_pad": 0.20,   # pad for the raw mask bbox when GrabCut is off/fails;
                            # the measured zero-clip pad for that (looser) box
    # --- abstain guards ------------------------------------------------------
    "abstain_area_frac": 0.83,  # box covers most of the frame -> already tight
    "min_area_frac": 0.10,      # degenerate
    "aspect_min": 0.5,
    "aspect_max": 4.0,
}

Box = tuple[int, int, int, int]   # x0, y0, x1, y1 in ORIGINAL image pixels


@dataclass
class BookBoundary:
    """Where the book is, and whether we are willing to act on it.

    ``emit`` and ``search`` are always valid boxes in ORIGINAL image
    coordinates; when ``applied`` is False both are the full frame, so a caller
    can use them unconditionally and still get the uncropped behaviour.
    """

    applied: bool
    reason: str
    emit: Box
    search: Box
    diag: dict = field(default_factory=dict)


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update((cfg or {}).get("book_crop", {}) or {})
    return params


# --------------------------------------------------------------------------
# Mask
# --------------------------------------------------------------------------


def _odd(n: int) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 == 1 else n + 1


def paper_mask(image: np.ndarray, p: dict, work_w: int | None = None
               ) -> tuple[np.ndarray, float]:
    """Largest bright, low-saturation component — the book's paper.

    Returns ``(component_mask, scale)`` where the mask is at the working width
    and ``scale`` converts working -> original pixels. Returns ``(None, scale)``
    when nothing survives.

    ``work_w`` overrides the configured width so the GrabCut seed can be built
    at ITS working size rather than downsampled from the search mask's. The
    morphology kernels are scaled with the width for exactly that reason — a
    fixed 15 px kernel means something different at 680 px than at 480 px, and
    the seed measured in ``testset/gt/book_box.json`` was built at the latter.
    """
    h, w = image.shape[:2]
    work_w = int(p["work_w"]) if work_w is None else int(work_w)
    sc = work_w / w
    kscale = work_w / float(DEFAULTS["work_w"])
    small = cv2.resize(image, (work_w, max(1, int(h * sc))))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32) / 255.0
    val = hsv[:, :, 2].astype(np.float32) / 255.0

    m = (((sat < p["sat_max"]) & (val > p["val_min"])).astype(np.uint8)) * 255
    ck, ok = _odd(p["close_k"] * kscale), _odd(p["open_k"] * kscale)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((ck, ck), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((ok, ok), np.uint8))

    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None, sc
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (lab == i).astype(np.uint8), sc


def _pad_box(box: Box, pad: float, w: int, h: int) -> Box:
    """Grow a box outward by ``pad`` of its OWN size, clipped to the frame.

    Padding relative to the box (not the frame) keeps a small detection from
    being swamped by a pad sized for a large one.
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    return (max(0, int(x0 - bw * pad)), max(0, int(y0 - bh * pad)),
            min(w, int(x1 + bw * pad)), min(h, int(y1 + bh * pad)))


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


# --------------------------------------------------------------------------
# The two boxes
# --------------------------------------------------------------------------


def search_box(comp: np.ndarray, sc: float, p: dict, w: int, h: int) -> Box:
    """Box that aims the gutter search: percentile-trimmed, modestly padded.

    Extremes of the paper component follow thin bright leaks (a cable, a chair
    edge) far past the book; percentiles do not, because a leak carries almost
    no pixel mass.
    """
    ys, xs = np.nonzero(comp)
    q = float(p["trim_pct"])
    x0, x1 = np.percentile(xs, [q, 100.0 - q])
    y0, y1 = np.percentile(ys, [q, 100.0 - q])
    box = (int(x0 / sc), int(y0 / sc), int(x1 / sc), int(y1 / sc))
    return _pad_box(box, float(p["search_pad"]), w, h)


def grabcut_box(image: np.ndarray, p: dict) -> Box | None:
    """Box that decides which pixels become the page, via seeded GrabCut.

    The paper mask alone under-covers coloured page areas (headers, side
    strips); GrabCut, seeded from it, grows across them. Returns None if the
    segmentation collapses, so the caller can fall back rather than crop wrong.
    """
    h, w = image.shape[:2]
    gw = int(p["gc_work_w"])
    gsc = gw / w
    small = cv2.resize(image, (gw, max(1, int(h * gsc))))
    # Build the seed at GrabCut's own working width. Downsampling the search
    # mask instead was measured to matter: it thickened the eroded GC_FGD core
    # and left de_02 clipping 17.6 % of its labelled book instead of 0.0 %.
    seed, _ = paper_mask(image, p, work_w=gw)
    if seed is None:
        return None
    seed = seed[:small.shape[0], :small.shape[1]]
    if seed.shape != small.shape[:2]:
        seed = cv2.resize(seed, (small.shape[1], small.shape[0]),
                          interpolation=cv2.INTER_NEAREST)

    gm = np.full(small.shape[:2], cv2.GC_PR_BGD, np.uint8)
    dk, ek = int(p["gc_seed_dilate"]), int(p["gc_seed_erode"])
    gm[cv2.dilate(seed, np.ones((dk, dk), np.uint8)) > 0] = cv2.GC_PR_FGD
    gm[cv2.erode(seed, np.ones((ek, ek), np.uint8)) > 0] = cv2.GC_FGD
    # The frame border is background by construction: the book is never flush
    # with the edge in a capture worth cropping, and this anchors the colour
    # model on the room rather than letting it drift onto the page.
    b = max(2, int(gw * 0.01))
    gm[:b, :] = cv2.GC_BGD
    gm[-b:, :] = cv2.GC_BGD
    gm[:, :b] = cv2.GC_BGD
    gm[:, -b:] = cv2.GC_BGD

    try:
        cv2.grabCut(small, gm, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), int(p["gc_iters"]),
                    cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None

    fg = (((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD)).astype(np.uint8)) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, _ = stats[i]
    box = (int(x / gsc), int(y / gsc), int((x + bw) / gsc), int((y + bh) / gsc))
    return _pad_box(box, float(p["emit_pad"]), w, h)


# --------------------------------------------------------------------------
# Resolver
# --------------------------------------------------------------------------


def find_book(image: np.ndarray, p: dict | None = None) -> BookBoundary:
    """Locate the book. Abstaining is a normal, recorded outcome.

    On abstain both boxes are the full frame, so Stage 02 runs exactly as it did
    before this module existed — that is how the 13 tightly-framed fixtures keep
    byte-identical output without any threshold being tuned for them.
    """
    p = dict(DEFAULTS) if p is None else p
    h, w = image.shape[:2]
    full: Box = (0, 0, w, h)
    frame_area = float(w * h)

    def refuse(reason: str, diag: dict | None = None) -> BookBoundary:
        return BookBoundary(applied=False, reason=reason, emit=full,
                            search=full, diag=diag or {})

    if not p.get("enabled", True):
        return refuse("book_crop disabled in config")

    comp, sc = paper_mask(image, p)
    if comp is None:
        return refuse("no bright low-saturation region found")

    seed_frac = float(comp.sum()) / float(comp.size)
    diag: dict = {"seed_frac": round(seed_frac, 4)}
    if seed_frac < p["min_seed_frac"]:
        return refuse(
            f"paper region is {seed_frac:.1%} of the frame (< "
            f"{p['min_seed_frac']:.0%}) — too small to be a book spread", diag)

    sbox = search_box(comp, sc, p, w, h)

    ebox = grabcut_box(image, p) if p.get("grabcut", True) else None
    if ebox is None:
        # Fall back to the raw (untrimmed) mask bbox with the wider pad measured
        # for it. Never fall back to the SEARCH box: it is trimmed inward and
        # would clip page content, which is the one failure that cannot be undone.
        ys, xs = np.nonzero(comp)
        raw = (int(xs.min() / sc), int(ys.min() / sc),
               int(xs.max() / sc), int(ys.max() / sc))
        ebox = _pad_box(raw, float(p["fallback_pad"]), w, h)
        diag["emit_source"] = "mask_bbox_fallback"
    else:
        diag["emit_source"] = "grabcut"

    # The emitted region must contain everything the search may point at, or a
    # gutter found in the search box could land outside the pixels being cut.
    ebox = _union(ebox, sbox)

    ex0, ey0, ex1, ey1 = ebox
    area_frac = ((ex1 - ex0) * (ey1 - ey0)) / frame_area
    aspect = (ex1 - ex0) / max(1, (ey1 - ey0))
    diag.update({"emit_area_frac": round(area_frac, 3),
                 "emit_aspect": round(aspect, 3),
                 "search_area_frac": round(
                     ((sbox[2] - sbox[0]) * (sbox[3] - sbox[1])) / frame_area, 3)})

    if area_frac >= p["abstain_area_frac"]:
        return refuse(
            f"book fills {area_frac:.0%} of the frame (>= "
            f"{p['abstain_area_frac']:.0%}) — already tightly framed, not cropping",
            diag)
    if area_frac < p["min_area_frac"]:
        return refuse(
            f"book box is {area_frac:.1%} of the frame (< "
            f"{p['min_area_frac']:.0%}) — implausible, not cropping", diag)
    if not (p["aspect_min"] <= aspect <= p["aspect_max"]):
        return refuse(
            f"book box aspect {aspect:.2f} outside "
            f"[{p['aspect_min']}, {p['aspect_max']}] — implausible, not cropping",
            diag)

    return BookBoundary(applied=True, reason="cropped to detected book",
                        emit=ebox, search=sbox, diag=diag)
