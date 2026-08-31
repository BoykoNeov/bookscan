"""Stage 08 — Render (editable ``document.json`` -> re-typeset HTML / PDF).

The counterpart to Stage 07: assemble builds the editable document, render turns
it — and ONLY it — into the finished, searchable, re-typeset output. Because
render is a **pure function of ``document.json`` + ``document_assets/``**, it is
safe to run any number of times: bake a PDF now, edit the document later, re-run
and the edits appear. It NEVER reads the per-page stage folders (self-containment
rule, ``docs/GATE4_SPEC.md``), so a document saved months ago still renders.

**Renders the CURRENT editable values, not provenance** — ``Word.text`` (not
``text_ocr``), ``Block.type`` / ``reading_order`` (not ``*_auto``) — so every
edit round-trips. In particular:

  * **``Block.text`` translation override supersedes the words.** This is the
    headline reason the requirement changed ("translate the text first"): when a
    block carries an edited/translated ``text``, it renders that plainly and the
    per-word OCR/flags are bypassed (words remain in the model as provenance).
  * **Uncertainty modes ride ``Word.flag_visible``** (the owner's per-word rule):
    a still-visible marker renders as a highlighted span (flag) or an inline
    image crop (patch); an *edited* word — even one that was flagged — renders as
    plain text, because editing it cleared the marker.
  * **Figures are cropped from the full-res page image** (``image_asset``) at the
    block bbox and placed in reading order; a FIGURE block renders the crop, not
    its (meaningless) OCR words. Its caption is the one Stage 07's grouping pass
    PAIRED to it (``Block.figure_ref`` — by printed number, else guarded
    geometry), rendered inside the same ``<figure>`` however far away it sits on
    the page. Only when a figure has no paired caption does the old adjacency
    rule apply, and then only to a following caption that claims no figure of its
    own — a caption bound elsewhere is never swallowed.
  * **Running headers / page numbers are stripped by default** (per the CURRENT
    block type, so a user retype is honored); toggles in ``DocSettings``.
  * Output text is real text -> the HTML (and any PDF made from it) is searchable;
    ``DocSettings.fonts`` drive the embedded font stack (Latin + Cyrillic).

**HTML is the deliverable; the PDF engine is a thin consumer of it.** The HTML is
written print-ready (``@page``, page breaks) and fully self-contained (every image
inlined as a data URI — no external refs, no broken paths). The PDF backend is
**headless Chromium via Playwright** (owner decision): it renders the exact
``page.html`` this stage produces, so the PDF matches the browser preview 1:1
(``print_background`` keeps the flag highlight, ``prefer_css_page_size`` honors
``@page``). ``config.yaml reconstruct.pdf_backend`` selects it (``chromium`` |
``weasyprint`` | ``auto`` | ``none``); if the chosen engine is unavailable render
still writes ``page.html`` and says so in meta — the gate is never blocked.

**De-hyphenation on reflow** is a wired seam (repo pattern: ship the conservative
default arm, wire the hook — cf. the Stage-06 disagreement trigger): a line-end
hyphen is joined with the next line only if it starts lowercase AND the joined
token is in the per-language dictionary; with no dictionary loaded the default is
conservative — keep the hyphen. The gap is noted honestly in meta.

Contract:
  * **Reads** ``<job>/document.json`` + ``<job>/document_assets/`` ONLY.
  * **Writes** ``<job>/render/page.html`` (always), ``<job>/render/page.pdf``
    (when a PDF backend is available), and ``<job>/render/meta.json``.

Usage:
    python -m pipeline.stage08_render jobs/<job>/ [--debug]
"""

from __future__ import annotations

import argparse
import base64
import html
import statistics as st
import time
from pathlib import Path

import cv2
import numpy as np

from pipeline.page_model import (
    BBox, Block, BlockType, Document, DocPage, PairSource, StageMeta, Word,
)
from pipeline import stage04_layout as S4
from pipeline.second_opinion import load_lexicon, normalize_token

STAGE = "stage08_render"
VERSION = "0.3.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Bundled, tracked fonts embedded as @font-face data URIs (self-containment
# rule: the HTML must render Noto on any machine, with or without it installed —
# otherwise Chromium/WeasyPrint silently fall back to a system serif like Times
# New Roman and Cyrillic can tofu). NotoSerif.ttf is a VARIABLE font (wght
# 100–900) so a single file yields Regular through Bold with no faux-bolding.
# Its family name MUST match the CSS ``font-family`` stack strings exactly.
FONTS_DIR = REPO_ROOT / "pipeline" / "assets" / "fonts"

# (file, family, font-weight, font-style). Add Noto Sans here when bundled — the
# loader emits a face for whatever files are PRESENT, independent of a document's
# ``settings.fonts`` (which defaults to []), so embedding never silently drops.
_FONT_FACES: list[tuple[str, str, str, str]] = [
    ("NotoSerif.ttf", "Noto Serif", "100 900", "normal"),
]

# Block types dropped by default (running headers / page numbers), gated by the
# document's toggles. Keyed on the CURRENT type so a user retype is honored.
_STRIP = {
    BlockType.HEADER: "strip_running_headers",
    BlockType.PAGE_NUMBER: "strip_page_numbers",
}


