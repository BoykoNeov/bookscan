"""Unit tests for pipeline.stage04_layout pure geometry — NMS, reading-order
XY-Cut, the reading-row tie-break, and the abandon-class split.

Hand-built boxes with a known correct order — no photos, no torch, no Tesseract.
Two tests are REGRESSION tests for bugs the Gate 3 A/B caught (see docs/RESULTS.md
Gate 3 section): same-line orphan words must read left-to-right despite jittery
box tops, and stacked blocks must read top-to-bottom (a fixed row-tolerance broke
the latter). Run with pytest, or directly:
    python -m pipeline.tests.test_stage04_layout
"""

from __future__ import annotations

import numpy as np

from pipeline.page_model import BBox, BlockType
from pipeline.stage04_layout import (
    DEFAULTS, RawDet, _contain_frac, _map_abandon, _reading_rows, dets_to_blocks,
    nms_and_dedup, split_merged_figures, xy_cut_order,
)


def _b(x: int, y: int, w: int, h: int) -> BBox:
    return BBox(x=x, y=y, w=w, h=h)


# Synthetic page for the figure-split tests: a cream page (warm, low-saturation,
# high-value — like the real book paper) with strongly-colored "photo" bands, so
# the background mask cleanly separates page from photo. BGR.
_CREAM = (200, 215, 225)
_BLUE = (180, 60, 40)
_GREEN = (40, 160, 40)


def _stacked_photos_page(w=400, h=600) -> np.ndarray:
    """Two photos (blue over green) separated by a FULL-WIDTH cream gutter, on a
    cream page. The figure box (20,50,360,490) spans both photos + the gutter."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = _CREAM
    img[50:250, 20:380] = _BLUE       # top photo
    # rows 250..290 stay cream = the full-width gutter seam
    img[290:540, 20:380] = _GREEN     # bottom photo
    return img


_INK = (30, 30, 30)


def _lshape_page(w=400, h=600) -> np.ndarray:
    """The it_geo_06-right geometry in miniature: a full-width photo on top, a
    full-width cream gutter, then a band of ``caption text | cream gutter | photo``.
    The figure box (20,50,360,490) swallows all of it — including the caption."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = _CREAM
    img[50:250, 20:380] = _BLUE           # top photo (full width of the box)
    # rows 250..290 stay cream = the full-WIDTH horizontal seam (Phase A cuts here)
    for ln in range(310, 520, 30):        # caption text lines, left column
        img[ln:ln + 12, 30:140] = _INK
    # cols 140..190 stay cream = the full-HEIGHT vertical seam (Phase B cuts here)
    img[290:540, 190:380] = _GREEN        # the second photo, right of the caption
    return img


