"""Scoring rules of the per-page selection probe.

The probe's expensive half (split, dewarp, Tesseract) is measured on real
fixtures and is not what these tests are for. What they pin is the ARITHMETIC on
top of those numbers — the part that decides what the probe reports, and the part
that quietly changed once already when a 142-vs-142 tie was being reported as
"the two sides disagree".
"""

from __future__ import annotations

import numpy as np

from tools.perpage_choice_probe import (
    CHURN_WORDS,
    _poly_page_coverage,
    proxy_agreement,
    verdict,
)


def _side(words: int, conf: float, sharp: float = 100.0,
          glyph: float = 8.0, ink: float = 0.1) -> dict:
    return {
        "dewarp_conf_ge_80": words, "dewarp_mean_conf": conf,
        "proxy_flat": {"sharp": sharp, "glyph_px": glyph, "ink_frac": ink},
        "proxy_dewarp": {"sharp": sharp, "glyph_px": glyph, "ink_frac": ink},
    }


def _frame(fid: str, left: dict, right: dict | None = None) -> dict:
    sides = {"left.png": left} if right is None else {"left.png": left,
                                                      "right.png": right}
    if right is None:
        sides = {"single.png": left}
    return {"id": fid, "two_sided": right is not None, "sides": sides}


def test_a_tie_is_not_a_disagreement_between_the_sides():
    """Both frames reading the same word count on a side is no opinion at all.

    This is the zoomset_en_02 case: 142 words each on the right page, and the
    first-listed frame was being crowned by ``max``, which turned a tie into a
    reported "the sides prefer different photographs".
    """
    frames = [
        _frame("a", _side(114, 90.9), _side(142, 75.2)),
        _frame("b", _side(106, 83.2), _side(142, 85.2)),
    ]
    v = verdict(frames, "a")
    assert v["races"]["right.png"]["tie"] is True
    assert v["races"]["right.png"]["winner"] is None
    assert v["races"]["right.png"]["tied_between"] == ["a", "b"]
    assert v["tie_on_a_side"] is True
    assert v["same_winner_both_sides"] is False


def test_gain_needs_both_statistics_and_the_full_churn_floor():
    """More words alone is not a gain, and the floor is not rescaled per side."""
    over_words_only = [
        _frame("pick", _side(100, 90.0), _side(100, 90.0)),
        _frame("rival", _side(100 + CHURN_WORDS + 1, 89.0), _side(50, 80.0)),
    ]
    assert verdict(over_words_only, "pick")["per_page_gain"] is False

    inside_the_floor = [
        _frame("pick", _side(100, 90.0), _side(100, 90.0)),
        _frame("rival", _side(100 + CHURN_WORDS, 95.0), _side(50, 80.0)),
    ]
    assert verdict(inside_the_floor, "pick")["per_page_gain"] is False

    clears_it = [
        _frame("pick", _side(100, 90.0), _side(100, 90.0)),
        _frame("rival", _side(100 + CHURN_WORDS + 1, 95.0), _side(50, 80.0)),
    ]
    v = verdict(clears_it, "pick")
    assert v["per_page_gain"] is True
    assert v["races"]["left.png"]["gain_by"] == ["rival"]


def test_a_frame_that_does_not_split_cannot_be_a_page_source():
    frames = [
        _frame("splits", _side(200, 90.0), _side(200, 90.0)),
        _frame("single", _side(900, 99.0)),          # would win on any statistic
    ]
    v = verdict(frames, "splits")
    assert v["ineligible_single_page"] == ["single"]
    assert v["eligible"] == ["splits"]
    assert v["per_page_measurable"] is False
    assert v["races"]["left.png"]["challengers"] == []


def test_proxy_agreement_reports_chance_not_just_hits():
    """A two-way race is won by a coin flip half the time; three-way, a third."""
    out = {
        "two": {"frames": [_frame("a", _side(200, 90.0, sharp=10.0)),
                           _frame("b", _side(100, 80.0, sharp=99.0))]},
        "three": {"frames": [
            _frame("a", _side(200, 90.0, sharp=99.0), _side(200, 90.0, sharp=99.0)),
            _frame("b", _side(100, 80.0, sharp=10.0), _side(100, 80.0, sharp=10.0)),
            _frame("c", _side(50, 70.0, sharp=1.0), _side(50, 70.0, sharp=1.0)),
        ]},
    }
    # "two" holds single-page frames, so it contributes no race at all.
    pa = proxy_agreement(out)
    assert pa["races"] == 2
    assert pa["expected_by_chance"] == 0.7          # 2 x 1/3, rounded
    assert pa["hits"]["sharp@flat"] == 2


def test_page_coverage_is_the_fraction_of_the_PAGE_the_footprint_covers():
    """Not the fraction of the frame — the bar in rule 6 is about the page."""
    shape = (100, 200)
    page = (100, 0, 100, 100)                        # the right half
    whole = [[0, 0], [200, 0], [200, 100], [0, 100]]
    assert _poly_page_coverage(whole, page, shape) == 1.0
    # A footprint that covers the whole LEFT half covers none of the right page,
    # even though it is half the frame.
    left = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert _poly_page_coverage(left, page, shape) < 0.02
    # Half the page: the bar (0.98) must reject this.
    half = [[100, 0], [150, 0], [150, 100], [100, 100]]
    assert 0.45 <= _poly_page_coverage(half, page, shape) <= 0.55


def test_page_coverage_clips_a_footprint_that_leaves_the_frame():
    shape = (100, 200)
    page = (150, 50, 100, 100)                       # runs off the right/bottom
    whole = [[0, 0], [200, 0], [200, 100], [0, 100]]
    cov = _poly_page_coverage(np.array(whole).tolist(), page, shape)
    assert 0.0 < cov <= 1.0
