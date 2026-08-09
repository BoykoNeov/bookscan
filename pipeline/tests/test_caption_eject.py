"""Unit tests for ``pipeline.caption_eject`` — moving a caption that is PRINTED
INSIDE a figure box out into its own block, and Stage 08's masking of the region
it left behind.

The load-bearing property is the same one the grouping work holds: ejection is
DESTRUCTIVE (it takes text off a figure and paints that region out of the
artwork), so acceptance is number-first — a caption header must parse, and
density/alignment are guards on top of that, never an alternative route in. The
gate that set this bar: over all 15 testset images, 50 figure blocks yielded 6
clusters dense enough to qualify and exactly 1 header parsed — the real defect
(it_geo_05-left C2). The other five are artwork lettering and must stay put.

No Tesseract here: ``_reocr`` is monkeypatched, so the tests pin the decision
logic and the word bookkeeping, which is where the risk is.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import caption_eject as CE
from pipeline import stage04_layout as S4
from pipeline import stage08_render as R
from pipeline.page_model import BBox, Block, BlockType, Word

LAYOUT_P = S4.resolve_params({})
PAGE_W, PAGE_H = 2052, 3000

# The real it_geo_05-left header, as the targeted re-OCR returns it.
HEADER_TEXT = ("In questa pagina:\nFigura 2\nLa geografia nei\n"
               "dintorni della penisola\nitaliana nel Giurassico\n")


def _word(text, x, y, line_id, w=40, h=28):
    return Word(text=text, bbox=BBox(x=x, y=y, w=w, h=h), conf=96.0,
                engine="tesseract", line_id=line_id, block_id=0, decision=None)


def _caption_words(n_lines=6, per_line=4, x0=259, y0=2189, lh=33):
    out = []
    for li in range(n_lines):
        for wi in range(per_line):
            out.append(_word(f"w{li}_{wi}", x0 + wi * 45, y0 + li * lh, li))
    return out


def _figure_with(words, bbox=(231, 331, 1806, 2658)):
    x, y, w, h = bbox
    return Block(id=0, type=BlockType.FIGURE,
                 bbox=BBox(x=x, y=y, w=w, h=h), reading_order=0, words=list(words))


def _eject(monkeypatch, blocks, reocr_text=HEADER_TEXT, lang="ita"):
    monkeypatch.setattr(CE, "_reocr",
                        lambda img, box, tb, td, lg, up, p: reocr_text)
    img = np.zeros((PAGE_H, PAGE_W, 3), np.uint8)
    return CE.eject_inline_captions(blocks, img, "tesseract-not-used", "",
                                    lang, LAYOUT_P, PAGE_W, PAGE_H)


# --------------------------------------------------------------------------
# The header parse — the ONLY route to acceptance.
# --------------------------------------------------------------------------

def test_header_number_reads_the_real_it_geo_05_header():
    assert CE.header_number(HEADER_TEXT, "ita") == 2


def test_header_number_ignores_artwork_lettering():
    # The real de_02 / it_geo_02 clusters that the gate showed must abstain.
    assert CE.header_number("Rotwandhüt- te, 2283 m, CAI.\nMitte Juni bis Ende",
                            "deu") is None
    assert CE.header_number("Porfidi atesini (IMF) e Arenarie\nVETTE FELTRINE",
                            "ita") is None


def test_header_number_is_anchored_to_the_opening_lines():
    # 'Figura 12' deep inside a paragraph is a CROSS-REFERENCE, not this block's
    # header; treating it as one would eject a body paragraph.
    body = "\n".join([f"riga di testo numero {i}" for i in range(8)])
    assert CE.header_number(body + "\ncome mostrato in Figura 12", "ita") is None


# --------------------------------------------------------------------------
# Ejection.
# --------------------------------------------------------------------------

def test_ejects_the_caption_and_conserves_every_word(monkeypatch):
    words = _caption_words()
    fig = _figure_with(words + [_word("BELLUNO", 900, 700, 99)])
    before = len(fig.words)
    out, notes = _eject(monkeypatch, [fig])
    assert len(notes) == 1 and "Figura 2" in notes[0]
    caps = [b for b in out if b.type is BlockType.CAPTION]
    figs = [b for b in out if b.type is BlockType.FIGURE]
    assert len(caps) == 1 and len(figs) == 1
    # Words MOVED, never created or dropped — Stage 05 asserts conservation.
    assert sum(len(b.words) for b in out) == before
    assert len(caps[0].words) == len(words)
    assert [w.text for w in figs[0].words] == ["BELLUNO"]


def test_ejected_block_covers_the_header_it_was_read_from(monkeypatch):
    # The header sits ABOVE the first recognised line and has no word boxes, so a
    # words-only bbox leaves "In questa pagina: Figura 2" stranded on the artwork
    # after Stage 08 masks the body — the defect all over again.
    words = _caption_words()
    top_word = min(w.bbox.y for w in words)
    out, _ = _eject(monkeypatch, [_figure_with(words)])
    cap = next(b for b in out if b.type is BlockType.CAPTION)
    assert cap.bbox.y < top_word
    assert cap.bbox.y2 >= max(w.bbox.y2 for w in words)


def test_caption_lands_in_reading_order_not_appended(monkeypatch):
    # It must be re-ranked by the same XY-Cut Stage 04 uses. On the real page the
    # caption is at the FOOT of the figure, so it follows it.
    header = Block(id=0, type=BlockType.HEADER, bbox=BBox(x=225, y=104, w=57, h=33),
                   reading_order=0, words=[_word("168", 225, 104, 0)])
    fig = _figure_with(_caption_words())
    fig.id, fig.reading_order = 1, 1
    out, _ = _eject(monkeypatch, [header, fig])
    types = [b.type for b in out]
    assert types == [BlockType.HEADER, BlockType.FIGURE, BlockType.CAPTION]
    # ids/reading_order renumbered gaplessly, and every word points at its block.
    assert [b.reading_order for b in out] == [0, 1, 2]
    assert all(w.block_id == b.id for b in out for w in b.words)


def test_no_header_means_no_change(monkeypatch):
    fig = _figure_with(_caption_words())
    out, notes = _eject(monkeypatch, [fig], reocr_text="Bacino di Belluno\nTrento")
    assert notes == []
    assert len(out) == 1 and out[0].type is BlockType.FIGURE
    assert len(out[0].words) == 24


def test_sparse_lettering_never_reaches_the_reocr(monkeypatch):
    # The word/line floors exist to keep a subprocess off obvious non-candidates.
    def boom(*a, **k):
        raise AssertionError("re-OCR ran on a cluster below the floors")
    monkeypatch.setattr(CE, "_reocr", boom)
    img = np.zeros((PAGE_H, PAGE_W, 3), np.uint8)
    few = [_word("PIATTAFORMA", 400, 900, 0), _word("FRIULANA", 700, 900, 0)]
    out, notes = CE.eject_inline_captions([_figure_with(few)], img, "x", "",
                                          "ita", LAYOUT_P, PAGE_W, PAGE_H)
    assert notes == [] and len(out) == 1


def test_one_line_of_many_words_is_not_a_caption(monkeypatch):
    # A long single-line map label clears min_words but not min_lines.
    def boom(*a, **k):
        raise AssertionError("re-OCR ran on a single-line cluster")
    monkeypatch.setattr(CE, "_reocr", boom)
    img = np.zeros((PAGE_H, PAGE_W, 3), np.uint8)
    row = [_word(f"L{i}", 300 + i * 60, 900, 0) for i in range(12)]
    out, notes = CE.eject_inline_captions([_figure_with(row)], img, "x", "",
                                          "ita", LAYOUT_P, PAGE_W, PAGE_H)
    assert notes == [] and len(out) == 1


def test_text_blocks_are_left_alone(monkeypatch):
    # Only FIGURE blocks are candidates; a real paragraph must never be split.
    para = Block(id=0, type=BlockType.PARAGRAPH,
                 bbox=BBox(x=259, y=2189, w=365, h=610),
                 reading_order=0, words=_caption_words())
    out, notes = _eject(monkeypatch, [para])
    assert notes == [] and out[0].type is BlockType.PARAGRAPH
    assert len(out[0].words) == 24


# --------------------------------------------------------------------------
# Stage 08 masking — the other half: the pixels the caption left behind.
# --------------------------------------------------------------------------

def _blocks_for_mask():
    fig = Block(id=0, type=BlockType.FIGURE, bbox=BBox(x=0, y=0, w=400, h=400),
                reading_order=0, words=[])
    cap = Block(id=1, type=BlockType.CAPTION, bbox=BBox(x=50, y=300, w=100, h=60),
                reading_order=1, words=[_word("ciao", 50, 300, 0)])
    return fig, cap


def test_contained_caption_is_masked_out_of_the_crop():
    fig, cap = _blocks_for_mask()
    assert R._contained_text_boxes(fig, [fig, cap]) == [cap.bbox]


def test_a_nested_figure_is_never_masked():
    # A sub-figure inside a figure is ARTWORK. Painting it out destroys the picture.
    fig, _ = _blocks_for_mask()
    inner = Block(id=2, type=BlockType.FIGURE, bbox=BBox(x=20, y=20, w=80, h=80),
                  reading_order=2, words=[_word("x", 20, 20, 0)])
    assert R._contained_text_boxes(fig, [fig, inner]) == []


def test_text_outside_the_figure_is_not_masked():
    fig, _ = _blocks_for_mask()
    outside = Block(id=3, type=BlockType.PARAGRAPH,
                    bbox=BBox(x=500, y=500, w=100, h=60),
                    reading_order=3, words=[_word("fuori", 500, 500, 0)])
    straddling = Block(id=4, type=BlockType.PARAGRAPH,
                       bbox=BBox(x=350, y=350, w=200, h=100),
                       reading_order=4, words=[_word("mezzo", 350, 350, 0)])
    assert R._contained_text_boxes(fig, [fig, outside, straddling]) == []


def test_an_empty_block_is_not_masked():
    fig, _ = _blocks_for_mask()
    empty = Block(id=5, type=BlockType.OTHER, bbox=BBox(x=10, y=10, w=50, h=50),
                  reading_order=5, words=[])
    assert R._contained_text_boxes(fig, [fig, empty]) == []


def test_masking_actually_repaints_those_pixels():
    page = np.zeros((400, 400, 3), np.uint8)
    page[:] = (200, 200, 200)
    page[300:360, 50:150] = (10, 10, 10)          # the "caption" ink
    box = BBox(x=0, y=0, w=400, h=400)
    mask = [BBox(x=50, y=300, w=100, h=60)]
    plain = R._crop_data_uri(page, box)
    masked = R._crop_data_uri(page, box, mask)
    assert plain is not None and masked is not None and plain != masked
    # ... and the fill comes from the crop's own border, not a hard-coded white,
    # because these regions sit on artwork rather than page background.
    import base64
    import cv2
    arr = cv2.imdecode(np.frombuffer(base64.b64decode(masked.split(",", 1)[1]),
                                     np.uint8), cv2.IMREAD_COLOR)
    assert arr[330, 100].tolist() == [200, 200, 200]


def test_masking_is_off_by_default():
    page = np.zeros((400, 400, 3), np.uint8)
    box = BBox(x=0, y=0, w=400, h=400)
    assert R._crop_data_uri(page, box) == R._crop_data_uri(page, box, None)


@pytest.mark.parametrize("bad", [BBox(x=-50, y=-50, w=30, h=30),
                                 BBox(x=390, y=390, w=100, h=100)])
def test_mask_boxes_off_the_crop_are_clipped_not_crashed(bad):
    page = np.zeros((400, 400, 3), np.uint8)
    assert R._crop_data_uri(page, BBox(x=0, y=0, w=400, h=400), [bad]) is not None
