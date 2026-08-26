"""Caption<->figure GROUPING — the owner's #1 layout priority, made real.

CLAUDE.md's non-negotiable: *"Figures are cropped from the full-resolution
dewarped image and placed with their captions as a single block in reading
order."* Until now that grouping existed only as **adjacency** in Stage 08
(``blocks[i+1].type is CAPTION``), and the two modules that actually solve it —
``caption_parser`` (types a caption + reads its printed number) and
``figure_label`` (reads a figure's in-photo corner-label number) — were imported
ONLY by ``tools/layout_order_eval``. Their measured wins (caption typing 0/6 ->
6/6, number-keyed pairing 2/6 on it_geo_06) therefore moved **zero** of the
production output. This module is the single place where those two are combined
into a decision, and it is called by BOTH Stage 07 (production) and the eval
(measurement) so the number in RESULTS.md is the number the pipeline produces.

WHY ADJACENCY CANNOT DO THIS (measured, it_geo_06 left subpage):
the four cliff captions form a STACK in a narrow column on the far side of the
subpage (x~1600) while three of their figures are the left column (x203..1561),
and the caption stack's order (25, 26, 27, 28) does NOT track figure position —
physical F26 is the top-RIGHT plate. So neither "the next block" nor "the
nearest figure" recovers the true partner of C26. Only the printed number does.

THE PAIRING POLICY (two arms, number first, geometry guarded):

1. **Number arm (authoritative).** A caption whose printed number equals exactly
   one figure's recovered corner-label number pairs to it, wherever that figure
   sits. This is what defeats the C26->F26 trap.

2. **Guarded geometry arm (the ordinary book).** Most books print no in-photo
   corner labels, so the number arm recovers nothing and grouping would vanish
   entirely. A caption with no number pair may still pair to a figure it is
   plainly attached to — but ONLY when the attachment is unambiguous. There are
   two attachment SHAPES, and they are not equally strong evidence:

   * **stacked** (the caption sits UNDER or OVER its figure) — horizontal
     overlap >= ``geom_min_overlap_frac`` of the narrower box, vertical gap
     <= ``geom_max_gap_frac`` of the page height;
   * **side-set** (the caption sits BESIDE its figure, inside that figure's
     vertical band) — vertical overlap >= ``side_min_yov_frac`` of the shorter
     box and horizontal gap <= ``side_max_gap_frac`` of the page WIDTH.
     Measured on ``en_coins_01/02/03`` (2026-08-18): every caption in that
     English book sits to the RIGHT of its coin plate with x-overlap **exactly
     0.00** and a 11-36px horizontal gap, so the stacked rule rejected all nine
     of them and grouping recovered nothing on the whole book.

   Sitting beside a figure is WEAKER evidence than sitting under it: a block
   merely beside a photo may belong to a neighbouring column that has nothing to
   do with it. ``de_01``'s icon sidebar is exactly that — its Gehzeiten panel
   has y-overlap 1.00 and a 28px gap to the page photo and is not its caption.
   So the side-set shape additionally requires the block to **declare itself a
   caption in print** (a parsed "Fig. NN" header). Two independent signals for
   the weaker geometry. Honest limit: side-set pairing therefore does nothing
   for a book that sets captions beside its figures and prints no numbers.

   Whichever shape applies, all of these must also hold:
     * **mutual nearest** — the figure's own closest eligible caption is this
       caption (kills "two captions both grab the one figure");
     * **unambiguous** — the runner-up figure is at least
       ``geom_ambiguity_ratio`` x further away than the winner;
     * **figure-numbering-regime guard** — if any PLAUSIBLE figure number was
       recovered on this subpage, the book is printing figure numbers, so a
       caption that HAS a printed number and found no numeric partner ABSTAINS
       instead of guessing geometrically. Its figure's label simply did not OCR;
       geometry is not entitled to overrule the printed numbering. (Without this
       guard, it_geo_06's C25 would grab the top-right F26 — the exact mispairing
       the fixture was built to trap.) "Plausible" means inside the span of the
       caption numbers printed on the SAME subpage, widened by
       ``fig_number_window`` — figures and captions on one page belong to one
       short run of numbers. Measured need: on ``en_coins_03``-right
       ``figure_label`` reads **4** off a Honduras Peso photograph that carries no
       printed number at all, on a subpage whose captions read 104 and 105, and
       that single false read used to suppress the geometry arm for both of them.
     * **caption-numbering-regime guard** — if ANY caption on this subpage
       carries a printed number, the book numbers its captions, so a block typed
       ``caption`` that carries NO number is not one of them and does not pair.
       Measured need: this book's run-in "Description:" section labels are typed
       ``caption`` by the detector and sit 11-40px below a coin plate — closer to
       it than the real caption is — so without this guard the pass emits
       "Description:" as the plate's caption while the real caption abstains.

3. **Sole figure, sole printed caption (no geometry at all).** Measured
   2026-08-26 on the two remaining pairing misses in the corpus — ``it_geo_04``'s
   "A lato: Figura 20" and ``it_geo_05``'s "Sopra: Figura 3". Both books set the
   caption in a side column far from its plate: column overlap 0.04 and **0.00**,
   vertical gap 0.38 and 0.39 of the page height. Proximity carries no
   information on that layout, and the distances involved are the same ones the
   ``it_geo_06`` trap is built out of, so **loosening arm 2's limits would buy
   these two pairs by re-opening the wrong-photo failure it exists to prevent.**

   What IS present is uniqueness. So this arm fires only when the subpage prints
   **exactly one figure**, that figure is still unpaired, and **exactly one**
   eligible caption remains — and that caption carries a printed figure number.
   Two independent signals again, neither of them a distance: the block declares
   itself a caption *in print*, and there is no other figure on the page it could
   be describing. It runs LAST, so a caption arm 2 can already place keeps its
   proximity-backed provenance and nothing that pairs today changes.

   Honest limit, and the shape of the only way it can be wrong: a spread whose
   single figure on one page belongs to the FACING page's caption while this
   page's caption describes the figure over there. Nothing in this corpus does
   that; the arm would mispair it, and no available signal would catch it.

**The success bar is ZERO WRONG PAIRS, not N pairs** — the same invariant
``figure_label`` already holds for its digit reads. A caption printed under the
wrong photo is worse output than a caption rendered on its own, so every rule
above is a reason to ABSTAIN. Abstentions are counted and reported, never hidden.

This module is pure decision logic over a ``BlockView`` (a minimal
key/type/bbox/text record). It touches no files. Pixels enter only through the
optional ``page_bgr`` handed to ``figure_label`` for corner-label OCR; with no
image or no Tesseract the number arm degrades to routed text and the geometry
arm still works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from pipeline import caption_parser as CP
from pipeline import figure_label as FL
from pipeline.page_model import BBox, Block, BlockRef, BlockType, PairSource

# Geometry knobs: layout geometry (fractions of the boxes/page), the same
# allowed heuristic class as Stage 04's XY-cut gaps and figure-split seams —
# NOT the adaptive OCR-confidence thresholds CLAUDE.md forbids hard-coding.
DEFAULTS: dict[str, float] = {
    "geom_min_overlap_frac": 0.50,   # x-overlap / min(caption_w, figure_w)
    "geom_max_gap_frac": 0.08,       # vertical caption<->figure gap, frac of page height
    "geom_ambiguity_ratio": 1.60,    # runner-up gap must be >= this x the winner's
    "geom_gap_floor_frac": 0.01,     # gaps below this (frac of page h) compare as equal
    "geom_max_nest_frac": 0.50,      # caption area inside the figure box => swallowed
    # Relaxed gap for the unambiguous SOLO case only: exactly one figure and one
    # eligible caption on the subpage, sharing a column. With nothing to confuse
    # it with there is no wrong figure available to pick, so a caption further
    # down the column can still be claimed. Measured need: it_geo_04's right
    # subpage puts the Fig.21 panorama caption 577px (0.19 of page height) below
    # its panorama with no other figure present.
    "geom_solo_max_gap_frac": 0.25,
    # SIDE-SET attachment (caption beside its figure, inside the figure's
    # vertical band). Measured on en_coins_01/02/03 (2026-08-18): the nine real
    # captions score y-overlap 0.77-1.00 and horizontal gaps of 11-36px on
    # ~2000px-wide subpages (0.006-0.018), while the it_geo gutter-side caption
    # columns this must NOT claim sit 1151-1170px away (0.55+). Both floors sit
    # in the wide empty middle of that separation.
    "side_min_yov_frac": 0.50,       # y-overlap / min(caption_h, figure_h)
    "side_max_gap_frac": 0.05,       # horizontal caption<->figure gap, frac of page WIDTH
    # How far outside the subpage's caption-number span a recovered FIGURE number
    # may sit before it is read as a misread rather than a figure number. See
    # _plausible_figure_numbers.
    "fig_number_window": 3.0,
}

# Detector types eligible for promotion to CAPTION by the textual parser.
# NEVER promote a figure/table/header; NEVER demote anything (caption_parser's
# own invariant) — a promotion can only add a caption, so the non-regression
# argument stays arithmetic.
PROMOTABLE = ("paragraph", "other", "list")


@dataclass(frozen=True)
class BlockView:
    """The minimal block record the grouping decision needs.

    Deliberately NOT ``page_model.Block``: the eval grades Stage-04 output joined
    to routed OCR words (its own ``DetBlock``), while Stage 07 works on editable
    ``Block``s. A tiny shared view lets both call the SAME decision code instead
    of maintaining two implementations — which is exactly how the eval-only
    "parser arm" drifted away from production in the first place.
    """

    key: str        # caller-stable identity (eval: det index; Stage 07: block id)
    btype: str      # block type as a plain string ("figure", "caption", ...)
    bbox: BBox
    text: str = ""  # routed OCR text (empty for most figures)


@dataclass
class Grouping:
    """The decision: what was typed, what was numbered, what was paired, and —
    just as load-bearing — what deliberately was not."""

    promoted: dict[str, int] = field(default_factory=dict)         # key -> caption number
    caption_numbers: dict[str, int] = field(default_factory=dict)  # key -> printed number
    figure_numbers: dict[str, int] = field(default_factory=dict)   # key -> corner label
    pairs: dict[str, str] = field(default_factory=dict)            # caption key -> figure key
    pair_source: dict[str, str] = field(default_factory=dict)      # caption key -> arm
    abstained: dict[str, str] = field(default_factory=dict)        # caption key -> why not paired

    def effective_type(self, view: BlockView) -> str:
        """Block type after caption promotion."""
        return "caption" if (view.btype == "caption" or view.key in self.promoted) else view.btype

    @property
    def n_by_number(self) -> int:
        return sum(1 for s in self.pair_source.values() if s == "number")

    @property
    def n_by_geometry(self) -> int:
        return sum(1 for s in self.pair_source.values() if s == "geometry")

    @property
    def n_by_sole_figure(self) -> int:
        return sum(1 for s in self.pair_source.values() if s == "sole_figure")


# --------------------------------------------------------------------------
# Geometry helpers (pure)
# --------------------------------------------------------------------------


def _x_overlap_frac(a: BBox, b: BBox) -> float:
    """Horizontal overlap as a fraction of the NARROWER box. A caption sits under
    (or over) its figure, so it shares that figure's column; a caption in the
    gutter-side column beside a DIFFERENT column's photo scores ~0 here, which is
    what keeps it_geo_06's caption stack from grabbing the cliff photos."""
    ov = min(a.x2, b.x2) - max(a.x, b.x)
    if ov <= 0:
        return 0.0
    return ov / max(1, min(a.w, b.w))


