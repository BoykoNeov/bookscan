"""Blocks whose text cannot be read — keep the PIXELS instead of the noise.

THE CASE THIS EXISTS FOR (measured, `de_01`, the German via-ferrata guide).
The left page carries a vertical **icon sidebar**: star rating, difficulty grade,
walking times, altitude, GPS coordinates — each a pictogram with a scrap of text
beside it. Tesseract reads it as scattered garbage
(``"2842 m (5 )N 4638379 LE 1.526074 46.38138"``), and because the panel is the
leftmost column it lands EARLY in reading order, so the re-typeset document opens
with a paragraph of noise. The 2026-07-18 real-capture note (Finding 3, symptom 1)
recorded this and deferred the decision, on the grounds that *in a climbing guide
that difficulty/time/GPS panel is high-value structured information, not junk to
drop*. That is exactly right, and it rules out the obvious two answers: rendering
the noise is wrong, and stripping the panel throws away the information.

THE DECISION: **re-type the block FIGURE, so Stage 08 renders the pixels.**
Nothing about the panel's position changes — the note is explicit that its
leftmost-first placement is already correct, so this touches typing only. It is
the block-level analogue of the per-word ``patch`` mode CLAUDE.md already
mandates: where the recognizer cannot be trusted, show the reader the original
image. The information survives, the noise does not, and the cost is stated —
that panel is not searchable text in the output.

Two things make this a normalization rather than an invention:
* the facing fixture `de_02` carries the SAME panel, and its detector already
  types it ``figure`` — the desired end state already exists in the pipeline, on
  one page of one book but not the other;
* the words are kept on the block, so a user who disagrees re-types it in the
  editor and gets the text back. ``type_promoted`` marks the change as automatic,
  never as a human edit.

THE TEST IS ADAPTIVE, NOT A GLOBAL CUTOFF (CLAUDE.md's non-negotiable). A block
is unreadable when its **median word confidence falls below ``conf_ratio`` of the
job's own median text-block confidence**. A uniformly poor scan moves the
reference down with it and nothing fires; only a block that is bad *relative to
its own document* does.

MEASURED on the production path — the full pipeline plus assemble over all 15
testset spreads, 326 blocks. **Exactly 4 convert, and all 4 are unreadable
junk**: both German icon sidebars (`de_01` at 0.68 of its job's reference,
`de_02` at 0.63), `de_02`'s garbled banner strip (0.27) and `it_geo_05`'s stray
map glyphs (0.29). Nothing fires on any Bulgarian, English or other Italian page.
The `min_words` floor is where it is because the sweep says so: at 5 it converts
two more blocks, both still junk; at 3 it starts converting real text (the
"English Version" headings, which OCR at 32-41 because they are set in a coloured
banner). So the shipped floor keeps two junk blocks of margin between it and the
first false positive.

HONEST LIMITS. Every block this fires on is a picture instead of searchable text,
and that is a real loss, taken deliberately because the alternative on these
pages is noise. It is calibrated on one corpus of four books. And it does NOT
clean up the whole sidebar: on `de_01` the detector fragments the panel, and the
1-, 3- and 5-word slivers it leaves behind stay below ``min_words`` and still
render as text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from pipeline.page_model import Block, BlockType

DEFAULTS: dict[str, float] = {
    # Block median conf / job median text-block conf, below which the block is
    # read as unreadable. de_01's sidebar sits at 0.45 and 0.62 of its job's
    # reference; the lowest ordinary text block in the corpus sits at 0.92.
    "conf_ratio": 0.75,
    # Too few words is a fragment, not a panel — and converting a fragment to a
    # picture is a worse trade (de_02's stray "2806 m" is two words at conf 26.5
    # and deliberately does NOT convert).
    "min_words": 8.0,
}

# Types that may be re-typed. A FIGURE already renders as pixels; a header or
# page number is stripped anyway; a caption belongs to its figure. Deliberately
# narrow: this pass may only ever turn body-text-shaped blocks into pictures.
CONVERTIBLE = (BlockType.PARAGRAPH, BlockType.OTHER, BlockType.LIST,
               BlockType.CAPTION, BlockType.HEADING)

# Types counted when computing the job's reference confidence — the ordinary
# running text of the document. Figures are excluded because stray glyphs routed
# into a photograph are exactly the low-confidence noise we are measuring against.
REFERENCE_TYPES = (BlockType.PARAGRAPH, BlockType.LIST, BlockType.HEADING,
                   BlockType.CAPTION)


@dataclass
class PanelScan:
    """What the pass decided, and what it measured to decide it."""

    reference_conf: float | None = None      # job median text-block confidence
    # (page index, block id) -> the block's median conf. Keyed by PAGE too:
    # Block.id is page-scoped, not document-unique (which is why a pairing is a
    # page-scoped BlockRef), so a bare id would convert the same-numbered block
    # on every page — measured, on de_01, where block 7 of the left page is the
    # icon panel and block 7 of the right page is the English translation column.
    converted: dict[tuple[int, int], float] = field(default_factory=dict)
    n_considered: int = 0

    @property
    def n_converted(self) -> int:
        return len(self.converted)


def resolve_params(overrides: dict | None = None) -> dict[str, float]:
    p = dict(DEFAULTS)
    if overrides:
        p.update({k: float(v) for k, v in overrides.items() if k in DEFAULTS})
    return p


def _block_conf(blk: Block) -> float | None:
    """Median confidence over the block's non-blank words, or None if it has none.

    Median rather than mean: one confidently-read word ("Sept.") in a panel of
    garbage should not lift the block, and one garbled word in a clean paragraph
    should not sink it."""
    confs = [w.conf for w in blk.words if w.text.strip()]
    return median(confs) if confs else None


def scan(blocks_by_page: Sequence[Sequence[Block]],
         params: dict | None = None) -> PanelScan:
    """Decide which blocks across a whole JOB are unreadable panels.

    Job-scoped on purpose: the reference is "confidence normal FOR THIS
    DOCUMENT", the same convention Stage 06 uses for its adaptive word threshold.
    A per-page reference would let a page that is ALL panel declare itself normal.
    """
    p = resolve_params(params)
    out = PanelScan()

    ref_pool = [c for page in blocks_by_page for blk in page
                if blk.type in REFERENCE_TYPES
                for c in [_block_conf(blk)] if c is not None]
    if not ref_pool:
        return out                       # no running text to compare against
    out.reference_conf = float(median(ref_pool))
    floor = p["conf_ratio"] * out.reference_conf

    for pi, page in enumerate(blocks_by_page):
        for blk in page:
            if blk.type not in CONVERTIBLE:
                continue
            n_words = sum(1 for w in blk.words if w.text.strip())
            if n_words < int(p["min_words"]):
                continue
            out.n_considered += 1
            c = _block_conf(blk)
            if c is not None and c < floor:
                out.converted[(pi, blk.id)] = float(c)
    return out


def apply_to_blocks(blocks: list[Block], sc: PanelScan, page_index: int) -> list[Block]:
    """Re-type the scanned blocks FIGURE (returns new Blocks).

    Sets BOTH ``type`` and ``type_auto`` and raises ``type_promoted``, exactly as
    caption promotion does: this is an AUTOMATIC decision and the editor must not
    read it as a user override. Any caption bookkeeping the block carried is
    cleared — a picture does not have a caption number, and a pairing keyed on a
    block that is no longer a caption would render as a caption again."""
    out: list[Block] = []
    for b in blocks:
        if (page_index, b.id) not in sc.converted:
            out.append(b)
            continue
        out.append(b.model_copy(update={
            "type": BlockType.FIGURE,
            "type_auto": BlockType.FIGURE,
            "type_promoted": True,
            "caption_number": None,
            "figure_ref": None,
            "pair_source": None,
        }))
    return out
