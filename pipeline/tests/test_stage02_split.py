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


def _curved_spread_no_ink_valley(w: int = 4000, h: int = 3000,
                                 gutter: int = 2000) -> np.ndarray:
    """A spread with NO ink whitespace valley (text spans continuously across the
    gutter, so the ink profile is flat and Layer 1 cannot fire) but whose bright
    page region is PINCHED at the binding — the Finding-2 case (de_01/de_02/taleb).

    Dark 'fabric' background; a bright page block with a triangular wedge eaten
    out of its top and bottom edges near the gutter (deepest at the spine). The
    wedge shortens the page's vertical extent at the spine (the pinch cue) while
    leaving the mid-height text intact (so no ink valley).
    """
    img = np.full((h, w), 30, np.uint8)                    # dark background
    ptop, pbot = int(h * 0.05), int(h * 0.95)
    page_x0, page_x1 = int(w * 0.10), int(w * 0.90)
    img[ptop:pbot, page_x0:page_x1] = 235                  # bright page block
    _text_block(img, page_x0 + 40, page_x1 - 40)           # text across the gutter
    # Carve the spine pinch: a wedge eaten from top and bottom, deepest (~20% of
    # page height each) at the gutter, tapering to 0 within notch_hw px.
    notch_hw, notch_max = 300, int((pbot - ptop) * 0.20)
    for x in range(gutter - notch_hw, gutter + notch_hw):
        eat = int(notch_max * (1 - abs(x - gutter) / notch_hw))
        img[ptop:ptop + eat, x] = 30
        img[pbot - eat:pbot, x] = 30
    return img


def _single_page_dark_bg(w: int = 4000, h: int = 3000) -> np.ndarray:
    """One page (bright rectangle) on DARK fabric, no central spine — the exact
    conditions under which the pinch cue fires, minus the pinch. This is the
    single-page safety the more eager resolver must not erode: ink has no valley
    AND the page extent is flat, so BOTH layers must decline (-> single.png)."""
    img = np.full((h, w), 30, np.uint8)                       # dark background
    page_x0, page_x1 = int(w * 0.08), int(w * 0.92)
    img[int(h * 0.05):int(h * 0.95), page_x0:page_x1] = 235   # one bright page
    _text_block(img, page_x0 + 40, page_x1 - 40)              # full-width text
    return img


def test_dark_bg_single_page_not_split_by_pinch():
    img = _single_page_dark_bg()
    gx, diag = detect_gutter(img, DEFAULTS)
    assert gx is None, (
        f"single page on dark bg wrongly split (method={diag['method']}, "
        f"ink ratio={diag['ratio']:.2f}, pinch depth={diag['pinch_depth']:.2f})")
    assert diag["method"] == "none"
    assert diag["pinch_depth"] < DEFAULTS["pinch_min_depth"]


def test_curved_spread_splits_via_pinch():
    img = _curved_spread_no_ink_valley(gutter=2000)
    gx, diag = detect_gutter(img, DEFAULTS)
    # ink alone must NOT be confident here (that is the whole Finding-2 failure)…
    assert diag["ratio"] >= DEFAULTS["valley_ratio"], (
        f"synthetic curved spread unexpectedly has an ink valley "
        f"(ratio={diag['ratio']:.2f}); it no longer exercises the pinch layer")
    # …yet the spine pinch rescues the split at the right column.
    assert diag["method"] == "pinch"
    assert gx is not None and abs(gx - 2000) < 150, f"pinch gutter {gx} off"


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
