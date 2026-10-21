"""The vision-model book box: reading an answer, refusing a bad one, and the
guarantee that it never cuts pixels.

The model itself is not exercised here — a unit test must not need Ollama, and
what the model *says* is graded by tools/split_eval --vlm against real labels
(21/21, RESULTS 2026-08-29). What is tested here is everything around it: the
fixed coordinate convention, the refusals, and the separation of the search box
from the emit box that makes this path clip-free by construction.
"""
from __future__ import annotations

import numpy as np
import pytest

from pipeline import book_boundary as BB
from pipeline import vlm_box as VLM

W, H = 4000, 3000


def _frame() -> np.ndarray:
    return np.full((H, W, 3), 200, dtype=np.uint8)


# --------------------------------------------------------------------------
# Reading the answer
# --------------------------------------------------------------------------


def test_reads_the_documented_qwen_shape():
    box, how = VLM.parse_box('{"bbox_2d": [100, 200, 900, 800], "label": "book"}', W, H)
    assert how == "norm1000"
    assert box == (400, 600, 3600, 2400)


def test_reads_a_box_buried_in_chatty_prose():
    text = 'Sure! Here is the box:\n{"bbox_2d": [0, 0, 1000, 1000]}\nHope that helps.'
    box, how = VLM.parse_box(text, W, H)
    assert how == "norm1000"
    assert box == (0, 0, W, H)


def test_corners_given_in_the_wrong_diagonal_are_normalised():
    # x1<x0 is a corner-order slip, not a different convention: the box is the
    # same rectangle either way, so it is straightened rather than refused.
    box, _ = VLM.parse_box('[900, 800, 100, 200]', W, H)
    assert box == (400, 600, 3600, 2400)


def test_an_answer_with_no_four_number_list_is_refused():
    box, how = VLM.parse_box("I cannot see a book in this image.", W, H)
    assert box is None and how == "unparseable"


def test_pixel_coordinates_are_refused_not_reinterpreted():
    """The prompt asks for 0-1000. An answer in pixels is REFUSED.

    Rescuing it would mean choosing a reading per image, which is exactly the
    per-image selection that makes a box result unfalsifiable. Refusing costs
    only the pre-existing behaviour.
    """
    box, how = VLM.parse_box('[400, 600, 3600, 2400]', W, H)
    assert box is None and how == "out-of-range"


# --------------------------------------------------------------------------
# Refusing a box that cannot be a book
# --------------------------------------------------------------------------


@pytest.mark.parametrize("box,expect", [
    ((100, 100, 100, 900), "degenerate"),
    ((900, 100, 100, 900), "degenerate"),
    ((0, 0, W + 10, H), "outside the frame"),
    ((0, 0, 200, 200), "too small"),
    ((0, 0, W, H), "locates nothing"),
])
def test_implausible_boxes_are_named_and_rejected(box, expect):
    p = dict(VLM.DEFAULTS)
    assert expect in (VLM.plausible(box, W, H, p) or "")


def test_a_normal_book_box_is_accepted():
    p = dict(VLM.DEFAULTS)
    assert VLM.plausible((400, 300, 3600, 2700), W, H, p) is None


def test_a_full_frame_box_is_rejected_because_it_locates_nothing():
    # The whole point of asking is to narrow the spine search. A box that IS the
    # frame narrows nothing, so it must fall back rather than pretend to help.
    p = dict(VLM.DEFAULTS)
    assert VLM.plausible((0, 0, W, H), W, H, p) is not None


# --------------------------------------------------------------------------
# Failure is always the same failure
# --------------------------------------------------------------------------


def test_an_unreachable_server_returns_no_box_and_says_why():
    p = dict(VLM.DEFAULTS)
    p.update(url="http://127.0.0.1:9", timeout_s=2)   # nothing listens on port 9
    box, diag = VLM.find_box(_frame(), p)
    assert box is None
    assert diag["refused"], "a refusal must always carry its reason"
    assert "ms" in diag


def test_config_opts_in_and_the_default_is_off():
    assert VLM.resolve_params({})["enabled"] is False
    assert VLM.resolve_params({"vlm_box": {"enabled": True}})["enabled"] is True
    assert VLM.resolve_params({"vlm_box": {"model": "other"}})["model"] == "other"


# --------------------------------------------------------------------------
# The guarantee: it aims the search, it never cuts
# --------------------------------------------------------------------------


def test_search_only_keeps_the_emitted_pixels_exactly_as_they_were():
    """The load-bearing property. Emit is copied, so this path CANNOT clip."""
    img = _frame()
    base = BB.find_book(img, BB.resolve_params({}))
    out = BB.search_only(img, (400, 300, 3600, 2700), base, BB.resolve_params({}))
    assert out.emit == base.emit
    assert out.applied == base.applied
    assert out.reason == base.reason


