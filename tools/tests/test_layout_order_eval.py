"""Unit tests for the pure grading logic in tools.layout_order_eval — the Gate-3
block-order metric. No OCR / GPU: DetBlocks are constructed by hand so every
answer is known. The it_geo_04 driver path is exercised separately by actually
running the tool (see docs/RESULTS.md); here we pin the maths.

Run: ``python -m pytest tools/tests/test_layout_order_eval.py`` or directly.
"""

from __future__ import annotations

from pipeline.page_model import BBox
from tools.layout_order_eval import (
    DetBlock, anchor_score, grouping_eval, kendall_tau, match_subpage, norm_tokens,
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
    # the real it_geo_04 right-native case: 4 blocks, conc=4 disc=2 -> 1/3
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


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
