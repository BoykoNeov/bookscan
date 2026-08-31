"""Panorama Phase 0 - is the leftover displacement a TARGET problem?

``docs/plans/panorama-and-next-steps.md`` section 1. Pasting close-ups into an
enlarged spread was measured and refused (RESULTS 2026-08-29): the text came out
doubled, because a homography is a plane-to-plane map and a photographed page is
a cylinder seen off-axis. The plan's premise is a reorder - **flatten first,
stitch second**. This measures whether registering onto flattened pixels removes
the displacement, and it does so on the whole population instead of one close-up.

Two things about the earlier run shape this one, and both were found by reading
it rather than by re-running it:

  * ``temp/stitch2/superres.py`` registered onto the **anchor** and *already*
    applied ``figure_hires._mesh_refine``. So "add the local-bend correction" is
    not the open question; the TARGET is.
  * its published 6.5 px / 59 px / 5.3 px / 45 px come from **one** close-up.
    They are context. Every arm here is compared against arm A, on the same
    population, with the same matcher and the same acceptance rule.

Six placements, one matcher (SIFT), one acceptance rule (inliers >= 20 and
masked NCC >= 0.45), scale recorded but never gated on::

    A  raw close-up      -> anchor            homography
    B  raw close-up      -> anchor            homography + mesh
    C  raw close-up      -> dewarped page     homography
    D  raw close-up      -> dewarped page     homography + mesh
    E  UVDoc-flattened   -> dewarped page     homography
    F  UVDoc-flattened   -> dewarped page     homography + mesh

and, behind ``--control``, the floor the whole apparatus cannot read below::

    Cc the TARGET's own pixels, resampled into the source frame -> C's arm
    Dc the same, through D's arm

A/B are the failed route on the full population. C/D flatten the target. E/F are
the plan's actual premise - flatten BOTH - and they are in scope only because a
probe showed UVDoc flattens a borderless close-up in 0.2-0.5 s. Without E/F a
failure would say nothing about the premise, and in this repo a refusal becomes a
do-not-re-attempt line.

``figure_hires.candidates()`` is deliberately NOT reused for the registration:
its gate stack is figure-tuned (``min_scale`` 1.15, ``min_piece``, ``min_ncc``
0.60) and would admit a different subset per arm, which is exactly what a
cross-arm comparison cannot survive.

The gate is pre-registered in ``docs/data/panorama_phase0_prereg_20260831.md``
and is not to be moved after the fact: **median residual under 2 px AND
neighbour-tile disagreement under 5 px**, at anchor-equivalent scale, on the
non-sofa population.

Usage::

    python -m tools.panorama_phase0 [--job jobs/<id>] [--pages page_013 ...]
                                    [--out docs/data/panorama_phase0.json]
                                    [--no-uvdoc] [--control]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH          # noqa: E402
from pipeline import stage03_dewarp as S3        # noqa: E402

DEFAULT_JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
# The spreads photographed on a pale sofa. Their flattened pages are
# geometrically wrong for an unrelated, already-recorded reason (CLAUDE.md), so
# they are tagged and reported apart rather than silently averaged in.
SOFA_PAGES = {"page_001", "page_002", "page_003", "page_004"}

DS = 0.5                 # detect scale, as in the run this replicates
RATIO = 0.75
RANSAC_PX = 4.0
MIN_INLIERS = 20
MIN_NCC = 0.45
TILE = 128               # the tile size the earlier row reports
MIN_RESP = 0.05          # tile admission, identical to _mesh_refine's
MIN_VAR = 25.0
MIN_FOOTPRINT = 256      # a bbox smaller than two tiles cannot be measured
ARMS = ("A", "B", "B0", "C", "D", "E", "F", "Cc", "Dc")


# --------------------------------------------------------------------------
# registration - ONE function for every arm
# --------------------------------------------------------------------------

def _sift():
    if not hasattr(_sift, "_i"):
        _sift._i = cv2.SIFT_create(nfeatures=6000)
    return _sift._i


def _flann():
    if not hasattr(_flann, "_i"):
        _flann._i = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5),
                                          dict(checks=64))
    return _flann._i


def feats(img: np.ndarray):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=DS, fy=DS, interpolation=cv2.INTER_AREA)
    return _sift().detectAndCompute(g, None)


def register(src_kd, dst_kd):
    """H mapping SOURCE pixels -> TARGET pixels, plus the inlier pairs.

    Returned points are full-resolution, so a sub-window refit can reuse them.
    """
    kc, dc = src_kd
    ka, da = dst_kd
    if dc is None or da is None or len(kc) < 4 or len(ka) < 4:
        return None
    knn = _flann().knnMatch(dc, da, k=2)
    good = [m for m, n in (q for q in knn if len(q) == 2)
            if m.distance < RATIO * n.distance]
    if len(good) < 8:
        return None
    src = np.float32([kc[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([ka[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
    if H is None:
        return None
    S = np.diag([DS, DS, 1.0])
    Hf = np.linalg.inv(S) @ H @ S
    if not FH._sane(Hf):
        return None
    keep = mask.ravel().astype(bool)
    return {"H": Hf, "inliers": int(keep.sum()), "good": len(good),
            "src_pts": (src.reshape(-1, 2)[keep] / DS).astype(np.float32),
            "dst_pts": (dst.reshape(-1, 2)[keep] / DS).astype(np.float32)}


def place(img: np.ndarray, H: np.ndarray, shape):
    h, w = shape
    warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_CUBIC)
    m = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), H, (w, h),
                            flags=cv2.INTER_NEAREST)
    return warped, m


def footprint(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    if (x1 - x0) < MIN_FOOTPRINT or (y1 - y0) < MIN_FOOTPRINT:
        return None
    return x0, y0, x1, y1


# --------------------------------------------------------------------------
# the statistic
# --------------------------------------------------------------------------

def tile_field(base: np.ndarray, warped: np.ndarray, mask: np.ndarray,
               tile: int = TILE, off: int = 0):
    """Per-tile leftover displacement, on _mesh_refine's own admission rule.

    Returns (grid of complex displacements, NaN where a tile abstained; the
    number of tiles that were CANDIDATES, so coverage can be reported).
    """
    h, w = base.shape[:2]
    g1 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
    ny, nx = (h - off) // tile, (w - off) // tile
    if ny < 1 or nx < 1:
        return None, 0
    win = cv2.createHanningWindow((tile, tile), cv2.CV_32F)
    d = np.full((ny, nx), complex(np.nan, np.nan), np.complex64)
    cand = 0
    for i in range(ny):
        for j in range(nx):
            y0, x0 = off + i * tile, off + j * tile
            m = mask[y0:y0 + tile, x0:x0 + tile]
            if float((m > 0).mean()) < 0.9:
                continue
            a = g1[y0:y0 + tile, x0:x0 + tile]
            b = g2[y0:y0 + tile, x0:x0 + tile]
            if a.std() < MIN_VAR or b.std() < MIN_VAR:
                continue
            cand += 1
            (sx, sy), r = cv2.phaseCorrelate(a * win, b * win)
            if r < MIN_RESP:
                continue
            d[i, j] = complex(sx, sy)
    return d, cand


def stats_from_field(d, cand: int):
    """Residual and neighbour disagreement, plus the tile-answer coverage that
    says how much of a field the numbers rest on. A residual read off a handful
    of answering tiles is a global translation wearing a mesh's clothes."""
    if d is None:
        return None
    ok = np.isfinite(d.real) & np.isfinite(d.imag)
    n = int(ok.sum())
    if n < 4:
        return {"tiles": n, "candidates": cand, "coverage": None,
                "resid_med": None, "resid_p95": None, "resid_max": None,
                "neigh_med": None, "neigh_p95": None}
    mag = np.abs(d[ok])
    diffs = []
    ny, nx = d.shape
    for i in range(ny):
        for j in range(nx):
            if not ok[i, j]:
                continue
            for di, dj in ((0, 1), (1, 0)):
                a, b = i + di, j + dj
                if a < ny and b < nx and ok[a, b]:
                    diffs.append(abs(d[i, j] - d[a, b]))
    return {
        "tiles": n, "candidates": cand,
        "coverage": round(n / cand, 3) if cand else None,
        "resid_med": round(float(np.median(mag)), 2),
        "resid_p95": round(float(np.percentile(mag, 95)), 2),
        "resid_max": round(float(mag.max()), 2),
        "neigh_med": (round(float(np.median(diffs)), 2) if diffs else None),
        "neigh_p95": (round(float(np.percentile(diffs, 95)), 2) if diffs else None),
    }


