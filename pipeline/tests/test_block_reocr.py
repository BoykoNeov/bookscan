"""Unit tests for ``pipeline.block_reocr`` — re-reading a text block the
full-subpage OCR pass starved.

The risk here is not "does Tesseract read better" (that is measured on real
pixels in docs/RESULTS.md); it is that this is the ONE pass allowed to change a
block's word set rather than move it. So these tests pin the two things that can
silently corrupt a document: the ACCEPTANCE rule (a worse read must never win)
and the COORDINATE map (a rescued word's box must land where the ink is, because
Stage 06 patch-mode crops the full-res dewarp from exactly that box).

No Tesseract here — ``run_tesseract`` is monkeypatched so the decision logic and
the bookkeeping are what is under test.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import block_reocr as BR
from pipeline.page_model import BBox, Block, BlockType, Word

PAGE = np.zeros((3000, 2080, 3), dtype=np.uint8)


def _tsv(rows: list[tuple[str, float, int, int, int, int]],
         line_of: list[int] | None = None) -> str:
    """Build a Tesseract TSV whose level-5 rows are ``rows``."""
    head = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext")
    out = [head]
    for i, (text, conf, left, top, w, h) in enumerate(rows):
        ln = line_of[i] if line_of else 1
        out.append(f"5\t1\t1\t1\t{ln}\t{i + 1}\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}")
    return "\n".join(out)


def _block(words: list[Word], bbox=(1527, 2464, 501, 223),
           btype=BlockType.PARAGRAPH, bid=22) -> Block:
    x, y, w, h = bbox
    return Block(id=bid, type=btype, bbox=BBox(x=x, y=y, w=w, h=h),
                 reading_order=bid, words=words)


def _word(text, conf=77.5, x=1530, y=2470, w=40, h=28, line_id=3) -> Word:
    return Word(text=text, bbox=BBox(x=x, y=y, w=w, h=h), conf=conf,
                engine="tesseract", line_id=line_id, block_id=22, decision=None)


def _patch(monkeypatch, tsv: str):
    monkeypatch.setattr(BR, "run_tesseract",
                        lambda *a, **k: tsv)


# --------------------------------------------------------------------------
# Acceptance — a comparison against this block's own page-pass score
# --------------------------------------------------------------------------


def test_more_words_and_higher_conf_is_rescued(monkeypatch):
    """The it_geo_07 T5right shape: 2 starved words, a re-read with 4 better ones."""
    _patch(monkeypatch, _tsv([("In", 90.0, 3, 6, 30, 24), ("questo", 92.0, 40, 6, 70, 24),
                              ("contesto", 91.0, 3, 40, 90, 24), ("nel", 93.0, 100, 40, 40, 24)]))
    blk = _block([_word("In"), _word("cont,")])
    out, notes, dropped, added = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=9)
    assert [n.block_id for n in notes] == [22]
    assert (dropped, added) == (2, 4)
    assert [w.text for w in out[0].words] == ["In", "questo", "contesto", "nel"]


def test_more_words_but_lower_conf_is_refused(monkeypatch):
    """The junk-from-a-neighbour shape: extra tokens bought with worse reads."""
    _patch(monkeypatch, _tsv([("La", 40.0, 3, 6, 30, 24), ("Dolomia", 42.0, 40, 6, 70, 24),
                              ("XX", 38.0, 3, 40, 90, 24)]))
    blk = _block([_word("La", conf=93.8), _word("Dolomia", conf=93.8)])
    out, notes, dropped, added = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=9)
    assert notes == [] and (dropped, added) == (0, 0)
    assert [w.text for w in out[0].words] == ["La", "Dolomia"]


def test_fewer_words_is_refused_even_when_cleaner(monkeypatch):
    """The de_01 #1 shape — a clearly BETTER read that this rule deliberately
    rejects, because it rescues starvation and not garbling. Scope limit, pinned."""
    _patch(monkeypatch, _tsv([("Talort", 99.0, 3, 6, 60, 24)]))
    blk = _block([_word("Ta", conf=71.4), _word("lort", conf=71.4)])
    out, notes, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "deu", 1, 1.0, next_line_id=9)
    assert notes == []
    assert [w.text for w in out[0].words] == ["Ta", "lort"]


def test_empty_block_accepts_any_read(monkeypatch):
    """A block the page pass read as nothing is invisible to Stage 06; any words
    at all beat none, and a bad one arrives WITH its low confidence attached."""
    _patch(monkeypatch, _tsv([("Piattaforma", 96.3, 3, 6, 90, 24)]))
    blk = _block([], btype=BlockType.CAPTION, bid=16)
    out, notes, dropped, added = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert (dropped, added) == (0, 1)
    assert notes[0].conf_before == 0.0 and notes[0].n_after == 1
    assert out[0].words[0].conf == pytest.approx(96.3)


def test_equal_word_count_is_refused(monkeypatch):
    """Strictly MORE words. An equal-count re-read is not a rescue, however
    confident — swapping text on a whim is not what was measured."""
    _patch(monkeypatch, _tsv([("In", 99.0, 3, 6, 30, 24), ("questo", 99.0, 40, 6, 70, 24)]))
    blk = _block([_word("In"), _word("cont,")])
    _, notes, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=9)
    assert notes == []


# --------------------------------------------------------------------------
# The coordinate contract — Stage 06 patch-mode crops from these boxes
# --------------------------------------------------------------------------


def test_rescued_boxes_are_page_coords_not_crop_coords(monkeypatch):
    """A word at (3, 6) INSIDE the crop of a block at (1527, 2464) must be stored
    at (1530, 2470). Get this wrong and every patch crop is offset by the block
    origin — silently, because the text still looks right."""
    _patch(monkeypatch, _tsv([("In", 90.0, 3, 6, 30, 24), ("questo", 90.0, 40, 6, 70, 24),
                              ("nel", 90.0, 3, 40, 40, 24)]))
    blk = _block([_word("In")])
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    boxes = [(w.bbox.x, w.bbox.y, w.bbox.w, w.bbox.h) for w in out[0].words]
    assert boxes == [(1530, 2470, 30, 24), (1567, 2470, 70, 24), (1530, 2504, 40, 24)]


def test_rescued_boxes_divide_by_the_page_upscale(monkeypatch):
    """When the subpage pass ran at 2x, the crop was upscaled too, so the re-read's
    boxes are in 2x coords and must be halved BEFORE the block origin is added —
    the same ``/scale`` map-back Stage 05's ``_word_box`` does."""
    _patch(monkeypatch, _tsv([("In", 90.0, 6, 12, 60, 48), ("questo", 90.0, 80, 12, 140, 48)]))
    blk = _block([_word("In")])
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 2.0, next_line_id=0)
    assert [(w.bbox.x, w.bbox.y, w.bbox.w, w.bbox.h) for w in out[0].words] == [
        (1530, 2470, 30, 24), (1567, 2470, 70, 24)]