def _nest_frac(cap: BBox, fig: BBox) -> float:
    """Fraction of the CAPTION's area lying inside the figure's box.

    A high value does not mean "very close" — it means the detector's figure box
    SWALLOWED the caption. it_geo_06's right subpage is exactly this: the L-shaped
    F29+F30 detection absorbed the C29 caption column (Phase B's caption ejection
    was never built), so C29's box sits 97% inside the box the eval matches to
    GT F30. Treating that as adjacency pairs the caption to the wrong photo,
    which is how this rule earned its place: containment is an ABSTAIN signal,
    never an attachment signal.
    """
    ix = min(cap.x2, fig.x2) - max(cap.x, fig.x)
    iy = min(cap.y2, fig.y2) - max(cap.y, fig.y)
    if ix <= 0 or iy <= 0:
        return 0.0
    return (ix * iy) / max(1, cap.w * cap.h)


def _v_gap(cap: BBox, fig: BBox) -> float:
    """Vertical clearance between caption and figure (0 if they overlap in y)."""
    if cap.y >= fig.y2:
        return float(cap.y - fig.y2)      # caption below the figure (the common case)
    if fig.y >= cap.y2:
        return float(fig.y - cap.y2)      # caption above the figure
    return 0.0


def _y_overlap_frac(a: BBox, b: BBox) -> float:
    """Vertical overlap as a fraction of the SHORTER box — the side-set mirror of
    ``_x_overlap_frac``. A caption set beside its figure lies wholly inside that
    figure's vertical band (1.00 on the en_coins plates); a block beside a
    DIFFERENT figure scores 0."""
    ov = min(a.y2, b.y2) - max(a.y, b.y)
    if ov <= 0:
        return 0.0
    return ov / max(1, min(a.h, b.h))


