"""Re-cut a FIGURE from the sharpest photograph that actually contains it.

The problem this solves, and why it is not "stitching"
------------------------------------------------------
The operator shoots a spread, then several close-ups of parts of it. Stage 01's
job was to fold those close-ups back into ``anchor.png``. That cannot help a
picture, and the reason is arithmetic rather than tuning: a close-up must be
warped DOWN into the anchor's coordinate frame to be blended, so the extra pixels
it was taken for are resampled away before anything is written. Measured on this
repo's own 25-spread book (RESULTS 2026-08-29): the located close-ups sit at a
median 1.30x the anchor's linear resolution over their own footprint, and after
that warp they read FEWER high-confidence words than the anchor did (0.77x).

So this module never warps a close-up down. It goes the other way: it takes the
figure we want, finds every capture that holds a piece of it, and rebuilds the
figure AT THOSE CAPTURES' SCALE. The page keeps its own resolution; only the
figure asset gets bigger. Stitching still happens — it just happens in the
picture's own frame, where it pays, instead of in the anchor's, where it cannot.

Why matching a figure works where matching a page failed
--------------------------------------------------------
Stage 01 registers a whole close-up against a whole spread, and a spread is
mostly text - repetitive, self-similar, and a rich source of matches that are
individually plausible and collectively contradictory. Over the same book that
path located 49 of 317 close-ups; the median attempt found 39 good matches and
5 RANSAC inliers, which is not a weak homography, it is noise.

A figure is the opposite kind of image: a photograph or a drawing, locally
unique, with no repeating motif for a descriptor to confuse. Matching the figure
CROP against a candidate frame is therefore a much easier problem than the one
Stage 01 is solving, and measurably so - on ``page_023``'s cover photograph six
frames register here that Stage 01 never located, the best at 91 inliers and
0.77 photometric agreement.

Acceptance
----------
Per FRAME, asking whether it may contribute at all:

  * ``min_inliers``   - did RANSAC find a consensus (a precondition, no more);
  * ``min_ncc``       - THE acceptance test. Inliers come out of the matcher, so
                        they cannot referee the matcher (Stage 01's docstring
                        learned this the expensive way). Pull the candidate back
                        into the crop's own frame and ask whether the ink agrees.
                        Measured separation on this book is wide: accepted
                        sources 0.63-0.90, rejected ones -0.25 to +0.37;
  * ``min_scale``     - is it worth having? Below ~1.15x linear a source only
                        trades one resampling for another;
  * ``min_piece``     - does it hold enough of the figure to be worth pasting.

Then once, of the WHOLE SET, the question that decides the asset:

  * ``min_coverage``  - between them, do the sources cover the picture? Whatever
                        they miss is filled from the page crop, feathered, so a
                        shortfall costs detail on a band rather than correctness -
                        but past about a tenth the result stops being a picture
                        with a soft edge and starts being a visible patchwork.

Failing every gate is the normal outcome and means "keep the page crop", which is
exactly what the pipeline did before this module existed. Nothing here can make
a figure worse than it was: the page crop is always still there, and the upgrade
is written as a SEPARATE asset that Stage 08 falls back from if the block's bbox
no longer matches the one the asset was cut for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DEFAULTS = {
    "enabled": True,
    # SIFT, not ORB. This is a different question from Stage 01's - there the
    # engine is fixed by CLAUDE.md and swapping it is the owner's call, here the
    # module is new and the choice is made once, on the evidence: ORB's binary
    # descriptors are weak on the smooth tonal gradients a photograph is made of,
    # which is the only content this module ever looks at.
    "detect_scale": 0.5,        # detect on a half-size copy, rescale H back
    "ratio_test": 0.75,
    "ransac_reproj_px": 4.0,
    "min_inliers": 20,
    # How much of the figure the source has to contain. Not 1.0, because a
    # hand-held close-up is framed by eye and the best one on this book's cover
    # photograph holds 94 % of it at 1.64x — refusing that would throw away the
    # upgrade to avoid a 6 % border. ``render`` fills whatever the source misses
    # from the page crop, feathered, so a shortfall costs detail on that band and
    # nothing else. Below ~0.9 the band stops being a border and starts being a
    # visibly two-sharpness picture.
    "min_coverage": 0.90,
    # Smallest share of the figure a single frame must hold to JOIN the composite.
    # Low on purpose: a frame that sees a third of the picture at 2.6x is a third
    # of the picture at 2.6x. ``min_coverage`` is then asked of the union, which is
    # the question that actually matters.
    "min_piece": 0.10,
    # A source only joins the composite if it brings this much of the figure that
    # nothing already in it has. Painting a source that adds no new pixels cannot
    # add detail, only its own alignment error, and the sources with least to add
    # are exactly the ones judged over the smallest footprint.
    "min_new_coverage": 0.03,
    # Feather width, in PAGE-CROP pixels: it is multiplied by the canvas scale so
    # a join is the same width on the printed page whether the asset came out at
    # 1.2x or 3.6x. As a constant it silently narrowed as the canvas grew.
    "feather_px": 24.0,
    # Bend each source onto the flattened page before laying it down. A source is
    # a photograph of a CURVED page and the crop it must fill was flattened by
    # Stage 03; one homography is a plane-to-plane map and cannot express the
    # difference, so a globally well-fitted source still sits a few pixels out in
    # places. Measured on the owner's via-ferrata topo map: without this the
    # sharpest-first composite tore the word "Arzalpenturm" in half at a seam, and
    # agreement with the page crop was 0.833; with it the tear is gone and
    # agreement is 0.871. Set false to fall back to homography-only placement.
    "mesh_align": True,
    "mesh_tiles": 12,
    "mesh_max_frac": 0.02,      # a correction larger than this is an error
    "mesh_min_resp": 0.05,
    "mesh_min_var": 25.0,
    # The finished asset, compared COARSELY against the page crop it replaces.
    # A BACKSTOP, not the main defence: min_ncc and the greedy source choice are
    # what keep a wrong source out, and this catches a composite that went wrong
    # anyway. 0.80 because on this book the five upgrades confirmed correct by eye
    # scored 0.825-0.922 and the two rejected as wrong scored 0.623 and 0.759 —
    # n = 6 with one labelled negative, which is thin, so it is deliberately set
    # to catch a gross failure rather than to discriminate a marginal one.
    # See _result_agreement for why this cannot be a near-identity bar.
    "min_result_ncc": 0.80,
    # Per-source photometric agreement. 0.60, not the 0.50 an earlier single-source
    # measurement suggested: with partial-coverage sources admitted, agreement is
    # computed over each source's OWN footprint, and every mis-registered source
    # observed on this book scored 0.51-0.52 while every correct one scored 0.63 or
    # better. The gate sits in that gap, on the correct side of both.
    "min_ncc": 0.60,
    "refine_scale": 1.0,        # ECC works on <=400 px; 1.0 = that cap, <1 is coarser
    "refine_iters": 60,
    "min_scale": 1.15,          # linear; below this resampling is the only effect
    "max_scale": 4.0,           # a "match" claiming 60x is a degenerate homography
    "min_figure_px": 20000,     # smaller than this and there is nothing to see
    "max_output_px": 40_000_000,  # cap one asset (guards a bad scale estimate)
}


@dataclass(frozen=True)
class HiResSource:
    """Provenance for one upgraded figure - every gate's input, not just the
    verdict, so a decision is diagnosable from ``document.meta.json`` alone."""

    frame: str
    scale: float          # linear px(source)/px(page crop)
    inliers: int
    good_matches: int
    ncc: float
    coverage: float

    def as_dict(self) -> dict:
        return {"frame": self.frame, "scale": round(self.scale, 3),
                "inliers": self.inliers, "good_matches": self.good_matches,
                "ncc": round(self.ncc, 3), "coverage": round(self.coverage, 3)}


class FrameIndex:
    """SIFT keypoints for one candidate frame, computed once per page.

    Detection dominates the cost (a 6 Mpx frame is ~2 s at full size), and a page
    has one frame set but many figures, so the index is built per FRAME and
    queried per FIGURE rather than the other way round.
    """

    def __init__(self, name: str, path: Path, params: dict) -> None:
        self.name = name
        self.path = path
        self._params = params
        self._img: np.ndarray | None = None
        self.kp = None
        self.desc = None
        self._built = False

    @property
    def image(self) -> np.ndarray | None:
        if self._img is None:
            self._img = cv2.imread(str(self.path), cv2.IMREAD_COLOR)
        return self._img

    def build(self) -> bool:
        if self._built:
            return self.desc is not None
        self._built = True
        img = self.image
        if img is None:
            return False
        s = float(self._params["detect_scale"])
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if s != 1.0:
            g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        self.kp, self.desc = _sift().detectAndCompute(g, None)
        return self.desc is not None

    def release(self) -> None:
        """Drop the pixels but keep the descriptors - a page's frames are 6-12 Mpx
        each and holding twelve of them decoded is 400 MB for no reason."""
        self._img = None


_SIFT = None


def _sift():
    global _SIFT
    if _SIFT is None:
        if not hasattr(cv2, "SIFT_create"):
            raise RuntimeError(
                "figure_hires needs cv2.SIFT_create (opencv-python >= 4.4). "
                "Set figure_hires.enabled: false in config.yaml to skip it.")
        _SIFT = cv2.SIFT_create()
    return _SIFT


def resolve_params(cfg: dict) -> dict:
    p = dict(DEFAULTS)
    p.update((cfg or {}).get("figure_hires", {}) or {})
    return p


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------


def local_scale(H: np.ndarray, x: float, y: float) -> float:
    """Linear px(destination)/px(source) of ``H`` at the source point (x, y).

    Read off the local Jacobian rather than from a corner-to-corner ratio: a
    close-up shot at an angle is genuinely higher resolution at its near edge
    than at its far one, and averaging the two would understate the good half and
    overstate the bad."""
    pts = np.float32([[[x, y]], [[x + 1.0, y]], [[x, y + 1.0]]])
    q = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    a, b = q[1] - q[0], q[2] - q[0]
    return float(math.sqrt(abs(a[0] * b[1] - a[1] * b[0])))


def _sane(H: np.ndarray | None) -> bool:
    if H is None or not np.all(np.isfinite(H)):
        return False
    det = float(np.linalg.det(H[:2, :2]))
    return det > 0 and 0.02 < abs(det) < 50.0


def _coverage(H: np.ndarray, w: int, h: int, fw: int, fh: int) -> float:
    """Fraction of the crop's area that lands inside the candidate frame."""
    gx, gy = np.meshgrid(np.linspace(0, w - 1, 16), np.linspace(0, h - 1, 16))
    pts = np.float32(np.stack([gx.ravel(), gy.ravel()], 1)).reshape(-1, 1, 2)
    q = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    return float(((q[:, 0] >= 0) & (q[:, 0] < fw)
                  & (q[:, 1] >= 0) & (q[:, 1] < fh)).mean())