def test_padding_shifts_the_origin_it_read_from(monkeypatch):
    """With padding on, the crop starts ABOVE and LEFT of the block, so the origin
    added back must be the padded one or every box drifts by the pad."""
    _patch(monkeypatch, _tsv([("In", 90.0, 0, 0, 30, 24), ("questo", 90.0, 40, 0, 70, 24)]))
    blk = _block([_word("In")])
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0, p={"pad_px": 10})
    assert (out[0].words[0].bbox.x, out[0].words[0].bbox.y) == (1517, 2454)


# --------------------------------------------------------------------------
# Bookkeeping the rest of Stage 05 depends on
# --------------------------------------------------------------------------


def test_line_ids_are_seeded_past_the_page_pass(monkeypatch):
    """Line ids are per-subpage and Stage 06 de-hyphenates on them, so a rescued
    block must not reuse an id another block already holds."""
    _patch(monkeypatch, _tsv(
        [("In", 90.0, 3, 6, 30, 24), ("questo", 90.0, 40, 6, 70, 24),
         ("nel", 90.0, 3, 40, 40, 24)], line_of=[1, 1, 2]))
    blk = _block([_word("In", line_id=3)])
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=17)
    assert [w.line_id for w in out[0].words] == [17, 17, 18]


def test_block_id_is_synced_on_rescued_words(monkeypatch):
    _patch(monkeypatch, _tsv([("a", 90.0, 3, 6, 30, 24), ("b", 90.0, 40, 6, 30, 24)]))
    blk = _block([_word("a")], bid=7)
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert {w.block_id for w in out[0].words} == {7}


