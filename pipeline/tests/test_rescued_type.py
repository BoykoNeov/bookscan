"""Tests for pipeline.rescued_type — typing the blocks Stage 05 rescues.

The fixtures are the REAL geometry of the two blocks that decide this rule, taken
from the 2026-08-26 census of all 16 rescued blocks on the block-order GT subpages
(docs/data/rescued_type_census_20260826.json):

  * ``_true_footnote()`` — en_coins_01 left: "1 Spalding, Eastern Exchange Currency
    and Finance, (314)." at y=2704, 8 words of height 24, under a paragraph column
    at y=2492..2675 whose words are height 28. The one rescued block in the corpus
    that is body text the document should carry.
  * ``_bottom_margin_noise()`` — it_geo_07 right: "i: dad aan" at y=2874, 3 words of
    height 39, below the body but overlapping NO text column. Same *shape* as the
    footnote on the "below the body" test alone; it is the column condition that
    tells them apart, so it is tested explicitly rather than assumed.

Everything else is a guard on a way the rule could be talked into a wrong call.
"""

from __future__ import annotations

import pytest

from pipeline import rescued_type as RT
from pipeline.page_model import Block, BlockType, Word


def _blk(btype: BlockType, x: int, y: int, w: int, h: int,
         n_words: int = 0, word_h: int = 0, block_id: int = 0) -> Block:
    """A block whose words are laid out left-to-right on one line, so the median
    word height is exactly ``word_h``."""
    words = [
        Word(text=f"w{i}", bbox={"x": x + i * 10, "y": y, "w": 8, "h": word_h},
             conf=90.0, block_id=block_id)
        for i in range(n_words)
    ]
    return Block(id=block_id, type=btype, bbox={"x": x, "y": y, "w": w, "h": h},
                 reading_order=block_id, words=words)


def _page_real() -> list[Block]:
    """en_coins_01 left, the blocks that matter: the column the footnote hangs
    under, an earlier column, a side-set caption, and the page number BELOW the
    footnote (which must not count as body, or nothing is ever 'below the body')."""
    return [
        _blk(BlockType.PARAGRAPH, 170, 1008, 1819, 317, n_words=134, word_h=29, block_id=1),
        _blk(BlockType.CAPTION, 1324, 2070, 603, 322, n_words=52, word_h=25, block_id=2),
        _blk(BlockType.PARAGRAPH, 91, 2492, 1854, 183, n_words=79, word_h=28, block_id=3),
        _blk(BlockType.PAGE_NUMBER, 1000, 2809, 58, 35, n_words=1, word_h=30, block_id=4),
    ]


def _true_footnote() -> Block:
    return _blk(BlockType.OTHER, 102, 2704, 723, 31, n_words=8, word_h=24, block_id=-1)


def _bottom_margin_noise() -> Block:
    """Below the body, but sitting outside every text column (x=1500..1900 against a
    column spanning 91..1945 would still overlap — the real one does not, because on
    that page the strays sit past the column's right edge)."""
    return _blk(BlockType.OTHER, 1960, 2874, 120, 126, n_words=3, word_h=39, block_id=-1)


# --------------------------------------------------------------------------
# The rung fires on the one true positive
# --------------------------------------------------------------------------


def test_true_footnote_is_typed_footnote():
    [v] = RT.type_rescued([_true_footnote()], _page_real())
    assert v.type is BlockType.FOOTNOTE
    assert "below the body" in v.reason and "ratio 0.86" in v.reason


def test_page_number_below_it_does_not_block_the_call():
    """A footnote sits above the page number; page numbers and headers are excluded
    from 'the body' precisely so this still works."""
    real = _page_real()
    assert any(b.type is BlockType.PAGE_NUMBER for b in real)
    [v] = RT.type_rescued([_true_footnote()], real)
    assert v.type is BlockType.FOOTNOTE


# --------------------------------------------------------------------------
# ...and abstains everywhere else
# --------------------------------------------------------------------------


def test_bottom_margin_noise_is_left_as_other():
    """The discriminator that carries the rule: same 'below the body' shape, but it
    hangs under no text column."""
    [v] = RT.type_rescued([_bottom_margin_noise()], _page_real())
    assert v.type is BlockType.OTHER


def test_a_block_inside_the_body_is_left_as_other():
    mid = _blk(BlockType.OTHER, 200, 1400, 700, 31, n_words=8, word_h=24, block_id=-1)
    [v] = RT.type_rescued([mid], _page_real())
    assert v.type is BlockType.OTHER


