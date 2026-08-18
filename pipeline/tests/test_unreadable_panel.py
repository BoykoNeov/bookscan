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
from pipeline.page_model import (BBox, Block, BlockRef, BlockType, DocPage,
                                 PairSource, Word)
from pipeline.stage08_render import _caption_bindings


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


# --------------------------------------------------------------------------
# The seam with caption<->figure grouping (pipeline/figure_grouping.py)
# --------------------------------------------------------------------------
# Stage 07 pairs captions to figures FIRST and runs this pass AFTER, so a block
# can be paired as a caption and then converted to a picture. Nothing in the
# 326-block corpus is both (a convertible caption needs a printed "Fig. NN" AND
# median confidence under 0.75x reference AND >= 8 words), so this is a latent
# seam rather than a live defect — which is exactly why it wants a test.


def test_a_live_pairing_dangles_nowhere_because_figure_ref_is_one_directional():
    """THE POINT: the association is recorded ONLY on the caption
    (``Block.figure_ref`` -> figure). The figure carries no back-pointer — its
    ``figure_number`` is a number read off the photo, not a caption id — so
    clearing the caption side leaves nothing stale behind. Recorded here so the
    next person does not have to re-derive it from the schema."""
    fig = Block(id=3, type=BlockType.FIGURE,
                bbox=BBox(x=0, y=0, w=200, h=200), reading_order=0)
    cap = _blk(9, BlockType.CAPTION, 41.5, n=30).model_copy(update={
        "caption_number": 96,
        "figure_ref": BlockRef(page_id="pg", block_id=3),
        "pair_source": PairSource.GEOMETRY,
    })
    sc = UP.scan([_clean_page() + [fig, cap]])
    out = UP.apply_to_blocks([fig, cap], sc, 0)

    assert out[0] == fig                          # the figure side is untouched
    assert out[1].figure_ref is None and out[1].pair_source is None
    assert out[0].model_dump().get("caption_ref", "absent") == "absent"


def test_a_converted_caption_stops_claiming_its_figure_in_the_renderer():
    """The end-to-end consequence: Stage 08 resolves pairs by scanning for
    CAPTION blocks that carry a figure_ref, so the converted block drops out on
    both counts and its figure renders uncaptioned rather than bound to a
    picture."""
    fig = Block(id=3, type=BlockType.FIGURE,
                bbox=BBox(x=0, y=0, w=200, h=200), reading_order=0)
    cap = _blk(9, BlockType.CAPTION, 41.5, n=30).model_copy(update={
        "figure_ref": BlockRef(page_id="pg", block_id=3),
        "pair_source": PairSource.GEOMETRY,
    })
    page = DocPage(page_id="pg", source_spread="page_001", subpage="single",
                   width=200, height=200, image_asset="document_assets/pg.png",
                   blocks=[fig, cap])

    before, bound = _caption_bindings(page, [fig, cap])
    assert before == {3: cap} and bound == {9}    # paired before the pass

    sc = UP.scan([_clean_page() + [fig, cap]])
    conv = UP.apply_to_blocks([fig, cap], sc, 0)
    after, bound_after = _caption_bindings(page, conv)
    assert after == {} and bound_after == set()   # and claims nothing after it


def test_reading_order_survives_the_conversion():
    """A converted panel keeps its slot — the 2026-07-18 note is explicit that
    the sidebar's leftmost-first position is already CORRECT, so this pass must
    change typing and nothing else."""
    page = _clean_page() + [_blk(9, BlockType.OTHER, 41.5, n=30)]
    sc = UP.scan([page])
    out = UP.apply_to_blocks(page, sc, 0)
    assert [b.reading_order for b in out] == [b.reading_order for b in page]
    assert out[-1].reading_order == 9 and out[-1].bbox == page[-1].bbox
