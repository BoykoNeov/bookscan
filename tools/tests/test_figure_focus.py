"""tools/figure_focus_labels + tools/figure_focus_eval (hand-off item 5, prereg
docs/data/figure_focus_prereg_20261112.md): the statistic's controls, the blind
decode, and the refusal to score before every verdict is in."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools import figure_focus_eval as E
from tools import figure_focus_labels as L


def _texture(h=120, w=160, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.random((h, w, 3)) * 255).astype(np.uint8)


def test_ratio_of_a_picture_against_itself_is_exactly_one():
    a = _texture()
    assert E.focus_ratio(a, a) == 1.0


def test_blurred_copy_scores_below_one():
    a = _texture()
    assert E.focus_ratio(cv2.GaussianBlur(a, (0, 0), 2.0), a) < 1.0


def test_upgrade_is_shrunk_to_the_crop_size_not_the_other_way():
    crop = _texture(60, 80)
    big = cv2.resize(crop, (160, 120), interpolation=cv2.INTER_NEAREST)
    # nearest-neighbour enlargement shrunk back by area averaging returns the crop
    assert abs(E.focus_ratio(big, crop) - 1.0) < 1e-6


def test_decode_maps_a_side_to_a_verdict_about_the_upgrade():
    assert L.decode("left", "upgrade") == "upgrade_sharper"
    assert L.decode("right", "upgrade") == "crop_sharper"
    assert L.decode("left", "crop") == "crop_sharper"
    assert L.decode("right", "crop") == "upgrade_sharper"
    assert L.decode("cannot_tell", "crop") == "cannot_tell"


def test_blind_order_is_fixed_by_the_seed_and_uses_both_sides():
    a, b = L.blind_order(40), L.blind_order(40)
    assert a == b and set(a) == {"crop", "upgrade"}


def test_score_refuses_incomplete_labels():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "labels.json"
        p.write_text(json.dumps({"job": "x", "complete": False,
                                 "items": [{"answer": "left"}, {"answer": None}]}))
        with pytest.raises(SystemExit):
            E.cmd_score(p, Path(td))