def test_too_few_words_is_left_as_other():
    tiny = _blk(BlockType.OTHER, 102, 2704, 723, 31, n_words=2, word_h=24, block_id=-1)
    [v] = RT.type_rescued([tiny], _page_real())
    assert v.type is BlockType.OTHER


def test_not_smaller_than_its_column_is_left_as_other():
    """Body-sized text under the last column is a continuation, not a footnote."""
    same = _blk(BlockType.OTHER, 102, 2704, 723, 31, n_words=8, word_h=28, block_id=-1)
    [v] = RT.type_rescued([same], _page_real())
    assert v.type is BlockType.OTHER


def test_page_with_no_text_column_never_yields_a_footnote():
    """it_geo_05 left is a full-page figure with two header blocks and nothing else,
    so 'below the body' is vacuously true for every stray on it. Without this guard
    all three of that page's strays would be typed footnote."""
    real = [
        _blk(BlockType.HEADER, 100, 90, 900, 60, n_words=4, word_h=40, block_id=0),
        _blk(BlockType.FIGURE, 231, 331, 1806, 2658, block_id=1),
    ]
    strays = [
        _blk(BlockType.OTHER, 259, 280, 700, 48, n_words=3, word_h=20, block_id=-1),
        _blk(BlockType.OTHER, 259, 1971, 900, 671, n_words=14, word_h=31, block_id=-1),
    ]
    assert all(v.type is BlockType.OTHER for v in RT.type_rescued(strays, real))


def test_a_caption_is_not_a_column_a_footnote_can_hang_under():
    """COLUMN_TYPES is narrower than BODY_TYPES on purpose: a stray under a side-set
    caption must not qualify as that caption's footnote."""
    real = [_blk(BlockType.CAPTION, 1324, 2070, 603, 322, n_words=52, word_h=28, block_id=0)]
    stray = _blk(BlockType.OTHER, 1330, 2500, 590, 31, n_words=8, word_h=24, block_id=-1)
    [v] = RT.type_rescued([stray], real)
    assert v.type is BlockType.OTHER


def test_partial_column_overlap_is_not_enough():
    """The block must sit INSIDE the column, not merely touch its edge."""
    real = _page_real()
    edge = _blk(BlockType.OTHER, 1800, 2704, 723, 31, n_words=8, word_h=24, block_id=-1)
    # overlaps the column (91..1945) by 145 of its own 723 px -> ratio 0.20
    [v] = RT.type_rescued([edge], real)
    assert v.type is BlockType.OTHER


# --------------------------------------------------------------------------
# Invariants of the module as a whole
# --------------------------------------------------------------------------


def test_never_emits_a_stripped_type():
    """HEADER and PAGE_NUMBER are unreachable BY DESIGN — both are stripped by
    default, so a wrong call there deletes text instead of mislabelling it."""
    real = _page_real()
    cands = [_true_footnote(), _bottom_margin_noise(),
             _blk(BlockType.OTHER, 100, 50, 800, 40, n_words=6, word_h=20, block_id=-1)]
    got = {v.type for v in RT.type_rescued(cands, real)}
    assert not (got & {BlockType.HEADER, BlockType.PAGE_NUMBER})


def test_one_verdict_per_input_in_order():
    cands = [_bottom_margin_noise(), _true_footnote(), _bottom_margin_noise()]
    got = [v.type for v in RT.type_rescued(cands, _page_real())]
    assert got == [BlockType.OTHER, BlockType.FOOTNOTE, BlockType.OTHER]


def test_empty_inputs_are_fine():
    assert RT.type_rescued([], _page_real()) == []
    assert [v.type for v in RT.type_rescued([_true_footnote()], [])] == [BlockType.OTHER]


def test_params_override_the_defaults():
    """The thresholds are measured values, not laws — a caller can move them, and
    the module must read the override rather than its own DEFAULTS."""
    fn = _true_footnote()
    assert RT.type_rescued([fn], _page_real())[0].type is BlockType.FOOTNOTE
    strict = {"rescue_footnote_max_height_ratio": 0.5}
    assert RT.type_rescued([fn], _page_real(), strict)[0].type is BlockType.OTHER
    loose = {"rescue_footnote_min_words": 99}
    assert RT.type_rescued([fn], _page_real(), loose)[0].type is BlockType.OTHER


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
