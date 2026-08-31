"""Work out which cell of its table each word of a TABLE block sits in.

THE DEFECT. Stage 08 renders a TABLE block the same way it renders a paragraph:
its words, in reading order, joined by spaces. On a real table that is unreadable.
The owner's route table comes out as ``... 7 Std. 9 Std. 2½ Std. 6½ Std. ...`` —
every time detached from its route, page numbers stranded — because the page
pass reads the table COLUMN BY COLUMN and the words arrive in that order. The
photograph it replaces is perfectly legible, so this is a loss, not a downgrade.

WHY THE ROWS CANNOT BE WORKED OUT AT RENDER TIME, which is the whole reason this
module exists rather than a function in Stage 08:

  * ``Word.line_id`` groups a CELL, not a row. On ``page_003__left`` #7 the route
    names are lines 0-35, the times 43-75, the heights 92-124. Grouping by line
    gives columns, which is exactly the defect.
  * The printed columns are STAGGERED against each other by roughly 0.7 of the row
    pitch (the route name sits low in its cell, the numbers high), on top of a
    residual skew from dewarp. So neighbouring columns' words are not on a shared
    baseline and cannot be clustered into rows by their y.
  * And the stagger is large enough to ALIAS. Measured on that block: sliding the
    name column by a whole row pitch scores a mean residual of 7.4 px against
    8.1 px for the correct correspondence — the wrong answer fits BETTER. No
    threshold rescues this; absolute-y matching is the wrong instrument.

WHAT DOES KNOW THE ROWS. Tesseract reading the block's own crop as one uniform
block (``psm 6``) has the ruled lines and the baselines, and gets the rows right:
its TSV lines span the full table width (x 36-2344 of 2370 on that block, against
a page-pass line's 126-506 of 1185) and each one is a whole table row. So this
pass runs that read purely as a ROW ORACLE.

**It is an oracle for STRUCTURE ONLY, and that division is measured, not tidy.**
The block re-read is WORSE at the actual characters than the page pass — mean
confidence 68.5-70.6 against 91.8, ``2,2 4½ Std.`` read as ``, .``, ``1250`` as
``[250``, the page number ``102`` as ``I Ly``. The page pass reads those same
cells right. So the shipped answer takes ROWS from the re-read and TEXT from the
page pass, and this module NEVER changes a word: it only writes ``table_row`` and
``table_col``. Word conservation is therefore untouched by construction, and an
abstain costs nothing at all.

(Re-reading in ``deu`` rather than ``eng`` does NOT fix those cells — 68.5 vs
70.6 mean confidence, and it introduces ``Hım``/``Huım``. Recorded so this is not
deferred to the per-block-language work on a wrong excuse.)

HOW A CELL FINDS ITS ROW. Not by band: one top/bottom band across the whole table
cannot follow a skewed row, and measured that way two cells collide in one band
low down the table. Each page-pass cell is matched to the oracle WORDS IT
OVERLAPS, and takes their line. That is a local comparison, so skew cancels.

ACCEPTANCE — structural, never word count or confidence. This is the reason it is
a new module and not a rule inside ``block_reocr``, whose acceptance is "more
words AND no lower confidence": the oracle read is worse on BOTH of those while
being the right answer, so that module would correctly refuse it. The test here is
that the re-read's lines span materially more of the block's width than the page
pass's do — i.e. that it is reading rows where the page pass read columns — plus
the grid coming out grid-shaped. A block that fails any check keeps no cells and
renders as it always did.

Contract: reads a block's words and the subpage image, writes ONLY
``Word.table_row`` / ``Word.table_col``. Never adds, drops or edits a word.
"""
from __future__ import annotations

import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from pipeline.page_model import Block, BlockType, Word
from tools import ocr_metrics as M
from tools.gate1_harness import run_tesseract, to_gray, upscale

