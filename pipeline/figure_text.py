r"""Text the detector clipped off a figure's edge — put it back on the picture.

THE DEFECT. Stage 04's figure box does not always reach the ink. On
``it_geo_05``-left the box starts 3px BELOW the map's printed title
("CL'INEAMENTO PERIADR\A"); on ``it_geo_07``-right it starts 6px below the
cross-section's "Livello del [mare]" label. Those words fall inside no block, so
``attach_words`` rescues them into synthetic ``OTHER`` blocks, XY-Cut ranks them
by position, and the re-typeset document opens the page with a loose paragraph
reading ``CL 'INEAMENTO`` — a fragment of a map's title, standing in the reading
flow as if it were prose. The 2026-08-26 rescued-block census
(``docs/data/rescued_type_census_20260826.json``) counted five such blocks and
recorded the right verdict for them: *they are text, but they belong to the
artwork, not to the reading flow — typing them is not what they need, they need
SEGMENTING.* This module is that segmentation.

THE FIX IS A MERGE, NOT A RE-TYPE. Re-typing a stray ``FIGURE`` would be wrong in
the deliverable: Stage 08 renders a figure as *the crop of its own bbox*, so the
map's title would come out as a 234x48px picture of a title, floating where the
paragraph used to be. What the page actually shows is one picture whose top strip
the detector missed. So the stray is folded INTO the figure block: the figure's
bbox grows to cover it (the crop now includes the title) and the words move onto
the figure (they stop rendering as text). Stage 08 needs no change — it already
draws figure pixels and ignores figure words.

WHY THE WORDS MOVE RATHER THAN GET DROPPED. Stage 05 asserts word conservation:
every recognized word ends in exactly one block. Absorption re-routes words; it
never creates or destroys one, so the invariant holds unchanged. It also keeps
the text recoverable — a user who disagrees re-types the figure in the editor and
the words are still there.

THE GATES, AND THE MEASURED GAPS THEY SIT IN. Run over every rescued block on the
eight block-order GT subpages (16 blocks, the census above). Three qualify:

  | block                        | v-gap to figure | h-inside | nearest text |
  |------------------------------|-----------------|----------|--------------|
  | `CL 'INEAMENTO` it_geo_05 L  | +3px            | 1.00     | 130px        |
  | `PERIADR\A`     it_geo_05 L  | -12px (overlap) | 1.00     | 158px        |
  | `Livello del`   it_geo_07 R  | -6px (overlap)  | 1.00     |  36px        |

and the nearest thing that must NOT is `ME` (de_01-left, one garbage token): 33px
below a figure, but 18px from a paragraph. So:

* **Vertical gap** (``figtext_max_gap_frac``, fraction of page height). Accepted
  blocks sit at +3px or overlapping; the closest rejected one at 33px. On these
  3000px pages that is 0.0010 against 0.0110. The gate is 0.005 — inside the gap,
  deliberately nearer the accepted side, because the claim being made is
  "touching, allowing for OCR box jitter", not "nearby".
* **Horizontal containment** (``figtext_min_h_inside``, x-overlap / stray width).
  All three accepted are 1.00; the nearest rejected is 0.69 (`Cc arbonatiche`,
  it_geo_04-left, which is 135px from its figure anyway). 0.85 is the midpoint.
* **Closer to the figure than to any text.** An independent guard, and the one
  that rejects `ME` on its own merits rather than on a pixel count: a stray 33px
  under a picture but 18px under a paragraph is not the picture's. Every accepted
  block clears this by 40px or more.
* **The grown band must be empty.** The strip the figure gains must contain no
  other block's words. Growing a figure over live text would paint that text into
  the picture *and* leave it rendering as its own block — the duplicated-caption
  defect ``caption_eject`` already paid for once.
* **Unambiguous.** If two figures pass the gates for one stray, abstain. Nothing
  in this corpus is ambiguous; the guard costs nothing and bounds a case the
  measurement has not seen.

WHAT IS DELIBERATELY NOT ABSORBED. `it_geo_07`-left's two scale bars
(``0.5 cm = 200m``, ``lo 0.5 cm =5 Km``) are the other two census blocks that
belong to artwork, and they FAIL these gates: 53px and 150px above the nearest
figure, with no figure box anywhere near them. They are a legend for a whole
column of stacked cross-sections, not text clipped off one picture's edge, and
folding them into the topmost diagram would be a guess about which figure owns
them. They stay loose, which is a known-wrong output recorded here rather than a
wrong pairing shipped — the same bar (`0 wrong`) that ``figure_grouping`` holds.

HONEST LIMIT. Three true positives on one corpus of four books, and none of them
matches a GT anchor — so ``tools/layout_order_eval``'s accuracy columns are
structurally blind to a wrong call here, exactly as they are for
``rescued_type``. The evidence that this does the right thing is PIXELS: both
sites are cropped in ``docs/data/figure_text_ab_20260828_*.png``, and in both the
un-absorbed figure box runs straight through the middle of the words (a
handwritten ``LINEAMENTO PERIADRIATICO`` across a map; an italic ``Livello del
mare`` printed on a cross-section at the waterline).

AND IT IS NOT SIDE-EFFECT FREE — the measured A/B (RESULTS 2026-08-28) says so.
Six of eight images are bit-identical and every accuracy column holds (seg
112/112, pairs 16/19 with 0 wrong, no order field moved), but growing ``D7`` on
``it_geo_07``-right by 17px moved a runner-up gap 53px -> 36px, inside
``figure_grouping``'s ambiguity band (1.60 x max(4, 30) = 48), so a pair that
arm used to emit now abstains. That pair was a SUB-LABEL being paired to its
figure as if it were a caption (the GT for ``D6`` says the text "stays inside"),
so neither arm is right and abstaining is the better of two wrongs — but do not
repeat the claim this line used to make, that every other number is unchanged.

TUNING. Both thresholds live in ``DEFAULTS`` below and are read out of Stage 04's
resolved param dict, so an override goes in the **layout** section of
``config.yaml`` under the same key names — the same seam ``rescued_type`` uses,
so the pipeline and ``tools.layout_order_eval`` can never be tuned apart.

This module is PURE: boxes in, decisions out. No I/O, no OCR, no cv2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipeline.page_model import BBox, BlockType

DEFAULTS: dict[str, float] = {
    # Vertical gap between the stray and the figure, as a fraction of page
    # height. Accepted: +3px / overlapping (0.0010 and below). Rejected nearest:
    # 33px (0.0110). See the table in the module docstring.
    "figtext_max_gap_frac": 0.005,
    # x-overlap / stray width. Accepted: 1.00 x3. Rejected nearest: 0.69.
    "figtext_min_h_inside": 0.85,
}


@dataclass(frozen=True)
class Absorption:
    """One stray folded into one figure: which, into which, and why."""

    stray: int          # index into the strays passed in
    figure: int         # index into the real (Stage 04) blocks
    reason: str


def _x_overlap(a: BBox, b: BBox) -> int:
    return max(0, min(a.x2, b.x2) - max(a.x, b.x))


def _y_overlap(a: BBox, b: BBox) -> int:
    return max(0, min(a.y2, b.y2) - max(a.y, b.y))


def _v_gap(a: BBox, b: BBox) -> int:
    """Vertical distance from ``a`` to ``b``: positive when separated, negative
    (minus the overlap height) when they overlap. Ordering by this puts "deepest
    overlap" first, which is what "most plainly the same object" means here."""
    if a.y2 <= b.y:
        return b.y - a.y2
    if a.y >= b.y2:
        return a.y - b.y2
    return -_y_overlap(a, b)


