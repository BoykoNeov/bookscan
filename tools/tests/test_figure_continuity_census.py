"""The continuity statistic and the pair rule, on synthetic pages."""

import numpy as np

from tools import figure_continuity_census as FC


def _fig(i, x, y, w, h, **kw):
    return {"id": i, "type": "figure", "bbox": {"x": x, "y": y, "w": w, "h": h}, **kw}


def test_continuous_picture_scores_low_and_a_printed_boundary_high():
    rng = np.random.default_rng(0)
    # one textured picture 200 rows tall; a seam at row 100 cuts nothing
    tex = rng.integers(0, 255, (200, 120, 3)).astype(np.uint8)
    D = FC.step_image(tex)
    cont = FC.continuity_c(D, 0, 120, (0, 100), (100, 200))["C"]
    # same texture, but rows 95..105 are flat paper: two pictures and a white line
    two = tex.copy()
    two[95:106] = 250
    D2 = FC.step_image(two)
    edge = FC.continuity_c(D2, 0, 120, (0, 95), (106, 200))["C"]
    assert cont < 0.2
    assert edge > 0.9


def test_pair_rule_needs_overlap_small_gap_and_no_figure_between():
    page = {"page_id": "p", "source_spread": "page_010", "height": 1000, "blocks": [
        _fig(0, 0, 0, 400, 200),
        _fig(1, 0, 220, 400, 200),       # 20 px below 0: a pair
        _fig(2, 600, 0, 200, 200),       # beside, no overlap: not a pair
        _fig(3, 0, 700, 400, 100),       # 280 px below 1 (> 5 %): not a pair
    ]}
    pairs = FC.find_pairs(page)
    assert [(p["a"], p["b"]) for p in pairs] == [(0, 1)]
    assert pairs[0]["class"] == "empty"


def test_a_text_block_in_the_gap_makes_the_class_between():
    page = {"page_id": "p", "source_spread": "page_010", "height": 1000, "blocks": [
        _fig(0, 0, 0, 400, 200),
        {"id": 5, "type": "caption", "bbox": {"x": 10, "y": 205, "w": 300, "h": 20}},
        _fig(1, 0, 240, 400, 200),
    ]}
    (p,) = FC.find_pairs(page)
    assert p["class"] == "between" and p["between"] == ["caption"]


def test_sofa_class_applies_only_to_the_named_spreads():
    page = {"page_id": "p", "source_spread": "page_001", "height": 1000, "blocks": [
        _fig(0, 0, 0, 400, 200), _fig(1, 0, 220, 400, 200)]}
    assert FC.find_pairs(page)[0]["class"] == "sofa_spread"
    assert FC.find_pairs(page, ())[0]["class"] == "empty"