def test_search_only_narrows_the_search_to_the_padded_box():
    img = _frame()
    p = BB.resolve_params({})
    base = BB.find_book(img, p)
    out = BB.search_only(img, (1000, 800, 3000, 2200), base, p)
    sx0, sy0, sx1, sy1 = out.search
    # Padded outward by search_pad, and strictly inside the frame it started from.
    assert sx0 < 1000 and sx1 > 3000
    assert (sx1 - sx0) < W, "a search window that is the whole frame narrows nothing"
    assert out.diag["search_source"] == "vlm"
    assert out.diag["vlm_box"] == [1000, 800, 3000, 2200]


def test_search_only_records_the_box_for_a_later_reader():
    img = _frame()
    p = BB.resolve_params({})
    out = BB.search_only(img, (400, 300, 3600, 2700), BB.find_book(img, p), p)
    assert out.diag["vlm_box"] == [400, 300, 3600, 2700]


# --------------------------------------------------------------------------
# The cut (owner's decision 2026-10-21) and the second question that gates it
# --------------------------------------------------------------------------


def test_the_cut_is_off_unless_config_turns_it_on():
    assert VLM.resolve_params({})["cut"] is False
    assert VLM.resolve_params({"vlm_box": {"cut": True}})["cut"] is True


def test_check_reads_four_booleans_out_of_a_fenced_answer():
    text = ('```json\n{"left": false, "right": true, "top": false, '
            '"bottom": false}\n```')
    assert VLM.parse_check(text) == {"left": False, "right": True,
                                     "top": False, "bottom": False}


@pytest.mark.parametrize("text", [
    '{"left": false, "right": false, "top": false}',            # an edge missing
    '{"left": "false", "right": false, "top": false, "bottom": false}',  # a string
    "No edge is cut off.",                                      # prose
])
def test_check_answers_that_are_not_four_booleans_are_refused(text):
    assert VLM.parse_check(text) is None


def test_only_edges_inside_the_frame_count_as_moved():
    assert VLM.moved_edges((0, 100, W, H - 5), W, H) == ["top", "bottom"]
    assert VLM.moved_edges((0, 0, W, H), W, H) == []


def _answers(check_text: str):
    def fake(p, prompt, b64):
        assert prompt == VLM.CHECK_PROMPT, "only the check may be asked here"
        return check_text
    return fake


def test_a_true_on_a_moved_edge_refuses_the_cut(monkeypatch):
    monkeypatch.setattr(VLM, "_ask", _answers(
        '{"left": true, "right": false, "top": false, "bottom": false}'))
    ok, diag = VLM.check_cut(_frame(), (300, 0, W, H))
    assert ok is False
    assert "left" in diag["refused"]


def test_a_true_on_an_edge_the_cut_did_not_move_is_ignored(monkeypatch):
    """The photographer cut the book there, not us; a tight shot must not refuse."""
    monkeypatch.setattr(VLM, "_ask", _answers(
        '{"left": false, "right": true, "top": true, "bottom": true}'))
    ok, diag = VLM.check_cut(_frame(), (300, 0, W, H))
    assert ok is True, diag
    assert diag["moved_edges"] == ["left"]


def test_an_unreadable_check_answer_refuses_the_cut(monkeypatch):
    monkeypatch.setattr(VLM, "_ask", _answers("I think it looks fine."))
    ok, diag = VLM.check_cut(_frame(), (300, 200, 3700, 2800))
    assert ok is False and diag["refused"]


def test_an_unreachable_server_refuses_the_cut():
    p = dict(VLM.DEFAULTS)
    p.update(url="http://127.0.0.1:9", timeout_s=2)
    ok, diag = VLM.check_cut(_frame(), (300, 200, 3700, 2800), p)
    assert ok is False and diag["refused"]


def test_model_cut_pads_exactly_as_a_hand_drawn_box_is_padded():
    """No new pad and no new value: the operator path's arithmetic."""
    img = _frame()
    p = BB.resolve_params({})
    box = (1000, 800, 3000, 2200)
    cut = BB.model_cut(img, box, BB.find_book(img, p), p)
    drawn = BB.user_box(img, box, p)
    assert cut.applied is True
    assert (cut.emit, cut.search) == (drawn.emit, drawn.search)
    assert cut.diag["emit_source"] == "vlm"


def test_model_cut_that_reaches_every_frame_edge_cuts_nothing():
    img = _frame()
    p = BB.resolve_params({})
    base = BB.find_book(img, p)
    cut = BB.model_cut(img, (50, 40, W - 50, H - 40), base, p)
    assert cut.applied == base.applied and cut.emit == base.emit
