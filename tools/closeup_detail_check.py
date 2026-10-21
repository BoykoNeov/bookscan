"""How much REAL detail does a close-up add over the whole-spread shot?

A close-up can carry more pixels per letter without carrying more detail: a
phone's digital zoom crops the sensor and interpolates. This asks the pixels,
not the file size.

1. Register the close-up onto the anchor with SIFT (Stage 01's ORB fails on
   close-ups shot near the page: 9 inliers where SIFT finds 140, 2026-10-21),
   seeded, three draws; report the linear scale (close-up pixels per anchor
   pixel). Draws that disagree mean the placement is not trustworthy.
2. Enlarge the anchor's matching region into the close-up's frame (bicubic) —
   what a pure digital zoom of the anchor would deliver — and compare
   variance-of-Laplacian over the shared area, eroded off the footprint edge.
   Ratio ~1 = the close-up is an enlargement; well above 1 = real detail.
3. The same at the anchor's scale (close-up shrunk onto the anchor), as a
   control: it should sit near 1, because the anchor's own detail is all that
   survives at the anchor's scale.

Two crops of the same patch go to ``--out`` for looking at. **They show detail,
not alignment** — to check alignment use a checkerboard (CLAUDE.md guardrail).
Variance-of-Laplacian also rewards the phone's sharpening halos and a printed
halftone screen, so read the crops with the number.

Measured 2026-10-21 on the owner's Galaxy S23, one coin-book spread each
(STATUS 2026-10-21; n = 1 scene, not pre-registered):

    3x CameraX zoom, from a distance   scale 3.27  detail ratio  1.52  control 1.03
    1x, phone moved close              scale 3.61  detail ratio 14.53  control 1.04

Nearly the same pixels per letter, ten times the detail: the 3x frame is an
interpolated crop. (A first scratch run read the 1x scale as 6.53 from the
homography at the image corner; the footprint gives 3.61.)

Both on the main lens (EXIF 5.4 mm, f/1.8): CameraX's 3x is a crop, the
telephoto is never used. The 1x close shot resolves the printed halftone dots.

Usage:
    python -m tools.closeup_detail_check jobs/<job>/<page>/ [--closeup frame_01.png]
        [--anchor frame_00.png] [--out W:\\temp\\claude\\detail]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def _scale(H: np.ndarray, shape: tuple[int, int]) -> float:
    """Close-up pixels per anchor pixel, linear, over the WHOLE close-up: the
    square root of (close-up area / its footprint's area on the anchor). Not
    ``det(H[:2, :2])`` — under perspective that is the scale at the image
    origin only: two runs on one close-up read 6.53 and 5.24 from it, where
    the footprint says 3.61 (2026-10-21)."""
    h, w = shape
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    foot = cv2.perspectiveTransform(corners, H)
    return float(np.sqrt((w * h) / max(cv2.contourArea(foot), 1e-6)))


def _register(g_close: np.ndarray, g_anchor: np.ndarray, seeds=(1, 2, 3)
              ) -> list[tuple[np.ndarray, int, float]]:
    """[(H close->anchor, inliers, close-up px per anchor px)] per seeded draw."""
    sift = cv2.SIFT_create(8000)
    kc, dc = sift.detectAndCompute(g_close, None)
    ka, da = sift.detectAndCompute(g_anchor, None)
    if dc is None or da is None:
        return []
    pairs = cv2.BFMatcher().knnMatch(dc, da, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 8:
        return []
    src = np.float32([kc[g.queryIdx].pt for g in good])
    dst = np.float32([ka[g.trainIdx].pt for g in good])
    out = []
    for seed in seeds:
        cv2.setRNGSeed(seed)
        H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None:
            continue
        out.append((H, int(inl.sum()), _scale(H, g_close.shape)))
    return out


def _lap_var(g: np.ndarray, mask: np.ndarray) -> float:
    return float(cv2.Laplacian(g, cv2.CV_64F)[mask].var())


def _footprint(shape_from: tuple[int, int], H: np.ndarray, size_to: tuple[int, int],
               erode: int) -> np.ndarray:
    m = cv2.warpPerspective(np.full(shape_from, 255, np.uint8), H, size_to) > 0
    return cv2.erode(m.astype(np.uint8), np.ones((erode, erode), np.uint8)) > 0


def check(page_dir: Path, closeup: str, anchor: str, out: Path | None) -> dict:
    ing = page_dir / "00_ingest"
    a = cv2.imread(str(ing / anchor), cv2.IMREAD_GRAYSCALE)
    c = cv2.imread(str(ing / closeup), cv2.IMREAD_GRAYSCALE)
    if a is None or c is None:
        raise SystemExit(f"cannot read {ing / anchor} or {ing / closeup}")
    draws = _register(c, a)
    if not draws:
        return {"registered": False}
    H = draws[0][0]
    (hc, wc), (ha, wa) = c.shape, a.shape

    enlarged = cv2.warpPerspective(a, np.linalg.inv(H), (wc, hc), flags=cv2.INTER_CUBIC)
    shared = _footprint(a.shape, np.linalg.inv(H), (wc, hc), 31)
    close_lv, enl_lv = _lap_var(c, shared), _lap_var(enlarged, shared)

    shrunk = cv2.warpPerspective(c, H, (wa, ha), flags=cv2.INTER_AREA)
    on_anchor = _footprint(c.shape, H, (wa, ha), 15)
    shr_lv, anc_lv = _lap_var(shrunk, on_anchor), _lap_var(a, on_anchor)

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        ys, xs = np.where(shared)
        cy, cx = int(np.median(ys)), int(np.median(xs))
        y0, x0 = max(cy - 300, 0), max(cx - 400, 0)
        cv2.imwrite(str(out / "closeup_crop.png"), c[y0:y0 + 600, x0:x0 + 800])
        cv2.imwrite(str(out / "anchor_enlarged_crop.png"), enlarged[y0:y0 + 600, x0:x0 + 800])

    return {
        "registered": True,
        "draws": [{"inliers": n, "scale": round(s, 3)} for _, n, s in draws],
        "sharpness_closeup": round(close_lv, 1),
        "sharpness_anchor_enlarged": round(enl_lv, 1),
        "detail_ratio": round(close_lv / enl_lv, 2) if enl_lv else None,
        "control_ratio_at_anchor_scale": round(shr_lv / anc_lv, 2) if anc_lv else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("page_dir", type=Path)
    ap.add_argument("--closeup", default="frame_01.png")
    ap.add_argument("--anchor", default="frame_00.png")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    r = check(args.page_dir, args.closeup, args.anchor, args.out)
    for k, v in r.items():
        print(f"{k}: {v}")
    return 0 if r.get("registered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