# --------------------------------------------------------------------------
# De-hyphenation seam (pure, unit-tested)
# --------------------------------------------------------------------------


def _dehyphen_lexicon(cfg: dict, source_language: str | None):
    """The per-language lexicon that activates the de-hyphenation rule, or None.

    Same lexicon and same loader as Stage 05's disagreement trigger
    (``engines.easyocr.lexicon`` in config.yaml, built by tools/setup_lexicons.py
    into gitignored models/lexicons/). Returning None keeps the conservative
    behaviour — every line-end hyphen retained — which is what a fresh clone
    with no downloaded dictionaries gets.

    A multi-language document language (``deu+ita``) takes the FIRST code: the
    lexicon is per language and a join only has to be right, not exhaustive.
    """
    if not source_language:
        return None
    paths = (((cfg.get("engines") or {}).get("easyocr") or {}).get("lexicon") or {})
    path = paths.get(str(source_language).split("+")[0])
    if not path:
        return None
    try:
        return load_lexicon([REPO_ROOT / path])
    except Exception:
        return None                       # a broken lexicon must not fail a render



def join_hyphen(left: str, right: str, dictionary: set[str] | None) -> str | None:
    """Return the de-hyphenated join of a line-end ``left`` with the next line's
    ``right``, or None to keep them separate (hyphen retained).

    Rule (CLAUDE.md): join only if ``left`` ends with a hyphen AND ``right`` starts
    lowercase AND the joined token is in the per-language dictionary. With no
    dictionary the default is conservative — never join (a wired seam, not a TODO):
    returns None, so the hyphen is kept until a dictionary is supplied.
    """
    ls = left.rstrip()
    if not ls.endswith("-") or not right[:1].islower():
        return None
    if dictionary is None:
        return None                       # conservative default: keep the hyphen
    candidate = ls[:-1] + right
    # The membership test must be on the NORMALIZED token, not ``.lower()``: the
    # second half of a broken word usually carries the line's punctuation
    # ("Tourenvor-" + "schlaege,"), and a trailing comma fails every lexicon. The
    # emitted text keeps the punctuation; only the lookup drops it. This is also
    # what makes a HunspellLexicon a drop-in here — it keys on normalized tokens.
    probe = normalize_token(candidate)
    return candidate if probe and probe in dictionary else None


def merge_hyphens(words: list[Word], dictionary: set[str] | None) -> list[Word]:
    """Fold line-end hyphenated plain words into the following word per
    ``join_hyphen``. Flagged/edited words at the boundary are left untouched
    (their marker must survive). Default (no dictionary) is a no-op."""
    out: list[Word] = []
    i = 0
    while i < len(words):
        w = words[i]
        if (i + 1 < len(words) and not w.flag_visible and not words[i + 1].flag_visible
                and w.line_id is not None and words[i + 1].line_id is not None
                and words[i + 1].line_id != w.line_id):
            joined = join_hyphen(w.text, words[i + 1].text, dictionary)
            if joined is not None:
                nxt = words[i + 1]
                out.append(w.model_copy(update={
                    "text": joined,
                    "text_ocr": (w.text_ocr or "") + (nxt.text_ocr or ""),
                }))
                i += 2
                continue
        out.append(w)
        i += 1
    return out


# --------------------------------------------------------------------------
# Inlining assets as data URIs (keeps the HTML self-contained + path-bug-proof)
# --------------------------------------------------------------------------


