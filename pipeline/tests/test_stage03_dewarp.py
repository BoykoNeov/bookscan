"""Unit tests for pipeline.stage03_dewarp classical text-line rectification.

Synthetic pages with a hand-known warp — no photos, no Tesseract. The core
assertion: a page whose straight rows are bent by a known curl comes back
STRAIGHTER after dewarp; a genuinely flat page is left unchanged but FLAGGED
(never a silent passthrough). Run with pytest, or directly:
    python -m pipeline.tests.test_stage03_dewarp
"""

from __future__ import annotations

import numpy as np

from pipeline.stage03_dewarp import DEFAULTS, dewarp_classical, detect_baselines


def _lined_page(w: int = 1200, h: int = 1600, spacing: int = 40) -> np.ndarray:
    """White page with evenly spaced dark horizontal 'text' bars (BGR)."""
    gray = np.full((h, w), 245, np.uint8)
    for y in range(120, h - 120, spacing):
        gray[y:y + 8, 60:w - 60] = 20
    return np.dstack([gray] * 3)


def _bend(bgr: np.ndarray, amp: float) -> np.ndarray:
    """Bend straight rows into a cylindrical curl of peak ``amp`` px."""
    h, w = bgr.shape[:2]
    xs = np.arange(w, dtype=np.float32)
    disp = (amp * 4.0 * (xs / w - 0.5) ** 2).astype(np.float32)   # 0 centre, amp edges
    ys, xg = np.mgrid[0:h, 0:w].astype(np.float32)
    import cv2
    map_y = (ys + disp[None, :]).astype(np.float32)
    return cv2.remap(bgr, xg, map_y, interpolation=cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def _curvature(bgr: np.ndarray) -> float:
    """Mean vertical spread (max-min y) of detected baselines — 0 == perfectly
    straight lines."""
    import cv2
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bls, _ = detect_baselines(gray, DEFAULTS)
    if not bls:
        return 0.0
    return float(np.mean([ys.max() - ys.min() for _, ys in bls]))


def test_dewarp_straightens_curved_text():
    warped = _bend(_lined_page(), amp=45.0)
    before = _curvature(warped)
    out, pd, _ = dewarp_classical(warped, DEFAULTS)
    after = _curvature(out)
    assert pd.applied and pd.method == "classical", pd.note
    assert out.shape == warped.shape, "dewarp must preserve full resolution"
    assert before > 20, f"synthetic warp too weak to test ({before:.1f}px)"
    assert after < 0.5 * before, f"not straightened: {before:.1f} -> {after:.1f}px"


def test_flat_page_is_identity_and_flagged():
    flat = _lined_page()
    out, pd, _ = dewarp_classical(flat, DEFAULTS)
    assert not pd.applied and pd.method == "identity", pd.note
    assert np.array_equal(out, flat), "flat page must be emitted byte-identical"
    assert "flat" in pd.note or "displacement" in pd.note


def test_blank_page_too_few_lines_flagged():
    blank = np.full((1600, 1200, 3), 245, np.uint8)
    out, pd, _ = dewarp_classical(blank, DEFAULTS)
    assert not pd.applied and pd.method == "identity"
    assert pd.n_lines < DEFAULTS["min_lines"]
    assert np.array_equal(out, blank)


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