def _h_gap(cap: BBox, fig: BBox) -> float:
    """Horizontal clearance between caption and figure (0 if they overlap in x)."""
    if cap.x >= fig.x2:
        return float(cap.x - fig.x2)      # caption to the right of the figure
    if fig.x >= cap.x2:
        return float(fig.x - cap.x2)      # caption to the left of the figure
    return 0.0


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------


def resolve_params(overrides: dict | None = None) -> dict[str, float]:
    p = dict(DEFAULTS)
    if overrides:
        p.update({k: float(v) for k, v in overrides.items() if k in DEFAULTS})
    return p


def promote_captions(views: Sequence[BlockView], lang: str) -> dict[str, int]:
    """Re-type promotable blocks whose OCR text STARTS with a printed caption
    header ("Figura 26", "Sopra: Figura 29") and return key -> parsed number.

    Start-anchored by ``caption_parser``, so body prose that merely mentions
    "(fig. 28)" mid-sentence is never promoted."""
    out: dict[str, int] = {}
    for v in views:
        if v.btype not in PROMOTABLE:
            continue
        ref = CP.parse_caption(v.text, lang)
        if ref is not None:
            out[v.key] = ref.number
    return out


def read_figure_numbers(views: Sequence[BlockView], page_bgr: np.ndarray | None,
                        tess_bin: str | None,
                        page_h: int | None = None,
                        second_opinion: bool = True) -> dict[str, int]:
    """Recover each figure's printed number: first from routed text (the cheap,
    pure path — a corner label that happened to OCR into the block), else from
    the figure's PIXELS via ``figure_label.read_corner_label``.

    ``page_h`` is passed straight through to ``figure_label``, which needs it to
    size the label it is hunting for: the number is printed at a page-relative
    size, not a figure-relative one.

    ``second_opinion`` enables ``figure_label``'s two-recognizer arm on figures the
    strict read misses (it_geo_06 F28). It only ever turns a miss into a number, but
    it costs a recognizer load plus a re-crop sweep per missed figure, so callers
    that want the cheap path can switch it off.

    Only successful reads appear in the result; ``figure_label`` returns None
    rather than guessing (its "0 wrong" invariant), and that conservatism is what
    the number arm's authority rests on."""
    out: dict[str, int] = {}
    try:
        for v in views:
            if v.btype != "figure":
                continue
            n = CP.figure_number(v.text)
            if n is None and page_bgr is not None and tess_bin:
                b = v.bbox
                crop = page_bgr[max(0, b.y):b.y2, max(0, b.x):b.x2]
                if crop.size:
                    n = FL.read_corner_label(crop, tess_bin, page_h=page_h,
                                             second_opinion=second_opinion)
            if n is not None:
                out[v.key] = n
    finally:
        # Release the second-opinion model here rather than leaving it resident
        # for the process: Stage 05 keeps its own EasyOCR reader, and two models
        # on one consumer card is what the GPU-hygiene rule forbids. Loading is
        # lazy, so this is a no-op when the arm never fired.
        if second_opinion:
            FL.close_reader()
    return out