def _data_uri_from_bytes(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _data_uri_from_file(path: Path) -> str | None:
    try:
        return _data_uri_from_bytes(path.read_bytes())
    except OSError:
        return None


def _crop_data_uri(page_bgr: np.ndarray, box: BBox,
                   mask: list[BBox] | None = None) -> str | None:
    h, w = page_bgr.shape[:2]
    x0, y0 = max(0, box.x), max(0, box.y)
    x1, y1 = min(w, box.x2), min(h, box.y2)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = _paint_out(page_bgr[y0:y1, x0:x1], mask, x0, y0, x1, y1)
    ok, buf = cv2.imencode(".png", crop)
    return _data_uri_from_bytes(buf.tobytes()) if ok else None


def _paint_out(crop: np.ndarray, mask: list[BBox] | None,
               x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Hide text blocks that are printed ON this artwork.

    A caption printed INSIDE the figure box is now its own block (Stage 05 ejects
    it), but it is still in these pixels — so the crop would show the caption a
    second time, in the photo, right next to its own rendered text. Paint it out.
    The fill is sampled from the crop's border rather than a fixed white, because
    these regions sit on artwork (a map's pale margin), not on page background.
    Cutting instead of masking is not an option here: the only cut that separates
    this caption slices the map in half.

    ``x0..y1`` are the crop's rectangle in PAGE coordinates, which is where the
    mask boxes live. The crop's own pixel size need not match that rectangle — a
    higher-resolution figure asset is the same rectangle with more pixels — so the
    boxes are scaled by the ratio rather than used as pixel offsets.
    """
    if not mask:
        return crop
    out = crop.copy()
    sx = out.shape[1] / max(1, x1 - x0)
    sy = out.shape[0] / max(1, y1 - y0)
    edge = np.concatenate([out[0, :], out[-1, :], out[:, 0], out[:, -1]])
    fill = np.median(edge.reshape(-1, edge.shape[-1]), axis=0)
    for m in mask:
        mx0 = int(round((max(x0, m.x) - x0) * sx))
        my0 = int(round((max(y0, m.y) - y0) * sy))
        mx1 = int(round((min(x1, m.x2) - x0) * sx))
        my1 = int(round((min(y1, m.y2) - y0) * sy))
        if mx1 > mx0 and my1 > my0:
            out[my0:my1, mx0:mx1] = fill
    return out


def _figure_data_uri(blk: Block, page_bgr: np.ndarray | None,
                     mask: list[BBox] | None, job_dir: Path) -> str | None:
    """The figure's pixels: the higher-resolution asset when one was cut for
    exactly this rectangle, else the page crop.

    The bbox check is the whole safety of the thing. ``document.json`` is mutable
    and the asset is not re-cut on an edit, so a figure the user resized would
    otherwise be filled with a high-resolution picture of its OLD outline — a
    wrong picture, which is worse than a soft one. Any mismatch falls back
    silently to the page crop, which is always right.
    """
    if blk.figure_asset and blk.figure_asset_box == blk.bbox:
        img = cv2.imread(str(job_dir / blk.figure_asset), cv2.IMREAD_COLOR)
        if img is not None:
            b = blk.bbox
            out = _paint_out(img, mask, b.x, b.y, b.x2, b.y2)
            ok, buf = cv2.imencode(".png", out)
            if ok:
                return _data_uri_from_bytes(buf.tobytes())
    return _crop_data_uri(page_bgr, blk.bbox, mask) if page_bgr is not None else None


def _contained_text_boxes(blk: Block, blocks: list[Block]) -> list[BBox]:
    """Text blocks whose bbox lies inside this figure's — i.e. text that is
    printed ON the artwork and therefore appears twice in the output unless the
    figure crop is masked. Figures nested in figures are NOT masked: a sub-figure
    is artwork, and painting it out would destroy the picture.

    THE RULE IS GEOMETRIC, WITH NO PROVENANCE CHECK, and this runs on the EDITED
    document — so a block the user moves (or creates) inside a figure's bbox in
    the editor will be painted out of that figure, and a block whose words were
    all deleted but which carries a ``text`` override still masks. Both follow
    from "text shown inside the picture is shown twice", but they mean an edit can
    change what a figure LOOKS like, not just what it reads. Measured over every
    assembled document in ``jobs/`` at the time this landed: 0 of 43 figure blocks
    would mask anything, i.e. nothing pre-existing is silently repainted."""
    out = []
    for b in blocks:
        if b.id == blk.id or b.type is BlockType.FIGURE:
            continue
        if not b.words and b.text is None:
            continue
        if (b.bbox.x >= blk.bbox.x and b.bbox.y >= blk.bbox.y
                and b.bbox.x2 <= blk.bbox.x2 and b.bbox.y2 <= blk.bbox.y2):
            out.append(b.bbox)
    return out


# --------------------------------------------------------------------------
# Word / block -> HTML
# --------------------------------------------------------------------------


def _word_html(w: Word, mode: str, job_dir: Path) -> str:
    """One word as an inline fragment, honoring its still-visible uncertainty
    marker. An edited word (marker cleared) renders as plain escaped text."""
    txt = html.escape(w.text)
    if not w.flag_visible:
        return txt
    if mode == "patch" and w.patch_asset:
        uri = _data_uri_from_file(job_dir / w.patch_asset)
        if uri:
            return f'<img class="patch" alt="{txt}" title="{txt}" src="{uri}">'
    return f'<span class="flag" title="uncertain (conf {w.conf:.0f})">{txt}</span>'


class _EitherLexicon:
    """Membership in EITHER of two lexicons, for a block printed in one language
    inside a document written in another.

    This is a UNION and not a replacement, and the reason is measured. Over the
    whole corpus, de-hyphenating a labelled block against its own dictionary
    ALONE gains 16 joins and loses one: ``de_02``'s English paragraph names the
    ``Rosen- garten``, a German massif, which the German lexicon joins and the
    English one cannot. A book that prints one language inside another is exactly
    a book full of the other's proper nouns — Italian route names in German text,
    German mountains in English text — so the block's language must be the extra
    authority, not the only one. With the union: 16 gained, 0 lost.
    """

    __slots__ = ("_a", "_b")

    def __init__(self, a, b) -> None:
        self._a, self._b = a, b

    def __contains__(self, token: str) -> bool:
        return token in self._a or token in self._b


def block_dictionary(blk: Block, dictionary: set[str] | None,
                     lexicons: dict[str, object] | None):
    """The lexicon to de-hyphenate THIS block with.

    ``Block.language`` is set only where a block's words clearly fit a different
    dictionary from the document's (pipeline/block_lang.py). None — the normal
    case, and what every document written before that field existed says — means
    "use the document's language", so this returns the document lexicon unchanged
    and the render is byte-identical to what it was before.

    A label naming a language whose dictionary is not installed also falls back:
    a missing lexicon must keep the hyphen, never drop the join silently to some
    other language's rules.
    """
    if lexicons and blk.language:
        got = lexicons.get(blk.language)
        if got is not None:
            return got if dictionary is None else _EitherLexicon(got, dictionary)
    return dictionary


def _block_body_html(blk: Block, mode: str, job_dir: Path,
                     dictionary: set[str] | None,
                     lexicons: dict[str, object] | None = None) -> str:
    """Inline HTML for a text block: the translated override if present, else the
    words rendered with de-hyphenation + per-word markers."""
    if blk.text is not None:                       # translation / block-level edit
        return html.escape(blk.text)
    words = [w for w in merge_hyphens(blk.words, block_dictionary(
        blk, dictionary, lexicons)) if w.text.strip()]
    return " ".join(_word_html(w, mode, job_dir) for w in words)


def cell_order(words: list[Word]) -> list[Word]:
    """The words of one table cell, in the order a human reads them.

    Neither document order nor a plain y-sort is right. Document order fails when
    the page pass broke ONE printed line into two — the tail carries the lower
    ``line_id`` and comes out first ("ivieri/Gianni Aglio @ B10 Ferrata Giuseppe
    Ol"). A plain y-sort fails the other way, scrambling words of the same line
    whose boxes differ by a pixel ("Std. 7%" for "7% Std."). So: group into
    visual lines by vertical overlap, order the lines down the cell, and each
    line left to right.
    """
    if len(words) < 2:
        return list(words)
    # 0.9 of a word height, not the 0.6 a clean page would want: a dewarped page
    # keeps a few degrees of skew, so the two halves of ONE printed line can sit
    # 12 px apart vertically when they are 250 px apart horizontally. At 0.6 they
    # split into two "lines" and the right-hand half sorts FIRST. A genuinely
    # wrapped cell still separates, because its line pitch is 1.3x a height or more.
    tol = 0.9 * (st.median([w.bbox.h for w in words]) or 1)
    lines: list[list[Word]] = []
    mids: list[float] = []
    for w in sorted(words, key=lambda w: w.bbox.y + w.bbox.h / 2):
        mid = w.bbox.y + w.bbox.h / 2
        # against the running mean of the line, not its first word, so a long
        # skewed line does not shed its tail once the drift exceeds the tolerance
        if lines and abs(mid - mids[-1] / len(lines[-1])) <= tol:
            lines[-1].append(w)
            mids[-1] += mid
        else:
            lines.append([w])
            mids.append(mid)
    return [w for line in lines for w in sorted(line, key=lambda w: w.bbox.x)]


def _table_html(blk: Block, mode: str, job_dir: Path,
                dictionary: set[str] | None,
                lexicons: dict[str, object] | None = None) -> str | None:
    """A TABLE block as a real ``<table>``, or None when it has no cells.

    The cells come from ``Word.table_row`` / ``Word.table_col``, worked out at
    Stage 05 where the pixels still are (pipeline/table_grid.py) — they cannot be
    recovered here, because the row correspondence of a staggered table is not a
    function of word geometry. So this is deliberately a DUMB renderer: it groups
    by the two fields and lays the result out. No geometry, no guessing.

    Returning None is the normal case and not a failure: a table the grid pass
    abstained on, an older document written before the fields existed, or a block
    a user re-typed TABLE by hand. The caller then renders the paragraph it always
    did, so nothing is ever lost by this path.

    A block-level ``text`` override still wins — that is a human's (or a
    translator's) copy of the whole block, and re-gridding it into stale cells
    would contradict it.
    """
    if blk.text is not None:
        return None
    cells: dict[tuple[int, int], list[Word]] = {}
    for w in blk.words:
        if w.table_row is None or w.table_col is None or not w.text.strip():
            continue
        cells.setdefault((w.table_row, w.table_col), []).append(w)
    if not cells:
        return None
    # Every word must be in a cell, or the table would silently drop text. The
    # grid pass places every word by construction; this is the check that says so
    # at the point where the loss would happen.
    if sum(len(v) for v in cells.values()) != len([w for w in blk.words
                                                   if w.text.strip()]):
        return None
    # The row and column values PRESENT, not range(max + 1). Stage 05 numbers
    # them densely, but the document is mutable and the editor can split a block:
    # the second half keeps rows 17-33, and range() would emit seventeen empty
    # <tr>s before the first real one. The schema stores the cell on the WORD
    # precisely so an edit cannot invalidate it, and the renderer has to honour
    # that rather than assume Stage 05's numbering survived.
    row_ids = sorted({r for r, _ in cells})
    col_ids = sorted({c for _, c in cells})
    rows_html: list[str] = []
    for r in row_ids:
        tds: list[str] = []
        for c in col_ids:
            got = cells.get((r, c))
            if not got:
                tds.append("<td></td>")
                continue
            got_words = cell_order(got)
            # De-hyphenation runs PER CELL. merge_hyphens keys on a line_id
            # change, and inside a table two cells of the same column are two
            # different line_ids — so run over the whole block it would happily
            # join the end of one cell to the start of the one below it.
            body = " ".join(_word_html(w, mode, job_dir)
                            for w in merge_hyphens(
                                got_words,
                                block_dictionary(blk, dictionary, lexicons))
                            if w.text.strip())
            tds.append(f"<td>{body}</td>")
        rows_html.append("<tr>" + "".join(tds) + "</tr>")
    return ('<div class="table-wrap"><table class="table">'
            + "".join(rows_html) + "</table></div>")


_TAG = {
    BlockType.TITLE: ("h1", "title"),
    BlockType.HEADING: ("h2", "heading"),
    BlockType.PARAGRAPH: ("p", "paragraph"),
    BlockType.LIST: ("p", "list"),
    BlockType.TABLE: ("p", "table"),
    BlockType.FOOTNOTE: ("p", "footnote"),
    # A caption PAIRED to a figure is emitted by _figure_html as a real
    # <figcaption> inside its <figure>. This entry is only reached by an UNPAIRED
    # caption, which must not emit a bare <figcaption> — that tag is invalid
    # outside a <figure>. Unpaired captions are now common by design (the grouping
    # pass abstains rather than guess), so they render as a styled paragraph.
    BlockType.CAPTION: ("p", "caption"),
    BlockType.HEADER: ("p", "header"),
    BlockType.PAGE_NUMBER: ("p", "page-number"),
    BlockType.OTHER: ("p", "other"),
}


def _figure_html(blk: Block, page_bgr: np.ndarray | None,
                 caption: Block | None, mode: str, job_dir: Path,
                 dictionary: set[str] | None,
                 lexicons: dict[str, object] | None = None,
                 siblings: list[Block] | None = None) -> str:
    """A FIGURE block: crop from the full-res page image at its bbox (NOT its OCR
    words), optionally with the following CAPTION grouped in the same <figure>.

    ``siblings`` are the page's other blocks; any TEXT block contained in this
    figure's bbox is masked out of the crop, so text printed on the artwork is not
    shown twice (once as pixels, once as its own rendered block)."""
    inner = ""
    mask = _contained_text_boxes(blk, siblings) if siblings else None
    uri = _figure_data_uri(blk, page_bgr, mask, job_dir)
    if uri:
        inner += f'<img class="figure" src="{uri}" alt="figure">'
    else:
        inner += '<div class="figure-missing">[figure]</div>'
    if caption is not None:
        inner += ('<figcaption class="caption">'
                  + _block_body_html(caption, mode, job_dir, dictionary, lexicons)
                  + '</figcaption>')
    return f'<figure class="figure-block">{inner}</figure>'


def _caption_bindings(page: DocPage, blocks: list[Block]
                      ) -> tuple[dict[int, Block], set[int]]:
    """Resolve Stage 07's ``figure_ref`` pairings into (figure_id -> caption,
    bound caption ids) for this page.

    A caption floats with the figure it was PAIRED to (by printed number, or by
    the guarded geometry rule), not with whatever block precedes it in reading
    order — that adjacency assumption is exactly what cannot express it_geo_06,
    where the captions are a stack on the far side of the subpage.

    Two references are deliberately left rendering in place rather than dropped:
    a ref to a figure on ANOTHER page (the cross-gutter panorama case — the
    schema can express it, this renderer does not yet float across pages), and a
    second caption claiming a figure that is already spoken for. Neither can
    silently lose text.

    **A HUMAN ruling outranks an inferred one.** When two captions claim the same
    figure, ``pair_source=user`` wins regardless of reading order; only then does
    reading order break the tie. Correcting a wrong pair is the entire point of
    the editor's pairing control, and the case it exists for — it_geo_06's
    cross-paired caption stack — is exactly the case where the pipeline's own
    guess would otherwise beat the user to the figure and their correction would
    vanish from the output while the editor still showed it as paired. The loser
    still renders standalone, so no text is lost either way.
    """
    fig_ids = {b.id for b in blocks if b.type is BlockType.FIGURE}
    claims = [b for b in blocks
              if b.type is BlockType.CAPTION and b.figure_ref is not None
              and b.figure_ref.page_id == page.page_id
              and b.figure_ref.block_id in fig_ids]
    cap_for_fig: dict[int, Block] = {}
    bound: set[int] = set()
    for user_tier in (True, False):        # human rulings first, then inferred pairs
        for b in claims:                   # `blocks` is reading-order sorted by the caller
            if (b.pair_source is PairSource.USER) is not user_tier:
                continue
            if b.figure_ref.block_id in cap_for_fig:
                continue
            cap_for_fig[b.figure_ref.block_id] = b
            bound.add(b.id)
    return cap_for_fig, bound


def _page_html(page: DocPage, doc: Document, job_dir: Path,
               dictionary: set[str] | None,
               lexicons: dict[str, object] | None = None) -> str:
    """One physical page: blocks in reading order, stripped/figured/typed."""
    mode = doc.settings.uncertainty_mode
    page_bgr = cv2.imread(str(job_dir / page.image_asset), cv2.IMREAD_COLOR)

    blocks = sorted(page.blocks, key=lambda b: b.reading_order)
    cap_for_fig, bound_caps = _caption_bindings(page, blocks)

    parts: list[str] = [f'<section class="page" data-page="{html.escape(page.page_id)}">']
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        strip_key = _STRIP.get(blk.type)
        if strip_key and getattr(doc.settings, strip_key):
            i += 1
            continue
        if blk.is_surface:
            # Not part of the book: a band of the surface it was photographed
            # on, which Stage 02's crop failed to exclude (see
            # pipeline/figure_surface.py). The block is still in the document
            # and the editor can clear the flag; it just does not render.
            i += 1
            continue
        if blk.id in bound_caps:
            i += 1                                  # rendered inside its figure below
            continue
        if blk.type is BlockType.FIGURE:
            cap = cap_for_fig.get(blk.id)           # explicit pairing wins
            if cap is None and i + 1 < len(blocks):
                nxt = blocks[i + 1]
                # Adjacency fallback — ONLY for a caption that claims no figure of
                # its own AND that no human has ruled on. A caption bound to a
                # DIFFERENT figure must never be swallowed by whichever figure
                # happens to precede it (on it_geo_06 that would hand the top-left
                # cliff the whole caption stack's first entry); and a caption the
                # user DELIBERATELY UNPAIRED in the editor (pair_source=user with
                # figure_ref None) must not be silently re-paired here — that would
                # make "detach this caption" a no-op in the rendered output for the
                # commonest case, a caption sitting right under the wrong figure.
                if (nxt.type is BlockType.CAPTION and nxt.figure_ref is None
                        and nxt.pair_source is not PairSource.USER):
                    cap = nxt
                    i += 1                          # consume the grouped caption
            parts.append(_figure_html(blk, page_bgr, cap, mode, job_dir,
                                      dictionary, lexicons, blocks))
            i += 1
            continue
        if blk.type is BlockType.TABLE:
            tbl = _table_html(blk, mode, job_dir, dictionary, lexicons)
            if tbl is not None:
                parts.append(tbl)
                i += 1
                continue
            # else: no cells — fall through to the paragraph render, which is
            # exactly what this block got before the grid pass existed.
        tag, cls = _TAG.get(blk.type, ("p", "other"))
        body = _block_body_html(blk, mode, job_dir, dictionary, lexicons)
        if body.strip():
            parts.append(f'<{tag} class="{cls}">{body}</{tag}>')
        i += 1
    parts.append("</section>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Document -> full HTML page (print-ready, self-contained)
# --------------------------------------------------------------------------


def _font_face_css(fonts_dir: Path = FONTS_DIR) -> str:
    """`@font-face` rules embedding each bundled TTF as a base64 data URI.

    Driven by files PRESENT on disk (not a document's ``settings.fonts``), so an
    empty-fonts document still gets Noto embedded. A variable font declares its
    full weight range (``font-weight: 100 900``) so Chromium synthesizes every
    weight from one file. Missing dir/file -> no faces (graceful degrade to the
    named-stack system fallback, same as before this fix); noted in meta."""
    faces: list[str] = []
    for fname, family, weight, style in _FONT_FACES:
        p = fonts_dir / fname
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        faces.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
            f'font-style: {style}; font-display: swap; '
            f'src: url(data:font/ttf;base64,{b64}) format("truetype"); }}'
        )
    return "\n".join(faces) + ("\n" if faces else "")


def _css(fonts: list[str]) -> str:
    stack = ", ".join(f'"{f}"' for f in fonts) or '"Noto Serif", serif'
    stack += ", serif"
    return _font_face_css() + f"""
@page {{ size: A4; margin: 22mm 20mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: {stack}; font-size: 11.5pt; line-height: 1.45;
       color: #111; max-width: 46rem; margin: 0 auto; padding: 1.5rem; }}
h1.title {{ font-size: 1.7em; margin: 1.2em 0 .5em; }}
h2.heading {{ font-size: 1.3em; margin: 1em 0 .4em; }}
p {{ margin: 0 0 .7em; text-align: justify; }}
p.footnote {{ font-size: .85em; color: #444; }}
p.list {{ margin-left: 1.2em; }}
.section-sep {{ border: 0; border-top: 1px dashed #ccc; margin: 1.4em 0; }}
.flag {{ background: #fff2a8; border-bottom: 1px solid #e0c000; padding: 0 1px;
         border-radius: 2px; }}
img.patch {{ height: 1.15em; vertical-align: text-bottom; margin: 0 1px;
             border: 1px solid #d9534f; }}
figure.figure-block {{ margin: 1em 0; text-align: center; page-break-inside: avoid; }}
img.figure {{ max-width: 100%; height: auto; }}
figcaption.caption {{ font-size: .9em; color: #333; margin-top: .3em; }}
.figure-missing {{ color: #999; font-style: italic; }}
/* A wide table must scroll inside its own box rather than push the page
   sideways; in print it simply shrinks with the type. */
div.table-wrap {{ overflow-x: auto; margin: 0 0 .8em; }}
table.table {{ border-collapse: collapse; width: 100%; font-size: .88em;
               page-break-inside: avoid; }}
table.table td {{ border: 1px solid #ccc; padding: .18em .4em;
                  vertical-align: top; text-align: left; }}
table.table tr:nth-child(odd) td {{ background: #fafafa; }}
section.page + section.page {{ margin-top: 1.4em; }}
@media print {{ section.page {{ break-before: page; }}
                section.page:first-child {{ break-before: auto; }} }}
"""


def render_html(doc: Document, job_dir: Path,
                dictionary: set[str] | None = None,
                lexicons: dict[str, object] | None = None) -> str:
    title = html.escape(doc.document_id)
    body = []
    for pi, page in enumerate(doc.pages):
        if pi:
            body.append('<hr class="section-sep">')
        body.append(_page_html(page, doc, job_dir, dictionary, lexicons))
    lang = doc.settings.target_language or doc.settings.source_language
    return (
        f'<!doctype html>\n<html lang="{html.escape(lang)}">\n<head>\n'
        f'<meta charset="utf-8">\n<title>{title}</title>\n'
        f"<style>{_css(doc.settings.fonts)}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
# PDF backend (owner decision: headless Chromium via Playwright)
# --------------------------------------------------------------------------
#
# The PDF is a thin consumer of the print-ready, fully self-contained page.html.
# Chromium is primary because it renders the EXACT HTML the preview already
# produces, so the PDF matches the browser 1:1 (one rendering target, not two).
# WeasyPrint stays as a secondary fallback (its own CSS engine may diverge).
# Whatever is chosen, if it is unavailable we fall through and still emit HTML,
# so the gate is never blocked.


def _pdf_via_chromium(html_path: Path, out_pdf: Path) -> tuple[bool, str]:
    """Render ``render/page.html`` to PDF with Playwright headless Chromium.

    Loads the LOCAL file (``file://``) rather than pushing the HTML string over
    CDP: the HTML inlines full-res dewarped images as data URIs and can be many
    MB, so a local load is faster and less flaky. ``file://`` resolves ``data:``
    images fine, so the self-contained HTML needs no asset server.

    Two flags are load-bearing:
      * ``print_background=True`` — Chromium prints backgrounds OFF by default,
        which would silently drop the ``.flag`` uncertainty highlight (CLAUDE.md's
        load-bearing feature) from the PDF.
      * ``prefer_css_page_size=True`` — honor the HTML's ``@page { size: A4; ... }``
        instead of Chromium's default Letter/margins.

    NOTE (Gate 5): the sync Playwright API raises if called inside a running
    asyncio loop. Fine for this CLI (no loop); the future FastAPI server must
    drive PDF export off the request loop (async API or a subprocess), not call
    this directly.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return False, "playwright not importable"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html_path.as_uri(), wait_until="load")
                page.pdf(path=str(out_pdf), print_background=True,
                         prefer_css_page_size=True)
            finally:
                browser.close()
    except Exception as e:  # pragma: no cover - depends on a launched browser
        return False, f"Chromium present but failed ({e!r})"
    try:                                    # version is cosmetic; never fail on it
        from importlib.metadata import version
        ver = version("playwright")
    except Exception:
        ver = "?"
    return True, f"PDF written via headless Chromium (Playwright {ver})"


def _pdf_via_weasyprint(html_str: str, out_pdf: Path) -> tuple[bool, str]:
    """Secondary fallback: HTML string -> PDF with WeasyPrint if importable."""
    try:
        import weasyprint  # type: ignore
    except Exception:
        return False, "weasyprint not importable"
    try:
        weasyprint.HTML(string=html_str).write_pdf(str(out_pdf))
        return True, f"PDF written via WeasyPrint {weasyprint.__version__}"
    except Exception as e:  # pragma: no cover - depends on system libs
        return False, f"WeasyPrint present but failed ({e!r})"


def try_render_pdf(html_str: str, out_pdf: Path, backend: str = "chromium",
                   html_path: Path | None = None) -> tuple[bool, str]:
    """Dispatch HTML->PDF by the configured ``backend``. Returns (wrote_pdf, note).

    ``backend``: ``chromium`` (default), ``weasyprint``, ``auto`` (chromium then
    weasyprint), or ``none`` (skip). Chromium needs the on-disk ``html_path``
    (it loads the local file); WeasyPrint consumes the HTML string. A chosen
    engine that is unavailable falls through to the next candidate, and if none
    succeed we return False with a clear note — render still wrote page.html.
    """
    backend = (backend or "chromium").lower()
    if backend == "none":
        return False, "pdf_backend=none — emitted HTML only (PDF skipped by config)."

    attempts: list[tuple[bool, str]] = []
    order = {"chromium": ["chromium"], "weasyprint": ["weasyprint"],
             "auto": ["chromium", "weasyprint"]}.get(backend, ["chromium"])
    for name in order:
        if name == "chromium" and html_path is not None:
            ok, note = _pdf_via_chromium(html_path, out_pdf)
        elif name == "weasyprint":
            ok, note = _pdf_via_weasyprint(html_str, out_pdf)
        else:
            ok, note = False, f"{name}: html_path unavailable"
        if ok:
            return True, note
        attempts.append((ok, f"{name}: {note}"))

    tried = "; ".join(n for _, n in attempts)
    hint = ("install it with `pip install playwright && playwright install "
            "chromium`" if "chromium" in order else "")
    return False, (f"pdf_backend={backend} unavailable — emitted HTML only "
                   f"[{tried}]. {hint}".rstrip())


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(job_dir: Path, cfg: dict, debug: bool = False) -> Path:
    t0 = time.perf_counter()
    job_dir = job_dir.resolve()
    doc_json = job_dir / "document.json"
    if not doc_json.exists():
        raise FileNotFoundError(
            f"missing {doc_json} — Stage 08 renders the editable document. Run "
            f"stage07_assemble on this job first.")
    doc = Document.model_validate_json(doc_json.read_text(encoding="utf-8"))

    out_dir = job_dir / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    # De-hyphenation needs the document's own language, not the config default:
    # the document records what it was actually read in, and a lexicon for the
    # wrong language would silently refuse every join.
    dictionary = _dehyphen_lexicon(cfg, doc.settings.source_language)
    # A block printed in another language de-hyphenates against ITS OWN
    # dictionary (Block.language, written by pipeline/block_lang.py). Only the
    # languages this document actually labels are loaded — a document with no
    # labels loads nothing extra and renders exactly as it did before.
    block_langs = {b.language for p_ in doc.pages for b in p_.blocks
                   if b.language} - {str(doc.settings.source_language or "").split("+")[0]}
    lexicons = {lc: lex for lc, lex in
                ((lc, _dehyphen_lexicon(cfg, lc)) for lc in sorted(block_langs))
                if lex is not None}
    html_str = render_html(doc, job_dir, dictionary=dictionary,
                           lexicons=lexicons)
    html_path = out_dir / "page.html"
    html_path.write_text(html_str, encoding="utf-8")

    backend = str((cfg.get("reconstruct") or {}).get("pdf_backend", "chromium"))
    wrote_pdf, pdf_note = try_render_pdf(
        html_str, out_dir / "page.pdf", backend=backend, html_path=html_path)

    n_blocks = sum(len(p.blocks) for p in doc.pages)
    n_words = sum(bool(w.text.strip()) for p in doc.pages for b in p.blocks for w in b.words)
    n_flag = sum(w.flag_visible for p in doc.pages for b in p.blocks for w in b.words)
    n_trans = sum(1 for p in doc.pages for b in p.blocks if b.text is not None)
    n_fig = sum(1 for p in doc.pages for b in p.blocks if b.type is BlockType.FIGURE)
    order_mode = doc.settings.order_mode
    n_order_unreviewed = sum(
        b.order_review_visible(order_mode) for p in doc.pages for b in p.blocks)

    embedded = [fam for fname, fam, *_ in _FONT_FACES if (FONTS_DIR / fname).exists()]
    if embedded:
        font_note = ("Fonts embedded as @font-face data URIs (self-contained): "
                     + ", ".join(embedded) + " — covers Latin + Cyrillic; renders "
                     "identically without the font installed on the host.")
    else:
        font_note = (f"No bundled TTFs found in {FONTS_DIR} — HTML names the font "
                     "stack but embeds nothing; the renderer falls back to a system "
                     "serif (Cyrillic may tofu). Bundle NotoSerif.ttf to fix.")

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={
            "pages": len(doc.pages), "blocks": n_blocks, "words": n_words,
            "flag_visible": n_flag, "translated_blocks": n_trans, "figures": n_fig,
            "mode": doc.settings.uncertainty_mode,
            "order_mode": order_mode,
            "order_unreviewed": n_order_unreviewed,
            "source_language": doc.settings.source_language,
            "block_languages": {lc: sum(1 for p_ in doc.pages for b in p_.blocks
                                        if b.language == lc)
                                for lc in sorted(block_langs)},
            "target_language": doc.settings.target_language,
            "pdf_backend": backend,
            "wrote_pdf": wrote_pdf,
            "embedded_fonts": embedded,
            "reads": ["document.json", "document_assets/"],
        },
        timings_ms={"total": round(total_ms, 1)},
        warnings=[
            pdf_note,
            font_note,
            (f"De-hyphenation ACTIVE for {doc.settings.source_language}: a line-end "
             f"hyphen is joined only when the next line starts lowercase AND the "
             f"joined token is in that language's lexicon; otherwise the hyphen is "
             f"kept."
             if dictionary is not None else
             "De-hyphenation is INERT: no lexicon for "
             f"{doc.settings.source_language or 'this document'} "
             "(engines.easyocr.lexicon), so every line-end hyphen is conservatively "
             "KEPT. Run `python -m tools.setup_lexicons` to activate joins."),
            "Render is a pure function of document.json + document_assets/ (reads "
            "no per-stage folders); re-run any time after edits. Images inlined as "
            "data URIs -> the HTML is self-contained and portable.",
        ] + ([
            f"order_mode=review and {n_order_unreviewed} block(s) still have an "
            "unreviewed reading order (not renumbered, not confirmed) — the output "
            "used Stage 04's automatic order for them. Open the editor to confirm/"
            "correct before treating this render as final. Editor-only signal; not "
            "shown in the print output.",
        ] if order_mode == "review" and n_order_unreviewed else []),
    )
    (out_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return html_path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage 08 — render the editable document.json to HTML (+PDF)")
    ap.add_argument("job_dir", type=Path, help="job folder, e.g. jobs/<job>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = S4.load_config(args.config)
    html_path = run(args.job_dir, cfg, debug=args.debug)
    meta = (args.job_dir / "render" / "meta.json")
    print(f"{args.job_dir}: wrote {html_path}")
    if meta.exists():
        import json
        p = json.loads(meta.read_text(encoding="utf-8"))["params"]
        print(f"  pages={p['pages']} words={p['words']} figures={p['figures']} "
              f"flagged={p['flag_visible']} translated_blocks={p['translated_blocks']} "
              f"mode={p['mode']} pdf={p['wrote_pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
