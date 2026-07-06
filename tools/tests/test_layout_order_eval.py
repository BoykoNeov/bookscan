"""Unit tests for the pure grading logic in tools.layout_order_eval — the Gate-3
block-order metric. No OCR / GPU: DetBlocks are constructed by hand so every
answer is known. The it_geo_04 driver path is exercised separately by actually
running the tool (see docs/RESULTS.md); here we pin the maths.

Run: ``python -m pytest tools/tests/test_layout_order_eval.py`` or directly.
"""

from __future__ import annotations

from pipeline.page_model import BBox
from tools.layout_order_eval import (
    DetBlock, _bbox_iou, anchor_score, grouping_eval, kendall_tau, match_subpage,
    norm_tokens,
)


def _db(idx, ro, btype, x, y, w, h, text="", native=None):
    return DetBlock(idx=idx, ro=ro, btype=btype, bbox=BBox(x=x, y=y, w=w, h=h),
                    text=text, native_ranks=native or [])


# --- normalization / anchor scoring --------------------------------------

def test_norm_tokens_dehyphenates_and_strips_punct():
    assert norm_tokens("clinostra- tificazioni") == ["clinostratificazioni"]
    assert norm_tokens("A lato: Figura 20!") == ["a", "lato", "figura", "20"]


def test_anchor_score_full_and_partial():
    anchor = "tettoniche che impediscono ricostruzioni paleoambientali"
    # de-hyphenated OCR text contains every anchor token
    block = "tettoniche che impediscono rico- struzioni paleoambientali e in piccole"
    assert anchor_score(anchor, block) == 1.0
    # only distinctive half present -> 0.5-ish, still argmax-able
    assert 0.0 < anchor_score(anchor, "tettoniche che varie parole") < 1.0
    assert anchor_score(anchor, "") == 0.0


# --- Kendall-tau ----------------------------------------------------------

def test_kendall_tau_known_values():
    assert kendall_tau([(0, 0), (1, 1), (2, 2)]) == 1.0
    assert kendall_tau([(0, 2), (1, 1), (2, 0)]) == -1.0
    assert kendall_tau([(0, 0)]) is None
    # 4 blocks, conc=4 disc=2 -> 1/3. This WAS the it_geo_04 right-native value
    # when the B6R map (a text-bearing figure) leaked into the native arm; tau now
    # excludes figures from both arms, so that grade is 1.0 over its 3 text blocks.
    # Kept here as a pure-function fixture for the partial-concordance case.
    tau = kendall_tau([(0, 286), (1, 43), (2, 128), (3, 337)])
    assert abs(tau - 1 / 3) < 1e-9


# --- matching -------------------------------------------------------------

def test_match_figures_by_ro_rank_text_by_anchor():
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "P1", "type": "paragraph",
         "anchor": "nuo verso sud versante est"},
        {"order": 2, "id": "C1", "type": "caption",
         "anchor": "a lato figura 20 piattaforma"},
    ]
    det = [
        _db(0, 0, "figure", 0, 0, 100, 100),
        _db(1, 1, "paragraph", 0, 200, 100, 50, text="nuo verso sud versante est bla"),
        _db(2, 2, "caption", 0, 300, 100, 50, text="a lato figura 20 piattaforma foto"),
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 0, "P1": 1, "C1": 2}
    assert misses == []


def test_match_reports_missing_figure_when_fewer_detected():
    # two GT figures, only one detected -> the second GT figure is a miss
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "F2", "type": "figure", "anchor": "lagazuoi piccolo"},
    ]
    det = [_db(0, 0, "figure", 0, 0, 100, 100)]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 0}
    assert misses == ["F2"]


def test_bbox_iou_values():
    # identical boxes -> 1; disjoint -> 0; half-overlap -> intersection/union
    b = BBox(x=0, y=0, w=100, h=100)
    assert _bbox_iou([0, 0, 100, 100], b) == 1.0
    assert _bbox_iou([200, 200, 50, 50], b) == 0.0
    # GT [0,0,100,50] vs det 100x100: inter=100*50=5000, union=10000+5000-5000
    assert abs(_bbox_iou([0, 0, 100, 50], b) - 5000 / 10000) < 1e-9