def _plausible_figure_numbers(read: dict[str, int], caption_numbers: dict[str, int],
                              window: int) -> dict[str, int]:
    """Drop a recovered figure number that cannot belong to this page's numbering.

    Figures and captions printed on one page belong to the same short run of
    figure numbers, so a corner label far outside the span of the caption numbers
    on that same subpage is a MISREAD, not a figure number. Measured need
    (en_coins_03-right, 2026-08-18): ``figure_label`` returns **4** for a Honduras
    Peso photograph that carries no printed number anywhere, on a subpage whose
    captions read 104 and 105. Left standing, that one false read put the whole
    subpage into "this book prints figure numbers" mode and suppressed the
    geometry arm for both real captions.

    The window is deliberately loose (a figure whose caption sits on the facing
    page still clears it) — the job is to reject a read from a different order of
    magnitude, not to police off-by-one."""
    if not read or not caption_numbers:
        return dict(read)
    lo, hi = min(caption_numbers.values()), max(caption_numbers.values())
    return {k: n for k, n in read.items() if lo - window <= n <= hi + window}


def _geometric_pairs(caps: list[BlockView], figs: list[BlockView], page_h: int,
                     p: dict[str, float], page_w: int,
                     numbered: frozenset[str] = frozenset()
                     ) -> tuple[dict[str, str], dict[str, str]]:
    """The guarded proximity arm over the captions/figures the number arm left.

    ``numbered`` is the set of caption keys that carry a printed caption number;
    only those are eligible for the weaker SIDE-SET attachment shape (see the
    module docstring). Returns ``(pairs, abstain_reasons)``. Every guard is a
    reason to abstain — see the module docstring for why a wrong pair costs more
    than a missing one.
    """
    solo = len(caps) == 1 and len(figs) == 1
    gap_frac = p["geom_solo_max_gap_frac"] if solo else p["geom_max_gap_frac"]
    max_gap = gap_frac * max(1, page_h)
    max_side_gap = p["side_max_gap_frac"] * max(1, page_w)
    floor = p["geom_gap_floor_frac"] * max(1, page_h)
    pairs: dict[str, str] = {}
    why: dict[str, str] = {}

    def candidates(cap: BlockView) -> list[tuple[float, BlockView]]:
        """Eligible figures for ``cap``, nearest first.

        Distance is the box-to-box edge clearance on the axis that separates the
        two boxes: a stacked caption is separated vertically (h_gap 0), a
        side-set one horizontally (v_gap 0), so ``max(h_gap, v_gap)`` is the one
        number that ranks BOTH shapes on the same scale. That matters because the
        mutual-nearest and ambiguity tests below compare candidates that may have
        arrived by different shapes.
        """
        out = []
        for f in figs:
            if _nest_frac(cap.bbox, f.bbox) > p["geom_max_nest_frac"]:
                continue          # swallowed by this figure's box, not attached to it
            vg, hg = _v_gap(cap.bbox, f.bbox), _h_gap(cap.bbox, f.bbox)
            stacked = (_x_overlap_frac(cap.bbox, f.bbox) >= p["geom_min_overlap_frac"]
                       and vg <= max_gap)
            side = (cap.key in numbered
                    and _y_overlap_frac(cap.bbox, f.bbox) >= p["side_min_yov_frac"]
                    and hg <= max_side_gap)
            if not (stacked or side):
                continue
            out.append((max(vg, hg), f))
        return sorted(out, key=lambda t: t[0])

    cand_by_cap = {c.key: candidates(c) for c in caps}

    for cap in caps:
        cands = cand_by_cap[cap.key]
        if not cands:
            why[cap.key] = "no figure shares this caption's column within the gap limit"
            continue
        best_gap, best_fig = cands[0]
        if len(cands) > 1:
            runner_up = cands[1][0]
            if runner_up < p["geom_ambiguity_ratio"] * max(best_gap, floor):
                why[cap.key] = (f"ambiguous: two figures are comparably close "
                                f"({best_gap:.0f}px vs {runner_up:.0f}px)")
                continue
        # Mutual-nearest: the winning figure's own closest eligible caption must
        # be THIS caption, else two captions are competing for one figure and we
        # cannot tell which is the real partner.
        rivals = [(cand_by_cap[c.key][0][0], c.key) for c in caps
                  if cand_by_cap[c.key] and cand_by_cap[c.key][0][1].key == best_fig.key]
        if rivals and min(rivals)[1] != cap.key:
            why[cap.key] = (f"another caption ({min(rivals)[1]}) is closer to the "
                            f"same figure — cannot tell which is the partner")
            continue
        pairs[cap.key] = best_fig.key
    return pairs, why