DEFAULTS = {
    # On by default. It cannot change a word, only annotate one, and Stage 08
    # falls back to the old paragraph render whenever no cells are present — so
    # the downside of a wrong grid is a wrong TABLE, not lost text.
    "enabled": True,
    # Read the crop as ONE uniform block, same mechanism and same reason as
    # block_reocr: the page pass already tried automatic segmentation, and
    # segmenting a table is what it got wrong.
    "psm": 6,
    "pad_px": 0,
    # Below this a crop is not a table. Deliberately larger than block_reocr's
    # 12: a table needs at least a couple of rows and columns to be one.
    "min_side_px": 40,
    # Colour, for block_reocr's measured reason — Tesseract does its own
    # binarization and can use the channels to do it.
    "colour_crop": True,

    # --- what counts as a grid -------------------------------------------
    "min_rows": 2,
    "min_cols": 2,
    "min_cells": 6,
    # A horizontal gap wider than this many median word heights ends a cell
    # (within a line) or a column (across the block).
    "cell_gap_mult": 1.2,
    "col_gap_mult": 1.0,

    # --- acceptance -------------------------------------------------------
    # The oracle's lines must span at least this many times more of the block's
    # width than the page pass's lines do. Below it, the re-read is reading the
    # same columns the page pass read and has nothing to tell us. Measured on
    # the owner's route table: page pass 0.30 of the width, oracle 0.97 — a
    # ratio of 3.2, so this bar is not close to the observed case either way.
    "min_span_gain": 1.5,
    # A cell that overlaps no oracle word falls back to the nearest oracle line
    # by y. That keeps the "never lose a word" promise, but it is a guess; too
    # many guesses and the grid is not trustworthy.
    "max_weak_frac": 0.25,
    # Two cells of the same column landing in one row, FROM DIFFERENT PRINTED
    # ROWS, means the oracle and the page pass disagree about the structure.
    # The qualifier is load-bearing and was measured: most same-slot pairs are a
    # cell the page pass split across two lines and the oracle correctly kept
    # whole (a wrapped route name), which is the right answer, not a fault.
    # Counting those refused the main fixture at 16% against a 15% bar.
    "max_collision_frac": 0.15,
}

# The only type this pass touches. A block is a table because Stage 04 said so or
# because a human said so in the editor — never because this module guessed from
# geometry, which would turn two-column prose into a table.
TABLE_TYPES = frozenset({BlockType.TABLE})


@dataclass
class GridNote:
    """One block that got a grid, for ``meta.json`` provenance."""

    block_id: int
    n_rows: int
    n_cols: int
    n_words: int
    span_page: float          # median page-pass line span, as a fraction of width
    span_oracle: float        # median oracle line span, same units
    weak_frac: float          # cells placed by nearest-line fallback
    collision_frac: float     # cells sharing a slot with another


@dataclass
class GridSkip:
    """One block this pass looked at and left alone, and why."""

    block_id: int
    reason: str


# --------------------------------------------------------------------------
# Geometry helpers (pure)
# --------------------------------------------------------------------------


def _span(cell: list[Word]) -> tuple[int, int, int, int]:
    return (min(w.bbox.x for w in cell), min(w.bbox.y for w in cell),
            max(w.bbox.x2 for w in cell), max(w.bbox.y2 for w in cell))


def split_cells(words: list[Word], gap: float) -> list[list[Word]]:
    """Split each line of ``words`` into cells at horizontal gaps wider than
    ``gap``.

    A line is a cell candidate, not a row: with the page pass a whole line is
    usually ONE cell of one column, and with a block re-read it is a whole row
    that must be cut into cells. Both are handled by the same cut, which is why
    this does not care which pass produced the words.
    """
    lines: dict[object, list[Word]] = defaultdict(list)
    for w in words:
        lines[w.line_id].append(w)
    cells: list[list[Word]] = []
    for group in lines.values():
        group.sort(key=lambda w: w.bbox.x)
        cur = [group[0]]
        for prev, nxt in zip(group, group[1:]):
            if nxt.bbox.x - prev.bbox.x2 > gap:
                cells.append(cur)
                cur = [nxt]
            else:
                cur.append(nxt)
        cells.append(cur)
    return cells


def find_columns(cells: list[list[Word]], gap: float) -> list[tuple[int, int]]:
    """Column x-extents, from the gaps in the cells' horizontal coverage.

    Whitespace that runs the full height of the block is a column separator; a
    space between two words is not. Nothing here looks at y, so a skewed or
    staggered table columns exactly as well as a straight one.
    """
    intervals = sorted((_span(c)[0], _span(c)[2]) for c in cells)
    out: list[tuple[int, int]] = []
    x0, x1 = intervals[0]
    for a, b in intervals[1:]:
        if a - x1 > gap:
            out.append((x0, x1))
            x0, x1 = a, b
        else:
            x1 = max(x1, b)
    out.append((x0, x1))
    return out


