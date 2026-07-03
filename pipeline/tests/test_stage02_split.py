"""Unit tests for pipeline.stage02_split gutter detection.

Pure-logic tests on synthetic spreads with a hand-known answer — no photos, no
Tesseract. Run with pytest, or directly:
    python -m pipeline.tests.test_stage02_split
"""

from __future__ import annotations

import numpy as np

from pipeline.stage02_split import DEFAULTS, cut_pages, detect_gutter


def _text_block(canvas: np.ndarray, x0: int, x1: int) -> None:
    """Fill a column band with evenly spaced dark horizontal 'text' rows."""
    h = canvas.shape[0]
    for y in range(int(h * 0.1), int(h * 0.9), 12):
        canvas[y:y + 6, x0:x1] = 20  # dark ink rows


def _two_page_spread(w: int = 4000, h: int = 3000, gutter: int = 2000) -> np.ndarray:
    """White spread with two text columns and a white gutter down the middle."""
    img = np.full((h, w), 245, np.uint8)
    _text_block(img, int(w * 0.05), gutter - 120)   # left page text
    _text_block(img, gutter + 120, int(w * 0.95))   # right page text
    return img


def _single_page(w: int = 4000, h: int = 3000) -> np.ndarray:
    """One wide text block spanning the centre — no gutter."""
    img = np.full((h, w), 245, np.uint8)
    _text_block(img, int(w * 0.05), int(w * 0.95))
    return img


def test_detects_central_gutter():
    img = _two_page_spread(gutter=2000)
    gx, diag = detect_gutter(img, DEFAULTS)
    assert gx is not None, "should find a gutter in a two-page spread"
    assert abs(gx - 2000) < 120, f"gutter {gx} not near true centre 2000"
    assert diag["ratio"] < DEFAULTS["valley_ratio"]


def test_detects_off_centre_gutter_within_window():
    # Gutter shifted right but still inside the 30-70% search band.
    img = _two_page_spread(gutter=2400)
    gx, _ = detect_gutter(img, DEFAULTS)
    assert gx is not None and abs(gx - 2400) < 150


def test_single_page_has_no_confident_gutter():
    img = _single_page()
    gx, diag = detect_gutter(img, DEFAULTS)
    assert gx is None, f"single page wrongly split (ratio={diag['ratio']:.2f})"


def test_cut_pages_loses_no_columns_and_overlaps():
    img = _two_page_spread(gutter=2000)
    w = img.shape[1]
    margin = int(w * DEFAULTS["margin_frac"])
    pieces = cut_pages(np.dstack([img] * 3), 2000, margin)
    names = [n for n, _, _ in pieces]
    assert names == ["left.png", "right.png"]
    (_, left, lbox), (_, right, rbox) = pieces
    # No column is dropped: left reaches past the cut, right starts before it.
    assert lbox.x2 == 2000 + margin
    assert rbox.x == 2000 - margin
    # Combined widths cover the whole spread (with the 2*margin overlap).
    assert left.shape[1] + right.shape[1] == w + 2 * margin


def test_single_page_emits_one_subpage():
    img = np.dstack([_single_page()] * 3)
    pieces = cut_pages(img, None, 40)
    assert [n for n, _, _ in pieces] == ["single.png"]
    assert pieces[0][2].w == img.shape[1]


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