def _diagram_on_page_background(w=400, h=600) -> np.ndarray:
    """ONE figure that must never be cut: a diagram drawn in ink directly on the
    page, whose two halves are separated by a full-HEIGHT cream column. Every row
    carries ink on both sides, so there is no horizontal seam — but the vertical
    seam is real. This is it_geo_05-left (the full-page map) in miniature."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = _CREAM
    for ln in range(60, 530, 20):
        img[ln:ln + 10, 20:170] = _INK    # left half of the diagram
        img[ln:ln + 10, 210:380] = _INK   # right half
    return img


def test_two_column_reading_order():
    """Header spanning the top, then a left and right column (one tall block
    each) -> header, left column, right column."""
    boxes = [
        _b(520, 120, 430, 980),   # 0: right column (deliberately first in input)
        _b(50, 20, 900, 50),      # 1: full-width header
        _b(50, 120, 430, 980),    # 2: left column
    ]
    order = xy_cut_order(boxes, DEFAULTS, page_w=1000, page_h=1200)
    assert order == [1, 2, 0], order   # header, left, right


def test_footnote_orphans_read_left_to_right():
    """REGRESSION (Gate 3 A/B): a single line of tightly-spaced boxes with
    jittery tops (like undetected footnote words) must read LEFT-TO-RIGHT. A
    y-primary tie-break scrambled them ('Eastern Exchange' -> 'Exchange
    Eastern')."""
    # x-gaps < v_gap and overlapping y -> no clean cut -> the reading-row base
    # case. Tops jitter 100/102/109/105 so a pure y-sort would emit 0,1,3,2.
    boxes = [
        _b(100, 100, 60, 21),
        _b(165, 102, 120, 29),
        _b(288, 109, 70, 16),
        _b(360, 105, 110, 26),
    ]
    order = xy_cut_order(boxes, DEFAULTS, page_w=800, page_h=1000)
    assert order == [0, 1, 2, 3], order


def test_reading_rows_stacked_blocks_top_to_bottom():
    """REGRESSION (Gate 3 A/B): in the tie-break, vertically-stacked blocks read
    TOP-TO-BOTTOM regardless of x — a fixed row-tolerance collapsed them into one
    row and x-sorted them (bg_01 +7.5pp)."""
    boxes = [
        _b(600, 0, 300, 300),     # 0: upper block, on the right
        _b(0, 320, 300, 300),     # 1: lower block, on the left
    ]
    assert _reading_rows([0, 1], boxes) == [0, 1]
    # ...and two boxes on the same line still read left-to-right:
    same_line = [_b(400, 50, 100, 40), _b(100, 52, 100, 40)]
    assert _reading_rows([0, 1], same_line) == [1, 0]


def test_reading_rows_bridged_column_not_inverted():
    """REGRESSION (Finding 3, de_01-right): a tall neighbour (a page-height second
    column) bridges a column-STACKED group into one reading-row. A flat x-sort then
    emits that column by x — and because the paragraphs have ragged left margins
    that GROW downward, the column comes out fully reversed (Route->Zustieg->Anreise
    became blocks 0,1,2 -> emitted 2,1,0). The row must sub-cluster into x-columns
    and read each column top-to-bottom: left column A->B->C first, then the tall
    bridging column."""
    boxes = [
        _b(118, 1211, 1417, 285),   # 0: 'Anreise'  (top,    left margin 118)
        _b(106, 1501, 1431, 200),   # 1: 'Zustieg'  (middle, left margin 106)
        _b(99, 1704, 1443, 319),    # 2: 'Route'    (bottom, left margin  99)
        _b(1574, 1246, 262, 956),   # 3: tall English column bridging all three
        _b(28, 148, 1801, 1029),    # 4: top figure spanning BOTH columns
    ]
    # The bridged row alone (blocks 0-3): left column top-to-bottom, then the tall
    # bridging column. A flat x-sort would give [2, 1, 0, 3] (German reversed).
    assert _reading_rows([0, 1, 2, 3], boxes) == [0, 1, 2, 3]
    # Whole-page path: the spanning figure (4) kills the vertical cut and the tall
    # column (3) kills the horizontal cut, so all five blocks fall into the
    # tie-break. Figure first, then the German column top-to-bottom, then English.
    assert xy_cut_order(boxes, DEFAULTS, page_w=2057, page_h=3000) == [4, 0, 1, 2, 3]


def test_map_abandon_by_position():
    h = 3000
    assert _map_abandon(_b(200, 100, 600, 50), h) == BlockType.HEADER
    assert _map_abandon(_b(900, 2900, 120, 40), h) == BlockType.PAGE_NUMBER
    assert _map_abandon(_b(400, 1500, 200, 40), h) == BlockType.OTHER


def test_nms_keeps_higher_conf_and_prunes_contained():
    dets = [
        RawDet(label="plain text", bbox=_b(500, 100, 300, 200), conf=0.90),     # A
        RawDet(label="figure", bbox=_b(520, 120, 60, 40), conf=0.50),           # inside A
        RawDet(label="plain text", bbox=_b(100, 100, 200, 50), conf=0.61),      # B
        RawDet(label="figure_caption", bbox=_b(100, 100, 200, 50), conf=0.33),  # dup of B
    ]
    kept = nms_and_dedup(dets, DEFAULTS)
    labels = sorted((d.label, round(d.conf, 2)) for d in kept)
    # the .33 cross-class dup of B and the .50 box contained in A are pruned
    assert ("figure_caption", 0.33) not in labels
    assert ("figure", 0.5) not in labels
    assert labels == [("plain text", 0.61), ("plain text", 0.9)], labels


def test_dets_to_blocks_orders_and_types():
    dets = [
        RawDet(label="plain text", bbox=_b(50, 400, 900, 300), conf=0.9),
        RawDet(label="abandon", bbox=_b(50, 20, 400, 40), conf=0.8),   # header (top)
        RawDet(label="figure", bbox=_b(50, 100, 900, 260), conf=0.9),
    ]
    blocks = dets_to_blocks(dets, page_w=1000, page_h=1000, p=DEFAULTS)
    # reading_order is a contiguous 0..n-1 in reading sequence
    assert [b.reading_order for b in blocks] == [0, 1, 2]
    assert [b.type for b in blocks] == [
        BlockType.HEADER, BlockType.FIGURE, BlockType.PARAGRAPH]


def test_split_merged_figure_at_full_width_gutter():
    """A merged figure spanning two photos + a full-width page-background gutter
    splits into two sub-boxes, each hugging its photo (not the gutter)."""
    img = _stacked_photos_page()
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.4)]
    out = split_merged_figures(dets, img, DEFAULTS)
    assert len(out) == 2 and all(d.label == "figure" for d in out)
    top, bot = sorted(out, key=lambda d: d.bbox.y)
    # sub-boxes tightened to the photo bands (~50..250 and ~290..540), gutter excluded
    assert 45 <= top.bbox.y <= 60 and 240 <= top.bbox.y2 <= 260
    assert 285 <= bot.bbox.y <= 300 and 530 <= bot.bbox.y2 <= 545
    assert all(d.conf == 0.4 for d in out)          # sub-boxes inherit parent conf


