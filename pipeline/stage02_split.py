"""Stage 02 — gutter split.

Splits a two-page book spread into ``left.png`` / ``right.png`` (or emits a
single ``single.png`` when no confident gutter is found). This is the first
concrete stage; it establishes the three-artifact contract every later stage
copies (see CLAUDE.md):

  * output image(s) + ``split.json`` (the stage's data: subpage manifest +
    crop geometry in ORIGINAL spread coordinates),
  * ``meta.json`` (StageMeta: version, params, timings, warnings),
  * a debug overlay in ``debug/02_split.png`` so a bad cut is visible at a glance.

Input contract: reads ONLY ``01_fuse/anchor.png`` from the page directory. To
test before Stage 00/01 exist, seed a page folder by copying a testset spread
to ``<page>/01_fuse/anchor.png`` (see ``tools`` / the eval harness).

Detector rationale (grounded in the actual handheld photos, not assumed):
the gutter is a WIDE bright whitespace valley between the two text blocks with
only a soft binding shadow — not a hard dark band. The page also sits on darker
fabric, so the far left/right columns are dark background. We therefore (a)
measure per-column INK (adaptive-threshold text mask, which is immune to the
smooth binding-shadow gradient), and (b) search only the CENTRAL band so the
dark fabric margins can't masquerade as the gutter. The cut is biased to sit in
the middle of the whitespace with a small overlap margin: losing text is the
only real failure; carrying a sliver of the other page's margin is harmless
(dewarp/layout re-crop downstream).

**Per-page frame selection (v0.4.0, opt-in, OFF by default).** Normally one
photograph becomes both pages: this stage cuts ``anchor.png`` in two. With
``per_page_source.mode: ocr`` in config.yaml (or ``--per-page-source ocr``) the
left and right pages may instead be cut from DIFFERENT full-spread photographs
of the same spread — whichever reads better on that side once flattened. The
machinery, the measured reason the default is off, and the documented CLAUDE.md
exception it needs (this stage then reads the candidate frames back out of
``00_ingest/``, named by ``01_fuse/fuse.json``) all live in
``pipeline/page_source.py``. When it is off, nothing extra runs and the output
is byte-identical to v0.3.0's.

Known v1 limitations (recorded in meta.warnings): a single VERTICAL cut assumes
a near-vertical gutter; strong tilt/curvature is Stage 03's (dewarp) job. The
``single.png`` branch is untested — the current testset is all two-page spreads.

**v0.5.0 says what it does not know (no accuracy change).** Three reporting
defects found by the 2026-08-28 device session, where two real captures split
wrongly and the artifacts explained the failure inaccurately:

  * the spine-pinch cue now tests whether it can run at all before reporting a
    depth. On pixels with no visible page outline its number is noise, and
    ``paleset_02``'s 0.012 was being read as "this book has no pinch" when it
    was "this cue never measured anything". Layer 2 is skipped when the cue is
    inapplicable — measured to change no shipped answer on the 21 fixtures, and
    the point is the fixture it would refuse next.
  * ``corroborated`` became ``pinch_corroborated``, which is what it always
    asked, and ``corroborated_by`` is the new field about the column that
    actually shipped. On ``paleset_01`` the old flag read ``true`` for a column
    ~1000 px away from the cut.
  * when the two non-deciding cues agree with each other and not with the
    winner, ``other_cues_agree_elsewhere`` says so. Reported, never acted on.

The book-boundary crop's matching fix — an abstain reason that no longer claims
the shot was "already tightly framed" when it never found the book — is in
``pipeline/book_boundary.py`` and surfaces here as ``book_crop_evidence``.

Usage:
    python -m pipeline.stage02_split jobs/<job_id>/<page>/ [--debug]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from pydantic import BaseModel, Field

from pipeline import book_boundary as BB
from pipeline import page_source as PS
from pipeline.page_model import BBox, StageMeta

STAGE = "stage02_split"
VERSION = "0.5.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Detector defaults (overridable via config.yaml `split:`). These are tuned
# against the testset spreads; they are geometry heuristics, not the adaptive
# CONFIDENCE thresholds that CLAUDE.md forbids hard-coding (those live in
# Stage 06). Central search band keeps dark fabric margins out of the running.
DEFAULTS = {
    "search_lo": 0.30,     # gutter search window, fraction of width
    "search_hi": 0.70,
    "smooth_frac": 0.02,   # column-profile moving-average width, fraction of W
    # Confident gutter iff valley ink < ratio * page ink. Tuned on the 13
    # correctly-oriented flat testset spreads: real gutters score 0.11-0.47, so
    # 0.55 clears them all with margin. NOTE: the single-page side of this cut is
    # UNVALIDATED — the current testset has no single-page capture; a body-text
    # single page should score ~1.0, but a page with a central figure could dip.
    # Revisit when a single-page test image is appended (testset follow-up).
    "valley_ratio": 0.55,
    "margin_frac": 0.010,  # cut overlap each side, fraction of W (never lose text)
    "adaptive_block": 31,  # adaptiveThreshold blockSize (odd)
    "adaptive_C": 15,
    # --- Layer 2: spine-pinch cue (curved/tightly-held real spreads) ---------
    # On a curved handheld spread the inner text runs right to the binding, so
    # the ink whitespace valley (Layer 1) washes out (Finding 2: de_01/de_02 and
    # the Taleb prose spread score 0.85/0.67/0.91 — all above valley_ratio). But
    # the physical page is PINCHED at the spine: photographed from above, an open
    # book's paper outline dips down on top and rises up on the bottom at the
    # binding, so the per-column vertical EXTENT of the bright page region has a
    # minimum right at the gutter. That pinch is content-independent (it survives
    # figure-heavy pages where the ink valley and shadow both fail) and, crucially,
    # is created by the very curvature that kills Layer 1 — the two cues are
    # complementary, not competing. Calibrated on the testset: flat spreads pinch
    # <=0.09, the three curved spreads pinch 0.14-0.18 -> gate at 0.11 sits in the
    # gap. This layer only runs when Layer 1 is NOT confident, so all 13 flat
    # spreads keep their exact ink result (non-regression by construction).
    "pinch_smooth_frac": 0.04,   # extent-profile smoothing (2x the ink smoothing)
    "pinch_min_depth": 0.11,     # confident pinch iff extent dip >= this fraction
    # The pinch cue reads the FIRST and LAST bright row of each column, so it
    # only measures a page outline when there is visible background above and
    # below the page. When the bright region reaches the top and bottom of
    # nearly every column the profile is pinned at the image height and the
    # depth it reports is noise. Mean column extent over the search band, as a
    # fraction of image height, separates cleanly (measured on all 21 fixtures
    # 2026-08-28): outline visible 0.798-0.840 (paleset_01, de_01, de_02,
    # zoomset_de_01), pinned 0.924-0.991 (everything else, incl. paleset_02 at
    # 0.977). Gate at the midpoint of that gap, the rule this file already uses
    # for pinch_min_depth and Stage 00's OSD 180 floor.
    "pinch_max_mean_extent": 0.88,
    "corroborate_frac": 0.03,    # a 2nd cue "agrees" if within this frac of W
    "pinch_margin_frac": 0.020,  # wider overlap for pinch (curved) cuts vs 0.010
}


# --------------------------------------------------------------------------
# Output schema (stage-local for v1; formalize into page_model when Stage 03
# consumes it, in its own schema commit — see CLAUDE.md).
# --------------------------------------------------------------------------


class SubPage(BaseModel):
    """One page carved out of the spread, with its crop box in spread coords.

    ``source`` names the PHOTOGRAPH these pixels came from, and ``box`` is in
    that photograph's coordinates. With per-page frame selection off (the
    default) every subpage says ``01_fuse/anchor.png`` and this is the
    long-standing "ORIGINAL spread coordinates" contract verbatim. With it on
    (``per_page_source.mode: ocr``) the two sides may come from different
    frames, so "the original spread" is no longer a single image and the box is
    only meaningful together with ``source`` — asserted in test_stage02_split.
    """

    name: str            # left.png | right.png | single.png
    box: BBox            # crop rectangle in ``source``'s pixel coordinates
    source: str = "01_fuse/anchor.png"   # page-dir-relative path to those pixels
    # Per-side geometry. Identical to the top-level fields unless this side was
    # cut from a different frame, in which case the top-level numbers describe
    # the anchor and these describe the frame that actually supplied the page.
    gutter_x: int | None = None
    book_crop: BBox | None = None


class UserBookBox(BaseModel):
    """``<page_dir>/book_box.json`` — the book box an operator drew.

    **A documented exception to the stage contract, and a narrow one.** Item 2 of
    the contract (CLAUDE.md) says a stage reads only the previous stage's
    artifacts. This file is not an artifact of any stage: it is USER INPUT, the
    same kind of thing as ``config.yaml`` or ``--mode patch``, and it lives at the
    page-dir ROOT rather than inside a numbered folder so it is never mistaken for
    one. No stage writes it; ``tools/book_box_editor`` does, from a human's mouse.

    ``frame`` and ``frame_size`` are the box's provenance and they are CHECKED,
    not decoration. A box drawn on one anchor and applied to another is a wrong
    crop carrying a human's full confidence — precisely the class of failure the
    2026-08-28 honesty work exists to stop — so Stage 02 refuses a box whose frame
    does not match and says why, rather than cropping to it.
    """

    box: list[int]                        # x0, y0, x1, y1 in ``frame`` pixels
    frame: str = "01_fuse/anchor.png"     # page-dir-relative frame it was drawn on
    frame_size: list[int]                 # [width, height] of that frame
    drawn_at: str = ""                    # ISO timestamp, informational
    note: str = ""                        # free text from the operator


class SplitResult(BaseModel):
    """Contents of ``02_split/split.json`` — the stage's inter-stage data."""

    source: str
    width: int
    height: int
    gutter_x: int | None            # cut column in spread coords, None if single
    confident: bool
    method: str = "none"            # which layer resolved it: ink | pinch | none
    pages: list[SubPage] = Field(default_factory=list)
    # diagnostics (why the confidence decision went the way it did)
    valley: float = 0.0             # Layer 1: min ink in central band
    page_ref: float = 0.0           # Layer 1: typical text-column ink
    ratio: float = 0.0              # Layer 1: valley / page_ref (< valley_ratio => split)
    pinch_depth: float = 0.0        # Layer 2: extent dip at spine (>= pinch_min_depth => split)
    # Whether the pinch cue could work here at all. False => pinch_depth is not
    # a small pinch, it is no measurement (see extent_profile). Layer 2 is
    # skipped when False, so a meaningless number can never decide a split.
    pinch_applicable: bool = True
    pinch_extent_frac: float = 0.0  # mean column extent / image height, over the band
    pinch_x: int | None = None      # Layer 2: spine column from the page-pinch cue
    shadow_x: int | None = None     # binding-shadow luminance-valley column (corroboration only)
    # The window every cue's argmin was taken over, in ORIGINAL spread pixels. A
    # cue reported ON this boundary is the band clipping its profile, not a
    # feature of the page — the single most common way to misread the columns
    # above (it accounts for 4 of the 5 other_cues_agree_elsewhere hits).
    band_x: list[int] = Field(default_factory=list)
    # Scoped to the PINCH CANDIDATE, computed whether or not pinch decided: did
    # shadow OR ink land within tol of pinch_x? Named for its scope since
    # 2026-08-28 — as a bare ``corroborated`` it read as endorsing the shipped
    # gutter, which on paleset_01 it was ~1000 px away from. MEANINGLESS when
    # ``pinch_applicable`` is False: it then reports agreement with a column
    # that was never measured (paleset_02 reads True on exactly that footing).
    pinch_corroborated: bool = False
    # Scoped to the gutter that ACTUALLY SHIPPED: which other cues agree with it.
    corroborated_by: list[str] = Field(default_factory=list)
    # True when the two cues that did NOT decide agree with each other and both
    # disagree with the one that did — evidence against the shipped column.
    # Reported, never acted on (that is the plan's Phase 2 consensus override).
    other_cues_agree_elsewhere: bool = False
    # --- book-boundary crop (pipeline/book_boundary.py, v0.3.0) -------------
    # Every box and column in this file is in ORIGINAL spread pixels whether or
    # not a crop was applied, so Stage 03 and patch-mode word crops need to know
    # nothing about the crop. Asserted in test_stage02_split.
    book_crop_applied: bool = False
    # "detector" | "operator" | "operator-refused". Never infer this from
    # book_crop_applied: an operator box that failed its provenance check leaves
    # applied False with the DETECTOR's own reason, and a reader has to be able
    # to tell that from a page nobody ever drew on.
    book_crop_source: str = "detector"
    book_crop_reason: str = ""
    # How far ``book_crop_reason`` licenses a conclusion. Load-bearing when the
    # crop abstained on area: that refusal is NOT a finding that the shot was
    # tightly framed. See pipeline/book_boundary.py.
    book_crop_evidence: str = ""
    book_crop: BBox | None = None    # pixels emitted as the page(s)
    book_search: BBox | None = None  # region the gutter search was restricted to
    # --- per-page frame selection (pipeline/page_source.py, v0.4.0) ----------
    # None when the option is off (the default) — which is the shipped state and
    # the measured one: RESULTS 2026-08-26 found the two sides do prefer
    # different photographs on 3 of 7 sets but nothing clears the bar. When on,
    # this records every candidate's reading of every side and why each side's
    # source was kept or swapped.
    per_page_source: PS.SelectionResult | None = None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update(cfg.get("split", {}) or {})
    return params


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def ink_profile(gray: np.ndarray, block: int, c: int) -> np.ndarray:
    """Per-column count of text-ink pixels via adaptive threshold.

    Adaptive (local) thresholding turns dark text strokes into ink=1 while
    ignoring the smooth binding-shadow gradient and even lighting. Fabric
    background outside the central band produces some ink noise, but the gutter
    search never looks there.
    """
    block = block if block % 2 == 1 else block + 1
    ink = cv2.adaptiveThreshold(
        gray, 1, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=block, C=c,
    )
    return ink.sum(axis=0).astype(np.float64)


