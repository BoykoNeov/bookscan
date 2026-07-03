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

from pipeline.page_model import BBox, BlockType
from pipeline.stage04_layout import (
    DEFAULTS, RawDet, _map_abandon, _reading_rows, dets_to_blocks,
    nms_and_dedup, xy_cut_order,
)


def _b(x: int, y: int, w: int, h: int) -> BBox:
    return BBox(x=x, y=y, w=w, h=h)


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


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
