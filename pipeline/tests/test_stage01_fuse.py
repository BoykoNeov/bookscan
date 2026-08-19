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

# Registration and "is it worth blending" are two separate policies, so the
# registration tests switch the do-no-harm gate off rather than fight it: a crop
# that has been upscaled and warped back down is necessarily SOFTER than its
# source, so every honest registration fixture fails that gate by construction.
# The gate gets its own tests below.
REG_ONLY = dict(S.DEFAULTS, min_sharpness_ratio=0.0)



def test_stitch_relocates_an_upscaled_crop():
    base = _textured(seed=1)
    # A close-up: crop a region and upscale 2x (higher effective resolution).
    y0, y1, x0, x1 = 150, 450, 200, 600
    closeup = cv2.resize(base[y0:y1, x0:x1], None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
    blended, res, note = S.stitch_closeup(base, closeup, REG_ONLY)
    assert blended is not None, f"crop should re-locate on its source ({note})"
    assert res.inliers >= S.DEFAULTS["min_inliers"]
    assert res.ncc >= S.DEFAULTS["min_ncc"], "a crop of the base must agree with it"
    assert res.corners is not None and len(res.corners) == 4
    assert blended.shape == base.shape


def test_stitch_rejects_unrelated_image():
    base = _textured(seed=2)
    rng = np.random.default_rng(99)
    noise = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    blended, _res, _note = S.stitch_closeup(base, noise, REG_ONLY)
    assert blended is None, "unrelated image must not be stitched in"


def test_registration_ncc_sees_a_misregistration():
    """The measure itself: warp a crop back onto its source correctly and NCC is
    high; slide the same warp 40 px and it collapses. Without this the gate is
    just a number nobody has checked."""
    base = _textured(seed=5)
    crop = base[150:450, 200:600]
    H_ok = np.float64([[1, 0, 200], [0, 1, 150], [0, 0, 1]])
    H_off = np.float64([[1, 0, 240], [0, 1, 190], [0, 0, 1]])
    bh, bw = base.shape[:2]
    scores = []
    for H in (H_ok, H_off):
        w = cv2.warpPerspective(crop, H, (bw, bh))
        m = cv2.warpPerspective(np.full(crop.shape[:2], 255, np.uint8), H, (bw, bh))
        scores.append(S.registration_ncc(base, w, m))
    aligned, shifted = scores
    assert aligned > 0.9, f"a correct warp must agree with the source ({aligned})"
    assert shifted < aligned - 0.3, f"a 40px slide must show up ({scores})"
    assert aligned >= S.DEFAULTS["min_ncc"] > shifted


def test_photometric_gate_can_veto_a_high_inlier_fit():
    """The wiring: the photometric check runs AFTER RANSAC and outranks it.

    This is the zoomset_en_01_f03 shape — a registration with plenty of inlier
    consensus (27, over the old 25 gate) whose warped pixels were grass where the
    anchor had text. Here the same pair that normally stitches is refused purely
    because the photometry disagrees, with the inlier count still healthy."""
    base = _textured(seed=6)
    closeup = cv2.resize(base[150:450, 200:600], None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
    orig = S.registration_ncc
    S.registration_ncc = lambda b, w, m: 0.05
    try:
        blended, res, note = S.stitch_closeup(base, closeup, REG_ONLY)
    finally:
        S.registration_ncc = orig
    assert blended is None, "photometric disagreement must veto the blend"
    assert "ncc" in note and "inliers" in note, note
    assert res.inliers >= S.DEFAULTS["min_inliers"], (
        "the veto must happen DESPITE a passing inlier count, or this test proves "
        f"nothing (inliers={res.inliers})")


def test_do_no_harm_gate_refuses_a_correctly_placed_but_softer_closeup():
    """The gate the real captures needed. All five close-ups that Stage 01 locates
    correctly on the zoomset spreads are blurrier than the anchor over the same
    pixels (0.49-0.83), and blending them cost de_01 178 high-confidence OCR
    words. Correct placement is not a reason to blend."""
    base = _textured(seed=11)
    crop = base[150:450, 200:600]
    soft = cv2.GaussianBlur(cv2.resize(crop, None, fx=2.0, fy=2.0,
                                       interpolation=cv2.INTER_CUBIC), (9, 9), 0)
    blended, res, note = S.stitch_closeup(base, soft, S.DEFAULTS)
    assert blended is None, f"a softer close-up must not be blended ({note})"
    assert res.ncc >= S.DEFAULTS["min_ncc"], (
        "this must fail on SHARPNESS, not on placement, or it tests the wrong gate")
    assert 0.0 < res.sharpness_ratio < 1.0, res.sharpness_ratio
    assert "SOFTER" in note


def test_do_no_harm_gate_admits_a_genuinely_sharper_closeup():
    """...and it is a gate, not a ban: a close-up that really does carry more
    detail than the anchor's view of the same region still goes in."""
    sharp = _textured(seed=12)
    base = cv2.GaussianBlur(sharp, (7, 7), 0)      # anchor: a soft view
    closeup = cv2.resize(sharp[150:450, 200:600], None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
    blended, res, note = S.stitch_closeup(base, closeup, S.DEFAULTS)
    assert blended is not None, f"a sharper close-up must be blended in ({note})"
    assert res.sharpness_ratio > 1.0, res.sharpness_ratio
    assert blended.shape == base.shape


def test_sharpness_check_declines_to_judge_a_tiny_footprint():
    """"Cannot judge" must not be reported as "softer".

    A fixed 25x25 erosion ate a small patch entirely - an 80x80 footprint fell to
    3136 px, the function returned 0.0, and the gate refused the close-up citing a
    sharpness ratio that had never been measured. The erosion is scaled to the
    footprint now, and anything genuinely too small returns None. The zoomset
    cannot reach this case (all whole-spread re-zooms); a close-up of PART of a
    page, which is what the stage is for, can."""
    img = _textured(seed=13)
    big = np.zeros(img.shape[:2], np.uint8)
    big[200:500, 200:600] = 255
    assert S.footprint_sharpness_ratio(img, img, big) is not None, (
        "a normal footprint must still be judged")
    tiny = np.zeros(img.shape[:2], np.uint8)
    tiny[200:240, 200:240] = 255          # 1600 px, under the judgeable floor
    assert S.footprint_sharpness_ratio(img, img, tiny) is None
    # ...and the scaled kernel keeps a mid-size patch judgeable, where the old
    # fixed 25x25 kernel would have eroded it below the floor.
    mid = np.zeros(img.shape[:2], np.uint8)
    mid[200:290, 200:290] = 255           # 8100 px
    assert S.footprint_sharpness_ratio(img, img, mid) is not None


def test_gates_are_separate_knobs():
    """min_inliers used to gate BOTH the good-match count and the RANSAC inlier
    count. They answer different questions and are now separate; this pins that
    the precondition can be raised without silently moving the quality gate."""
    base = _textured(seed=3)
    closeup = cv2.resize(base[150:450, 200:600], None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
    strict = dict(REG_ONLY, min_good_matches=10_000)
    blended, res, note = S.stitch_closeup(base, closeup, strict)
    assert blended is None and "good matches" in note
    assert res.inliers == 0, "rejected at the precondition, before RANSAC ran"
    # ...and the same pair passes once only the precondition is relaxed back.
    blended, res, _ = S.stitch_closeup(base, closeup, REG_ONLY)
    assert blended is not None and res.inliers >= S.DEFAULTS["min_inliers"]


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
