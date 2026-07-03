"""Unit tests for pipeline.stage01_fuse.

Synthetic only — no photos. Covers frame partitioning (sharpest anchor + close-up
split), the ORB/homography stitch (a crop upscaled back onto its source must be
re-located), a non-match rejection, and the single-frame integration path that
the real testset exercises. Run with pytest, or directly:
    python -m pipeline.tests.test_stage01_fuse
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from pipeline import stage01_fuse as S


def _textured(h=600, w=800, seed=0) -> np.ndarray:
    """White canvas peppered with dark shapes → plenty of ORB corners."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 245, np.uint8)
    for _ in range(220):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        r = int(rng.integers(4, 18))
        color = tuple(int(c) for c in rng.integers(0, 90, 3))
        if rng.random() < 0.5:
            cv2.circle(img, (x, y), r, color, -1)
        else:
            cv2.rectangle(img, (x, y), (x + r, y + r), color, -1)
    return img


# --------------------------------------------------------------------------
# Partition
# --------------------------------------------------------------------------


def test_partition_single_frame():
    frames = [{"width": 4000, "height": 3000, "sharpness": 100.0}]
    base, full, close = S.partition_frames(frames, 0.70)
    assert base == 0 and full == [0] and close == []


def test_partition_burst_picks_sharpest():
    frames = [
        {"width": 4000, "height": 3000, "sharpness": 100.0},
        {"width": 4000, "height": 3000, "sharpness": 250.0},   # sharpest
        {"width": 4000, "height": 3000, "sharpness": 180.0},
    ]
    base, full, close = S.partition_frames(frames, 0.70)
    assert base == 1, "should anchor on the sharpest full-spread frame"
    assert full == [0, 1, 2] and close == []


def test_partition_separates_closeups():
    frames = [
        {"width": 4000, "height": 3000, "sharpness": 100.0},   # full spread
        {"width": 1200, "height": 900, "sharpness": 500.0},    # close-up (small)
    ]
    base, full, close = S.partition_frames(frames, 0.70)
    assert base == 0 and full == [0] and close == [1]


# --------------------------------------------------------------------------
# Stitch
# --------------------------------------------------------------------------


def test_stitch_relocates_an_upscaled_crop():
    base = _textured(seed=1)
    # A close-up: crop a region and upscale 2x (higher effective resolution).
    y0, y1, x0, x1 = 150, 450, 200, 600
    closeup = cv2.resize(base[y0:y1, x0:x1], None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
    blended, inliers, note = S.stitch_closeup(base, closeup, S.DEFAULTS)
    assert blended is not None, f"crop should re-locate on its source ({note})"
    assert inliers >= S.DEFAULTS["min_inliers"]
    assert blended.shape == base.shape


def test_stitch_rejects_unrelated_image():
    base = _textured(seed=2)
    rng = np.random.default_rng(99)
    noise = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    blended, _inliers, _note = S.stitch_closeup(base, noise, S.DEFAULTS)
    assert blended is None, "unrelated image must not be stitched in"


# --------------------------------------------------------------------------
# Integration — single-frame (the path the real testset exercises)
# --------------------------------------------------------------------------


def _seed_ingest(page: Path, frames: list[np.ndarray]) -> None:
    ing = page / "00_ingest"
    ing.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "x", "n_frames": len(frames), "frames": []}
    for i, f in enumerate(frames):
        name = f"frame_{i:02d}.png"
        cv2.imwrite(str(ing / name), f)
        h, w = f.shape[:2]
        manifest["frames"].append({
            "name": name, "source": f"{name}", "width": w, "height": h,
            "sharpness": float(S_sharp(f)), "applied_rotate": 0,
        })
    (ing / "ingest.json").write_text(json.dumps(manifest), encoding="utf-8")


def S_sharp(bgr: np.ndarray) -> float:
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def test_run_single_frame_produces_anchor():
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "page_001"
        frame = _textured(seed=3)
        _seed_ingest(page, [frame])
        result = S.run(page, cfg={})
        assert result.method == "single"
        assert result.anchor_source == "frame_00.png"
        anchor = cv2.imread(str(page / "01_fuse" / "anchor.png"))
        assert anchor is not None and anchor.shape == frame.shape
        assert (page / "01_fuse" / "fuse.json").exists()
        assert (page / "01_fuse" / "meta.json").exists()
        assert (page / "debug" / "01_fuse.png").exists()


def test_run_two_fullspread_picks_sharpest_anchor():
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "page_001"
        sharp = _textured(seed=4)
        blurry = cv2.GaussianBlur(sharp, (21, 21), 0)
        # order: blurry first, sharp second — anchor must be the sharp one
        _seed_ingest(page, [blurry, sharp])
        result = S.run(page, cfg={})
        assert result.anchor_source == "frame_01.png", "should pick sharper frame"
        assert result.method in ("sharpest", "sharpest+stitch")


def _run() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