def _sole_figure_pair(caps: list[BlockView], figs: list[BlockView],
                      all_figs: list[BlockView], numbered: frozenset[str]
                      ) -> tuple[str, str] | None:
    """The uniqueness arm: pair when there is nothing else on the page to pair to.

    Deliberately geometry-free — see arm 3 in the module docstring for why the
    distances on this layout are not usable, and why loosening arm 2 instead would
    re-open the ``it_geo_06`` wrong-photo trap.

    ``all_figs`` is every figure block on the subpage, not just the unpaired ones:
    the claim being made is "this page prints ONE figure", and a page that printed
    two and had one already claimed is not that page.

    Returns the (caption key, figure key) pair, or None to abstain.
    """
    if len(all_figs) != 1 or len(figs) != 1 or len(caps) != 1:
        return None
    cap = caps[0]
    if cap.key not in numbered:
        # No printed "Figura NN" header. Uniqueness alone is one signal, and one
        # signal is what de_01's icon sidebar would clear — it is the only block
        # of its kind beside the only photo on its half of the spread, and it is
        # not a caption. The print requirement is the second signal.
        return None
    return cap.key, figs[0].key


def group_figures(views: Sequence[BlockView], page_h: int, lang: str = "ita",
                  page_bgr: np.ndarray | None = None, tess_bin: str | None = None,
                  params: dict | None = None, page_w: int | None = None) -> Grouping:
    """Type, number and pair one SUBPAGE's blocks.

    Subpage-shaped on purpose: the eval grades per subpage, Stage 07 loops over
    the document's pages calling this once each. (The reverse — a document-shaped
    function the eval had to fake a document for — is what would let the two
    drift apart again.)

    ``page_h`` is the subpage image height (the geometry knobs are fractions of
    it). ``page_w`` is its width, used only by the side-set gap limit; when the
    caller does not know it, it is inferred from the blocks' own right edges,
    which under-estimates it slightly (so the side limit only ever gets tighter,
    never looser). ``page_bgr``/``tess_bin`` are optional; without them the
    corner-label arm is skipped and only routed text can supply a figure number.
    """
    p = resolve_params(params)
    if page_w is None:
        page_w = max((v.bbox.x2 for v in views), default=page_h)
    g = Grouping()

    g.promoted = promote_captions(views, lang)
    caps = [v for v in views if g.effective_type(v) == "caption"]
    figs = [v for v in views if v.btype == "figure"]

    for c in caps:
        if c.key in g.promoted:
            g.caption_numbers[c.key] = g.promoted[c.key]
        else:
            ref = CP.parse_caption(c.text, lang)      # already-typed captions too
            if ref is not None:
                g.caption_numbers[c.key] = ref.number

    # Corner-label OCR is the expensive step (a localization pass + 4 Tesseract
    # invocations per figure, ~2.7s on a 6-figure spread vs ~12ms for the rest of
    # assemble). The number arm needs BOTH sides, so reading figure labels on a
    # subpage where no caption carries a printed number can never produce a pair —
    # skip it. Consequence, stated rather than hidden: on such a subpage
    # ``figure_number`` is not recorded as provenance either.
    if g.caption_numbers:
        g.figure_numbers = _plausible_figure_numbers(
            read_figure_numbers(figs, page_bgr, tess_bin, page_h),
            g.caption_numbers, int(p["fig_number_window"]))

    # --- arm 1: printed number (authoritative) ---
    num_pairs = CP.pair_by_number(g.caption_numbers, dict(g.figure_numbers))
    for cid, fid in num_pairs.items():
        g.pairs[cid] = fid
        g.pair_source[cid] = "number"

    # --- arm 2: guarded geometry over what is left ---
    numbered_regime = bool(g.figure_numbers)
    # The mirror on the caption side: where the book numbers its captions, a
    # block typed `caption` that carries no number is not one of them.
    captions_numbered = bool(g.caption_numbers)
    rest_caps, held = [], {}
    for c in caps:
        if c.key in g.pairs:
            continue
        if not c.text.strip():
            # An empty caption block renders nothing, so pairing it buys no output
            # and could steal a figure from a caption that does carry text.
            held[c.key] = "caption block carries no text"
            continue
        if numbered_regime and c.key in g.caption_numbers:
            held[c.key] = (f"printed caption number {g.caption_numbers[c.key]} matched no "
                           f"figure number on a subpage that DOES print figure numbers — "
                           f"abstaining rather than overruling the printed numbering")
            continue
        if captions_numbered and c.key not in g.caption_numbers:
            held[c.key] = ("carries no printed caption number on a subpage whose captions "
                           "ARE numbered — more likely a mistyped label than a caption")
            continue
        rest_caps.append(c)
    rest_figs = [f for f in figs if f.key not in set(g.pairs.values())]

    geo_pairs, geo_why = _geometric_pairs(
        rest_caps, rest_figs, page_h, p, page_w,
        numbered=frozenset(g.caption_numbers))
    for cid, fid in geo_pairs.items():
        g.pairs[cid] = fid
        g.pair_source[cid] = "geometry"

    # --- arm 3: sole figure + sole printed caption (last, so arm 2 keeps
    # everything it can already place and no existing pair changes provenance) ---
    left_caps = [c for c in rest_caps if c.key not in g.pairs]
    claimed = set(g.pairs.values())
    left_figs = [f for f in rest_figs if f.key not in claimed]
    sole = _sole_figure_pair(left_caps, left_figs, figs, frozenset(g.caption_numbers))
    if sole is not None:
        cid, fid = sole
        g.pairs[cid] = fid
        g.pair_source[cid] = "sole_figure"
        geo_why.pop(cid, None)

    g.abstained = {**held, **geo_why}
    return g


