"""Cut the pixels each reader will read, once, before any reader runs.

For every block in the census population:
  crops/<page>__b<id>__page.jpg     the shipped flattened page crop (the bbox
                                    exactly, as the document shows it today)
  crops/<page>__b<id>__pagepad.jpg  the same page, padded 4 % per side: what the
                                    page-arm reader is shown
  crops/<page>__b<id>__close.jpg    the best close-up (the one holding >= 90 % of
                                    the block at >= 1.15x with the HIGHEST scale),
                                    resampled onto the block's own outline (padded
                                    4 % per side) at that close-up's scale, through
                                    a homography fitted LOCALLY: only page features
                                    within a window around the block (the block
                                    grown by max(300 px, half its size) per side),
                                    RANSAC seed 0. One plane per block, so the
                                    page's curvature inside the block is not undone.

First version cut the axis-aligned box of the projection through ONE homography
for the whole page. On page_017__left #2 that box took in the gutter and the next
panel's text: a single plane fitted to a curved page extrapolates badly near the
spine. Seen before any reader ran; replaced by the local fit.

Second correction, also before any reader ran: some local fits are degenerate
(page_004__left #1/#17/#18, page_017__left #7, page_018__left #9 came out as
smears or blank paper). Every cut is now CHECKED: resized to 64 px on
its longest side (as is the page crop -- a layout check, not a stroke check),
its normalised cross-correlation with the padded page crop must be
>= 0.60 (figure_hires' per-source min_ncc), with >= 12 RANSAC inliers (the
likeness check, not the count, is the guard). Fits are tried with SIFT on
half-size copies first, then full size (full size alone did WORSE: repeated
letter shapes defeat the ratio test). Fits are
tried in a fixed order -- half-size SIFT then full-size, each with the window
grown 300 px, 600 px, then the whole page --
and the first that passes is used. If none passes, the block has no usable
close-up and is read from the page only.

The choice rule and the padding are fixed here, before any reading
(textmerge-style pre-registration: ``../panelread_prereg_20261021.md``).

Run:  python -X utf8 docs/data/panelread_20261021/extract_crops.py
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from coverage_census import JOB
from coverage_census_v2 import MIN_CLOSEUP_SCALE

HERE = Path(__file__).parent
CROPS = HERE / "crops"
PAD = 0.04
RATIO = 0.75


MIN_NCC = 0.60
MIN_INLIERS = 12


def features(img, scale):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if scale != 1.0:
        g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    kp, desc = cv2.SIFT_create().detectAndCompute(g, None)
    pts = np.float32([k.pt for k in kp]) / scale if kp else np.zeros((0, 2), np.float32)
    return pts, desc


def homography(page_f, frame_f, win):
    pp, pd = page_f
    fp, fd = frame_f
    if win is not None:
        x0, y0, x1, y1 = win
        keep = (pp[:, 0] >= x0) & (pp[:, 0] < x1) & (pp[:, 1] >= y0) & (pp[:, 1] < y1)
        pp, pd = pp[keep], pd[keep]
    if pd is None or len(pd) < 10:
        return None, 0
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(pd, fd, k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < RATIO * b.distance]
    if len(good) < MIN_INLIERS:
        return None, 0
    cv2.setRNGSeed(0)
    H, mask = cv2.findHomography(pp[[g.queryIdx for g in good]],
                                 fp[[g.trainIdx for g in good]], cv2.RANSAC, 6.0)
    return H, (int(mask.sum()) if mask is not None else 0)


COARSE = 64   # longest side for the likeness check


def ncc(a, b) -> float:
    """Likeness at COARSE resolution: is this the same region? At full size a
    2 px shift of thin letter strokes scores near zero on a correct cut."""
    f = COARSE / max(b.shape[:2])
    size = (max(4, int(round(b.shape[1] * f))), max(4, int(round(b.shape[0] * f))))
    a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32).ravel()
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32).ravel()
    a -= a.mean(); b -= b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def main() -> None:
    CROPS.mkdir(exist_ok=True)
    rows = json.loads((HERE / "coverage_census_v2.json").read_text(encoding="utf-8"))
    doc = json.loads((JOB / "document.json").read_text(encoding="utf-8"))
    pages = {p["page_id"]: p for p in doc["pages"]}
    manifest = []
    for r in rows:
        p = pages[r["page"]]
        bb = r["bbox"]
        page = cv2.imread(str(JOB / p["image_asset"]), cv2.IMREAD_COLOR)
        stem = f"{r['page']}__b{r['block']:03d}"
        crop = page[bb["y"]:bb["y"] + bb["h"], bb["x"]:bb["x"] + bb["w"]]
        cv2.imwrite(str(CROPS / f"{stem}__page.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        # What the page-arm READER sees: the same 4 % margin the close-up arm
        # gets, so both readers are shown the same window.
        ph_, pw_ = page.shape[:2]
        mx, my = int(round(PAD * bb["w"])), int(round(PAD * bb["h"]))
        padded = page[max(0, bb["y"] - my):min(ph_, bb["y"] + bb["h"] + my),
                      max(0, bb["x"] - mx):min(pw_, bb["x"] + bb["w"] + mx)]
        cv2.imwrite(str(CROPS / f"{stem}__pagepad.jpg"), padded, [cv2.IMWRITE_JPEG_QUALITY, 92])
        entry = {"stem": stem, "page": r["page"], "block": r["block"], "type": r["type"],
                 "page_crop": f"crops/{stem}__page.jpg", "page_crop_size": [bb["w"], bb["h"]],
                 "page_read": f"crops/{stem}__pagepad.jpg",
                 "close_crop": None}
        ok = [s for s in r["sources"] if not s["is_anchor"] and s["coverage"] >= 0.90
              and s["scale"] >= MIN_CLOSEUP_SCALE]
        if ok:
            best = max(ok, key=lambda s: s["scale"])
            frame = cv2.imread(str(JOB / p["source_spread"] / "00_ingest" / best["frame"]),
                               cv2.IMREAD_COLOR)
            ph, pw = page.shape[:2]
            feats = {sc: (features(page, sc), features(frame, sc)) for sc in (0.5, 1.0)}
            s_ = float(best["scale"])
            px, py = PAD * bb["w"], PAD * bb["h"]
            ox, oy = bb["x"] - px, bb["y"] - py
            ow, oh = int(round((bb["w"] + 2 * px) * s_)), int(round((bb["h"] + 2 * py) * s_))
            # output pixel (u, v) -> page (ox + u/s, oy + v/s) -> frame via H
            S = np.array([[1 / s_, 0, ox], [0, 1 / s_, oy], [0, 0, 1]])
            tried = []
            for sc, grow in [(sc, g) for sc in (0.5, 1.0) for g in (300, 600, None)]:
                page_f, frame_f = feats[sc]
                if grow is None:
                    win = None
                else:
                    gx, gy = max(grow, bb["w"] // 2), max(grow, bb["h"] // 2)
                    win = (max(0, bb["x"] - gx), max(0, bb["y"] - gy),
                           min(pw, bb["x"] + bb["w"] + gx), min(ph, bb["y"] + bb["h"] + gy))
                H, inl = homography(page_f, frame_f, win)
                if H is None or inl < MIN_INLIERS:
                    tried.append({"detect": sc, "window": grow, "inliers": inl, "ncc": None})
                    continue
                out = cv2.warpPerspective(frame, H @ S, (ow, oh),
                                          flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                                          borderMode=cv2.BORDER_CONSTANT,
                                          borderValue=(255, 255, 255))
                back = cv2.resize(out, (padded.shape[1], padded.shape[0]),
                                  interpolation=cv2.INTER_AREA)
                v = ncc(back, padded)
                tried.append({"detect": sc, "window": grow, "inliers": inl, "ncc": round(v, 3)})
                if v >= MIN_NCC:
                    cv2.imwrite(str(CROPS / f"{stem}__close.jpg"), out,
                                [cv2.IMWRITE_JPEG_QUALITY, 92])
                    entry.update(close_crop=f"crops/{stem}__close.jpg",
                                 close_frame=best["frame"], close_scale=best["scale"],
                                 close_coverage=best["coverage"], close_size=[ow, oh],
                                 fit_window=grow, fit_detect=sc)
                    break
            entry["close_fit_tries"] = tried
        manifest.append(entry)
        print(stem, entry["close_crop"] or "-", entry.get("close_scale", ""), flush=True)
    (HERE / "crops_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