def test_figures_are_never_touched(monkeypatch):
    """A figure's words are artwork lettering (or a caption ``caption_eject`` has
    already ruled on). Re-reading a picture as a uniform text block is not what
    this measured."""
    _patch(monkeypatch, _tsv([("x", 99.0, 3, 6, 30, 24), ("y", 99.0, 40, 6, 30, 24),
                              ("z", 99.0, 80, 6, 30, 24)]))
    blk = _block([_word("BELLUNO", conf=49.9)], btype=BlockType.FIGURE, bid=5)
    _, notes, dropped, added = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert notes == [] and (dropped, added) == (0, 0)


def test_disabled_is_a_no_op(monkeypatch):
    _patch(monkeypatch, _tsv([("a", 99.0, 3, 6, 30, 24), ("b", 99.0, 40, 6, 30, 24)]))
    blk = _block([_word("junk", conf=10.0)])
    out, notes, dropped, added = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0, p={"enabled": False})
    assert notes == [] and (dropped, added) == (0, 0)
    assert [w.text for w in out[0].words] == ["junk"]


def test_a_tesseract_failure_leaves_the_page_alone(monkeypatch):
    """A rescue that cannot run must be a no-op, never a block emptied."""
    def boom(*a, **k):
        raise RuntimeError("tesseract exploded")
    monkeypatch.setattr(BR, "run_tesseract", boom)
    blk = _block([_word("In"), _word("cont,")])
    out, notes, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert notes == []
    assert [w.text for w in out[0].words] == ["In", "cont,"]


def test_a_block_smaller_than_the_geometry_floor_is_skipped(monkeypatch):
    _patch(monkeypatch, _tsv([("a", 99.0, 0, 0, 5, 5), ("b", 99.0, 6, 0, 5, 5)]))
    blk = _block([], bbox=(100, 100, 8, 8))
    _, notes, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert notes == []


def test_dropped_and_added_close_stage05s_amended_invariant(monkeypatch):
    """Stage 05 asserts ``attached == recognized - dropped + added``. That only
    holds if the counts this returns describe EVERY block it changed, so compose
    them over a mixed page: one rescued, one refused, one figure skipped."""
    _patch(monkeypatch, _tsv([("a", 95.0, 3, 6, 30, 24), ("b", 95.0, 40, 6, 30, 24),
                              ("c", 95.0, 80, 6, 30, 24)]))
    rescued = _block([_word("a", conf=50.0)], bid=1)
    refused = _block([_word("x", conf=99.0), _word("y", conf=99.0),
                      _word("z", conf=99.0), _word("w", conf=99.0)], bid=2)
    figure = _block([_word("BELLUNO", conf=49.9)], btype=BlockType.FIGURE, bid=3)
    recognized = sum(len(b.words) for b in (rescued, refused, figure))
    out, _, dropped, added = BR.rescue_starved_blocks(
        [rescued, refused, figure], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert sum(len(b.words) for b in out) == recognized - dropped + added
    assert (dropped, added) == (1, 3)


def test_conf_is_clamped_into_the_0_100_band(monkeypatch):
    """Tesseract emits -1 for structural rows; ``parse_tsv`` drops those, but the
    clamp is what Stage 06's percentile maths relies on."""
    _patch(monkeypatch, _tsv([("a", 150.0, 3, 6, 30, 24), ("b", 120.0, 40, 6, 30, 24)]))
    blk = _block([_word("a", conf=50.0)])
    out, _, _, _ = BR.rescue_starved_blocks(
        [blk], PAGE, "tess", "", "ita", 1, 1.0, next_line_id=0)
    assert all(0.0 <= w.conf <= 100.0 for w in out[0].words)