def _ncc(a: np.ndarray, b: np.ndarray, mask: np.ndarray,
         min_px: int = 5000) -> float:
    m = mask > 0
    if int(m.sum()) < min_px:
        return 0.0
    x = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)[m]
    y = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)[m]
    x -= x.mean()
    y -= y.mean()
    d = float(np.sqrt(float((x * x).sum()) * float((y * y).sum())))
    return float((x * y).sum() / d) if d > 0 else 0.0


# --------------------------------------------------------------------------
# The search
# --------------------------------------------------------------------------


def _match(crop: np.ndarray, idx: FrameIndex, params: dict):
    """(H, inliers, good) mapping CROP pixels -> FRAME pixels, or None."""
    if not idx.build():
        return None
    s = float(params["detect_scale"])
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if s != 1.0:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    kc, dc = _sift().detectAndCompute(g, None)
    if dc is None or len(kc) < 4:
        return None
    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(dc, idx.desc, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2)
            if m.distance < float(params["ratio_test"]) * n.distance]
    if len(good) < 8:
        return None
    src = np.float32([kc[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([idx.kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC,
                                 float(params["ransac_reproj_px"]))
    if H is None:
        return None
    if s != 1.0:                       # both sides were detected downscaled
        S = np.diag([s, s, 1.0])
        H = np.linalg.inv(S) @ H @ S
    H = _refine(crop, idx.image, H, params)
    return H, (int(mask.sum()) if mask is not None else 0), len(good)


def _refine(crop: np.ndarray, img: np.ndarray | None, H: np.ndarray,
            params: dict) -> np.ndarray:
    """Nudge a RANSAC fit onto the actual pixels, with ECC.

    RANSAC fits the matches; the matches are sparse, and this particular pairing
    has a systematic error no set of matches can remove: the crop comes from the
    DEWARPED page and the source is the raw photograph, so the two differ by
    however much Stage 03 unbent the paper. A homography cannot express that, and
    the residual shows up as the whole picture sitting a few per cent off — which
    on a figure asset means the delivered picture is framed differently from the
    box the document says it fills.

    ECC minimises photometric error over ALL the pixels instead of the matched
    ones, at low resolution where the un-modellable local part is invisible, so it
    takes out the global share of that error. Failure to converge is normal and
    returns the input fit unchanged: this is a refinement, never a gate.
    """
    if img is None or not _sane(H):
        return H
    h, w = crop.shape[:2]
    r = float(params["refine_scale"]) * min(1.0, 400.0 / max(h, w))
    cw, ch = max(32, int(w * r)), max(32, int(h * r))
    R = np.diag([cw / w, ch / h, 1.0]).astype(np.float64)
    Hi = np.linalg.inv(H)
    tpl = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_AREA)
    g1 = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY).astype(np.float32)
    back = cv2.warpPerspective(img, R @ Hi, (cw, ch))
    g2 = cv2.cvtColor(back, cv2.COLOR_BGR2GRAY).astype(np.float32)
    W = np.eye(3, dtype=np.float32)
    try:
        cv2.findTransformECC(
            g1, g2, W, cv2.MOTION_HOMOGRAPHY,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
             int(params["refine_iters"]), 1e-5), None, 5)
    except cv2.error:
        return H
    Wf = W.astype(np.float64)
    Ri = np.linalg.inv(R)
    # Both compositions of the correction are tried and SCORED rather than
    # reasoned about: OpenCV's ECC convention (does the warp map template into
    # input, or input into template?) is exactly the kind of detail that is easy
    # to get backwards and impossible to notice, because the wrong one still
    # produces a plausible picture — of the wrong place. Whichever agrees better
    # with the crop wins, and the unrefined fit is in the contest too, so a
    # refinement that helps nothing changes nothing.
    best, best_score = H, _agree_at(crop, img, H, cw, ch)
    for cand_inv in (Hi @ Ri @ Wf @ R, Hi @ Ri @ np.linalg.inv(Wf) @ R):
        try:
            cand = np.linalg.inv(cand_inv)
        except np.linalg.LinAlgError:
            continue
        if not _sane(cand):
            continue
        score = _agree_at(crop, img, cand, cw, ch)
        if score > best_score:
            best, best_score = cand, score
    return best


def _agree_at(crop: np.ndarray, img: np.ndarray, H: np.ndarray,
              cw: int, ch: int) -> float:
    """Photometric agreement of ``img`` placed by ``H``, judged at (cw, ch)."""
    h, w = crop.shape[:2]
    R = np.diag([cw / w, ch / h, 1.0]).astype(np.float64)
    try:
        M = R @ np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return -1.0
    back = cv2.warpPerspective(img, M, (cw, ch))
    m = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), M, (cw, ch),
                            flags=cv2.INTER_NEAREST)
    tpl = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_AREA)
    return _ncc(tpl, back, m, min_px=64)


