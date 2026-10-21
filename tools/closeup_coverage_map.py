"""Where did each close-up land on the whole-spread shot? A coverage map.

Registers every non-anchor frame of a page onto Stage 01's anchor (SIFT, ratio
0.75, RANSAC 3 px, seed 1 — one draw, so this is a MAP, not a gate), prints each
frame's inliers, linear scale and centre, the overlap between consecutive
frames, how many were placed, and the union's share of the anchor frame; draws
the footprints, numbered, on a quarter-size copy of the anchor.

A frame counts as placed only with >= 30 inliers, a scale in [1, 8] and a
convex footprint: on a text page a close-up can "register" to the wrong line
with a few inliers and a degenerate homography (scale in the thousands).

First used 2026-10-21 on the owner's S23 sweeps (STATUS 2026-10-21): 12 of 19
and 13 of 17 placed; the misses cluster on dense text, where every line looks
alike to a matcher working against the softer anchor.

Usage:
    python -m tools.closeup_coverage_map <page_dir> <out.png>
"""

import json, os, sys

import cv2
import numpy as np

P = sys.argv[1]
ing = os.path.join(P, "00_ingest")
man = json.load(open(os.path.join(ing, "ingest.json")))
fuse = json.load(open(os.path.join(P, "01_fuse", "fuse.json")))
anchor = fuse["anchor_source"]
A = cv2.imread(os.path.join(ing, anchor), cv2.IMREAD_GRAYSCALE)
sift = cv2.SIFT_create(8000)
ka, da = sift.detectAndCompute(A, None)
bm = cv2.BFMatcher()
polys = []
for f in man["frames"]:
    if f["name"] == anchor: continue
    C = cv2.imread(os.path.join(ing, f["name"]), cv2.IMREAD_GRAYSCALE)
    kc, dc = sift.detectAndCompute(C, None)
    good = [p[0] for p in bm.knnMatch(dc, da, k=2) if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 8: print(f["source"], "no registration", len(good)); polys.append(None); continue
    src = np.float32([kc[g.queryIdx].pt for g in good]); dst = np.float32([ka[g.trainIdx].pt for g in good])
    cv2.setRNGSeed(1); H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    h, w = C.shape
    foot = cv2.perspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2), H)
    area = cv2.contourArea(foot)
    scale = np.sqrt(w*h/area) if area > 0 else float('inf')
    ok = int(inl.sum()) >= 30 and 1.0 <= scale <= 8.0 and cv2.isContourConvex(foot.astype(np.int32))
    print(f"{f['source']}: inliers {int(inl.sum())}  scale {scale:.2f}  centre {foot.reshape(-1,2).mean(0).round()}  {'OK' if ok else 'NOT PLACED'}")
    polys.append(foot.astype(np.int32) if ok else None)
mask = np.zeros_like(A); masks = []
for p in polys:
    m = np.zeros_like(A)
    if p is not None: cv2.fillPoly(m, [p], 255)
    masks.append(m > 0); mask |= m
for i in range(1, len(masks)):
    a, b = masks[i-1], masks[i]
    if a.any() and b.any(): print(f"overlap frame {i}->{i+1}: {(a&b).sum()/min(a.sum(), b.sum()):.0%}")
print(f"placed {sum(p is not None for p in polys)} of {len(polys)}"); print(f"union of close-ups covers {mask.astype(bool).sum()/A.size:.0%} of the anchor frame")
vis = cv2.cvtColor(A, cv2.COLOR_GRAY2BGR)
for i, p in enumerate(polys):
    if p is not None:
        cv2.polylines(vis, [p], True, (0, 0, 255), 12); cv2.putText(vis, str(i+1), tuple(p.reshape(-1,2).mean(0).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 6, (0,0,255), 14)
cv2.imwrite(sys.argv[2], cv2.resize(vis, None, fx=0.25, fy=0.25))
