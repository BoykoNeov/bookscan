"""Tests for the unreadable-panel pass (pipeline/unreadable_panel.py).

The pass turns a block whose OCR cannot be trusted into a PICTURE. Its failure
mode is therefore "a picture where text was wanted", which is recoverable in the
editor — but it is still a loss of searchable text, so the tests below are mostly
about the pass STAYING SILENT: on ordinary text, on a uniformly bad scan, on
fragments, and on blocks it is not allowed to touch at all.

Numbers are the real de_01 ones (icon-sidebar blocks at median confidence 41.5
and 57.5 against a document median of 92.3).
"""
from __future__ import annotations

from pipeline import unreadable_panel as UP
from pipeline.page_model import BBox, Block, BlockType, Word


def _blk(bid: int, btype: BlockType, conf: float, n: int = 20,
         text: str = "wort") -> Block:
    return Block(
        id=bid, type=btype, bbox=BBox(x=0, y=bid * 100, w=200, h=90),
        reading_order=bid,
        words=[Word(text=f"{text}{i}", bbox=BBox(x=i, y=0, w=10, h=10), conf=conf)
               for i in range(n)],
    )


def _clean_page(start: int = 0) -> list[Block]:
    return [_blk(start + i, BlockType.PARAGRAPH, 92.3) for i in range(4)]


# --------------------------------------------------------------------------
# Fires where it must
# --------------------------------------------------------------------------


def test_converts_a_block_far_below_the_documents_own_confidence():
    page = _clean_page() + [_blk(9, BlockType.OTHER, 41.5, n=31)]
    sc = UP.scan([page])
    assert sc.reference_conf == 92.3
    assert sc.converted == {(0, 9): 41.5}


def test_converted_block_becomes_a_figure_marked_automatic():
    page = _clean_page() + [_blk(9, BlockType.CAPTION, 57.5, n=30)]
    sc = UP.scan([page])
    out = UP.apply_to_blocks(page, sc, 0)
    conv = out[-1]
    assert conv.type is BlockType.FIGURE and conv.type_auto is BlockType.FIGURE
    assert conv.type_promoted is True
    assert conv.structure_edited is False        # automatic, not a human edit
    assert [w.text for w in conv.words] == [w.text for w in page[-1].words]


def test_caption_bookkeeping_is_cleared_when_a_caption_becomes_a_picture():
    cap = _blk(9, BlockType.CAPTION, 41.5, n=30).model_copy(
        update={"caption_number": 12, "pair_source": None})
    sc = UP.scan([_clean_page() + [cap]])
    out = UP.apply_to_blocks([cap], sc, 0)
    assert out[0].caption_number is None and out[0].figure_ref is None


# --------------------------------------------------------------------------
# Stays silent where it must — the larger half
# --------------------------------------------------------------------------


def test_ordinary_text_is_never_converted():
    page = _clean_page() + [_blk(9, BlockType.PARAGRAPH, 88.6, n=40)]
    sc = UP.scan([page])
    assert sc.converted == {}            # 88.6 / 92.3 = 0.96, the corpus worst case


def test_a_uniformly_bad_scan_converts_nothing():
    """The whole point of an ADAPTIVE reference (CLAUDE.md forbids a global
    confidence cutoff): every block here would fail a fixed threshold of 75, and
    none of them is unusual FOR THIS DOCUMENT."""
    page = [_blk(i, BlockType.PARAGRAPH, 45.0, n=30) for i in range(5)]
    sc = UP.scan([page])
    assert sc.reference_conf == 45.0
    assert sc.converted == {}


def test_a_short_fragment_is_not_converted():
    """de_02's stray '2806 m' is two words at confidence 26.5 — a sliver, not a
    panel, and a two-word picture is a worse deal than two garbled words."""
    page = _clean_page() + [_blk(9, BlockType.OTHER, 26.5, n=2)]
    sc = UP.scan([page])
    assert sc.converted == {}


def test_headers_page_numbers_and_figures_are_out_of_scope():
    page = _clean_page() + [
        _blk(9, BlockType.HEADER, 20.0, n=30),
        _blk(10, BlockType.PAGE_NUMBER, 20.0, n=30),
        _blk(11, BlockType.FIGURE, 20.0, n=30),
        _blk(12, BlockType.TABLE, 20.0, n=30),
    ]
    sc = UP.scan([page])
    assert sc.converted == {}


def test_a_document_with_no_running_text_converts_nothing():
    sc = UP.scan([[_blk(0, BlockType.FIGURE, 10.0, n=30)]])
    assert sc.reference_conf is None and sc.converted == {}


def test_block_ids_are_page_scoped_so_only_the_right_page_converts():
    """Block.id is page-scoped, not document-unique. Measured on de_01: block 7 of
    the left page is the icon panel (conf 62.6) and block 7 of the RIGHT page is
    the English translation column (conf 89.8). Keying the decision on the bare id
    turned both into pictures."""
    left = _clean_page() + [_blk(7, BlockType.OTHER, 41.5, n=30)]
    right = _clean_page(20) + [_blk(7, BlockType.PARAGRAPH, 92.0, n=30)]
    sc = UP.scan([left, right])
    assert set(sc.converted) == {(0, 7)}
    assert UP.apply_to_blocks(right, sc, 1)[-1].type is BlockType.PARAGRAPH
    assert UP.apply_to_blocks(left, sc, 0)[-1].type is BlockType.FIGURE


def test_median_not_mean_so_one_clean_word_cannot_rescue_a_panel():
    page = _clean_page()
    panel = _blk(9, BlockType.OTHER, 40.0, n=20)
    panel = panel.model_copy(update={"words": panel.words + [
        Word(text="Sept.", bbox=BBox(x=0, y=0, w=10, h=10), conf=99.0)]})
    sc = UP.scan([page + [panel]])
    assert (0, 9) in sc.converted


def test_resolve_params_ignores_unknown_keys():
    p = UP.resolve_params({"conf_ratio": "0.5", "nonsense": 1})
    assert p["conf_ratio"] == 0.5 and set(p) == set(UP.DEFAULTS)