@dataclass
class Candidate:
    """One frame that has been proven to contain part of this figure."""

    H: np.ndarray          # crop pixels -> frame pixels
    frame: FrameIndex
    src: HiResSource


def candidates(crop: np.ndarray, frames: list[FrameIndex], params: dict
               ) -> list[Candidate]:
    """Every frame that holds a usable piece of ``crop``.

    ``crop`` is the figure exactly as the document shows it today (cut from the
    dewarped page), so a hit is guaranteed to be the same picture - the search is
    anchored on the deliverable, not on an intermediate.

    Coverage is NOT gated here. A frame that holds a third of the picture at 2.6x
    is evidence, not a failure; whether a third is enough is a question about the
    whole set, and ``compose`` asks it once, of the union.
    """
    h, w = crop.shape[:2]
    if h * w < int(params["min_figure_px"]):
        return []
    out: list[Candidate] = []
    for idx in frames:
        got = _match(crop, idx, params)
        if got is None:
            continue
        H, inliers, good = got
        if inliers < int(params["min_inliers"]) or not _sane(H):
            continue
        img = idx.image
        if img is None:
            continue
        fh, fw = img.shape[:2]
        cov = _coverage(H, w, h, fw, fh)
        if cov < float(params["min_piece"]):
            continue
        scale = local_scale(H, w / 2.0, h / 2.0)
        if not (float(params["min_scale"]) <= scale <= float(params["max_scale"])):
            continue
        # THE gate: pull the candidate back into the crop's own frame and ask
        # whether it is the same picture. Independent of the matcher on purpose.
        Hi = np.linalg.inv(H)
        back = cv2.warpPerspective(img, Hi, (w, h))
        bmask = cv2.warpPerspective(np.full((fh, fw), 255, np.uint8), Hi, (w, h))
        if _ncc(crop, back, bmask) < float(params["min_ncc"]):
            continue
        out.append(Candidate(H, idx,
                             HiResSource(idx.name, scale, inliers, good,
                                         _ncc(crop, back, bmask), cov)))
    return out


