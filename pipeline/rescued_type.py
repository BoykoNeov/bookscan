"""Give a RESCUED block a real type where the page proves one, and keep ``other``
where it does not.

WHAT A RESCUED BLOCK IS. Stage 05's ``attach_words`` routes every recognized word
into the Stage 04 block that contains it; the words that land inside no block at all
are grouped by their Tesseract paragraph into *synthetic* blocks so nothing is
dropped (the word-conservation invariant). Those synthetic blocks are typed
``BlockType.OTHER`` because the detector never proposed them and nothing has looked
at what they are. This module is that look.

WHY THIS IS ONE RUNG AND NOT A CLASSIFIER (census of all 16 rescued blocks on the
eight block-order GT subpages, 2026-08-26 — docs/data/rescued_type_census_20260826.json):

  * 10 are OCR noise, one or two garbage tokens each ("n,", "ME", "ei", "di i]",
    "orme", "ed bacri", "I nia pica ian na n PE aaa EEE EEE pa ...").
  * 5 are real words printed ON a figure — a map's title ("CL 'INEAMENTO
    PERIADR\\A"), scale-bar labels ("0.5 cm = 200m", "lo 0.5 cm =5 Km"), a level
    marker ("Livello del"). They are text, but they belong to the artwork, not to
    the reading flow. Typing them is not what they need (they need segmenting).
  * 1 is body text the document should carry: en_coins_01's single footnote line,
    "1 Spalding, Eastern Exchange Currency and Finance, (314)." — an honest
    detector miss, recorded in that fixture's ``known_detector_gap``.

So for 15 of 16, ``other`` is the ACCURATE label and the honest thing is to keep it.
Two rules that suggest themselves were measured and dropped rather than shipped:

  * "type them ``paragraph``" — ``stage08_render._TAG`` maps OTHER and PARAGRAPH to
    the same ``<p>`` with no CSS between them, so it changes nothing in the
    deliverable while asserting body-text status for 15 blocks that are not body
    text.
  * "run the caption parser over them" — ``figure_grouping.PROMOTABLE`` already
    contains ``other``, so a rescued caption is ALREADY promoted at Stage 07. The
    rung would be dead code, and it fires on nothing in this corpus anyway.

WHAT IS AND IS NOT REFUSED. ``HEADER`` and ``PAGE_NUMBER`` are deliberately
unreachable from here. Both are STRIPPED by default (``stage08_render._STRIP``), so
a wrong call on either does not mislabel text — it DELETES it. Nothing in this
corpus is a rescued header or page number, so there is no evidence to buy that risk
with. ``FOOTNOTE`` is safe in exactly the way they are not: it renders, only smaller,
so a wrong call costs a font size and never a sentence.

HONEST LIMIT, and it is a real one. The footnote rung has ONE true positive and no
second example. Worse, the eval cannot police it: the 15 noise blocks match no GT
anchor, so ``tools/layout_order_eval``'s type-accuracy column is structurally BLIND
to a wrong call on them. "111/112 -> 112/112" is evidence the rung fired once and
correctly, NOT evidence that it is safe — that part was checked by reading all 16
blocks by eye. The three conditions below are definitional (what a footnote IS in
typography) rather than fitted, which is the whole argument for trusting them past
n=1; the thresholds attached to them are not, and are stated with their measured
values so a later corpus can contradict them.

This module is PURE: blocks in, types out. No I/O, no OCR, no cv2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipeline.page_model import BBox, Block, BlockType

# Types that make a page's reading flow. Used for "is this block below ALL of the
# body" — headers and page numbers are excluded on purpose, because a footnote
# legitimately sits above the page number and below everything else.
BODY_TYPES = frozenset({
    BlockType.TITLE, BlockType.PARAGRAPH, BlockType.HEADING, BlockType.LIST,
    BlockType.TABLE, BlockType.CAPTION, BlockType.FOOTNOTE,
})

# Types that constitute a TEXT COLUMN a footnote can hang under. Narrower than
# BODY_TYPES on purpose: a footnote belongs to a column of running prose, and
# accepting a caption or a table as the column above would let a stray under a
# side-set caption qualify.
COLUMN_TYPES = frozenset({BlockType.PARAGRAPH, BlockType.LIST})

DEFAULTS: dict[str, float] = {
    # A footnote is a sentence. Below three tokens there is nothing to be a footnote
    # OF — and 10 of the 16 rescued blocks in the census are one- or two-token
    # garbage, so this floor is bought by the distribution, not by the one hit.
    "rescue_footnote_min_words": 3,
    # The block must sit INSIDE the column it hangs under, not merely touch it.
    # Measured: the true positive overlaps its column 1.00; the one competing
    # bottom-margin stray ("i: dad aan", it_geo_07 right) overlaps NO text column at
    # all, which is the condition that separates them.
    "rescue_footnote_min_column_overlap": 0.8,
    # Set smaller than the column it belongs to. Measured on the true positive:
    # word height 24 against its column's 28 (ratio 0.86). The 0.95 ceiling asks for
    # measurably smaller rather than merely not-larger, without demanding a gap this
    # single observation cannot justify.
    "rescue_footnote_max_height_ratio": 0.95,
}


@dataclass(frozen=True)
class RescueType:
    """The verdict for one rescued block: the type to use, and why."""

    type: BlockType
    reason: str


def _param(p: Mapping[str, object] | None, key: str) -> float:
    if p is not None and key in p:
        return float(p[key])  # type: ignore[arg-type]
    return float(DEFAULTS[key])


def _median_word_h(blk: Block) -> float:
    """Median word HEIGHT in a block — the block's own bbox height is useless here
    (a two-line block is twice as tall as a one-line block of the same type)."""
    hs = sorted(w.bbox.h for w in blk.words)
    return float(hs[len(hs) // 2]) if hs else 0.0


def _x_overlap(a: BBox, b: BBox) -> int:
    return max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))


def _footnote_verdict(blk: Block, real: Sequence[Block],
                      p: Mapping[str, object] | None) -> RescueType | None:
    """A footnote is, definitionally: a run of text that sits BELOW the body of the
    page, INSIDE the horizontal span of a text column, and is SET SMALLER than that
    column. All three, or abstain."""
    if len(blk.words) < _param(p, "rescue_footnote_min_words"):
        return None

    body = [b for b in real if b.type in BODY_TYPES]
    columns = [b for b in real if b.type in COLUMN_TYPES and b.words]
    if not body or not columns:
        # A page with no body and no column cannot have a footnote, and without them
        # "below everything" is vacuously true — which is exactly how three strays on
        # a full-page-figure subpage (it_geo_05 left) would otherwise qualify.
        return None

    if blk.bbox.y < max(b.bbox.y + b.bbox.h for b in body):
        return None                                  # not below the body

    # The column it hangs under: a text column that ENDS above this block and whose
    # horizontal span contains it. Nearest one above wins if several qualify.
    min_ov = _param(p, "rescue_footnote_min_column_overlap")
    above = [c for c in columns
             if c.bbox.y + c.bbox.h <= blk.bbox.y
             and blk.bbox.w > 0
             and _x_overlap(blk.bbox, c.bbox) / blk.bbox.w >= min_ov]
    if not above:
        return None
    col = max(above, key=lambda c: c.bbox.y + c.bbox.h)

    col_h, blk_h = _median_word_h(col), _median_word_h(blk)
    if col_h <= 0 or blk_h <= 0:
        return None
    ratio = blk_h / col_h
    if ratio > _param(p, "rescue_footnote_max_height_ratio"):
        return None

    return RescueType(
        BlockType.FOOTNOTE,
        f"below the body, inside the column at y={col.bbox.y} "
        f"(overlap {_x_overlap(blk.bbox, col.bbox) / blk.bbox.w:.2f}), "
        f"set smaller than it ({blk_h:g} vs {col_h:g}, ratio {ratio:.2f})")


def type_rescued(synth: Sequence[Block], real: Sequence[Block],
                 p: Mapping[str, object] | None = None) -> list[RescueType]:
    """Type each rescued block in ``synth`` against the page's ``real`` (Stage 04)
    blocks. One verdict per input block, in order; ``BlockType.OTHER`` means the page
    proved nothing and the honest label is still "unknown"."""
    out: list[RescueType] = []
    for blk in synth:
        v = _footnote_verdict(blk, real, p)
        out.append(v or RescueType(BlockType.OTHER, "no rung fired"))
    return out
