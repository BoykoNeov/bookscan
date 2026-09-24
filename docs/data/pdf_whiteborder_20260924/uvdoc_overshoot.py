"""How far does UVDoc push an imported flat page past its own frame?

Registers each page's Stage 02 image (UVDoc's input) to its Stage 03 image
(output, same size) with SIFT + RANSAC homography, maps the input's four edges
into the output, and reports how far each edge lands OUTSIDE the output frame,
as a fraction of the page's width (left/right) or height (top/bottom).
Geometry only; no word counts. This fixes the border width before any outcome
is looked at.
"""
import json
from pathlib import Path

import cv2
import numpy as np

W = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")
rows = []
for page in sorted(W.glob("*/page_*")):
    name = json.loads((page / "02_split" / "split.json").read_text(encoding="utf-8"))["pages"][0]["name"]
    a = cv2.imread(str(page / "02_split" / name), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(page / "03_dewarp" / name), cv2.IMREAD_GRAYSCALE)
    h, w = a.shape
    s = 1600 / max(h, w)
    a2, b2 = cv2.resize(a, None, fx=s, fy=s), cv2.resize(b, None, fx=s, fy=s)
    sift = cv2.SIFT_create(6000)
    ka, da = sift.detectAndCompute(a2, None)
    kb, db = sift.detectAndCompute(b2, None)
    m = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [x for x, y in m if x.distance < 0.75 * y.distance]
    pa = np.float32([ka[g.queryIdx].pt for g in good]) / s
    pb = np.float32([kb[g.trainIdx].pt for g in good]) / s
    H, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    n_in = int(inl.sum())
    # sample each input edge densely, map it, take the worst point per side
    t = np.linspace(0, 1, 50)
    edges = {"left": np.c_[np.zeros_like(t), t * (h - 1)],
             "right": np.c_[np.full_like(t, w - 1), t * (h - 1)],
             "top": np.c_[t * (w - 1), np.zeros_like(t)],
             "bottom": np.c_[t * (w - 1), np.full_like(t, h - 1)]}
    over = {}
    for side, pts in edges.items():
        q = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), H).reshape(-1, 2)
        if side == "left":
            over[side] = max(0.0, -q[:, 0].min()) / w
        elif side == "right":
            over[side] = max(0.0, q[:, 0].max() - (w - 1)) / w
        elif side == "top":
            over[side] = max(0.0, -q[:, 1].min()) / h
        else:
            over[side] = max(0.0, q[:, 1].max() - (h - 1)) / h
    rows.append({"page": f"{page.parent.name}/{page.name}", "inliers": n_in,
                 **{k: round(v, 4) for k, v in over.items()}})
    print(f"{page.parent.name}/{page.name}: inliers {n_in:5d}  overshoot "
          + "  ".join(f"{k} {v:.2%}" for k, v in over.items()), flush=True)
mx = {k: max(r[k] for r in rows) for k in ("left", "right", "top", "bottom")}
print("max overshoot per side:", {k: f"{v:.2%}" for k, v in mx.items()})
Path(r"W:\temp\claude\pdf_textlayer\uvdoc_overshoot.json").write_text(json.dumps(rows, indent=1))