def column_of(cell: list[Word], columns: list[tuple[int, int]]) -> int:
    """The column a cell belongs to: the one containing its horizontal midpoint,
    else the nearest. A cell that straddles a boundary still lands somewhere —
    losing it would lose its words."""
    x0, _, x1, _ = _span(cell)
    mid = (x0 + x1) / 2
    for i, (a, b) in enumerate(columns):
        if a <= mid <= b:
            return i
    return min(range(len(columns)),
               key=lambda i: abs(mid - (columns[i][0] + columns[i][1]) / 2))


def _median_line_span(words: list[Word], width: int) -> float:
    """Median horizontal extent of the words' lines, as a fraction of the block's
    width. This is the number the acceptance rule compares: a pass reading ROWS
    produces lines that cross the table, a pass reading COLUMNS does not."""
    if width <= 0:
        return 0.0
    lines: dict[object, list[Word]] = defaultdict(list)
    for w in words:
        lines[w.line_id].append(w)
    spans = [(max(g_.bbox.x2 for g_ in g) - min(g_.bbox.x for g_ in g)) / width
             for g in lines.values()]
    return float(st.median(spans)) if spans else 0.0


# --------------------------------------------------------------------------
# The row oracle
# --------------------------------------------------------------------------


def _oracle_words(img: np.ndarray, blk: Block, tess_bin: str, tessdata: str,
                  lang: str, oem: int, scale: float, p: dict
                  ) -> list[tuple[tuple[int, int, int], float, float, float, float]]:
    """Read the block's crop as one uniform block and return its words as
    ``(line_key, x0, y0, x1, y1)`` in the SAME 1x coordinates as ``blk.words``.

    Only the geometry and the line grouping are returned. The text is
    deliberately thrown away: it is measurably worse than the page pass's, and
    the one thing this read is good at is knowing which words share a row.
    """
    h, w = img.shape[:2]
    pad = int(p["pad_px"])
    x0, y0 = max(0, blk.bbox.x - pad), max(0, blk.bbox.y - pad)
    x1, y1 = min(w, blk.bbox.x2 + pad), min(h, blk.bbox.y2 + pad)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0 or min(crop.shape[:2]) < int(p["min_side_px"]):
        return []
    src = crop if p["colour_crop"] else to_gray(crop)
    src = upscale(src, scale)
    try:
        tsv = run_tesseract(tess_bin, src, lang, tessdata, oem, int(p["psm"]))
    except Exception:
        return []                      # a grid that cannot run leaves the block alone
    out = []
    for t in M.parse_tsv(tsv):
        out.append(((t.block_num, t.par_num, t.line_num),
                    t.left / scale + x0, t.top / scale + y0,
                    (t.left + t.width) / scale + x0,
                    (t.top + t.height) / scale + y0))
    return out


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------


