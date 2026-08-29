"""Tests for pipeline/text_panel.py — the "is this figure really text?" pass.

None of these call a model. What is pinned here is the CONTRACT: two text
questions must agree, EITHER surface question may veto, and every failure path
must leave the block a figure.
"""
from __future__ import annotations

import numpy as np
import pytest

from pipeline import figure_surface as FS
from pipeline import text_panel as TP
from pipeline.page_model import BBox, Block, BlockType, Word


@pytest.fixture
def page() -> np.ndarray:
    return np.full((600, 400, 3), 200, np.uint8)


BOX = BBox(x=40, y=40, w=300, h=400)
ON = {**TP.DEFAULTS, "enabled": True}


def _answers(monkeypatch, crop: str, page_ans: str,
             surf_crop: str = "PAGE", surf_page: str = "PAPER") -> list[str]:
    """Stub the model, recording which prompts were actually asked."""
    asked: list[str] = []
    table = {TP.CROP_PROMPT: ("text_crop", crop),
             TP.PAGE_PROMPT: ("text_page", page_ans),
             FS.CROP_PROMPT: ("surface_crop", surf_crop),
             FS.PAGE_PROMPT: ("surface_page", surf_page)}

    def fake(image, prompt, max_side, p):
        label, answer = table[prompt]
        asked.append(label)
        return answer

    monkeypatch.setattr(FS, "_ask", fake)
    return asked


def test_both_text_answers_promote(page, monkeypatch):
    _answers(monkeypatch, "TEXT", "TEXT")
    ok, diag = TP.is_text_panel(page, BOX, 20, ON)
    assert ok is True
    assert diag["crop_answer"] == "TEXT" and diag["page_answer"] == "TEXT"


@pytest.mark.parametrize("crop,page_ans", [
    ("PICTURE", "TEXT"),
    ("TEXT", "PICTURE"),    # the context arm's real saves look like this: a photo
    ("PICTURE", "PICTURE"), # banner, and a photograph of an information board
])
def test_one_text_answer_is_never_enough(page, monkeypatch, crop, page_ans):
    _answers(monkeypatch, crop, page_ans)
    ok, _ = TP.is_text_panel(page, BOX, 20, ON)
    assert ok is False


@pytest.mark.parametrize("surf_crop,surf_page", [
    ("SURFACE", "PAPER"),   # what the three upholstery blocks answered
    ("PAGE", "SURFACE"),
    ("SURFACE", "SURFACE"),
])
def test_either_surface_arm_vetoes(page, monkeypatch, surf_crop, surf_page):
    """Deliberately a WEAKER bar than figure_surface's own, and in the opposite
    direction: flagging a block surface deletes real content so it needs both
    arms, while refusing to promote costs only a picture that stays a picture.
    Without this veto, 3 of 21 promotions on the owner's book are out-of-focus
    upholstery that both TEXT questions confidently call text."""
    _answers(monkeypatch, "TEXT", "TEXT", surf_crop, surf_page)
    ok, _ = TP.is_text_panel(page, BOX, 20, ON)
    assert ok is False


def test_the_surface_veto_can_be_switched_off_for_the_ab(page, monkeypatch):
    _answers(monkeypatch, "TEXT", "TEXT", "SURFACE", "SURFACE")
    ok, diag = TP.is_text_panel(page, BOX, 20, {**ON, "surface_veto": False})
    assert ok is True and "surface_crop" not in diag


def test_a_no_from_an_earlier_arm_does_not_pay_for_the_later_ones(page, monkeypatch):
    """Each question costs about a second and a later one can only take a
    promotion away, never grant it, so it must not be asked."""
    asked = _answers(monkeypatch, "PICTURE", "TEXT")
    TP.is_text_panel(page, BOX, 20, ON)
    assert asked == ["text_crop"]

    asked = _answers(monkeypatch, "TEXT", "PICTURE")
    TP.is_text_panel(page, BOX, 20, ON)
    assert asked == ["text_crop", "text_page"]

    asked = _answers(monkeypatch, "TEXT", "TEXT", "SURFACE")
    TP.is_text_panel(page, BOX, 20, ON)
    assert asked == ["text_crop", "text_page", "surface_crop"]


