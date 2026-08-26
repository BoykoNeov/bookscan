"""Tests for the caption<->figure grouping pass (pipeline/figure_grouping.py).

The invariant under test throughout is **zero wrong pairs**: every guard below
exists so an ambiguous layout ABSTAINS rather than printing a caption under the
wrong photo. Tests are therefore split into "pairs when it should" and — the
larger half — "declines when it must".

Geometry here is a faithful miniature of it_geo_06's real coordinates (captured
from testset/gt/it_geo_06.blocks.json): three cliff figures in a left column at
x203..1561, the F26 plate top-RIGHT at x1611, and the four captions stacked in a
narrow right-hand column at x~1600 whose order does NOT track figure position.
"""
from __future__ import annotations

import pytest

from pipeline import figure_grouping as FG
from pipeline.page_model import BBox, Block, BlockType, PairSource


def _v(key: str, btype: str, x: int, y: int, w: int, h: int, text: str = "") -> FG.BlockView:
    return FG.BlockView(key=key, btype=btype, bbox=BBox(x=x, y=y, w=w, h=h), text=text)


PAGE_H = 3000


# --------------------------------------------------------------------------
# Caption typing (promotion)
# --------------------------------------------------------------------------


def test_promotes_paragraph_that_starts_with_a_caption_header():
    views = [_v("0", "paragraph", 1604, 1480, 467, 631,
                "Figura 26 Fossili della Maiolica rinvenuti")]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.promoted == {"0": 26}
    assert g.effective_type(views[0]) == "caption"
    assert g.caption_numbers["0"] == 26


def test_does_not_promote_prose_that_merely_mentions_a_figure():
    views = [_v("0", "paragraph", 0, 0, 500, 200,
                "La successione prosegue verso l'alto (fig. 28) con calcari marnosi.")]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.promoted == {}
    assert g.effective_type(views[0]) == "paragraph"


def test_never_promotes_a_figure_block_even_if_it_carries_caption_text():
    views = [_v("0", "figure", 0, 0, 500, 500, "Figura 26 Fossili")]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.promoted == {}


def test_already_typed_caption_still_gets_its_number_parsed():
    views = [_v("0", "caption", 0, 600, 400, 100, "Sopra: Figura 29 Il versante")]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.promoted == {}                     # nothing to promote — already caption
    assert g.caption_numbers == {"0": 29}


# --------------------------------------------------------------------------
# Number arm — the C26->F26 trap
# --------------------------------------------------------------------------