def grid_table_blocks(blocks: list[Block], img: np.ndarray, tess_bin: str,
                      tessdata: str, lang: str, oem: int, scale: float,
                      p: dict | None = None
                      ) -> tuple[list[Block], list[GridNote], list[GridSkip]]:
    """Annotate every TABLE block with the cell each of its words sits in.

    Mutates ``blocks`` in place (the caller already owns fresh copies) and returns
    it alongside a note per gridded block and a skip per block left alone. NEVER
    adds, drops or edits a word — an abstain is invisible downstream except in
    ``meta.json``.
    """
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    notes: list[GridNote] = []
    skips: list[GridSkip] = []
    if not pp["enabled"]:
        return blocks, notes, skips

    for blk in blocks:
        if blk.type not in TABLE_TYPES:
            continue
        words = [w for w in blk.words if w.text.strip()]
        if len(words) < int(pp["min_cells"]):
            skips.append(GridSkip(blk.id, "too few words"))
            continue

        mh = float(st.median([w.bbox.h for w in words])) or 1.0
        cells = split_cells(words, mh * float(pp["cell_gap_mult"]))
        columns = find_columns(cells, mh * float(pp["col_gap_mult"]))
        if len(columns) < int(pp["min_cols"]):
            skips.append(GridSkip(blk.id, f"only {len(columns)} column(s)"))
            continue

        oracle = _oracle_words(img, blk, tess_bin, tessdata, lang, oem, scale, pp)
        if not oracle:
            skips.append(GridSkip(blk.id, "row oracle returned nothing"))
            continue

        # Acceptance: is the oracle reading ROWS where the page pass read COLUMNS?
        width = blk.bbox.w
        span_page = _median_line_span(words, width)
        by_line: dict[tuple[int, int, int], list] = defaultdict(list)
        for key, ox0, oy0, ox1, oy1 in oracle:
            by_line[key].append((ox0, oy0, ox1, oy1))
        span_oracle = float(st.median(
            [(max(b[2] for b in g) - min(b[0] for b in g)) / max(1, width)
             for g in by_line.values()]))
        if span_oracle < span_page * float(pp["min_span_gain"]):
            skips.append(GridSkip(
                blk.id, f"re-read spans no more of the width than the page pass "
                        f"({span_oracle:.2f} vs {span_page:.2f})"))
            continue

        # Rows, in reading order down the block.
        rank = {key: i for i, key in enumerate(sorted(
            by_line, key=lambda k: min(b[1] for b in by_line[k])))}
        centres = {key: st.median([(b[1] + b[3]) / 2 for b in by_line[key]])
                   for key in by_line}

        placed: list[tuple[list[Word], int, int]] = []
        weak = 0
        for cell in cells:
            cx0, cy0, cx1, cy1 = _span(cell)
            score: Counter = Counter()
            for key, ox0, oy0, ox1, oy1 in oracle:
                area = (_overlap(cx0, cx1, ox0, ox1)
                        * _overlap(cy0, cy1, oy0, oy1))
                if area > 0:
                    score[key] += area
            if score:
                key = score.most_common(1)[0][0]
            else:
                # No oracle word over these pixels. Fall back to the nearest row
                # rather than drop the cell: this pass must never lose a word.
                key = min(centres, key=lambda k: abs((cy0 + cy1) / 2 - centres[k]))
                weak += 1
            placed.append((cell, rank[key], column_of(cell, columns)))

        rows_used = sorted({r for _, r, _ in placed})
        renumber = {r: i for i, r in enumerate(rows_used)}

        # A REAL collision: two cells sharing a slot that came from different
        # printed rows. Two cells closer together than one row pitch are one
        # wrapped cell the page pass happened to break in half, and merging them
        # is correct — so they are not counted.
        pitches = sorted(centres.values())
        pitch = float(st.median([b - a for a, b in zip(pitches, pitches[1:])])
                      or mh * 2) if len(pitches) > 1 else mh * 2
        slots: dict[tuple[int, int], list[float]] = defaultdict(list)
        for cell, r, c in placed:
            cy0, cy1 = _span(cell)[1], _span(cell)[3]
            slots[(r, c)].append((cy0 + cy1) / 2)
        collisions = 0
        for ys in slots.values():
            ys.sort()
            collisions += sum(1 for a, b in zip(ys, ys[1:]) if b - a > pitch)

        weak_frac = weak / len(placed)
        coll_frac = collisions / len(placed)
        if len(rows_used) < int(pp["min_rows"]):
            skips.append(GridSkip(blk.id, f"only {len(rows_used)} row(s)"))
            continue
        if weak_frac > float(pp["max_weak_frac"]):
            skips.append(GridSkip(
                blk.id, f"{weak_frac:.0%} of cells had no row to sit on"))
            continue
        if coll_frac > float(pp["max_collision_frac"]):
            skips.append(GridSkip(
                blk.id, f"{coll_frac:.0%} of cells collided in a slot"))
            continue

        for cell, r, c in placed:
            for w in cell:
                w.table_row = renumber[r]
                w.table_col = c
        notes.append(GridNote(
            block_id=blk.id, n_rows=len(rows_used), n_cols=len(columns),
            n_words=len(words), span_page=round(span_page, 2),
            span_oracle=round(span_oracle, 2), weak_frac=round(weak_frac, 3),
            collision_frac=round(coll_frac, 3)))
    return blocks, notes, skips