def test_single_photo_figure_never_splits():
    """A figure over ONE solid photo (no internal full-width cream band) is passed
    through unchanged — the over-split guard (full-span + sampled margin)."""
    img = _stacked_photos_page()
    solid = [RawDet(label="figure", bbox=_b(20, 50, 360, 200), conf=0.5)]  # top photo only
    out = split_merged_figures(solid, img, DEFAULTS)
    assert len(out) == 1 and out[0].bbox.h == 200


def test_split_leaves_non_figures_untouched():
    img = _stacked_photos_page()
    dets = [
        RawDet(label="plain text", bbox=_b(20, 50, 360, 490), conf=0.9),
        RawDet(label="figure_caption", bbox=_b(20, 560, 360, 30), conf=0.8),
    ]
    out = split_merged_figures(dets, img, DEFAULTS)
    assert [d.label for d in out] == ["plain text", "figure_caption"]


def test_lshape_splits_h_then_v_and_ejects_the_caption():
    """Phase B: the merged L-shape box becomes the top photo + the right photo,
    and the swallowed caption column is EJECTED — so no figure crop contains the
    caption's pixels (docs/FIGURE_SEPARATION_SCOPE.md §5, the it_geo_06-right
    duplicated-caption defect)."""
    img = _lshape_page()
    caption = RawDet(label="plain text", bbox=_b(25, 295, 130, 240), conf=0.86)
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.44), caption]
    figs = [d for d in split_merged_figures(dets, img, DEFAULTS)
            if d.label == "figure"]
    assert len(figs) == 2, [(d.bbox.x, d.bbox.y, d.bbox.w, d.bbox.h) for d in figs]
    top, side = sorted(figs, key=lambda d: d.bbox.y)
    assert 45 <= top.bbox.y <= 60 and 240 <= top.bbox.y2 <= 260   # H-cut, as Phase A
    assert side.bbox.x >= 180 and side.bbox.x2 >= 370             # V-cut kept the photo
    # the defect, expressed as the metric that caught it on the real page:
    for d in figs:
        assert _contain_frac(caption.bbox, d.bbox) < 0.05


def test_vsplit_refused_without_text_evidence():
    """REGRESSION (it_geo_05-left, measured): an unguarded V-cut sliced a single
    full-page MAP into two vertical strips (GT F2 IoU 1.000 -> 0.702), because a
    diagram drawn on page background legitimately contains full-height background
    columns. The vertical cut is therefore accepted only when it ejects a detected
    text column — here there is none, so the figure passes through untouched."""
    img = _diagram_on_page_background()
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.66)]
    out = split_merged_figures(dets, img, DEFAULTS)
    assert len(out) == 1 and out[0].bbox.w == 360 and out[0].bbox.h == 490


def test_vsplit_refused_on_a_band_with_no_absorbed_text():
    """The same guard one level down: the L-shape page WITHOUT the caption
    detection keeps Phase A's horizontal cut but leaves the lower band whole."""
    img = _lshape_page()
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.44)]
    out = split_merged_figures(dets, img, DEFAULTS)
    assert len(out) == 2
    assert all(d.bbox.w == 360 for d in out)      # full-width bands, no V-cut


def test_fig_vsplit_disabled_leaves_phase_a_intact():
    img = _lshape_page()
    dets = [
        RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.44),
        RawDet(label="plain text", bbox=_b(25, 295, 130, 240), conf=0.86),
    ]
    out = [d for d in split_merged_figures(dets, img, dict(DEFAULTS,
                                                           fig_vsplit=False))
           if d.label == "figure"]
    assert len(out) == 2 and all(d.bbox.w == 360 for d in out)


def test_all_subboxes_text_covered_abstains():
    """If EVERY sub-box looks like absorbed text we keep the original figure box
    rather than delete a figure outright."""
    img = _stacked_photos_page()
    dets = [
        RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.4),
        RawDet(label="plain text", bbox=_b(15, 45, 370, 210), conf=0.9),
        RawDet(label="plain text", bbox=_b(15, 285, 370, 260), conf=0.9),
    ]
    figs = [d for d in split_merged_figures(dets, img, DEFAULTS)
            if d.label == "figure"]
    assert len(figs) == 1 and figs[0].bbox.h == 490


def test_fig_split_disabled_is_noop():
    img = _stacked_photos_page()
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.4)]
    p = dict(DEFAULTS, fig_split=False)
    assert len(split_merged_figures(dets, img, p)) == 1


def test_dets_to_blocks_splits_when_image_supplied():
    """End-to-end through dets_to_blocks: the merged figure becomes two FIGURE
    blocks when bgr is supplied, one when it is not (bgr=None => no split)."""
    img = _stacked_photos_page()
    dets = [RawDet(label="figure", bbox=_b(20, 50, 360, 490), conf=0.4)]
    with_img = dets_to_blocks(dets, 400, 600, DEFAULTS, bgr=img)
    without = dets_to_blocks(dets, 400, 600, DEFAULTS, bgr=None)
    assert sum(b.type == BlockType.FIGURE for b in with_img) == 2
    assert sum(b.type == BlockType.FIGURE for b in without) == 1


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