def smooth(profile: np.ndarray, width: int) -> np.ndarray:
    width = max(1, width)
    kernel = np.ones(width) / width
    return np.convolve(profile, kernel, mode="same")


def extent_profile(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Per-column vertical extent (last-first bright row) of the page region.

    Otsu-separates the bright page from the dark capture background, then for
    each column measures how tall the bright run is. An open book photographed
    from above is pinched at the binding, so this profile dips at the spine — a
    content-independent gutter cue that survives figure-heavy pages where the
    ink-whitespace valley and the binding shadow both fail.

    ASSUMES the page's outline is visible — that there is background above and
    below it, and that the background is darker than the page. The caller tests
    that assumption (``pinch_max_mean_extent``) instead of trusting it, because
    when it fails this function still returns a perfectly ordinary-looking
    profile and a number that means nothing.

    The failure was originally modelled as "on a bright background Otsu inverts".
    Measurement says otherwise: on ``paleset_02`` (a book on a pale sofa) Otsu
    does NOT invert — the sofa still reads dark, 8.9 % of the pixels outside the
    labelled book pass as bright. What breaks the cue is that scattered bright
    specks reach the top and bottom edges of most columns, so ``first`` is ~0 and
    ``last`` is ~h-1 and the profile is pinned flat at the image height. Its dip
    is then 0.012, which is not "no pinch" — it is no measurement.
    """
    h, w = gray.shape
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    page = gray > thr
    any_bright = page.any(axis=0)
    first = np.argmax(page, axis=0)
    last = h - 1 - np.argmax(page[::-1], axis=0)
    ext = np.where(any_bright, last - first, 0).astype(np.float64)
    return ext, float(thr)


def detect_gutter(gray: np.ndarray, p: dict) -> tuple[int | None, dict]:
    """Layered gutter resolver. Returns (gutter_x, diagnostics).

    Priority cascade (mirrors the Stage 00 orientation resolver):
      Layer 1 — ink whitespace valley: confident on FLAT open spreads with a
                real gutter gap. When it fires, it wins outright, so all 13 flat
                testset spreads keep byte-identical behaviour (non-regression).
      Layer 2 — spine pinch: only consulted when Layer 1 is not confident. Rescues
                CURVED handheld spreads (Finding 2) whose inner text fills the
                gutter and washes the ink valley out.
      else    — no confident gutter -> None (emit single.png).

    diagnostics carries every layer's numbers for the overlay + meta, plus the
    resolving ``method``.
    """
    h, w = gray.shape
    x0, x1 = int(w * p["search_lo"]), int(w * p["search_hi"])
    x1 = max(x1, x0 + 1)
    band = slice(x0, x1)

    # --- Layer 1: ink whitespace valley --------------------------------------
    prof = ink_profile(gray, int(p["adaptive_block"]), int(p["adaptive_C"]))
    cols = smooth(prof, int(w * p["smooth_frac"]))
    ink_x = x0 + int(np.argmin(cols[band]))
    valley = float(cols[ink_x])
    # Page ink reference: typical text-column density, ignoring near-white
    # margin columns so the valley is compared to real text, not to whitespace.
    floor = 0.05 * float(cols.max()) if cols.max() > 0 else 0.0
    texty = cols[cols > floor]
    page_ref = float(np.median(texty)) if texty.size else 0.0
    ratio = valley / page_ref if page_ref > 0 else 1.0
    ink_confident = page_ref > 0 and ratio < p["valley_ratio"]

    # --- Layer 2: spine pinch (page vertical-extent minimum) -----------------
    # Ask whether the cue can work here BEFORE reading what it says. A pinned
    # profile (no visible page outline in the searched pixels) yields a depth
    # that is noise, and a reader cannot tell that from an honest "flat book, no
    # pinch" unless we say so. Non-regression is MEASURED, not structural: on
    # this corpus the only two spreads pinch decides (de_01 0.823, de_02 0.829)
    # are applicable with room to spare, so gating changes no shipped answer —
    # but a future fixture could be gated out, and that is the point of it.
    ext_raw, otsu_thr = extent_profile(gray)
    pinch_extent_frac = float(ext_raw[band].mean()) / float(h)
    pinch_applicable = pinch_extent_frac <= p["pinch_max_mean_extent"]
    ext = smooth(ext_raw, int(w * p["pinch_smooth_frac"]))
    pinch_x = x0 + int(np.argmin(ext[band]))
    pinch_val = float(ext[pinch_x])
    # Compare the dip to the page height at the OUTER fifths of the band (away
    # from the spine), not the band median — the median already includes the dip.
    fifth = max(1, (x1 - x0) // 5)
    edge_ref = float(np.median(
        np.concatenate([ext[x0:x0 + fifth], ext[x1 - fifth:x1]])))
    pinch_depth = (1.0 - pinch_val / edge_ref) if edge_ref > 0 else 0.0
    pinch_confident = pinch_applicable and pinch_depth >= p["pinch_min_depth"]

    # --- Binding-shadow luminance valley (corroboration only, never decides) --
    lum = smooth(gray.mean(axis=0).astype(np.float64), int(w * p["smooth_frac"]))
    shadow_x = x0 + int(np.argmin(lum[band]))

    # A pinch split is more trustworthy when a second, independent cue lands on
    # the same column. On prose the shadow/ink corroborate within ~30px; on
    # figure-heavy pages (de_01) shadow drifts onto a dark photo, so pinch stands
    # alone — we still split, but flag it (advisor: require agreement where we
    # can get it, don't gate the whole cue on it).
    #
    # NAME IT FOR WHAT IT ASKS. This question is about the PINCH CANDIDATE, and
    # it is asked whether or not pinch decides — so on paleset_01, where ink won
    # at x=2741, it was serialized as a bare ``corroborated: true`` describing a
    # column ~1000 px from the answer that actually shipped (RESULTS 2026-08-28).
    # Nothing was wrong with the arithmetic; a reader was entitled to think it
    # endorsed the split, and it did not.
    tol = int(w * p["corroborate_frac"])
    pinch_corroborated = (abs(shadow_x - pinch_x) <= tol
                          or abs(ink_x - pinch_x) <= tol)

    # Decide first, then say what agrees with the DECISION.
    if ink_confident:
        method, gutter = "ink", ink_x
    elif pinch_confident:
        method, gutter = "pinch", pinch_x
    else:
        method, gutter = "none", None

    cue_x = {"ink": ink_x, "pinch": pinch_x, "shadow": shadow_x}
    others = sorted(k for k in cue_x if k != method)
    corroborated_by = ([] if gutter is None else
                       sorted(k for k in others if abs(cue_x[k] - gutter) <= tol))
    # Two cues agreeing with each other, far from the column that shipped, is
    # positive evidence AGAINST the shipped column — the shape of paleset_01's
    # failure and of the 2026-08-19 "both flags true on the wrong edge" finding.
    # Reported only. Acting on it is the consensus override (C1) in
    # docs/plans/book-detector-pale-background.md, which that plan puts
    # deliberately last, after the crop works.
    other_cues_agree_elsewhere = (
        gutter is not None and not corroborated_by and len(others) == 2
        and abs(cue_x[others[0]] - cue_x[others[1]]) <= tol)

    diag = {
        "cols": cols, "window": (x0, x1), "valley": valley,
        "page_ref": page_ref, "ratio": ratio,
        "ink_x": ink_x,
        "ext": ext, "pinch_x": pinch_x, "pinch_depth": pinch_depth,
        "pinch_applicable": pinch_applicable,
        "pinch_extent_frac": pinch_extent_frac, "otsu_thr": otsu_thr,
        "shadow_x": shadow_x, "pinch_corroborated": pinch_corroborated,
        "corroborated_by": corroborated_by, "tol": tol,
        "other_cues_agree_elsewhere": other_cues_agree_elsewhere,
        "method": method,
    }
    return gutter, diag


# --------------------------------------------------------------------------
# Cutting + artifacts
# --------------------------------------------------------------------------


def cut_pages(image: np.ndarray, gutter_x: int | None, margin: int
              ) -> list[tuple[str, np.ndarray, BBox]]:
    """Carve the spread into subpages. Cut biased into whitespace with overlap
    so neither half loses text (advisor: losing text is the only real failure).
    """
    h, w = image.shape[:2]
    if gutter_x is None:
        return [("single.png", image, BBox(x=0, y=0, w=w, h=h))]

    lx2 = min(w, gutter_x + margin)
    rx1 = max(0, gutter_x - margin)
    left = image[:, :lx2]
    right = image[:, rx1:]
    return [
        ("left.png", left, BBox(x=0, y=0, w=lx2, h=h)),
        ("right.png", right, BBox(x=rx1, y=0, w=w - rx1, h=h)),
    ]


def draw_overlay(image: np.ndarray, gutter_x: int | None, diag: dict) -> np.ndarray:
    """Spread with the gutter line, search window, and column ink-profile drawn
    so a human can see at a glance whether the cut landed in the whitespace.
    """
    canvas = image.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    h, w = canvas.shape[:2]

    cols = diag["cols"]
    x0, x1 = diag["window"]
    # search window (faint blue verticals)
    for x in (x0, x1):
        cv2.line(canvas, (x, 0), (x, h), (200, 120, 0), 2)

    def _curve(prof: np.ndarray, color: tuple, amp_frac: float) -> None:
        if prof.max() <= prof.min():
            return
        norm = (prof - prof.min()) / (prof.max() - prof.min())
        base, amp = h - 10, int(h * amp_frac)
        pts = [(x, int(base - norm[x] * amp)) for x in range(0, w, max(1, w // 1000))]
        for a, b in zip(pts, pts[1:]):
            cv2.line(canvas, a, b, color, 1)

    # ink whitespace profile (orange, bottom third) and page-extent pinch
    # profile (green) so a human can see which cue carried the decision.
    _curve(cols, (0, 160, 255), 0.30)
    _curve(diag["ext"], (0, 200, 0), 0.30)

    method = diag.get("method", "none")
    # corroborating cue markers (thin): shadow = cyan, pinch candidate = green
    cv2.line(canvas, (diag["shadow_x"], 0), (diag["shadow_x"], h), (255, 200, 0), 1)
    if method != "pinch":
        cv2.line(canvas, (diag["pinch_x"], 0), (diag["pinch_x"], h), (0, 200, 0), 1)

    if gutter_x is not None:
        cv2.line(canvas, (gutter_x, 0), (gutter_x, h), (0, 0, 230), 3)
        agree = diag.get("corroborated_by") or []
        if method == "pinch":
            label = (f"gutter x={gutter_x} via PINCH depth={diag['pinch_depth']:.2f}"
                     f" pinch_corrob={diag['pinch_corroborated']}"
                     f" (ink ratio={diag['ratio']:.2f})")
        else:
            label = f"gutter x={gutter_x} via INK ratio={diag['ratio']:.2f}"
        # Corroboration OF THIS CUT, which is not the same question as
        # pinch_corrob above and used to be conflated with it.
        label += f"  agreeing cues: {','.join(agree) if agree else 'NONE'}"
        color = (0, 0, 230)
    else:
        pinch_say = (f"{diag['pinch_depth']:.2f}" if diag.get("pinch_applicable", True)
                     else "n/a (cue cannot run here)")
        label = (f"NO GUTTER  ink={diag['ratio']:.2f} pinch={pinch_say}"
                 f" (single page)")
        color = (0, 200, 255)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    if not diag.get("pinch_applicable", True):
        cv2.putText(canvas, "pinch cue NOT APPLICABLE: no page outline in these "
                    "pixels (profile pinned at full height)", (30, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 255), 3)
    if diag.get("other_cues_agree_elsewhere"):
        cv2.putText(canvas, "CUE DISSENT (weak: 4 of its 5 fixture hits are "
                    "correct splits): the two cues that did not decide agree "
                    "with EACH OTHER, elsewhere", (30, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 140, 255), 3)
    return canvas


def draw_overlay_full(image: np.ndarray, book: "BB.BookBoundary",
                      gutter_x: int | None, diag: dict) -> np.ndarray:
    """Full-frame overlay showing BOTH decisions: where the book was, and where
    the spine is.

    The column profiles only make sense over the pixels they were measured on,
    so the ordinary overlay is drawn on the search crop and pasted back into a
    dimmed copy of the whole frame. That way one picture answers both questions a
    human asks when a page comes out wrong — "did it find the book?" and "did it
    find the spine?" — and a wrong crop is obvious rather than inferred from a
    number (the convention Stage 01 set with its footprint outlines).
    """
    sx0, sy0, sx1, sy1 = book.search
    ex0, ey0, ex1, ey1 = book.emit
    gutter_local = None if gutter_x is None else gutter_x - sx0
    inner = draw_overlay(image[sy0:sy1, sx0:sx1], gutter_local, diag)

    canvas = (image.copy() * 0.45).astype(np.uint8)
    canvas[sy0:sy1, sx0:sx1] = inner
    h = canvas.shape[0]

    # green = book accepted, amber = refused (frame used as-is)
    ok = book.applied
    cv2.rectangle(canvas, (ex0, ey0), (ex1 - 1, ey1 - 1),
                  (0, 220, 0) if ok else (0, 190, 255), 6)
    cv2.rectangle(canvas, (sx0, sy0), (sx1 - 1, sy1 - 1), (255, 160, 0), 4)
    if gutter_x is not None:
        cv2.line(canvas, (gutter_x, 0), (gutter_x, h), (0, 0, 230), 3)
    label = (f"book crop {'APPLIED' if ok else 'REFUSED'}: {book.reason}"
             f"  [green=emit, blue=search]")
    if book.diag.get("emit_source") == "operator":
        ux0, uy0, ux1, uy1 = book.diag["user_box"]
        cv2.rectangle(canvas, (ux0, uy0), (ux1 - 1, uy1 - 1), (255, 255, 255), 3)
        cv2.putText(canvas, "white = the box you drew (emit is padded outward "
                    "from it, deliberately)", (30, h - 125),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(canvas, label, (30, h - 90), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (0, 220, 0) if ok else (0, 190, 255), 3)
    # The caveat belongs on the picture, not only in split.json — this overlay
    # is what a human looks at when pages come out wrong, and the sentence it
    # used to carry ("already tightly framed") is what sent an operator off to
    # reframe a correctly framed shot.
    if book.evidence:
        words, line, lines = book.evidence.split(), "", []
        for word in words:
            if len(line) + len(word) + 1 > 96:
                lines.append(line); line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        for i, text in enumerate(lines[:2]):
            cv2.putText(canvas, text, (30, h - 55 + i * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 190, 255), 2)
    return canvas


# --------------------------------------------------------------------------
# Operator-supplied book box (user input, not a stage artifact)
# --------------------------------------------------------------------------

USER_BOX_FILE = "book_box.json"


def load_user_box(page_dir: Path) -> UserBookBox | None:
    """Read ``<page_dir>/book_box.json``, or None when nobody has drawn one.

    A malformed file is reported as absent rather than raised: the operator's
    convenience tool must never be able to stop a page from processing. The
    warning path is the caller's.
    """
    f = page_dir / USER_BOX_FILE
    if not f.exists():
        return None
    try:
        return UserBookBox.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def user_box_mismatch(user: UserBookBox, w: int, h: int) -> str | None:
    """Why this box may NOT be applied to a ``w`` x ``h`` anchor, or None.

    Provenance, not geometry — geometry is ``book_boundary.user_box``'s job. A
    box drawn on a different frame is the dangerous case, because it looks
    perfectly valid and is confidently wrong.
    """
    if user.frame != "01_fuse/anchor.png":
        return (f"it was drawn on {user.frame!r}, but Stage 02 cuts "
                f"01_fuse/anchor.png")
    if list(user.frame_size) != [w, h]:
        return (f"it was drawn on a {user.frame_size[0]}x{user.frame_size[1]} "
                f"frame and this anchor is {w}x{h} — Stage 01 has re-run since, "
                f"so the coordinates no longer mean the same thing")
    if len(user.box) != 4:
        return f"box {user.box} is not [x0, y0, x1, y1]"
    return None


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, debug: bool = False) -> SplitResult:
    t0 = time.perf_counter()
    params = resolve_params(cfg)
    # Resolved BEFORE any work so a typo in the mode fails immediately rather
    # than after a dewarp-and-OCR probe has already run.
    ps_params = PS.resolve_params(cfg)
    warnings: list[str] = []

    src = page_dir / "01_fuse" / "anchor.png"
    if not src.exists():
        raise FileNotFoundError(
            f"missing {src} — Stage 02 reads 01_fuse/anchor.png. Seed it by "
            f"copying a spread there (Stage 00/01 not built yet)."
        )
    # IMREAD_IGNORE_ORIENTATION: never let cv2 apply the EXIF rotation here.
    # Orientation is Stage 00 (ingest)'s job; anchor.png is expected already
    # normalized to a readable LANDSCAPE spread (gutter vertical). We read the
    # raw buffer so a mis-normalized upstream shows up in the assertion below
    # instead of being silently rotated.
    image = cv2.imread(str(src), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise RuntimeError(f"unreadable image: {src}")
    h, w = image.shape[:2]

    # A two-page spread is always wider than tall. Portrait input means the
    # orientation was not normalized upstream — the vertical-gutter detector
    # would then be looking along the wrong axis. Fail loud (warn), don't
    # silently adapt (advisor): a dual-axis search would mask the ingest bug
    # and can mistake a horizontal paragraph gap for the gutter.
    if h > w:
        warnings.append(
            f"PORTRAIT input ({w}x{h}): a book spread must be landscape "
            f"(gutter vertical). Orientation not normalized upstream (Stage 00 "
            f"ingest); gutter detection along the vertical axis is unreliable."
        )

    # Find the book before looking for the spine. Without this the search runs
    # over the whole frame, and on a handheld capture that is 40-55 % room it
    # locks onto the book's outer edge instead of its binding (RESULTS
    # 2026-08-19). Two boxes come back and they are NOT interchangeable: the
    # search box aims the detector, the emit box decides which pixels become the
    # page. When the frame is already tight both are the full frame and every
    # line below behaves exactly as it did before.
    bb_params = BB.resolve_params(cfg)
    t_book = time.perf_counter()
    # An operator's box wins over detection — but only after its provenance is
    # checked. See UserBookBox and pipeline/book_boundary.user_box.
    user, crop_source = load_user_box(page_dir), "detector"
    if user is not None:
        bad = user_box_mismatch(user, w, h)
        if bad:
            warnings.append(
                f"operator book box in {USER_BOX_FILE} REFUSED: {bad}. Falling "
                f"back to detection. Redraw it with tools/book_box_editor.")
            crop_source = "operator-refused"
            book = BB.find_book(image, bb_params)
        else:
            book = BB.user_box(image, tuple(user.box), bb_params)
            crop_source = "operator"
            if book.diag.get("user_box_rejected"):
                # Unusable box -> detect instead. A box that merely crops nothing
                # is NOT this case: it is the human's answer and it stands, so
                # the artifacts keep saying "operator" rather than reporting the
                # detector's reasoning for a page a person acted on.
                warnings.append(f"operator book box REFUSED: {book.reason}")
                crop_source = "operator-refused"
                book = BB.find_book(image, bb_params)
    else:
        book = BB.find_book(image, bb_params)
    book_ms = (time.perf_counter() - t_book) * 1000.0
    if book.applied:
        warnings.append(
            f"book-boundary crop applied: emit={book.emit} search={book.search} "
            f"({book.diag.get('emit_source')}, "
            f"{book.diag.get('emit_area_frac', 0):.0%} of frame). Gutter searched "
            f"inside the book, not the whole frame.")
    else:
        warnings.append(f"book-boundary crop NOT applied: {book.reason}")
        if book.evidence:
            warnings.append(f"book-boundary crop, what that does NOT mean: "
                            f"{book.evidence}")

    ex0, ey0, ex1, ey1 = book.emit
    sx0, sy0, sx1, sy1 = book.search
    emit_img = image[ey0:ey1, ex0:ex1]
    search_gray = cv2.cvtColor(image[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)

    t_detect = time.perf_counter()
    gutter_local, diag = detect_gutter(search_gray, params)
    detect_ms = (time.perf_counter() - t_detect) * 1000.0
    # Back to ORIGINAL spread coordinates immediately, so nothing downstream ever
    # sees a search-box coordinate.
    gutter_x = None if gutter_local is None else gutter_local + sx0
    # Every cue column reported to a human is in ORIGINAL spread coordinates,
    # like everything else in this file.
    band_abs = (int(diag["window"][0]) + sx0, int(diag["window"][1]) + sx0)
    ink_abs = int(diag["ink_x"]) + sx0
    pinch_abs, shadow_abs = int(diag["pinch_x"]) + sx0, int(diag["shadow_x"]) + sx0

    method = diag["method"]
    if not diag["pinch_applicable"]:
        # Say "this cue could not run" rather than letting its number be read as
        # a measured absence of a spine. See extent_profile.
        warnings.append(
            f"spine-pinch cue (Layer 2) NOT APPLICABLE here: mean column extent "
            f"is {diag['pinch_extent_frac']:.3f} of the image height (> "
            f"{params['pinch_max_mean_extent']}), so the page outline is not "
            f"visible in the searched pixels and the profile is pinned flat. "
            f"Its depth={diag['pinch_depth']:.3f} is NOT a measurement of a "
            f"flat spine — it is no measurement, and Layer 2 was skipped.")
    if gutter_x is None:
        pinch_say = (f"pinch depth={diag['pinch_depth']:.2f} < "
                     f"{params['pinch_min_depth']}" if diag["pinch_applicable"]
                     else "pinch cue not applicable (see above)")
        warnings.append(
            f"no confident gutter (ink ratio={diag['ratio']:.2f} >= "
            f"{params['valley_ratio']}, {pinch_say}); emitting single.png"
        )
    elif method == "pinch":
        # Layer-2 rescue: the ink valley was washed out (curved spread); the
        # spine came from the page-pinch cue. Wider overlap margin because a
        # curved gutter is not a perfectly vertical line — the extra buffer keeps
        # the straight cut from clipping text at the page's top/bottom.
        warnings.append(
            f"gutter from spine-pinch (Layer 2): ink ratio={diag['ratio']:.2f} "
            f"failed, pinch depth={diag['pinch_depth']:.2f}, pinch_corroborated="
            f"{diag['pinch_corroborated']}. The cue needs a visible page outline; "
            f"here mean column extent is {diag['pinch_extent_frac']:.3f} of the "
            f"image height (<= {params['pinch_max_mean_extent']}), so it applies."
        )
        if not diag["pinch_corroborated"]:
            warnings.append(
                "pinch split is UNCORROBORATED (neither the binding-shadow nor "
                "the ink valley agree within tolerance) — lower confidence; "
                "check debug/02_split.png."
            )

    if gutter_x is not None:
        # Corroboration OF THE COLUMN THAT SHIPPED — the question a reader of
        # split.json actually has, and the one the old bare ``corroborated``
        # flag did not answer.
        agree = diag["corroborated_by"]
        warnings.append(
            f"gutter x={gutter_x} decided by {method}; other cues agreeing "
            f"within {diag['tol']}px: {', '.join(agree) if agree else 'NONE'} "
            f"(ink={ink_abs}, pinch={pinch_abs}, shadow={shadow_abs}; search "
            f"band x={band_abs[0]}..{band_abs[1]} - a cue sitting on a band edge "
            f"is the band clipping its profile, not a feature of the page)")
        if diag["other_cues_agree_elsewhere"]:
            # Honest about its own hit rate, because it is poor. Measured over
            # all 21 fixtures 2026-08-28: fires on 5, and 4 of those 5 are
            # CORRECT splits. In every one of the four, both agreeing cues sit
            # pinned at an END of the search band, which is the band clipping
            # their profile rather than a feature in the page — the artifact the
            # plan's band-edge guard (Phase 2, C3) is for. So: read the band
            # below first, and if both cues are sitting on its edge, ignore this.
            warnings.append(
                f"CUE DISSENT (weak signal, see below): the two cues that did "
                f"NOT decide agree with each other and both disagree with the "
                f"{method} column that shipped. ink={ink_abs} pinch={pinch_abs} "
                f"shadow={shadow_abs}, search band x={band_abs[0]}..{band_abs[1]}. "
                f"On the 21 testset fixtures this fires 5 times and 4 of those "
                f"are correct splits, every one of them with both cues pinned at "
                f"a band edge. It is a prompt to open debug/02_split.png, not "
                f"evidence. Nothing acts on it (consensus override is Phase 2 of "
                f"docs/plans/book-detector-pale-background.md).")

    margin_frac = params["pinch_margin_frac"] if method == "pinch" else params["margin_frac"]
    # Overlap is a fraction of the width being CUT. Identical to the old
    # ``int(w * margin_frac)`` whenever the crop abstains (emit == full frame).
    margin = int(emit_img.shape[1] * margin_frac)
    gutter_in_emit = None if gutter_x is None else gutter_x - ex0
    pieces = cut_pages(emit_img, gutter_in_emit, margin)

    # --- per-page frame selection (opt-in) ----------------------------------
    # Everything above is the anchor's own cut and is what ships by default. If
    # the option is on, a side may instead be taken from a DIFFERENT full-spread
    # photograph of this spread — one that reads better on that side once
    # flattened. See pipeline/page_source.py for why the default is off and why
    # the only criterion is OCR. The anchor's numbers stay in the top-level
    # fields either way; a swapped side carries its own geometry.
    anchor_box = BBox(x=ex0, y=ey0, w=ex1 - ex0, h=ey1 - ey0)
    emitted = [(name, img, BBox(x=box.x + ex0, y=box.y + ey0, w=box.w, h=box.h),
                "01_fuse/anchor.png", gutter_x, anchor_box)
               for name, img, box in pieces]
    selection: PS.SelectionResult | None = None
    chosen: dict = {}
    if ps_params["mode"] != "off":
        selection, chosen = PS.select(page_dir, cfg, ps_params, image, warnings)
        swapped = []
        for entry in emitted:
            name = entry[0]
            cand = chosen.get(name)
            if cand is None:
                swapped.append(entry)
                continue
            img, box = cand.pieces[name]
            bx0, by0, bx1, by1 = cand.book.emit
            swapped.append((name, img,
                            BBox(x=box[0], y=box[1], w=box[2], h=box[3]),
                            f"00_ingest/{cand.name}", cand.gutter_x,
                            BBox(x=bx0, y=by0, w=bx1 - bx0, h=by1 - by0)))
        emitted = swapped

    # Write artifacts.
    out_dir = page_dir / "02_split"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear the other branch's stale images so a re-run's folder reflects ONLY
    # this run (stage contract). Otherwise flipping single<->split leaves a
    # phantom page for any downstream stage that globs instead of reading the
    # split.json pages manifest.
    for stale in ("left.png", "right.png", "single.png"):
        (out_dir / stale).unlink(missing_ok=True)
    subpages: list[SubPage] = []
    for name, img, box, source, side_gutter, side_crop in emitted:
        cv2.imwrite(str(out_dir / name), img)
        # cut_pages works in the emitted crop's frame; SubPage.box is documented
        # as coordinates of ``source``, so the crop offset is already added back
        # above. This is the one place a silent error would propagate all the way
        # to patch-mode word crops, so it is asserted in the tests.
        subpages.append(SubPage(name=name, box=box, source=source,
                                gutter_x=side_gutter, book_crop=side_crop))

    result = SplitResult(
        source="01_fuse/anchor.png", width=w, height=h,
        gutter_x=gutter_x, confident=gutter_x is not None, method=method,
        pages=subpages,
        valley=round(diag["valley"], 1), page_ref=round(diag["page_ref"], 1),
        ratio=round(diag["ratio"], 3),
        pinch_depth=round(diag["pinch_depth"], 3),
        pinch_applicable=bool(diag["pinch_applicable"]),
        pinch_extent_frac=round(diag["pinch_extent_frac"], 3),
        pinch_x=int(diag["pinch_x"]) + sx0,
        shadow_x=int(diag["shadow_x"]) + sx0, band_x=list(band_abs),
        pinch_corroborated=bool(diag["pinch_corroborated"]),
        corroborated_by=list(diag["corroborated_by"]),
        other_cues_agree_elsewhere=bool(diag["other_cues_agree_elsewhere"]),
        book_crop_applied=book.applied, book_crop_source=crop_source,
        book_crop_reason=book.reason, book_crop_evidence=book.evidence,
        book_crop=anchor_box,
        book_search=BBox(x=sx0, y=sy0, w=sx1 - sx0, h=sy1 - sy0),
        per_page_source=selection,
    )
    (out_dir / "split.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    # Debug overlay (always — the contract requires one per stage).
    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    overlay = draw_overlay_full(image, book, gutter_x, diag)
    if any(sp.source != "01_fuse/anchor.png" for sp in subpages):
        # Say on the anchor's own overlay which sides it did NOT supply, and
        # write that frame's overlay too — otherwise a bad cut on the frame that
        # actually supplied a page would be invisible, which is exactly the
        # failure the per-stage overlay exists to make obvious.
        cv2.putText(overlay, "per-page sources: " + "  ".join(
            f"{sp.name}<-{Path(sp.source).name}" for sp in subpages),
            (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 200, 255), 3)
        for name in sorted({sp.source for sp in subpages
                            if sp.source != "01_fuse/anchor.png"}):
            cand = chosen[next(sp.name for sp in subpages if sp.source == name)]
            cv2.imwrite(
                str(debug_dir / f"02_split_source_{Path(name).stem}.png"),
                draw_overlay_full(cand.image, cand.book, cand.gutter_x, cand.diag))
    cv2.imwrite(str(debug_dir / "02_split.png"), overlay)
    if debug:
        # extra intermediates: raw + smoothed column profile as CSV
        np.savetxt(out_dir / "col_profile.csv", diag["cols"], delimiter=",")

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={**{k: params[k] for k in DEFAULTS},
                "book_crop": {k: bb_params[k] for k in BB.DEFAULTS},
                "per_page_source": {k: ps_params[k] for k in PS.DEFAULTS}},
        timings_ms={"book_boundary": round(book_ms, 1),
                    "detect": round(detect_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "single vertical cut assumes a near-vertical gutter; residual "
            "tilt/curvature is Stage 03 (dewarp)'s job. single.png branch is "
            "still untested (no single-page fixture in the testset).",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8"
    )
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 02 — gutter split")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--per-page-source", choices=list(PS.MODES), default=None,
                    help="override per_page_source.mode: 'ocr' lets each page "
                         "come from a different full-spread frame (costs a "
                         "dewarp + Tesseract pass per candidate per side). "
                         "Default comes from config.yaml (off).")
    ap.add_argument("--debug", action="store_true",
                    help="also dump column profile CSV")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.per_page_source is not None:
        cfg = {**cfg, "per_page_source": {**(cfg.get("per_page_source") or {}),
                                          "mode": args.per_page_source}}
    result = run(args.page_dir, cfg, debug=args.debug)
    names = ", ".join(
        p.name if p.source == "01_fuse/anchor.png"
        else f"{p.name}<-{Path(p.source).name}" for p in result.pages)
    if result.gutter_x is not None and result.method == "pinch":
        print(f"{args.page_dir}: gutter x={result.gutter_x} via PINCH "
              f"(depth={result.pinch_depth}, pinch_corrob="
              f"{result.pinch_corroborated}, agreeing="
              f"{','.join(result.corroborated_by) or 'NONE'}; "
              f"ink ratio={result.ratio}) -> {names}")
    elif result.gutter_x is not None:
        print(f"{args.page_dir}: gutter x={result.gutter_x} via INK "
              f"(ratio={result.ratio}, agreeing="
              f"{','.join(result.corroborated_by) or 'NONE'}) -> {names}")
    else:
        pinch_say = (str(result.pinch_depth) if result.pinch_applicable
                     else "n/a (cue cannot run here)")
        print(f"{args.page_dir}: no gutter (ink ratio={result.ratio}, "
              f"pinch depth={pinch_say}) -> {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