def test_a_dead_service_keeps_the_figure(page, monkeypatch):
    """_ask returns "" for every failure — no Ollama, a timeout, a bad response.
    A missing local service must never change a scan's outcome."""
    monkeypatch.setattr(FS, "_ask", lambda *a, **k: "")
    ok, _ = TP.is_text_panel(page, BOX, 20, ON)
    assert ok is False


def test_a_block_with_too_few_words_is_not_asked_about(page, monkeypatch):
    """Sweeping min_words from 8 to 3 adds 15 candidates on the book this was
    measured on and promotes none of them."""
    asked = _answers(monkeypatch, "TEXT", "TEXT")
    ok, diag = TP.is_text_panel(page, BOX, 3, ON)
    assert ok is False and asked == []
    assert "min_words" in diag["refused"]


def test_a_degenerate_bbox_is_refused_not_raised(page, monkeypatch):
    _answers(monkeypatch, "TEXT", "TEXT")
    ok, diag = TP.is_text_panel(page, BBox(x=10, y=10, w=0, h=50), 20, ON)
    assert ok is False and diag["refused"] == "degenerate bbox"


def test_a_bbox_running_past_the_page_is_clamped(page, monkeypatch):
    _answers(monkeypatch, "TEXT", "TEXT")
    ok, _ = TP.is_text_panel(page, BBox(x=300, y=400, w=999, h=999), 20, ON)
    assert ok is True


def test_the_pass_is_off_unless_configured():
    """Same contract as figure_surface and vlm_box: it needs a local service
    that may not be running, so config opts in rather than out."""
    assert TP.DEFAULTS["enabled"] is False
    assert TP.resolve_params({})["enabled"] is False
    assert TP.resolve_params({"text_panel": {"enabled": True}})["enabled"] is True


def _blocks() -> list[Block]:
    words = [Word(text=f"w{i}", bbox=BBox(x=i, y=0, w=5, h=5), conf=90.0,
                  line_id=0, block_id=1) for i in range(12)]
    return [Block(id=1, type=BlockType.FIGURE, bbox=BOX, reading_order=0,
                  words=words),
            Block(id=2, type=BlockType.PARAGRAPH, bbox=BOX, reading_order=1,
                  words=list(words))]


def test_promotion_keeps_everything_but_the_type(page, monkeypatch):
    """A wrongly promoted picture is GONE from the render (Stage 08 renders a
    paragraph from its words), so recoverability is the safety net: the block
    keeps its id, bbox, words and reading order, and type_promoted marks the
    change as automatic rather than as a user edit."""
    _answers(monkeypatch, "TEXT", "TEXT")
    blocks, notes = TP.promote_text_panels(_blocks(), page, ON)
    b = blocks[0]
    assert b.type is BlockType.PARAGRAPH and b.type_promoted is True
    assert (b.id, b.reading_order, b.bbox) == (1, 0, BOX)
    assert len(b.words) == 12
    assert [n.block_id for n in notes] == [1]
    assert notes[0].n_words == 12


def test_only_figures_are_candidates(page, monkeypatch):
    """Nothing may re-type a block that is already text — this pass exists to
    undo one Stage 04 call, not to second-guess every one."""
    asked = _answers(monkeypatch, "PICTURE", "TEXT")
    TP.promote_text_panels(_blocks(), page, ON)
    assert asked == ["text_crop"]           # block 2 (a paragraph) never asked about


def test_the_pass_is_inert_when_disabled(page, monkeypatch):
    asked = _answers(monkeypatch, "TEXT", "TEXT")
    blocks, notes = TP.promote_text_panels(_blocks(), page, TP.DEFAULTS)
    assert asked == [] and notes == []
    assert blocks[0].type is BlockType.FIGURE


def test_a_missing_page_image_is_not_a_crash(monkeypatch):
    _answers(monkeypatch, "TEXT", "TEXT")
    blocks, notes = TP.promote_text_panels(_blocks(), None, ON)
    assert notes == [] and blocks[0].type is BlockType.FIGURE


def test_promoted_blocks_stop_being_invisible_to_block_reocr():
    """The whole reason this runs before the starved-block re-read: that module
    skips FIGURE blocks, so a promoted panel is re-read for free."""
    from pipeline import block_reocr as BR
    assert BlockType.FIGURE in BR.SKIP_TYPES
    assert TP.PROMOTED_TYPE not in BR.SKIP_TYPES