def test_match_figures_by_bbox_overlap_beats_ro_rank():
    # it_geo_06 shape: the top-RIGHT plate (F_d) is emitted 2nd by Stage 04
    # (ro=3), out of column-major GT order (order=3, last). Bbox-overlap must pair
    # each GT figure with the det box it physically overlaps, NOT the i-th by rank
    # (which would give F_b the plate box and cascade the rest wrong).
    gt = [
        {"order": 0, "id": "Fa", "type": "figure", "anchor": None,
         "bbox": [0, 0, 100, 100]},          # top-left
        {"order": 1, "id": "Fb", "type": "figure", "anchor": None,
         "bbox": [0, 200, 100, 100]},        # mid-left
        {"order": 2, "id": "Fc", "type": "figure", "anchor": None,
         "bbox": [0, 400, 100, 100]},        # bottom-left
        {"order": 3, "id": "Fd", "type": "figure", "anchor": None,
         "bbox": [300, 0, 80, 90]},          # top-right plate
    ]
    det = [
        _db(0, 2, "figure", 2, 2, 98, 98),     # ro 2 -> top-left  (Fa)
        _db(1, 3, "figure", 300, 0, 80, 90),   # ro 3 -> plate     (Fd)  <- 2nd read
        _db(2, 4, "figure", 0, 200, 100, 100), # ro 4 -> mid-left  (Fb)
        _db(3, 5, "figure", 0, 400, 100, 100), # ro 5 -> bottom    (Fc)
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"Fa": 0, "Fd": 1, "Fb": 2, "Fc": 3}
    assert misses == []


def test_bbox_carrying_figure_with_no_overlap_is_honest_miss_no_rank_shift():
    # it_geo_07-left shape: the TOP diagram (G1) is undetected; only G2/G3 have
    # boxes. Rank would shift G1->G2's box and drop G3; bbox-overlap must flag G1
    # as the miss and match G2/G3 to their OWN boxes (no rank fallback for a
    # bbox-carrying figure that overlaps nothing).
    gt = [
        {"order": 0, "id": "G1", "type": "figure", "anchor": None,
         "bbox": [0, 0, 100, 80]},           # top -- NOT detected
        {"order": 1, "id": "G2", "type": "figure", "anchor": None,
         "bbox": [0, 200, 100, 100]},
        {"order": 2, "id": "G3", "type": "figure", "anchor": None,
         "bbox": [0, 400, 100, 100]},
    ]
    det = [
        _db(0, 5, "figure", 0, 200, 100, 100),  # overlaps G2
        _db(1, 6, "figure", 0, 400, 100, 100),  # overlaps G3
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"G2": 0, "G3": 1}
    assert misses == ["G1"]


def test_fragment_box_does_not_steal_whole_figure_match():
    # A partial-figure fragment (top slice, IoU ~0.3) and the whole-figure box
    # both overlap one GT figure. Greedy claims the whole box; the fragment,
    # overlapping no OTHER GT figure, stays unmatched rather than stealing.
    gt = [{"order": 0, "id": "F1", "type": "figure", "anchor": None,
           "bbox": [0, 0, 100, 300]}]
    det = [
        _db(0, 0, "figure", 0, 0, 100, 100),   # fragment: top third (IoU 1/3)
        _db(1, 1, "figure", 0, 0, 100, 300),   # whole figure (IoU 1.0)
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 1}
    assert misses == []


# --- grouping -------------------------------------------------------------

def test_grouping_single_figure_is_association_not_discriminated():
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    matched = {"C1": 1, "F1": 0}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 9, "caption", 500, 800, 100, 100)]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is True            # only one figure -> trivially nearest
    assert g.caption_typed_ok is True
    assert g.n_figures == 1
    assert "NOT discriminated" in g.reason


def test_grouping_flags_mistyped_caption():
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "right"}]
    matched = {"C1": 1, "F1": 0}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 3, "paragraph", 100, 200, 100, 100)]  # caption block mistyped
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.caption_typed_ok is False
    assert "mistyped" in g.reason


def test_grouping_discriminates_with_two_figures():
    # caption sits under F2; nearest-figure must pick F2, not F1
    gt_pairs = [{"caption": "C1", "figure": "F2", "subpage": "left"}]
    matched = {"C1": 2, "F1": 0, "F2": 1}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 1, "figure", 0, 1000, 100, 100),
           _db(2, 2, "caption", 0, 1120, 100, 40)]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is True
    assert g.n_figures == 2
    assert "NOT discriminated" not in g.reason

    # now the caption is nearer F1 -> pairing is WRONG
    matched_bad = {"C1": 2, "F1": 0, "F2": 1}
    det_bad = [_db(0, 0, "figure", 0, 0, 100, 100),
               _db(1, 1, "figure", 0, 1000, 100, 100),
               _db(2, 2, "caption", 0, 90, 100, 40)]
    (g2,) = grouping_eval(gt_pairs, matched_bad, det_bad)
    assert g2.nearest_ok is False


