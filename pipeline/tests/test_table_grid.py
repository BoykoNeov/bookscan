"""Unit tests for ``pipeline.table_grid`` — which cell of its table a word is in.

Whether Tesseract reads a table's rows correctly is measured on real pixels in
docs/RESULTS.md, not here. What these tests pin is everything that could silently
corrupt a document:

  * this pass must NEVER add, drop or edit a word — it only annotates, and that
    is the reason an abstain is free;
  * the ACCEPTANCE rule is structural (line span), never word count or
    confidence — the whole reason this is not a rule inside ``block_reocr``,
    whose rule would refuse the correct answer;
  * an abstain must leave the block with NO cells, so Stage 08 falls back to the
    paragraph render rather than emitting half a table.

``run_tesseract`` is monkeypatched throughout, so the decision logic and the
bookkeeping are what is under test.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import table_grid as TG
from pipeline.page_model import BBox, Block, BlockType, Word

PAGE = np.zeros((900, 1200, 3), dtype=np.uint8)


def W(text: str, x: int, y: int, w: int = 40, h: int = 20,
      line: int = 0) -> Word:
    return Word(text=text, bbox=BBox(x=x, y=y, w=w, h=h), conf=90.0, line_id=line)


def blk(words: list[Word], typ: BlockType = BlockType.TABLE) -> Block:
    return Block(id=1, type=typ, bbox=BBox(x=0, y=0, w=1000, h=400),
                 reading_order=0, words=words)


def tsv(rows: list[tuple[str, int, int, int, int, int]]) -> str:
    """Build a Tesseract TSV from (text, left, top, width, height, line_num)."""
    out = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
           "left\ttop\twidth\theight\tconf\ttext"]
    for i, (text, left, top, w, h, line) in enumerate(rows):
        out.append(f"5\t1\t1\t1\t{line}\t{i}\t{left}\t{top}\t{w}\t{h}\t88\t{text}")
    return "\n".join(out)


# A page pass that read a two-column table COLUMN BY COLUMN: each line_id is one
# cell, so lines span a fraction of the block's width. This is the defect.
COLUMN_MAJOR = [
    W("Alpha", 10, 10, line=0), W("Beta", 10, 60, line=1),
    W("Gamma", 10, 110, line=2),
    W("111", 700, 10, line=3), W("222", 700, 60, line=4),
    W("333", 700, 110, line=5),
]
# The oracle's view of the same pixels: one line per ROW, spanning the width.
ORACLE_ROWS = tsv([("Alpha", 20, 20, 80, 40, 0), ("111", 1400, 20, 60, 40, 0),
                   ("Beta", 20, 120, 80, 40, 1), ("222", 1400, 120, 60, 40, 1),
                   ("Gamma", 20, 220, 80, 40, 2), ("333", 1400, 220, 60, 40, 2)])


def patch(monkeypatch, text: str) -> None:
    monkeypatch.setattr(TG, "run_tesseract", lambda *a, **k: text)


# --------------------------------------------------------------------------
# The invariant that makes an abstain free
# --------------------------------------------------------------------------


@pytest.mark.parametrize("oracle", [ORACLE_ROWS, tsv([]), "garbage"])
def test_never_changes_a_word(monkeypatch, oracle):
    """Whatever happens, the words are the same words with the same text.

    This is the pass's whole safety argument: it takes ROWS from a re-read whose
    TEXT is measurably worse than the page pass's, so the re-read's text must
    never reach the document.
    """
    patch(monkeypatch, oracle)
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    before = [(w.text, w.bbox.x, w.bbox.y, w.conf) for w in b.words]
    TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert [(w.text, w.bbox.x, w.bbox.y, w.conf) for w in b.words] == before


def test_grids_a_column_major_read(monkeypatch):
    patch(monkeypatch, ORACLE_ROWS)
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not skips and len(notes) == 1
    assert (notes[0].n_rows, notes[0].n_cols) == (3, 2)
    cells = {(w.table_row, w.table_col): w.text for w in b.words}
    assert cells == {(0, 0): "Alpha", (0, 1): "111",
                     (1, 0): "Beta", (1, 1): "222",
                     (2, 0): "Gamma", (2, 1): "333"}


def test_abstain_leaves_no_cells(monkeypatch):
    """Half a grid is worse than none: Stage 08 falls back on 'no cells', so an
    abstain must not leave any word annotated."""
    patch(monkeypatch, tsv([]))
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not notes and skips
    assert all(w.table_row is None and w.table_col is None for w in b.words)


def test_tesseract_failure_is_survivable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no binary")
    monkeypatch.setattr(TG, "run_tesseract", boom)
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not notes and skips[0].reason == "row oracle returned nothing"


# --------------------------------------------------------------------------
# Acceptance is STRUCTURAL
# --------------------------------------------------------------------------


def test_refuses_an_oracle_that_read_columns_too(monkeypatch):
    """If the re-read's lines span no more of the width than the page pass's, it
    is reading the same columns and has nothing to say about rows."""
    patch(monkeypatch, tsv([("Alpha", 20, 20, 80, 40, 0),
                            ("Beta", 20, 120, 80, 40, 1),
                            ("Gamma", 20, 220, 80, 40, 2),
                            ("111", 1400, 20, 60, 40, 3),
                            ("222", 1400, 120, 60, 40, 4),
                            ("333", 1400, 220, 60, 40, 5)]))
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not notes
    assert "spans no more of the width" in skips[0].reason


def test_acceptance_ignores_word_count_and_confidence(monkeypatch):
    """The oracle read is WORSE on both counts than the page pass and is still
    the right answer. block_reocr's rule would refuse it; this one must not.

    This is the test that pins why ``table_grid`` is a separate module.
    """
    patch(monkeypatch, ORACLE_ROWS)                     # 6 words, conf 88
    b = blk([w.model_copy() for w in COLUMN_MAJOR])     # 6 words, conf 90
    for w in b.words:
        w.conf = 99.0
    _, notes, _ = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert notes and notes[0].n_rows == 3


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


@pytest.mark.parametrize("typ", [BlockType.PARAGRAPH, BlockType.FIGURE,
                                 BlockType.CAPTION, BlockType.HEADING])
def test_only_touches_tables(monkeypatch, typ):
    """A block is a table because Stage 04 or a human said so — never because
    this module liked the geometry. Gridding prose would turn two columns of
    text into a table."""
    patch(monkeypatch, ORACLE_ROWS)
    b = blk([w.model_copy() for w in COLUMN_MAJOR], typ)
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not notes and not skips
    assert all(w.table_row is None for w in b.words)


def test_disabled_is_inert(monkeypatch):
    patch(monkeypatch, ORACLE_ROWS)
    b = blk([w.model_copy() for w in COLUMN_MAJOR])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0,
                                           p={"enabled": False})
    assert not notes and not skips
    assert all(w.table_row is None for w in b.words)


def test_single_column_abstains(monkeypatch):
    """The marginal real case: an 8-word fragment of a table whose other columns
    the page pass never read is not a table anybody can render."""
    patch(monkeypatch, ORACLE_ROWS)
    b = blk([W("Alpha", 10, 10, line=0), W("Beta", 10, 60, line=1),
             W("Gamma", 10, 110, line=2), W("Delta", 10, 160, line=3),
             W("Eps", 10, 210, line=4), W("Zeta", 10, 260, line=5)])
    _, notes, skips = TG.grid_table_blocks([b], PAGE, "tess", "td", "eng", 1, 2.0)
    assert not notes and "column" in skips[0].reason


# --------------------------------------------------------------------------
# Pure geometry
# --------------------------------------------------------------------------


def test_split_cells_cuts_on_a_wide_gap_not_a_space():
    words = [W("one", 0, 0, w=40), W("two", 45, 0, w=40),   # a space
             W("far", 400, 0, w=40)]                        # a column gap
    cells = TG.split_cells(words, gap=24.0)
    assert [[w.text for w in c] for c in cells] == [["one", "two"], ["far"]]


def test_find_columns_ignores_y_entirely():
    """A staggered or skewed table columns exactly as well as a straight one —
    which is why columns are safe to derive from geometry and rows are not."""
    cells = [[W("a", 0, 0)], [W("b", 0, 500)],
             [W("c", 600, 33)], [W("d", 600, 517)]]
    assert TG.find_columns(cells, gap=24.0) == [(0, 40), (600, 640)]


def test_column_of_straddling_cell_still_lands_somewhere():
    """Dropping a cell would drop its words, so a straddler picks the nearest
    column rather than being discarded."""
    cols = [(0, 100), (600, 700)]
    assert TG.column_of([W("x", 560, 0, w=60)], cols) == 1