def best_source(crop: np.ndarray, frames: list[FrameIndex], params: dict
                ) -> tuple[np.ndarray, FrameIndex, HiResSource] | None:
    """The single highest-resolution frame that contains enough of ``crop``.

    Kept as the single-source answer (and what the tests pin); ``compose`` is the
    one the pipeline calls, because on real captures the picture is often spread
    across two frames and neither one alone clears the coverage bar."""
    ok = [c for c in candidates(crop, frames, params)
          if c.src.coverage >= float(params["min_coverage"])]
    if not ok:
        return None
    best = max(ok, key=lambda c: c.src.scale)
    return best.H, best.frame, best.src


def _mesh_refine(warped: np.ndarray, mask: np.ndarray, base: np.ndarray,
                 params: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """Bend a placed source onto the flattened page, locally.

    ``_refine`` already took out the global share of the dewarp-vs-homography
    disagreement, at low resolution, as a homography. What is left is not a
    homography at all: it is however much Stage 03 bent the paper, varying across
    the picture. Estimate it as a smooth displacement FIELD - phase-correlate the
    placed source against the (blurry, but geometrically correct) page crop tile
    by tile, keep only tiles that answer confidently and move plausibly,
    interpolate the rest, remap.

    Deliberately unable to do much: a tile that disagrees loudly, or one on blank
    paper with nothing to correlate, is DROPPED rather than trusted, and the field
    is smoothed, because page curvature is smooth and a spike in the field is an
    error rather than a finding. Returns None when too few tiles answered, which
    means "place it by the homography alone".
    """
    h, w = base.shape[:2]
    tiles = int(params["mesh_tiles"])
    th, tw = h // tiles, w // tiles
    if th < 24 or tw < 24:
        return None
    maxd = float(params["mesh_max_frac"]) * max(h, w)
    min_var = float(params["mesh_min_var"])
    min_resp = float(params["mesh_min_resp"])
    g1 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
    dx = np.zeros((tiles, tiles), np.float32)
    dy = np.zeros((tiles, tiles), np.float32)
    got = np.zeros((tiles, tiles), bool)
    win = cv2.createHanningWindow((tw, th), cv2.CV_32F)
    for i in range(tiles):
        for j in range(tiles):
            y0, x0 = i * th, j * tw
            a, b = g1[y0:y0 + th, x0:x0 + tw], g2[y0:y0 + th, x0:x0 + tw]
            if a.shape != (th, tw) or b.shape != (th, tw):
                continue
            # The tile has to be mostly source pixels, or the correlation is
            # partly the base against itself and answers zero by construction.
            if float((mask[y0:y0 + th, x0:x0 + tw] > 0).mean()) < 0.5:
                continue
            if float(a.std()) < min_var or float(b.std()) < min_var:
                continue
            (sx, sy), resp = cv2.phaseCorrelate(a * win, b * win)
            if resp < min_resp or abs(sx) > maxd or abs(sy) > maxd:
                continue
            dx[i, j], dy[i, j], got[i, j] = sx, sy, True
    if int(got.sum()) < 6:
        return None
    miss = (~got).astype(np.uint8)
    fx = cv2.GaussianBlur(cv2.inpaint(dx, miss, 3, cv2.INPAINT_TELEA), (3, 3), 0)
    fy = cv2.GaussianBlur(cv2.inpaint(dy, miss, 3, cv2.INPAINT_TELEA), (3, 3), 0)
    FX = cv2.resize(fx, (w, h), interpolation=cv2.INTER_CUBIC)
    FY = cv2.resize(fy, (w, h), interpolation=cv2.INTER_CUBIC)
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = cv2.remap(warped, gx + FX, gy + FY, cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE)
    nm = cv2.remap(mask, gx + FX, gy + FY, cv2.INTER_NEAREST,
                   borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return out, nm


def _harmonise(patch: np.ndarray, base: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Put ``patch`` on the same exposure as ``base`` over the pixels they share.

    Close-ups of the same spread differ in white balance and brightness by a lot
    (they are shot closer, often with the operator's own shadow moving), and a
    composite that ignores that is a visible patchwork whatever the geometry does.
    Per-channel mean and spread only: a stronger colour transfer would start
    editing the picture, which is not this module's business.
    """
    out = patch.astype(np.float32)
    sel = m > 0
    if int(sel.sum()) < 500:
        return patch
    for ch in range(out.shape[2]):
        a, b = out[..., ch][sel], base[..., ch].astype(np.float32)[sel]
        sa, sb = float(a.std()), float(b.std())
        if sa < 1e-3:
            continue
        g = float(np.clip(sb / sa, 0.5, 2.0))
        out[..., ch] = (out[..., ch] - a.mean()) * g + b.mean()
    return np.clip(out, 0, 255).astype(np.uint8)


def compose(crop: np.ndarray, cands: list[Candidate], params: dict
            ) -> tuple[np.ndarray, list[HiResSource]] | None:
    """Build the figure from every capture that holds a piece of it.

    This is the stitching that Stage 01 could not do, moved to the only frame
    where it pays: the picture's own. Stage 01 has to warp a close-up DOWN into
    the anchor, so a close-up's extra pixels are gone before the blend; here the
    canvas is the figure at the SOURCES' scale, so each one contributes what it
    was shot for and the page crop only fills what nothing covers.

    Returns None for "keep the page crop" — no candidates, nothing sharper than
    the page, or the union still not covering enough of the picture to be worth a
    second asset.
    """
    if not cands:
        return None
    h, w = crop.shape[:2]
    # Canvas scale comes from the SHARPEST source, not the widest one.
    #
    # It used to come from the candidate that saw the most of the figure, on the
    # argument that a frame holding a fifth of the picture must not decide the
    # resolution of the other four fifths. That argument confuses two things. The
    # canvas is only a container: a region is as good as the source that lands on
    # it, and building the container smaller cannot improve the four fifths - it
    # can only throw away the fifth. Measured on the owner's via-ferrata topo map,
    # eighteen frames match it, one holds a fifth of it at 3.16x, and the old rule
    # delivered the whole picture at 1.86x, resampling that fifth DOWN. The cost of
    # the new rule is bytes (a weaker region is stored upsampled); the cost of the
    # old one was detail, which is the thing this module exists for.
    scale = max(c.src.scale for c in cands)
    scale = float(np.clip(scale, float(params["min_scale"]),
                          float(params["max_scale"])))
    scale = min(scale, float(np.sqrt(float(params["max_output_px"]) / float(w * h))))
    ow, oh = int(round(w * scale)), int(round(h * scale))
    if ow < 2 or oh < 2:
        return None
    S = np.diag([ow / w, oh / h, 1.0]).astype(np.float64)

    base = cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_CUBIC)
    out = base.copy()
    union = np.zeros((oh, ow), np.uint8)
    used: list[HiResSource] = []
    feather = max(1.0, float(params["feather_px"]) * scale)
    # SHARPEST FIRST, and each source paints only the pixels no better source has
    # already claimed. Two bugs are fixed by that one rule. Painting every
    # candidate over its whole footprint was the first: on page_023 ten frames all
    # repainted the same middle, so the last one applied won it with its own
    # alignment error. Ordering by coverage was the second: the WIDEST source won
    # every overlap, which is precisely the source with least resolution to offer.
    # A source that adds no new pixels adds only its error, so it is skipped.
    for c in sorted(cands, key=lambda c: (-c.src.scale, -c.src.coverage)):
        img = c.frame.image
        if img is None:
            continue
        M = S @ np.linalg.inv(c.H)
        m = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), M,
                                (ow, oh), flags=cv2.INTER_NEAREST)
        fresh = float(((m > 0) & (union == 0)).mean())
        if used and fresh < float(params["min_new_coverage"]):
            continue
        if int((m > 0).sum()) < 500:
            continue
        warped = cv2.warpPerspective(img, M, (ow, oh), flags=cv2.INTER_CUBIC)
        if params.get("mesh_align", True):
            got = _mesh_refine(warped, m, base, params)
            if got is not None:
                warped, m = got
        warped = _harmonise(warped, out, m)
        paint = ((m > 0) & (union == 0)).astype(np.uint8)
        dist = cv2.distanceTransform(paint, cv2.DIST_L2, 5)
        alpha = np.clip(dist / feather, 0.0, 1.0)[..., None]
        out = (out * (1.0 - alpha) + warped * alpha).astype(np.uint8)
        union = np.maximum(union, m)
        used.append(c.src)
    if not used or float((union > 0).mean()) < float(params["min_coverage"]):
        return None
    # THE RESULT GATE. Everything above judges evidence; this judges the delivered
    # picture, once, as a whole. A correct upgrade is the same rectangle with more
    # pixels in it, so shrinking it back to the page crop's size must reproduce the
    # page crop almost exactly. The per-source agreement cannot stand in for this:
    # it is measured over each source's OWN footprint, so a source holding a fifth
    # of a rock face can agree with that fifth at 0.6 and still be pasted in the
    # wrong place, which is exactly how page_018 produced a confident picture of
    # the wrong part of the page.
    if _result_agreement(crop, out, union) < float(params["min_result_ncc"]):
        return None
    return out, used


def _result_agreement(crop: np.ndarray, out: np.ndarray,
                      union: np.ndarray | None = None) -> float:
    """Does the finished asset show the same thing as the page crop?

    Asked COARSELY, at a long side of ~128 px, and that is the whole design of the
    statistic. At full resolution the comparison cannot work: the page crop comes
    from the DEWARPED page and the sources are raw frames placed by a homography,
    so a flattened curve leaves a few pixels of local disagreement everywhere, and
    normalized correlation on fine photographic texture is punishing about that.
    Measured on this book, correct composites scored 0.70-0.79 at full resolution
    and so did a composite showing the wrong part of the page - the number simply
    does not separate there.

    Shrunk far enough that local warp error disappears, what is left is the
    question worth asking: is this the same picture, in the same place, the same
    way round? A composite assembled from a mis-registered source fails that badly
    (it is a different piece of the page), while a correct one is near-identical.
    """
    h, w = crop.shape[:2]
    s = 128.0 / max(h, w)
    dim = (max(8, int(w * s)), max(8, int(h * s)))
    a = cv2.resize(crop, dim, interpolation=cv2.INTER_AREA)
    b = cv2.resize(out, dim, interpolation=cv2.INTER_AREA)
    if union is None:
        m = np.full(dim[::-1], 255, np.uint8)
    else:
        m = (cv2.resize(union, dim, interpolation=cv2.INTER_AREA) > 127
             ).astype(np.uint8) * 255
    return _ncc(a, b, m, min_px=64)


def render(crop: np.ndarray, source: FrameIndex, H: np.ndarray,
           scale: float, params: dict) -> np.ndarray | None:
    """The figure, re-cut from ``source`` at ``scale`` times the page crop.

    The output is the SAME picture in the SAME rectangle - geometry identical to
    the page crop, so nothing downstream has to know where the pixels came from -
    just sampled from a photograph that has more of them.
    """
    img = source.image
    if img is None:
        return None
    h, w = crop.shape[:2]
    ow, oh = int(round(w * scale)), int(round(h * scale))
    if ow * oh > int(params["max_output_px"]) or ow < 2 or oh < 2:
        return None
    # crop -> output is a pure scale; compose it with (crop -> frame)^-1 so the
    # frame is sampled ONCE, at the output resolution. Warping twice would spend
    # the resolution this module exists to keep.
    S = np.diag([ow / w, oh / h, 1.0]).astype(np.float64)
    M = S @ np.linalg.inv(H)
    out = cv2.warpPerspective(img, M, (ow, oh), flags=cv2.INTER_CUBIC)
    covered = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), M,
                                  (ow, oh), flags=cv2.INTER_NEAREST)
    if int((covered == 0).sum()) == 0:
        return out
    # The source misses a sliver of the figure (a close-up framed a hair tight).
    # Fill it from the page crop rather than refusing the whole upgrade or, worse,
    # emitting a picture with a black edge: the covered part is genuinely sharper
    # and the sliver is exactly what the document already showed. Feathered so the
    # join is not a visible line between two sharpnesses.
    base = cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_CUBIC)
    dist = cv2.distanceTransform((covered > 0).astype(np.uint8), cv2.DIST_L2, 5)
    alpha = np.clip(dist / float(params["feather_px"]), 0.0, 1.0)[..., None]
    return (base * (1.0 - alpha) + out * alpha).astype(np.uint8)
