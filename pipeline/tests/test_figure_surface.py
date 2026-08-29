"""Tests for pipeline/figure_surface.py — the "is this block the sofa?" pass.

None of these call a model. What is worth pinning here is the CONTRACT: two
questions must agree, and every failure path must leave the block alone.
"""
from __future__ import annotations

import numpy as np
import pytest

from pipeline import figure_surface as FS
from pipeline.page_model import Block, BlockType, BBox


@pytest.fixture
def page() -> np.ndarray:
    return np.full((600, 400, 3), 200, np.uint8)


BOX = {"x": 40, "y": 40, "w": 300, "h": 400}


def _answers(monkeypatch, crop: str, page_ans: str) -> list[str]:
    """Stub the model, recording which prompts were actually asked."""
    asked: list[str] = []

    def fake(image, prompt, max_side, p):
        asked.append("crop" if prompt is FS.CROP_PROMPT else "page")
        return crop if prompt is FS.CROP_PROMPT else page_ans

    monkeypatch.setattr(FS, "_ask", fake)
    return asked


def test_both_answers_must_say_surface(page, monkeypatch):
    _answers(monkeypatch, "SURFACE", "SURFACE")
    flagged, diag = FS.is_surface(page, BOX, {**FS.DEFAULTS, "enabled": True})
    assert flagged is True
    assert diag["crop_answer"] == "SURFACE" and diag["page_answer"] == "SURFACE"


@pytest.mark.parametrize("crop,page_ans", [
    ("PAGE", "SURFACE"),     # the crop arm's own false positives look like this
    ("SURFACE", "PAPER"),    # ...and the context arm's
    ("PAGE", "PAPER"),
])
def test_one_answer_is_never_enough(page, monkeypatch, crop, page_ans):
    """Each single question was measured discarding real book content — a
    printed photo of an information board, and a tilted chapter banner. Only
    their intersection lost nothing (RESULTS 2026-08-29)."""
    _answers(monkeypatch, crop, page_ans)
    flagged, _ = FS.is_surface(page, BOX, {**FS.DEFAULTS, "enabled": True})
    assert flagged is False


def test_a_no_from_the_crop_arm_does_not_pay_for_the_second_question(page, monkeypatch):
    """The second call costs a second per figure and cannot turn a no into a
    yes, so it must not be made."""
    asked = _answers(monkeypatch, "PAGE", "SURFACE")
    FS.is_surface(page, BOX, {**FS.DEFAULTS, "enabled": True})
    assert asked == ["crop"]


def test_a_dead_service_keeps_the_block(page, monkeypatch):
    """_ask returns "" for every failure — no Ollama, a timeout, a bad
    response. A missing local service must never change a scan's outcome."""
    monkeypatch.setattr(FS, "_ask", lambda *a, **k: "")
    flagged, _ = FS.is_surface(page, BOX, {**FS.DEFAULTS, "enabled": True})
    assert flagged is False


def test_a_tiny_block_is_not_asked_about(page, monkeypatch):
    """Slivers are where both arms were worst, and are nobody's complaint."""
    asked = _answers(monkeypatch, "SURFACE", "SURFACE")
    flagged, diag = FS.is_surface(page, {"x": 0, "y": 0, "w": 20, "h": 20},
                                  {**FS.DEFAULTS, "enabled": True})
    assert flagged is False and asked == []
    assert "covers" in diag["refused"]


def test_a_degenerate_bbox_is_refused_not_raised(page, monkeypatch):
    _answers(monkeypatch, "SURFACE", "SURFACE")
    flagged, diag = FS.is_surface(page, {"x": 10, "y": 10, "w": 0, "h": 50},
                                  {**FS.DEFAULTS, "enabled": True})
    assert flagged is False and diag["refused"] == "degenerate bbox"


def test_a_bbox_running_past_the_page_is_clamped(page, monkeypatch):
    """Stage 04 boxes can touch or exceed the page edge; clamping keeps the
    crop non-empty instead of handing the model a zero-size image."""
    _answers(monkeypatch, "SURFACE", "SURFACE")
    flagged, _ = FS.is_surface(page, {"x": 300, "y": 400, "w": 999, "h": 999},
                               {**FS.DEFAULTS, "enabled": True})
    assert flagged is True


def test_the_pass_is_off_unless_configured():
    """Same contract as vlm_box: it needs a local service that may not be
    running, so config opts in rather than out."""
    assert FS.DEFAULTS["enabled"] is False
    assert FS.resolve_params({})["enabled"] is False
    assert FS.resolve_params({"figure_surface": {"enabled": True}})["enabled"] is True


def test_a_flagged_block_is_marked_not_deleted():
    """The schema carries a flag precisely so a wrong call is recoverable: the
    block keeps its id, bbox, words and reading order."""
    blk = Block(id=3, type=BlockType.FIGURE, bbox=BBox(x=0, y=0, w=10, h=10),
                reading_order=2)
    assert blk.is_surface is False
    blk.is_surface = True
    assert (blk.id, blk.reading_order, blk.type) == (3, 2, BlockType.FIGURE)