def _param(p: Mapping[str, object] | None, key: str) -> float:
    if p is not None and key in p:
        return float(p[key])  # type: ignore[arg-type]
    return float(DEFAULTS[key])


def union(a: BBox, b: BBox) -> BBox:
    """The smallest box covering both. A NEW object — Stage 04's boxes are shared
    by reference into Stage 05's block copies and are never mutated."""
    x, y = min(a.x, b.x), min(a.y, b.y)
    return BBox(x=x, y=y, w=max(a.x2, b.x2) - x, h=max(a.y2, b.y2) - y)


def _band_is_empty(fig: BBox, stray: BBox, occupied: Sequence[BBox]) -> bool:
    """True when the region the figure GAINS holds no other block's words.

    Tested as "does any occupied box meet the union while lying outside the
    figure" — a box already inside the figure was already covered by the crop and
    is not a new hazard."""
    grown = union(fig, stray)
    for ob in occupied:
        if _x_overlap(ob, grown) <= 0 or _y_overlap(ob, grown) <= 0:
            continue                              # not in the grown box at all
        if (ob.x >= fig.x and ob.y >= fig.y
                and ob.x2 <= fig.x2 and ob.y2 <= fig.y2):
            continue                              # already inside the figure
        return False
    return True


def absorb_figure_text(
    strays: Sequence[BBox],
    real_boxes: Sequence[BBox],
    real_types: Sequence[BlockType],
    real_has_words: Sequence[bool],
    page_h: int,
    p: Mapping[str, object] | None = None,
) -> list[Absorption]:
    """Decide which rescued blocks are text clipped off a figure's edge.

    ``real_*`` are parallel per-block views of Stage 04's blocks: box, type, and
    whether any recognized word routed into it. ``real_has_words`` is what makes
    a block count as a competing *text* block — an empty detection is not
    evidence that a stray belongs to the reading flow.

    Returns one ``Absorption`` per accepted stray, in stray order. A stray that
    fails any gate is simply absent from the result: it stays a rescued block and
    ``rescued_type`` types it exactly as before.
    """
    max_gap = _param(p, "figtext_max_gap_frac") * max(1, page_h)
    min_h_in = _param(p, "figtext_min_h_inside")

    figures = [i for i, t in enumerate(real_types) if t is BlockType.FIGURE]
    occupied = [b for i, b in enumerate(real_boxes) if real_has_words[i]]
    text_boxes = [b for i, b in enumerate(real_boxes)
                  if real_types[i] is not BlockType.FIGURE and real_has_words[i]]

    out: list[Absorption] = []
    for si, sb in enumerate(strays):
        if sb.w <= 0 or sb.h <= 0:
            continue
        cands = [fi for fi in figures
                 if _x_overlap(sb, real_boxes[fi]) / sb.w >= min_h_in
                 and _v_gap(sb, real_boxes[fi]) <= max_gap]
        if len(cands) != 1:
            continue                              # none, or ambiguous
        fi = cands[0]
        fig = real_boxes[fi]
        gap = _v_gap(sb, fig)

        # Closer to this figure than to any text block sharing its span.
        near_text = min((_v_gap(sb, tb) for tb in text_boxes
                         if _x_overlap(sb, tb) > 0), default=None)
        if near_text is not None and near_text <= gap:
            continue

        if not _band_is_empty(fig, sb, occupied):
            continue

        h_in = _x_overlap(sb, fig) / sb.w
        near = (f", nearest text {near_text:+d}px)" if near_text is not None
                else ", no text shares its span)")
        out.append(Absorption(
            stray=si, figure=fi,
            reason=(f"clipped off the figure at y={fig.y} "
                    f"(v-gap {gap:+d}px, {h_in:.2f} inside its span" + near)))
    return out
