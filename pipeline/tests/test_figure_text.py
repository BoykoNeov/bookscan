"""Gates of ``pipeline/figure_text.py``, each anchored on a MEASURED case from the
2026-08-26 rescued-block census (docs/data/rescued_type_census_20260826.json).

The boxes below are the real ones from that census and from the block dumps of
``tools/layout_order_eval`` — so a threshold change that breaks a real page
breaks a test here, rather than only showing up in a render diff.
"""

from __future__ import annotations

from pipeline.figure_text import (
    DEFAULTS, Absorption, absorb_figure_text, union)
from pipeline.page_model import BBox, BlockType

FIG = BlockType.FIGURE
PAR = BlockType.PARAGRAPH
CAP = BlockType.CAPTION
HDR = BlockType.HEADER


def bb(x, y, w, h) -> BBox:
    return BBox(x=x, y=y, w=w, h=h)


def _absorb(strays, real, page_h=3000, p=None):
    """``real`` is a list of (bbox, type, has_words) — the three parallel views
    the production caller builds out of Stage 04's blocks and the word routing."""
    return absorb_figure_text(
        strays, [b for b, _, _ in real], [t for _, t, _ in real],
        [hw for _, _, hw in real], page_h, p)


# --------------------------------------------------------------------------
# The three true positives, verbatim from the corpus
# --------------------------------------------------------------------------


def test_map_title_3px_above_its_figure_is_absorbed():
    """it_geo_05-left: the map's printed title sits 3px above the figure box."""
    stray = bb(1072, 280, 234, 48)                 # "CL 'INEAMENTO"
    real = [(bb(231, 331, 1806, 2658), FIG, True),  # F2, the whole-page map
            (bb(93, 90, 1300, 60), HDR, True)]      # running header, 130px away
    out = _absorb([stray], real)
    assert [a.figure for a in out] == [0]
    assert "v-gap +3px" in out[0].reason


def test_label_overlapping_the_figure_edge_is_absorbed():
    """it_geo_07-right: "Livello del [mare]" overlaps the cross-section's top
    edge by 6px, with its caption 36px above — the closest competing text of any
    accepted case."""
    stray = bb(104, 825, 149, 23)
    real = [(bb(91, 842, 876, 624), FIG, True),     # D7
            (bb(104, 729, 562, 60), CAP, True)]     # the caption above
    out = _absorb([stray], real)
    assert [a.figure for a in out] == [0]
    assert "v-gap -6px" in out[0].reason and "nearest text +36px" in out[0].reason


# --------------------------------------------------------------------------
# The rejections, each on the gate that does the rejecting
# --------------------------------------------------------------------------


def test_garbage_token_closer_to_the_paragraph_is_left_alone():
    """de_01-left's "ME": 33px above a figure but 18px below a paragraph. It
    fails the gap gate AND the closer-to-the-figure gate — check the second by
    widening the gap gate until only that one is left standing."""
    stray = bb(1799, 2021, 42, 3)
    real = [(bb(617, 2057, 1402, 796), FIG, True),
            (bb(600, 1200, 1400, 803), PAR, True)]  # ends 18px above the stray
    assert _absorb([stray], real) == []
    loose = dict(DEFAULTS, figtext_max_gap_frac=0.05)   # 150px — gap gate off
    assert _absorb([stray], real, p=loose) == []


def test_scale_bar_53px_from_the_figure_is_left_alone():
    """it_geo_07-left: a legend for a whole column of stacked cross-sections,
    53px above the topmost one. Deliberately NOT absorbed — see the module doc."""
    stray = bb(218, 857, 244, 91)
    real = [(bb(213, 1001, 828, 144), FIG, True),
            (bb(206, 291, 352, 429), PAR, True)]
    assert _absorb([stray], real) == []


def test_stray_hanging_off_the_side_of_the_figure_is_left_alone():
    """it_geo_04-left's "Cc arbonatiche" is only 0.69 inside its figure's
    horizontal span. Put it at touching distance so ONLY the containment gate
    can reject it."""
    stray = bb(1442, 190, 191, 52)                  # x 1442..1633
    real = [(bb(1501, 245, 480, 1081), FIG, True)]  # x 1501..1981 -> 0.69 inside
    assert _absorb([stray], real) == []


def test_two_candidate_figures_abstain():
    stray = bb(500, 495, 100, 10)
    real = [(bb(400, 200, 400, 290), FIG, True),    # ends 5px above
            (bb(400, 510, 400, 300), FIG, True)]    # starts 5px below
    assert _absorb([stray], real) == []


def test_growing_over_another_blocks_words_is_refused():
    """The strip the figure gains must be empty: a paragraph living between the
    stray and the figure would be painted into the picture AND still render."""
    stray = bb(400, 100, 200, 20)
    real = [(bb(390, 125, 400, 500), FIG, True),
            (bb(700, 105, 60, 30), PAR, True)]      # inside the grown band
    assert _absorb([stray], real) == []
    # ... and the same page without that block absorbs normally.
    assert len(_absorb([stray], real[:1])) == 1


def test_an_empty_detection_is_not_competing_text():
    """A detected paragraph with no routed words is not evidence that a stray
    belongs to the reading flow — only blocks that actually hold words compete."""
    stray = bb(1072, 280, 234, 48)
    real = [(bb(231, 331, 1806, 2658), FIG, True),
            (bb(1000, 200, 400, 60), PAR, False)]   # 20px away, but wordless
    assert [a.figure for a in _absorb([stray], real)] == [0]


def test_no_figure_on_the_page_absorbs_nothing():
    stray = bb(0, 1971, 21, 671)
    assert _absorb([stray], [(bb(100, 100, 500, 500), PAR, True)]) == []


# --------------------------------------------------------------------------
# Mechanics
# --------------------------------------------------------------------------


def test_union_covers_both_and_is_a_new_object():
    a, b = bb(231, 331, 1806, 2658), bb(1072, 280, 234, 48)
    u = union(a, b)
    assert (u.x, u.y, u.x2, u.y2) == (231, 280, 2037, 2989)
    assert u is not a and u is not b
    assert (a.x, a.y, a.w, a.h) == (231, 331, 1806, 2658)   # unmutated


def test_result_is_one_absorption_per_accepted_stray_in_order():
    real = [(bb(231, 331, 1806, 2658), FIG, True)]
    strays = [bb(1072, 280, 234, 48), bb(0, 10, 20, 20), bb(1403, 308, 231, 35)]
    out = _absorb(strays, real)
    assert [a.stray for a in out] == [0, 2]
    assert all(isinstance(a, Absorption) for a in out)


def test_thresholds_come_from_the_param_dict():
    stray = bb(218, 857, 244, 91)                   # the 53px scale bar
    real = [(bb(213, 1001, 828, 144), FIG, True)]
    assert _absorb([stray], real) == []
    loosened = dict(DEFAULTS, figtext_max_gap_frac=0.02)     # 60px on this page
    assert len(_absorb([stray], real, p=loosened)) == 1


def test_gap_gate_scales_with_page_height():
    """The gate is a fraction of page height, so the same pixel gap decides
    differently on a half-height page."""
    stray = bb(400, 90, 200, 20)
    real = [(bb(390, 122, 400, 500), FIG, True)]    # 12px gap
    assert len(_absorb([stray], real, page_h=3000)) == 1     # 15px allowance
    assert _absorb([stray], real, page_h=1000) == []         # 5px allowance