def test_grouping_uses_edge_gap_not_center_for_unequal_height_figures():
    """A caption sitting directly under a TALL figure's bottom edge must pair with
    that figure, not with a SHORT nearby figure whose center is closer. Center
    distance mis-attaches it (tall fig center is far up); edge gap fixes it. This
    is the ">=2 figures in one column" discrimination the Gate-3 grouping headline
    was blocked on, exercised on the pure metric (synthetic, detector-free)."""
    # Fig A tall (h=1000, center y=500); its caption directly under A's edge
    # (y=1010). Fig B short (h=100, center y=1150). Caption belongs to A.
    det = [_db(0, 0, "figure", 0, 0, 100, 1000),      # F1 (tall)
           _db(1, 2, "caption", 0, 1010, 100, 40),    # C1 under A's bottom edge
           _db(2, 1, "figure", 0, 1100, 100, 100)]    # F2 (short neighbor)
    matched = {"C1": 1, "F1": 0, "F2": 2}
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    (g,) = grouping_eval(gt_pairs, matched, det)
    # center distance would pick F2 (120 < 530) -> WRONG; edge gap picks F1
    # (10px < 50px) -> correct partner. n_figures==2 so it is DISCRIMINATED.
    assert g.nearest_ok is True
    assert g.n_figures == 2
    assert "NOT discriminated" not in g.reason


def test_edge_gap_does_not_encode_caption_above_below_known_limit():
    """BOUNDARY (documents a known limit, not a pass we want): edge-gap fixes the
    unequal-HEIGHT failure but does NOT encode the caption-above/below convention.
    Stacked figures with ASYMMETRIC spacing — a caption nearer the NEXT figure's
    top edge than its OWN figure's bottom edge — still mispair. No pure
    nearest-distance rule resolves above/below; a convention-aware rule is deferred
    until a real >=2-figure fixture exists to tune against (same discipline as the
    NMS near-miss). This test pins the current behavior so the boundary is explicit."""
    # cap1 belongs to Fig1 (above). But Fig2's top (y=135) is 5px below cap1's
    # bottom (y2=130), while Fig1's bottom (y2=100) is 10px above cap1 (y=110) ->
    # edge gap to Fig2 (5) < to Fig1 (10) -> edge-gap picks Fig2, the WRONG figure.
    det = [_db(0, 0, "figure", 0, 0, 100, 100),      # F1 (cap1's true partner)
           _db(1, 1, "caption", 0, 110, 100, 20),    # C1 (y2=130)
           _db(2, 2, "figure", 0, 135, 100, 100)]    # F2 (nearer below)
    matched = {"C1": 1, "F1": 0, "F2": 2}
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is False   # KNOWN LIMIT: edge-gap mispairs here (documented)


def test_two_figure_subpage_discriminates_both_captions_end_to_end():
    """Synthetic full subpage: TWO figures sharing one column, each with its own
    caption directly beneath it, plus a body paragraph. Drives the DRIVER-level
    path (match_subpage figures-by-ro-rank + text-by-anchor, then grouping_eval)
    so both captions must associate to the RIGHT figure with a wrong option
    present. This is the ">=2 figures / column" case that discriminates pairing —
    both pairs pass AND both count as discriminated (n_figures==2)."""
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "C1", "type": "caption", "anchor": "figura uno alpha"},
        {"order": 2, "id": "F2", "type": "figure", "anchor": None},
        {"order": 3, "id": "C2", "type": "caption", "anchor": "figura due beta"},
        {"order": 4, "id": "P1", "type": "paragraph", "anchor": "corpo del testo gamma"},
    ]
    det = [
        _db(0, 0, "figure",    0,    0, 400, 600),                       # -> F1
        _db(1, 1, "caption",   0,  610, 400,  60, text="figura uno alpha foto"),  # -> C1 (under F1)
        _db(2, 2, "figure",    0,  700, 400, 600),                       # -> F2
        _db(3, 3, "caption",   0, 1310, 400,  60, text="figura due beta foto"),   # -> C2 (under F2)
        _db(4, 4, "paragraph", 0, 1400, 400, 200, text="corpo del testo gamma e altro"),
    ]
    matched, misses = match_subpage(gt, det)
    assert misses == []
    assert matched == {"F1": 0, "C1": 1, "F2": 2, "C2": 3, "P1": 4}

    pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"},
             {"caption": "C2", "figure": "F2", "subpage": "left"}]
    groups = grouping_eval(pairs, matched, det)
    # both captions pair to the correct figure, both discriminated (2 figures)
    assert all(g.nearest_ok for g in groups)
    assert all(g.n_figures == 2 for g in groups)
    assert all(g.caption_typed_ok for g in groups)
    discriminated = sum(1 for g in groups if g.nearest_ok and g.n_figures >= 2)
    assert discriminated == 2


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
