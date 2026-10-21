"""Coverage census, second method: whole frame against whole page.

Why a second method. ``coverage_census.py`` searched each block's own crop with
``figure_hires.candidates`` and its CONTROL FAILED: the whole-spread photograph
holds every block, yet the search found it for only 17 of 28. Text panels are
small and repetitive, so a block crop gives SIFT too little to hold on to. Its
"no close-up" answers are therefore not evidence.

Here every capture is matched against the whole flattened page (thousands of
features instead of dozens), and the frame's outline is projected onto the page.
A block's coverage is the share of its box inside that outline; its scale is the
frame's pixels per page pixel at the block's centre. One homography cannot
describe a curved page exactly, so these are census numbers (is the block in the
shot, roughly how big), not a placement.

Not a single random draw: RANSAC runs under three seeds, and a frame counts as
placed only if all three draws clear ``MIN_INLIERS``; the coverage reported is
the smallest of the three.

CONTROL: the whole-spread photograph (``anchor_source``) must be placed over
every block. Every frame of this job predates the 2026-10-21 phone change, so
close-ups were shrunk on the phone to half their area.

Run:  python -X utf8 docs/data/panelread_20261021/coverage_census_v2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from coverage_census import JOB, population  # noqa: E402

OUT = Path(__file__).with_name("coverage_census_v2.json")
DETECT = 0.5          # SIFT on half-size copies, as figure_hires does
RATIO = 0.75
MIN_INLIERS = 40
SEEDS = (0, 1, 2)
# A frame "adds resolution" only past figure_hires' own floor (min_scale); below
# it the other whole-spread photographs would count as close-ups.
MIN_CLOSEUP_SCALE = 1.15

_sift = cv2.SIFT_create()


def features(img: np.ndarray):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=DETECT, fy=DETECT, interpolation=cv2.INTER_AREA)
    kp, desc = _sift.detectAndCompute(g, None)
    pts = np.float32([k.pt for k in kp]) / DETECT if kp else np.zeros((0, 2), np.float32)
    return pts, desc


def place(page_f, frame_f) -> list[np.ndarray] | None:
    """Homographies page -> frame, one per seed, or None if any draw is weak."""
    pp, pd = page_f
    fp, fd = frame_f
    if pd is None or fd is None or len(pd) < 10 or len(fd) < 10:
        return None
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(pd, fd, k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < RATIO * b.distance]
    if len(good) < MIN_INLIERS:
        return None
    src = pp[[g.queryIdx for g in good]]
    dst = fp[[g.trainIdx for g in good]]
    Hs = []
    for s in SEEDS:
        cv2.setRNGSeed(s)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        if H is None or int(mask.sum()) < MIN_INLIERS:
            return None
        Hs.append(H)
    return Hs


def coverage(H: np.ndarray, bb: dict, fw: int, fh: int) -> tuple[float, float]:
    """Share of the block inside the frame, and frame px per page px at its centre."""
    x0, y0, w, h = bb["x"], bb["y"], bb["w"], bb["h"]
    xs, ys = np.meshgrid(np.linspace(x0, x0 + w, 24), np.linspace(y0, y0 + h, 24))
    pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32).reshape(-1, 1, 2)
    q = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    inside = (q[:, 0] >= 0) & (q[:, 0] < fw) & (q[:, 1] >= 0) & (q[:, 1] < fh)
    cx, cy = x0 + w / 2, y0 + h / 2
    c = cv2.perspectiveTransform(np.float32([[[cx, cy]], [[cx + 1, cy]], [[cx, cy + 1]]]), H)
    c = c.reshape(-1, 2)
    d1, d2 = c[1] - c[0], c[2] - c[0]
    scale = float(np.sqrt(abs(d1[0] * d2[1] - d1[1] * d2[0])))
    return float(inside.mean()), scale


def main() -> None:
    doc = json.loads((JOB / "document.json").read_text(encoding="utf-8"))
    pop = population(doc)
    by_page: dict[str, list] = {}
    for p, b in pop:
        by_page.setdefault(p["page_id"], [p]).append(b)
    rows = []
    frame_cache: dict[str, dict] = {}
    for page_id, (p, *blocks) in by_page.items():
        spread = p["source_spread"]
        ing = json.loads((JOB / spread / "00_ingest" / "ingest.json").read_text(encoding="utf-8"))
        anchor = json.loads((JOB / spread / "01_fuse" / "fuse.json")
                            .read_text(encoding="utf-8"))["anchor_source"]
        if spread not in frame_cache:
            frame_cache.clear()
            frame_cache[spread] = {}
            for f in ing["frames"]:
                img = cv2.imread(str(JOB / spread / "00_ingest" / f["name"]), cv2.IMREAD_COLOR)
                frame_cache[spread][f["name"]] = (features(img), img.shape[1], img.shape[0])
        page = cv2.imread(str(JOB / p["image_asset"]), cv2.IMREAD_COLOR)
        page_f = features(page)
        placed = {}
        for name, (ff, fw, fh) in frame_cache[spread].items():
            Hs = place(page_f, ff)
            if Hs is not None:
                placed[name] = (Hs, fw, fh)
        for b in blocks:
            srcs = []
            for name, (Hs, fw, fh) in placed.items():
                covs = [coverage(H, b["bbox"], fw, fh) for H in Hs]
                cov = min(c for c, _ in covs)
                scale = float(np.median([s for _, s in covs]))
                if cov > 0:
                    srcs.append({"frame": name, "is_anchor": name == anchor,
                                 "coverage": round(cov, 3), "scale": round(scale, 3),
                                 "frame_size": [fw, fh]})
            srcs.sort(key=lambda s: -s["scale"])
            cl = [s for s in srcs if not s["is_anchor"]]
            whole = [s for s in cl if s["coverage"] >= 0.90
                     and s["scale"] >= MIN_CLOSEUP_SCALE]
            a = next((s for s in srcs if s["is_anchor"]), None)
            row = {"page": page_id, "block": b["id"], "type": b["type"],
                   "promoted": bool(b.get("type_promoted")), "bbox": b["bbox"],
                   "anchor": anchor, "anchor_coverage": a["coverage"] if a else 0.0,
                   "anchor_scale": a["scale"] if a else None,
                   "n_frames": len(ing["frames"]), "n_placed": len(placed),
                   "sources": srcs,
                   "best_whole_closeup_scale": max((s["scale"] for s in whole), default=None)}
            rows.append(row)
            print(f"{page_id:16s} #{b['id']:<3d} {b['type']:6s} anchor={row['anchor_coverage']:.2f}"
                  f"@{row['anchor_scale']} placed={len(placed)}/{len(ing['frames'])} "
                  + " ".join(f"{s['frame'][6:8]}:{s['coverage']:.2f}@{s['scale']:.2f}" for s in cl),
                  flush=True)
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    n = len(rows)
    ctrl = sum(1 for r in rows if r["anchor_coverage"] >= 0.99)
    part = sum(1 for r in rows if any(not s["is_anchor"] and s["scale"] >= MIN_CLOSEUP_SCALE
                                      for s in r["sources"]))
    whole = [r for r in rows if r["best_whole_closeup_scale"] is not None]
    print(f"\n{n} blocks. CONTROL anchor over the whole block: {ctrl}/{n}. "
          f"A close-up (>= {MIN_CLOSEUP_SCALE}x) touches the block: {part}. One holds >= 90 %: "
          f"{len(whole)} ({sum(1 for r in whole if r['type'] == 'table')} tables) "
          f"(scales {sorted(r['best_whole_closeup_scale'] for r in whole)})")


if __name__ == "__main__":
    main()