def test_number_arm_pairs_across_geometry_defeating_the_c26_trap():
    """C26 sits directly below the LEFT column's F27 in y, but its printed number
    is 26 and the top-right plate is the figure printed '26'. Number must win."""
    views = [
        _v("f25", "figure", 203, 262, 1358, 790, "25"),
        _v("f27", "figure", 203, 1052, 1358, 850),
        _v("f26", "figure", 1611, 253, 498, 622, "26"),
        _v("c26", "paragraph", 1604, 1480, 467, 631, "Figura 26 Fossili della Maiolica"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.figure_numbers == {"f25": 25, "f26": 26}
    assert g.pairs["c26"] == "f26"                     # NOT f27, the nearest figure
    assert g.pair_source["c26"] == "number"


def test_ambiguous_figure_numbers_pair_nothing():
    """Two figures both reading '25' (a merged/duplicated detector box) is doubt,
    not a coin flip."""
    views = [
        _v("a", "figure", 0, 0, 400, 400, "25"),
        _v("b", "figure", 500, 0, 400, 400, "25"),
        _v("c", "caption", 0, 450, 400, 80, "Figura 25 La Maiolica"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert "c" not in g.pairs


# --------------------------------------------------------------------------
# Geometry arm — the ordinary book (no printed corner labels)
# --------------------------------------------------------------------------


def test_geometry_pairs_a_lone_figure_with_the_caption_beneath_it():
    views = [
        _v("f", "figure", 100, 100, 600, 500),
        _v("c", "caption", 110, 640, 580, 90, "A view of the valley"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c": "f"}
    assert g.pair_source["c"] == "geometry"
    assert g.abstained == {}


def test_geometry_pairs_a_caption_above_its_figure():
    views = [
        _v("c", "caption", 110, 100, 580, 90, "The valley, seen from the ridge"),
        _v("f", "figure", 100, 230, 600, 500),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c": "f"}


def test_geometry_declines_when_the_caption_is_in_another_column():
    """it_geo_06's real failure shape: the caption column (x~1600) shares no
    horizontal extent with the cliff column (x203..1561)."""
    views = [
        _v("f27", "figure", 203, 1052, 1358, 850),
        _v("c27", "caption", 1605, 1100, 442, 218, "Il Calcare di Soccher"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {}
    assert "column" in g.abstained["c27"]


def test_geometry_declines_when_the_figure_is_too_far_away():
    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("c", "caption", 110, 1400, 580, 90, "Far below, unrelated"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {}


def test_geometry_declines_when_two_figures_are_comparably_close():
    """Stacked figures with a caption wedged between them: which one owns it?"""
    views = [
        _v("above", "figure", 100, 100, 600, 400),
        _v("c", "caption", 110, 540, 580, 90, "Ambiguous"),
        _v("below", "figure", 100, 660, 600, 400),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {}
    assert "ambiguous" in g.abstained["c"]


def test_geometry_declines_when_two_captions_compete_for_one_figure():
    """Mutual-nearest guard: without it the second caption would also be handed
    the same figure, or the wrong one of the two would win silently."""
    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("near", "caption", 110, 520, 580, 60, "The true caption"),
        _v("far", "caption", 110, 600, 580, 60, "A second block below it"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"near": "f"}                    # closest wins
    assert "far" in g.abstained and "closer" in g.abstained["far"]


def test_geometry_declines_a_caption_swallowed_by_the_figure_box():
    """it_geo_06's right subpage, to scale: the L-shaped F29+F30 detection absorbed
    the C29 caption column (Phase B's caption ejection was never built), so the
    caption sits ~97% INSIDE the lower figure box. Containment must read as
    'the detector swallowed it', not as zero gap = maximal adjacency — otherwise
    the caption is printed under the wrong photo."""
    views = [
        _v("f29", "figure", 154, 279, 1554, 1030),
        _v("f30", "figure", 154, 1341, 1554, 842),      # box also covers the caption
        _v("c29", "caption", 156, 1487, 440, 720, "Sopra: Figura 29 Il tipico paesaggio"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c29": "f29"}                    # the figure ABOVE it, not f30
    assert g.pair_source["c29"] == "geometry"


def test_solo_figure_and_caption_tolerate_a_larger_gap():
    """it_geo_04's right subpage: the Fig.21 panorama's caption sits 577px below
    it, well past the normal gap limit — but it is the ONLY figure and the ONLY
    caption on the subpage, so there is no wrong figure available to pick."""
    views = [
        _v("f", "figure", 0, 268, 2071, 1025),
        _v("c", "caption", 203, 1870, 430, 940, "Sopra: Figura 21 Ampia veduta dei monti"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c": "f"}

    # ...and the relaxation is scoped to that solo case: add a second figure and
    # the same caption falls back to the tight limit and abstains.
    views2 = views + [_v("f2", "figure", 0, 20, 2071, 100)]   # far above, own candidate to nobody
    assert FG.group_figures(views2, page_h=PAGE_H).pairs == {}


def test_empty_caption_block_is_not_paired():
    """A caption block with no routed text renders nothing, so pairing it buys no
    output and could steal a figure from a caption that does carry text."""
    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("empty", "caption", 110, 520, 580, 30, "   "),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {}
    assert "no text" in g.abstained["empty"]


# --------------------------------------------------------------------------
# The numbering-regime guard (the interaction between the two arms)
# --------------------------------------------------------------------------


def test_numbered_caption_abstains_when_the_page_prints_figure_numbers():
    """THE guard that keeps it_geo_06 at zero wrong pairs. C25's printed number is
    25; F25's label did not OCR, but F26's did — so this page numbers its figures
    and geometry must not hand C25 the top-right F26 plate it happens to sit
    under."""
    views = [
        _v("f25", "figure", 203, 262, 1358, 790),            # label unreadable
        _v("f26", "figure", 1611, 253, 498, 622, "26"),      # label readable
        _v("c25", "paragraph", 1608, 900, 459, 181,
           "In questa pagina: Figura 25 La Maiolica"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.figure_numbers == {"f26": 26}
    assert g.pairs == {}                                 # NOT c25 -> f26
    assert "printed" in g.abstained["c25"]


def test_unnumbered_caption_abstains_on_a_page_whose_captions_are_numbered():
    """The caption-side numbering-regime guard, and a DELIBERATE REVERSAL of the
    behaviour this test asserted before 2026-08-18 (it used to require that an
    unnumbered caption still pair geometrically here).

    Reversed because of what the reversal costs versus what it buys, measured on
    real pages: en_coins' run-in "Description:" section labels are typed `caption`
    by the detector and sit 11-40px BELOW a coin plate — nearer to it than the
    real caption is — so on three subpages the old rule emitted "Description:" as
    the plate's caption while the true caption abstained. Cost of the guard: a
    genuinely unnumbered caption on a page that numbers its other captions is now
    missed. Under the zero-wrong-pairs bar, a miss beats a wrong pair."""
    views = [
        _v("f26", "figure", 1611, 253, 498, 622, "26"),
        _v("c26", "caption", 1611, 940, 498, 90, "Figura 26 Fossili"),   # numbered
        _v("f", "figure", 100, 1400, 600, 400),
        _v("c", "caption", 110, 1840, 580, 90, "An unnumbered caption"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.figure_numbers == {"f26": 26}          # the page IS in numbered regime
    assert g.pairs["c26"] == "f26" and g.pair_source["c26"] == "number"
    assert "c" not in g.pairs
    assert "no printed caption number" in g.abstained["c"]


def test_unnumbered_caption_still_pairs_when_no_caption_on_the_page_is_numbered():
    """The caption-side guard is inert on a book that numbers nothing — which is
    the ordinary book the geometry arm exists for."""
    views = [
        _v("f", "figure", 100, 1400, 600, 400),
        _v("c", "caption", 110, 1840, 580, 90, "An unnumbered caption"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c": "f"} and g.pair_source["c"] == "geometry"


# --------------------------------------------------------------------------
# Side-set attachment (caption BESIDE its figure) — en_coins_01/02/03
# --------------------------------------------------------------------------

# Faithful miniature of en_coins_01-left: two coin plates stacked in one column
# with zero horizontal overlap with their captions, each caption bottom-aligned
# inside its own plate's vertical band, ~12-17px to the right of it.
def _side_set_views() -> list[FG.BlockView]:
    return [
        _v("f96", "figure", 234, 277, 1114, 647),
        _v("c96", "caption", 1360, 795, 573, 125,
           "Fig. 96. 1786-NG Guatemala Portrait Eight Reales"),
        _v("f97", "figure", 157, 1742, 1150, 658),
        _v("c97", "caption", 1324, 2070, 603, 322,
           "Fig. 97. 1805-NG Guatemala Portrait Eight Reales"),
    ]


def test_side_set_captions_pair_with_the_figure_they_sit_beside():
    """Two figures share the column, so the wrong answer is available and must be
    rejected: this is a DISCRIMINATING case, not a lone-figure association."""
    g = FG.group_figures(_side_set_views(), page_h=PAGE_H, page_w=2000, lang="eng")
    assert g.pairs == {"c96": "f96", "c97": "f97"}
    assert set(g.pair_source.values()) == {"geometry"}


def test_side_set_needs_the_caption_to_be_inside_the_figures_vertical_band():
    """Slide c96 down past the bottom of its plate and the attachment evaporates —
    it is the y-band, not mere nearness, that carries the claim."""
    views = _side_set_views()
    views[1] = _v("c96", "caption", 1360, 1000, 573, 125,
                  "Fig. 96. 1786-NG Guatemala Portrait Eight Reales")
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2000, lang="eng")
    assert "c96" not in g.pairs


def test_side_set_declines_a_block_that_carries_no_printed_number():
    """de_01's icon sidebar in miniature: the Gehzeiten pictogram panel is typed
    `caption` by the detector and sits inside the page photo's vertical band, 28px
    to its left — geometrically indistinguishable from a side-set caption. Sitting
    BESIDE a figure is weaker evidence than sitting under it, so the side-set shape
    demands the block declare itself a caption in print. This panel does not."""
    views = [
        _v("photo", "figure", 617, 2057, 1402, 796),
        _v("panel", "caption", 351, 2603, 238, 227,
           "Gehzeiten/Time Bergst.- Gamsstll.Sch.: 1 Std, Einstieg - Bivacco: 1 Std"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2023, lang="deu")
    assert g.pairs == {}


def test_side_set_does_not_reach_a_detached_gutter_caption_column():
    """it_geo_05-right in miniature: the caption is a gutter-side column 1170px
    from its figure. Numbered, y-overlapping — and still far outside the side-set
    gap limit, which is what keeps this rule from claiming the whole page.

    The DECOY second figure is load-bearing and was added 2026-08-26: with only
    one figure on the page this layout is now claimed by the uniqueness arm (arm
    3), and correctly so — the real it_geo_05-right GT pairs C3 to F3. A second
    figure removes the uniqueness, so what is left to reject the pair is the
    side-set gap limit alone, which is what this test is for. The solo version
    lives in ``test_sole_figure_pairs_a_side_column_caption_arm_2_cannot_reach``.
    """
    views = [
        _v("f3", "figure", 100, 800, 700, 900),
        _v("fdecoy", "figure", 100, 2000, 700, 500),
        _v("c3", "caption", 1970, 900, 400, 700, "Figura 3 Il fossile"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)
    assert g.pairs == {}
    assert "column" in g.abstained["c3"]


# --------------------------------------------------------------------------
# Figure-number plausibility
# --------------------------------------------------------------------------


def test_a_figure_number_far_outside_the_page_numbering_is_discarded():
    """en_coins_03-right in miniature: `figure_label` reads 4 off a coin photograph
    on a subpage whose captions read 104 and 105. Left standing, that one false
    read would put the subpage into numbered-figure regime and suppress the
    geometry arm for both real captions."""
    views = [
        _v("f104", "figure", 62, 592, 1196, 648, "4"),
        _v("c104", "caption", 1269, 1163, 574, 86,
           "Fig. 104. 1890 Honduras Peso (KM# 52)"),
        _v("f105", "figure", 62, 1288, 1196, 627),
        _v("c105", "caption", 1275, 1851, 575, 83,
           "Fig. 105. 1892/0 Honduras Peso (KM# 52)"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2016, lang="eng")
    assert g.figure_numbers == {}                       # the 4 is dropped, not recorded
    assert g.pairs == {"c104": "f104", "c105": "f105"}  # geometry stays enabled


def test_a_figure_number_inside_the_page_numbering_is_kept():
    """The complement, and the reason the window is loose: 26 next to a caption
    reading 25 is a neighbouring figure on the same page, not a misread — so the
    numbered regime (and the C25 trap defence above) still stands."""
    assert FG._plausible_figure_numbers({"f": 26}, {"c": 25}, 3) == {"f": 26}
    assert FG._plausible_figure_numbers({"f": 4}, {"c": 104, "d": 105}, 3) == {}


def test_corner_label_ocr_is_skipped_when_no_caption_carries_a_number():
    """The number arm needs BOTH sides, so localizing + OCR'ing figure labels on a
    subpage with no numbered caption can never produce a pair. Skipping it is the
    difference between ~2.7s and ~12ms of assemble time per spread."""
    calls: list = []

    def _boom(*a, **k):                      # would be the expensive pixel path
        calls.append(a)
        return 42

    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("c", "caption", 110, 540, 580, 90, "An unnumbered caption"),
    ]
    import numpy as np
    fake_img = np.zeros((PAGE_H, 800, 3), np.uint8)
    orig = FG.FL.read_corner_label
    FG.FL.read_corner_label = _boom
    try:
        g = FG.group_figures(views, page_h=PAGE_H, page_bgr=fake_img, tess_bin="tesseract")
    finally:
        FG.FL.read_corner_label = orig
    assert calls == []                       # never entered the expensive path
    assert g.pairs == {"c": "f"}             # geometry still groups


def test_no_figure_numbers_anywhere_leaves_geometry_fully_enabled():
    """The ordinary book: nothing prints a corner label, so a numbered caption
    still pairs geometrically."""
    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("c", "caption", 110, 540, 580, 90, "Figure 3 The north face"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H, lang="eng")
    assert g.pairs == {"c": "f"}
    assert g.pair_source["c"] == "geometry"


def test_a_figure_paired_by_number_is_not_reused_by_the_geometry_arm():
    views = [
        _v("f", "figure", 100, 100, 600, 400, "7"),
        _v("c7", "caption", 110, 520, 580, 60, "Figura 7 Il ghiacciaio"),
        _v("other", "caption", 110, 600, 580, 60, "An unnumbered neighbour"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H)
    assert g.pairs == {"c7": "f"}
    assert g.pair_source["c7"] == "number"
    assert "other" not in g.pairs


# --------------------------------------------------------------------------
# Degradation without pixels / Tesseract
# --------------------------------------------------------------------------


def test_runs_without_an_image_or_tesseract():
    """Assemble must not become OCR-dependent: with no image the corner-label arm
    is skipped and geometry still groups."""
    views = [
        _v("f", "figure", 100, 100, 600, 400),
        _v("c", "caption", 110, 540, 580, 90, "Figura 9 Il rifugio"),
    ]
    g = FG.group_figures(views, page_h=PAGE_H, page_bgr=None, tess_bin=None)
    assert g.figure_numbers == {}
    assert g.pairs == {"c": "f"}


# --------------------------------------------------------------------------
# Adapter onto the editable document
# --------------------------------------------------------------------------


def _blk(bid: int, btype: str, x: int, y: int, w: int, h: int, text: str | None = None) -> Block:
    return Block(id=bid, type=btype, bbox=BBox(x=x, y=y, w=w, h=h),
                 reading_order=bid, text=text)


def test_apply_to_blocks_records_promotion_as_automatic_not_an_edit():
    """type_promoted is an AUTOMATIC decision: it must land in type_auto as well,
    or the editor reads the pipeline's own promotion as a user override."""
    blocks = [_blk(0, "figure", 100, 100, 600, 400, text="12"),
              _blk(1, "paragraph", 110, 540, 580, 90, text="Figura 12 La cresta")]
    g = FG.group_figures(FG.views_from_blocks(blocks), page_h=PAGE_H)
    out = FG.apply_to_blocks(blocks, g, page_id="page_001__left")

    cap = out[1]
    assert cap.type is BlockType.CAPTION
    assert cap.type_auto is BlockType.CAPTION          # not 'paragraph'
    assert cap.type_promoted is True
    assert cap.structure_edited is False               # NOT a user edit
    assert cap.caption_number == 12
    assert cap.figure_ref.page_id == "page_001__left"  # page-scoped, not a bare id
    assert cap.figure_ref.block_id == 0
    assert cap.pair_source is PairSource.NUMBER
    assert out[0].figure_number == 12


def test_apply_to_blocks_leaves_unpaired_blocks_untouched():
    blocks = [_blk(0, "paragraph", 0, 0, 500, 200, text="Testo ordinario del capitolo")]
    g = FG.group_figures(FG.views_from_blocks(blocks), page_h=PAGE_H)
    out = FG.apply_to_blocks(blocks, g, page_id="p")
    assert out[0].type is BlockType.PARAGRAPH
    assert out[0].figure_ref is None and out[0].pair_source is None
    assert out[0].type_promoted is False


def test_views_from_blocks_prefers_a_block_level_translation():
    """A translated caption that kept its header must still parse."""
    blocks = [_blk(0, "paragraph", 0, 0, 500, 200, text="Figure 4 The north wall")]
    views = FG.views_from_blocks(blocks)
    assert views[0].text == "Figure 4 The north wall"
    assert views[0].key == "0"


@pytest.mark.parametrize("bad", [{"geom_max_gap_frac": "0.2"}, {"nonsense": 5}])
def test_resolve_params_ignores_unknown_and_coerces_known(bad):
    p = FG.resolve_params(bad)
    assert set(p) == set(FG.DEFAULTS)
    assert all(isinstance(v, float) for v in p.values())


# --------------------------------------------------------------------------
# Arm 3 — sole figure + sole printed caption (no geometry at all)
# --------------------------------------------------------------------------
#
# Coordinates below are the REAL ones the probe read off the two pairing misses
# this arm was built for (2026-08-26, dewarped subpage pixels):
#
#   it_geo_05-right  2028x3000  F3 x610..  y..1350   C3 [87,2520,466,292]
#                    column overlap 0.00, vertical gap 0.390 of page height
#   it_geo_04-left   1981x3000  B5 ends y1300        B8 [1438,2452,454,365]
#                    column overlap 0.04, vertical gap 0.384 of page height
#
# Both are far outside arm 2's limits in BOTH shapes, which is the point: the
# distances are not usable on this layout, so uniqueness has to carry the pair.


def test_sole_figure_pairs_a_side_column_caption_arm_2_cannot_reach():
    """it_geo_05-right: 'Sopra: Figura 3' sits 1170px below and 57px left of the
    only figure on the page. Column overlap 0.00 — arm 2 abstains by design."""
    views = [_v("f", "figure", 610, 300, 1300, 1050),
             _v("c", "caption", 87, 2520, 466, 292,
                "Sopra: Figura 3 Il fossile di Ellipsactinia, un idrozoo")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)

    assert FG._x_overlap_frac(views[1].bbox, views[0].bbox) == 0.0
    assert g.pairs == {"c": "f"}
    assert g.pair_source["c"] == "sole_figure"
    assert "c" not in g.abstained


def test_sole_figure_pairs_the_a_lato_caption_too():
    """it_geo_04-left: 'A lato: Figura 20', column overlap 0.04, gap 0.38H."""
    views = [_v("f", "figure", 300, 260, 1400, 1040),
             _v("c", "caption", 1438, 2452, 454, 365,
                "A lato: Figura 20 La piattaforma cassiana del Nuvolau")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=1981)
    assert g.pairs == {"c": "f"} and g.pair_source["c"] == "sole_figure"
    assert g.n_by_sole_figure == 1 and g.n_by_geometry == 0


def test_sole_figure_declines_without_a_printed_caption_number():
    """de_01's icon sidebar, the case the metric CANNOT catch: that GT scopes the
    panel out, so a mispair there would score 'ungraded', not 'wrong'. Uniqueness
    alone would claim it — the print requirement is what refuses, so it is pinned
    here as an assertion rather than left to the eval.

    Real coordinates: the Gehzeiten panel [351,2603,238,227] has y-overlap 1.00
    and a 28px gap to the page photo, i.e. it clears every proximity test there
    is. It carries no 'Figura NN' header, and that is the whole defence."""
    views = [_v("f", "figure", 617, 2400, 1000, 600),
             _v("c", "caption", 351, 2603, 238, 227,
                "Gehzeiten/Time Bergst.- Gamsstll.Sch.: 1 Std, Laner")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2023, lang="deu")
    assert g.pairs == {}
    assert g.caption_numbers == {}
    assert "c" in g.abstained


def test_sole_figure_declines_when_the_page_prints_two_figures():
    """Uniqueness is the evidence, so two figures means there is none. Neither
    figure is reachable by arm 2 here (column overlap 0.00 to both)."""
    views = [_v("f1", "figure", 610, 300, 1300, 500),
             _v("f2", "figure", 610, 900, 1300, 450),
             _v("c", "caption", 87, 2520, 466, 292, "Sopra: Figura 3 Il fossile")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)
    assert g.pairs == {}
    assert "c" in g.abstained


def test_sole_figure_declines_when_two_captions_compete_for_the_one_figure():
    views = [_v("f", "figure", 610, 300, 1300, 1050),
             _v("c1", "caption", 87, 2520, 466, 292, "Sopra: Figura 3 Il fossile"),
             _v("c2", "caption", 87, 2100, 466, 292, "A lato: Figura 4 La cresta")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)
    assert g.pairs == {}


def test_sole_figure_does_not_overrule_a_recovered_figure_number():
    """The numbering-regime guard runs first and holds the caption, so arm 3 never
    sees it: on a page that DOES print figure numbers, a caption whose number
    found no partner abstains rather than being handed the only figure."""
    views = [_v("f", "figure", 610, 300, 1300, 1050, text="5"),
             _v("c", "caption", 87, 2520, 466, 292, "Sopra: Figura 3 Il fossile")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)
    assert g.figure_numbers == {"f": 5}
    assert g.pairs == {}
    assert "printed caption number 3" in g.abstained["c"]


def test_geometry_keeps_its_provenance_when_it_can_reach_the_figure():
    """Arm 3 runs LAST. A solo page arm 2 can already place must be unchanged —
    this is what keeps the existing fixture reports non-regressive."""
    views = [_v("f", "figure", 300, 300, 1300, 1000),
             _v("c", "caption", 320, 1360, 1260, 200, "Sopra: Figura 21 Il panorama")]
    g = FG.group_figures(views, page_h=PAGE_H, page_w=2028)
    assert g.pairs == {"c": "f"}
    assert g.pair_source["c"] == "geometry"
    assert g.n_by_sole_figure == 0


def test_sole_figure_pair_is_stamped_on_the_editable_block():
    blocks = [_blk(0, "figure", 610, 300, 1300, 1050),
              _blk(1, "caption", 87, 2520, 466, 292, text="Sopra: Figura 3 Il fossile")]
    g = FG.group_figures(FG.views_from_blocks(blocks), page_h=PAGE_H, page_w=2028)
    out = FG.apply_to_blocks(blocks, g, page_id="page_002__right")
    assert out[1].pair_source is PairSource.SOLE_FIGURE
    assert out[1].figure_ref.block_id == 0