# --------------------------------------------------------------------------
# Adapter for the editable document (Stage 07)
# --------------------------------------------------------------------------


def views_from_blocks(blocks: Sequence[Block]) -> list[BlockView]:
    """Editable ``Block``s -> ``BlockView``s, keyed by ``str(block.id)``.

    Block text is the block-level override when present (a translation), else the
    joined word text — the same text a reader sees, so a translated caption still
    parses if the translation kept the "Figura NN" header."""
    out = []
    for b in blocks:
        text = b.text if b.text is not None else " ".join(
            w.text for w in b.words if w.text.strip())
        out.append(BlockView(key=str(b.id), btype=b.type.value, bbox=b.bbox, text=text))
    return out


def apply_to_blocks(blocks: list[Block], g: Grouping, page_id: str) -> list[Block]:
    """Write a ``Grouping`` back onto the editable blocks (returns new Blocks).

    Promotion sets BOTH ``type`` and ``type_auto`` and raises ``type_promoted``:
    it is an AUTOMATIC decision, so the editor must not read it as a user
    override (``structure_edited`` stays False). Callers must therefore apply
    this BEFORE seeding ``type_auto`` from ``type``, or the two disagree.
    """
    by_key = {str(b.id): b for b in blocks}
    out: list[Block] = []
    for b in blocks:
        k = str(b.id)
        upd: dict = {}
        if k in g.promoted:
            upd["type"] = BlockType.CAPTION
            upd["type_auto"] = BlockType.CAPTION
            upd["type_promoted"] = True
        if k in g.caption_numbers:
            upd["caption_number"] = g.caption_numbers[k]
        if k in g.figure_numbers:
            upd["figure_number"] = g.figure_numbers[k]
        if k in g.pairs:
            fig = by_key.get(g.pairs[k])
            if fig is not None:
                upd["figure_ref"] = BlockRef(page_id=page_id, block_id=fig.id)
                upd["pair_source"] = PairSource(g.pair_source[k])
        out.append(b.model_copy(update=upd) if upd else b)
    return out