def flow_stats(base: np.ndarray, warped: np.ndarray, mask: np.ndarray) -> dict:
    """The SAME leftover displacement, estimated by dense optical flow.

    The tile statistic is phase correlation, and so is ``_mesh_refine``.
    Measuring a correction with the estimator that produced it is not evidence -
    and here it is not even a finer-grained version of it: a footprint runs about
    1200-1700 px, so the correction's own 12x12 grid lands at 100-186 px tiles,
    the same scale as the 128 px measurement grid. Reading the grid half a tile
    across does not help, because an offset grid at the same pitch sits inside
    the same smooth field. So the corrected arms are read primarily off THIS
    number, which comes from a different estimator.

    Measurement only - it never rejects a placement.
    """
    m = cv2.erode(mask, np.ones((15, 15), np.uint8))
    g1 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    # Blank paper has no displacement to report and would drag every percentile
    # towards zero, so only textured pixels vote - the same reason _mesh_refine
    # drops a flat tile rather than trusting the zero it would answer.
    f = g1.astype(np.float32)
    mean = cv2.boxFilter(f, -1, (15, 15))
    var = cv2.boxFilter(f * f, -1, (15, 15)) - mean * mean
    ok = (m > 0) & (var > MIN_VAR * MIN_VAR)
    if int(ok.sum()) < 5000:
        return {"flow_med": None, "flow_p95": None, "flow_px": 0}
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fl = dis.calc(g1, g2, None)
    mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)[ok]
    return {"flow_med": round(float(np.median(mag)), 2),
            "flow_p95": round(float(np.percentile(mag, 95)), 2),
            "flow_px": int(ok.sum())}


def measure(base: np.ndarray, warped: np.ndarray, mask: np.ndarray) -> dict:
    """The statistic, at the tile grid and again at a half-tile offset.

    Measuring a phase-correlation correction with phase correlation is circular
    at the correction's OWN grid, so the tiles are much finer than
    ``_mesh_refine``'s 12x12 and the grid is also read half a tile across.
    """
    d0, c0 = tile_field(base, warped, mask, TILE, 0)
    s = stats_from_field(d0, c0) or {}
    d1, c1 = tile_field(base, warped, mask, TILE, TILE // 2)
    s1 = stats_from_field(d1, c1) or {}
    s["resid_med_off"] = s1.get("resid_med")
    s["neigh_med_off"] = s1.get("neigh_med")
    s.update(flow_stats(base, warped, mask))
    return s


# --------------------------------------------------------------------------
# the diagnostic: residual as a function of footprint size
# --------------------------------------------------------------------------

def window_refit(img, base, dst_pts, src_pts, box, levels=(1, 2, 4)) -> dict:
    """Re-fit the SAME correspondences over sub-windows of the footprint.

    ``figure_hires`` already places a raw source on a flattened target well over a
    figure-sized footprint. If the residual only crosses the bar below full
    frame, the answer is not "the route is dead" but "register whole-frame for
    the prior, then re-fit per window" - a much smaller build, and the search
    prior the per-block experiment died without.
    """
    x0, y0, x1, y1 = box
    out = {}
    for L in levels:
        ws, hs = (x1 - x0) / L, (y1 - y0) / L
        meds, windows = [], 0
        for i in range(L):
            for j in range(L):
                wx0, wy0 = int(x0 + j * ws), int(y0 + i * hs)
                wx1, wy1 = int(x0 + (j + 1) * ws), int(y0 + (i + 1) * hs)
                if (wx1 - wx0) < MIN_FOOTPRINT or (wy1 - wy0) < MIN_FOOTPRINT:
                    continue
                sel = ((dst_pts[:, 0] >= wx0) & (dst_pts[:, 0] < wx1) &
                       (dst_pts[:, 1] >= wy0) & (dst_pts[:, 1] < wy1))
                if int(sel.sum()) < 10:
                    continue
                Hw, _ = cv2.findHomography(src_pts[sel].reshape(-1, 1, 2),
                                           dst_pts[sel].reshape(-1, 1, 2),
                                           cv2.RANSAC, RANSAC_PX)
                if Hw is None or not FH._sane(Hw):
                    continue
                T = np.array([[1, 0, -wx0], [0, 1, -wy0], [0, 0, 1]], np.float64)
                ww, wh = wx1 - wx0, wy1 - wy0
                wimg, wmask = place(img, T @ Hw, (wh, ww))
                sub = base[wy0:wy1, wx0:wx1]
                d, c = tile_field(sub, wimg, wmask, TILE, 0)
                st = stats_from_field(d, c)
                if st and st.get("resid_med") is not None:
                    meds.append(st["resid_med"])
                    windows += 1
        out["L%d" % L] = {"windows": windows,
                          "resid_med": (round(float(np.median(meds)), 2)
                                        if meds else None)}
    return out


# --------------------------------------------------------------------------
# per page
# --------------------------------------------------------------------------

def word_height(page_dir: Path) -> dict:
    """Median Stage 05 word height per dewarped subpage - the text-sized unit, so
    a residual is not only a pixel count on a scale nobody can picture."""
    f = page_dir / "05_ocr" / "ocr.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for p in d.get("pages", []):
        hs = [w["bbox"]["h"] for b in p.get("blocks", [])
              for w in b.get("words", [])
              if w.get("text", "").strip() and w["bbox"]["h"] > 4]
        if hs:
            out[p["name"]] = float(np.median(hs))
    return out


def arm(img, base, H, params, mesh=None):
    """Place, optionally bend, measure over the footprint.

    ``mesh`` is None (homography alone), ``"footprint"`` - estimate the
    correction over the source's own footprint, which is what ``figure_hires``
    does, because there the base IS the crop - or ``"base"``, estimate it over
    the whole target, which is what the failed run did. Which of those the
    earlier result rests on is a question about that run, so it is answered by
    measurement here rather than by counting tiles on paper.
    """
    warped, m = place(img, H, base.shape[:2])
    box = footprint(m)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if mesh == "base":
        got = FH._mesh_refine(warped, m, base, params)
        if got is None:
            return {"mesh_applied": False, "mesh_scope": "base",
                    "box": [x0, y0, x1, y1], "resid_med": None}
        warped, m = got
    b = base[y0:y1, x0:x1]
    w = warped[y0:y1, x0:x1]
    mm = m[y0:y1, x0:x1]
    ncc = FH._ncc(b, w, cv2.erode(mm, np.ones((15, 15), np.uint8)))
    if mesh == "footprint":
        got = FH._mesh_refine(w, mm, b, params)
        if got is None:
            return {"mesh_applied": False, "mesh_scope": "footprint",
                    "ncc": round(float(ncc), 3),
                    "box": [x0, y0, x1, y1], "resid_med": None}
        w, mm = got
    st = measure(b, w, mm)
    st["ncc"] = round(float(ncc), 3)
    st["mesh_applied"] = True if mesh else None
    st["mesh_scope"] = mesh
    st["box"] = [x0, y0, x1, y1]
    # The correction's own grid, recorded so it can always be read against the
    # 128 px measurement grid instead of "much finer" being taken on trust.
    tiles = int(params["mesh_tiles"])
    if mesh == "footprint":
        st["mesh_tile_px"] = [(y1 - y0) // tiles, (x1 - x0) // tiles]
    elif mesh == "base":
        st["mesh_tile_px"] = [base.shape[0] // tiles, base.shape[1] // tiles]
    # A close-up straddling the gutter matches ONE dewarped subpage and lands as
    # a sliver, whose correction grid is a different regime. Tag it rather than
    # let two mechanisms average together.
    st["degenerate"] = bool(min(x1 - x0, y1 - y0) < 700
                            or max(x1 - x0, y1 - y0) > 3.0 * min(x1 - x0, y1 - y0))
    return st


def control_source(base, H, shape):
    """The target's OWN pixels, resampled backwards into the source's frame.

    Fed through the identical arm, the only displacement left is the one the
    machinery invents: interpolation, the mesh's own smoothing, and the floor of
    whatever estimator reads it. This repo has been here before - the close-up
    sharpness gate compared photographs against a bar that the anchor's own
    pixels scored 0.506 against, so nothing could ever pass and the number was
    measuring the warp. A pass at 1.4-1.7 px against a 2.0 px bar is close enough
    to that trap to have to be ruled out rather than argued about.

    It is a PESSIMISTIC bound: the synthetic source is interpolated twice where a
    real close-up is interpolated once, so the floor it reports is at least as
    high as the true one. Which is the useful direction - a measurement clearly
    below it is clearly real.
    """
    Hi = np.linalg.inv(H)
    return cv2.warpPerspective(base, Hi, (shape[1], shape[0]),
                               flags=cv2.INTER_LINEAR)


def run_page(page_dir: Path, params, uv, control: bool = False) -> list:
    name = page_dir.name
    fj = json.loads((page_dir / "01_fuse/fuse.json").read_text(encoding="utf-8"))
    ij = json.loads((page_dir / "00_ingest/ingest.json").read_text(encoding="utf-8"))
    full = set(fj.get("fullspread_frames", []))
    closeups = [f["name"] for f in ij.get("frames", []) if f["name"] not in full]
    if not closeups:
        return []
    anchor = cv2.imread(str(page_dir / "01_fuse/anchor.png"), cv2.IMREAD_COLOR)
    if anchor is None:
        return []
    pages = {}
    for sub in ("left.png", "right.png", "single.png"):
        p = page_dir / "03_dewarp" / sub
        if p.exists():
            im = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if im is not None:
                pages[sub] = im
    if not pages:
        return []
    xh = word_height(page_dir)
    kd_anchor = feats(anchor)
    kd_pages = {k: feats(v) for k, v in pages.items()}

    rows = []
    for fname in closeups:
        img = cv2.imread(str(page_dir / "00_ingest" / fname), cv2.IMREAD_COLOR)
        if img is None:
            # figure_hires skips a failed decode silently; here it is loud.
            rows.append({"page": name, "frame": fname, "error": "decode_failed",
                         "sofa": name in SOFA_PAGES})
            continue
        row = {"page": name, "frame": fname, "sofa": name in SOFA_PAGES,
               "size": [img.shape[1], img.shape[0]], "arms": {}}
        kd_raw = feats(img)

        # --- A/B : raw -> anchor -------------------------------------------
        scale_a = None
        reg = register(kd_raw, kd_anchor)
        if reg and reg["inliers"] >= MIN_INLIERS:
            st = arm(img, anchor, reg["H"], params)
            if st and st.get("ncc", 0.0) >= MIN_NCC:
                scale_a = FH.local_scale(reg["H"], img.shape[1] / 2.0,
                                         img.shape[0] / 2.0)
                st["inliers"] = reg["inliers"]
                st["scale_vs_anchor"] = round(1.0 / max(1e-6, scale_a), 3)
                row["scale_vs_anchor"] = st["scale_vs_anchor"]
                st["window"] = window_refit(img, anchor, reg["dst_pts"],
                                            reg["src_pts"], st["box"])
                row["arms"]["A"] = st
                row["arms"]["B"] = arm(img, anchor, reg["H"], params, "footprint")
                row["arms"]["B0"] = arm(img, anchor, reg["H"], params, "base")

        # --- C/D : raw -> dewarped page ------------------------------------
        best = None
        for sub, im in pages.items():
            r = register(kd_raw, kd_pages[sub])
            if not r or r["inliers"] < MIN_INLIERS:
                continue
            st = arm(img, im, r["H"], params)
            if not st or st.get("ncc", 0.0) < MIN_NCC:
                continue
            if best is None or r["inliers"] > best[0]["inliers"]:
                best = (r, st, sub, im)
        k_page = None
        if best is not None:
            r, st, sub, im = best
            sc = FH.local_scale(r["H"], img.shape[1] / 2.0, img.shape[0] / 2.0)
            if scale_a:
                k_page = sc / scale_a          # dewarped px per anchor px
            st["subpage"] = sub
            st["inliers"] = r["inliers"]
            st["k_page"] = round(k_page, 3) if k_page else None
            st["x_height"] = round(xh[sub], 1) if sub in xh else None
            st["window"] = window_refit(img, im, r["dst_pts"], r["src_pts"],
                                        st["box"])
            row["arms"]["C"] = st
            std = arm(img, im, r["H"], params, "footprint")
            if std:
                std["subpage"] = sub
                std["k_page"] = st["k_page"]
                std["x_height"] = st["x_height"]
                row["arms"]["D"] = std
            if control:
                syn = control_source(im, r["H"], img.shape)
                for a, mesh in (("Cc", None), ("Dc", "footprint")):
                    stc = arm(syn, im, r["H"], params, mesh)
                    if stc:
                        stc["subpage"] = sub
                        stc["k_page"] = st["k_page"]
                        stc["x_height"] = st["x_height"]
                        row["arms"][a] = stc

        # --- E/F : UVDoc-flattened close-up -> dewarped page ---------------
        if uv is not None:
            flat = None
            try:
                flat, _ = uv.dewarp(img)
            except Exception as e:                        # noqa: BLE001
                row["uvdoc_error"] = "%s: %s" % (type(e).__name__, e)
            if flat is not None:
                kd_flat = feats(flat)
                bestf = None
                for sub, im in pages.items():
                    r = register(kd_flat, kd_pages[sub])
                    if not r or r["inliers"] < MIN_INLIERS:
                        continue
                    st = arm(flat, im, r["H"], params)
                    if not st or st.get("ncc", 0.0) < MIN_NCC:
                        continue
                    if bestf is None or r["inliers"] > bestf[0]["inliers"]:
                        bestf = (r, st, sub, im)
                if bestf is not None:
                    r, st, sub, im = bestf
                    st["subpage"] = sub
                    st["inliers"] = r["inliers"]
                    st["k_page"] = round(k_page, 3) if k_page else None
                    st["x_height"] = round(xh[sub], 1) if sub in xh else None
                    st["window"] = window_refit(flat, im, r["dst_pts"],
                                                r["src_pts"], st["box"])
                    row["arms"]["E"] = st
                    stf = arm(flat, im, r["H"], params, "footprint")
                    if stf:
                        stf["subpage"] = sub
                        stf["k_page"] = st["k_page"]
                        stf["x_height"] = st["x_height"]
                        row["arms"]["F"] = stf

        rows.append(row)
        got = "".join(a for a in ARMS if row["arms"].get(a))
        detail = " ".join(
            "%s:%s" % (a, row["arms"][a].get("resid_med"))
            for a in ARMS
            if row["arms"].get(a) and row["arms"][a].get("resid_med") is not None)
        print("  %s/%-14s arms=%-6s %s" % (name, fname, got or "-", detail),
              flush=True)
    return rows


# --------------------------------------------------------------------------

def summarise(rows: list) -> dict:
    """Per-arm population medians, sofa spreads apart, and the intersection
    population - the only set on which two arms are strictly comparable."""
    def med(sel, a, key):
        v = [r["arms"][a][key] for r in sel
             if r["arms"].get(a) and r["arms"][a].get(key) is not None]
        return round(float(np.median(v)), 3) if v else None

    out = {}
    have = [r for r in rows if "arms" in r]
    groups = (("all", have),
              ("non_sofa", [r for r in have if not r["sofa"]]),
              ("sofa", [r for r in have if r["sofa"]]),
              # The arms register different subsets, so a per-arm median is a
              # median of a different population. This group is the only one on
              # which two arms are strictly comparable.
              ("intersection_ACE_non_sofa",
               [r for r in have if not r["sofa"]
                and all(r["arms"].get(a) for a in ("A", "C", "E"))]))
    for tag, sel in groups:
        d = {"closeups": len(sel)}
        for a in ARMS:
            n = sum(1 for r in sel if r["arms"].get(a))
            if not n:
                continue
            e = {"registered": n}
            for key in ("resid_med", "resid_p95", "resid_max", "neigh_med",
                        "neigh_p95", "coverage", "ncc", "resid_med_off",
                        "neigh_med_off", "tiles", "flow_med",
                        "flow_p95"):
                e[key] = med(sel, a, key)
            for L in ("L1", "L2", "L4"):
                v = [r["arms"][a]["window"][L]["resid_med"] for r in sel
                     if r["arms"].get(a) and r["arms"][a].get("window")
                     and r["arms"][a]["window"].get(L, {}).get("resid_med")
                     is not None]
                e["window_" + L] = ([round(float(np.median(v)), 2), len(v)]
                                    if v else None)
            e["degenerate"] = sum(1 for r in sel if r["arms"].get(a)
                                  and r["arms"][a].get("degenerate"))
            # The two tightest close-ups were the two worst placements on the
            # first spread measured. If that holds, a capture loop that frames
            # tighter to win resolution makes PLACEMENT worse - which is
            # decision-relevant for the plan's Phase 3 whatever the gate says.
            for lo, hi, zt in ((0.0, 1.4, "zoom_lt_1.4"),
                               (1.4, 1.8, "zoom_1.4_1.8"),
                               (1.8, 99.0, "zoom_ge_1.8")):
                v = [r["arms"][a]["flow_med"] for r in sel
                     if r["arms"].get(a)
                     and r["arms"][a].get("flow_med") is not None
                     and lo <= float(r.get("scale_vs_anchor") or 0.0) < hi]
                e[zt] = [round(float(np.median(v)), 2), len(v)] if v else None
            d[a] = e
        # C-F measure in dewarped-page pixels; the gate is in anchor pixels.
        for a in ("C", "D", "E", "F", "Cc", "Dc"):
            if a not in d:
                continue
            ks = [r["arms"][a]["k_page"] for r in sel
                  if r["arms"].get(a) and r["arms"][a].get("k_page")]
            k = float(np.median(ks)) if ks else None
            d[a]["k_page_med"] = round(k, 3) if k else None
            if k:
                for key in ("resid_med", "neigh_med", "flow_med", "flow_p95",
                            "resid_p95"):
                    if d[a].get(key) is not None:
                        d[a][key + "_anchor_px"] = round(d[a][key] / k, 2)
            xs = [r["arms"][a]["x_height"] for r in sel
                  if r["arms"].get(a) and r["arms"][a].get("x_height")]
            if xs and d[a].get("resid_med") is not None:
                d[a]["resid_med_xheights"] = round(
                    d[a]["resid_med"] / float(np.median(xs)), 3)
        d["intersection_ACE"] = sum(
            1 for r in sel if all(r["arms"].get(a) for a in ("A", "C", "E")))
        out[tag] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Panorama Phase 0 measurement")
    ap.add_argument("--job", default=str(DEFAULT_JOB))
    ap.add_argument("--pages", nargs="*", default=None)
    ap.add_argument("--out", default=str(REPO / "docs/data/panorama_phase0.json"))
    ap.add_argument("--no-uvdoc", action="store_true",
                    help="skip arms E/F (the flatten-both arms)")
    ap.add_argument("--control", action="store_true",
                    help="also run Cc/Dc: the TARGET's own pixels through the "
                         "identical arm, i.e. the floor the statistic cannot "
                         "read below")
    args = ap.parse_args()

    job = Path(args.job)
    pages = sorted(p for p in job.glob("page_*") if p.is_dir())
    if args.pages:
        want = set(args.pages)
        pages = [p for p in pages if p.name in want]
    params = FH.resolve_params({})
    uv = None
    if not args.no_uvdoc:
        cfg = S3.load_config(REPO / "config.yaml")
        warn = []
        uv = S3.make_dewarper("uvdoc", cfg, warn)
        print("UVDoc:", "loaded" if uv else "UNAVAILABLE %s" % warn, flush=True)

    t0 = time.time()
    rows = []
    try:
        for pd in pages:
            print("%s ..." % pd.name, flush=True)
            rows += run_page(pd, params, uv, args.control)
    finally:
        if uv is not None:
            uv.close()

    summary = summarise(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"job": str(job), "closeups": len(rows), "secs": round(time.time() - t0),
         "gate": {"resid_med_lt": 2.0, "neigh_med_lt": 5.0,
                  "prereg": "docs/data/panorama_phase0_prereg_20260831.md"},
         "summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print("\n%d close-ups, %.0fs -> %s" % (len(rows), time.time() - t0, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
