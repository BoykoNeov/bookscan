"""Unit tests for the pure grading logic in tools.layout_order_eval — the Gate-3
block-order metric. No OCR / GPU: DetBlocks are constructed by hand so every
answer is known. The it_geo_04 driver path is exercised separately by actually
running the tool (see docs/RESULTS.md); here we pin the maths.

Run: ``python -m pytest tools/tests/test_layout_order_eval.py`` or directly.
"""

from __future__ import annotations

from pipeline import stage04_layout as S4
from pipeline.page_model import BBox, Block, BlockType, Word
from tools import ocr_metrics as M
from tools.layout_order_eval import (
    DetBlock, _bbox_iou, _block_set_note, anchor_precision, anchor_score,
    apply_param_overrides, det_from_blocks, grouping_eval,
    kendall_tau, match_subpage, norm_tokens, order_with_figures,
)


def _db(idx, ro, btype, x, y, w, h, text="", native=None):
    return DetBlock(idx=idx, ro=ro, btype=btype, bbox=BBox(x=x, y=y, w=w, h=h),
                    text=text, native_ranks=native or [])


# --- normalization / anchor scoring --------------------------------------

def test_norm_tokens_dehyphenates_and_strips_punct():
    assert norm_tokens("clinostra- tificazioni") == ["clinostratificazioni"]
    assert norm_tokens("A lato: Figura 20!") == ["a", "lato", "figura", "20"]


def test_anchor_score_full_and_partial():
    anchor = "tettoniche che impediscono ricostruzioni paleoambientali"
    # de-hyphenated OCR text contains every anchor token
    block = "tettoniche che impediscono rico- struzioni paleoambientali e in piccole"
    assert anchor_score(anchor, block) == 1.0
    # only distinctive half present -> 0.5-ish, still argmax-able
    assert 0.0 < anchor_score(anchor, "tettoniche che varie parole") < 1.0
    assert anchor_score(anchor, "") == 0.0


# --- Kendall-tau ----------------------------------------------------------

def test_kendall_tau_known_values():
    assert kendall_tau([(0, 0), (1, 1), (2, 2)]) == 1.0
    assert kendall_tau([(0, 2), (1, 1), (2, 0)]) == -1.0
    assert kendall_tau([(0, 0)]) is None
    # 4 blocks, conc=4 disc=2 -> 1/3. This WAS the it_geo_04 right-native value
    # when the B6R map (a text-bearing figure) leaked into the native arm; tau now
    # excludes figures from both arms, so that grade is 1.0 over its 3 text blocks.
    # Kept here as a pure-function fixture for the partial-concordance case.
    tau = kendall_tau([(0, 286), (1, 43), (2, 128), (3, 337)])
    assert abs(tau - 1 / 3) < 1e-9


# --- matching -------------------------------------------------------------

def test_match_figures_by_ro_rank_text_by_anchor():
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "P1", "type": "paragraph",
         "anchor": "nuo verso sud versante est"},
        {"order": 2, "id": "C1", "type": "caption",
         "anchor": "a lato figura 20 piattaforma"},
    ]
    det = [
        _db(0, 0, "figure", 0, 0, 100, 100),
        _db(1, 1, "paragraph", 0, 200, 100, 50, text="nuo verso sud versante est bla"),
        _db(2, 2, "caption", 0, 300, 100, 50, text="a lato figura 20 piattaforma foto"),
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 0, "P1": 1, "C1": 2}
    assert misses == []


def test_short_anchor_does_not_steal_the_paragraph_that_mentions_it():
    """en_coins_03-right, reduced: the heading anchor is the single word the body
    paragraph also contains, so anchor RECALL ties at 1.0 on both blocks. Before
    the precision tie-break the heading claimed the paragraph's block and P2 was
    reported a segmentation miss with its text sitting in the document."""
    gt = [
        {"order": 0, "id": "H1", "type": "heading", "anchor": "Honduras"},
        {"order": 1, "id": "P2", "type": "paragraph",
         "anchor": "Despite their silver resources Honduras would not produce "
                   "their own crown-sized silver type"},
    ]
    det = [
        _db(0, 0, "heading", 0, 200, 240, 58, text="Honduras"),
        _db(1, 1, "paragraph", 0, 2487, 1873, 136,
            text="Despite their silver resources, Honduras would not produce "
                 "their own crown-sized silver type until the late 19th century"),
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"H1": 0, "P2": 1}
    assert misses == []


def test_precision_tiebreak_never_rejects_a_low_precision_true_match():
    """The tie-break must stay a TIE-break: a GT anchor is the first few words of
    its block, so a correct match against a long paragraph has low precision. It
    still wins, because its recall is higher than the rival's."""
    gt = [{"order": 0, "id": "P1", "type": "paragraph",
           "anchor": "il bacino di belluno si approfondisce"}]
    det = [
        # 6/6 anchor tokens but they are a sixth of the block -> precision ~0.17
        _db(0, 0, "paragraph", 0, 0, 100, 50,
            text="il bacino di belluno si approfondisce e vi si depongono "
                 "sedimenti pelagici mentre la piattaforma di trento comincia "
                 "lentamente a sprofondare sotto il livello del mare"),
        # a short block made entirely of anchor tokens -> precision 1.0, recall 0.5
        _db(1, 1, "caption", 0, 500, 100, 20, text="bacino belluno"),
    ]
    matched, _ = match_subpage(gt, det)
    assert matched == {"P1": 0}


def test_anchor_precision_is_the_other_direction_of_anchor_score():
    assert anchor_precision("Honduras", "Honduras") == 1.0
    assert anchor_precision("Honduras", "") == 0.0
    # one anchor token out of four distinct block tokens
    assert anchor_precision("Honduras", "silver Honduras crown type") == 0.25


def test_match_reports_missing_figure_when_fewer_detected():
    # two GT figures, only one detected -> the second GT figure is a miss
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "F2", "type": "figure", "anchor": "lagazuoi piccolo"},
    ]
    det = [_db(0, 0, "figure", 0, 0, 100, 100)]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 0}
    assert misses == ["F2"]


def test_bbox_iou_values():
    # identical boxes -> 1; disjoint -> 0; half-overlap -> intersection/union
    b = BBox(x=0, y=0, w=100, h=100)
    assert _bbox_iou([0, 0, 100, 100], b) == 1.0
    assert _bbox_iou([200, 200, 50, 50], b) == 0.0
    # GT [0,0,100,50] vs det 100x100: inter=100*50=5000, union=10000+5000-5000
    assert abs(_bbox_iou([0, 0, 100, 50], b) - 5000 / 10000) < 1e-9


def test_match_figures_by_bbox_overlap_beats_ro_rank():
    # it_geo_06 shape: the top-RIGHT plate (F_d) is emitted 2nd by Stage 04
    # (ro=3), out of column-major GT order (order=3, last). Bbox-overlap must pair
    # each GT figure with the det box it physically overlaps, NOT the i-th by rank
    # (which would give F_b the plate box and cascade the rest wrong).
    gt = [
        {"order": 0, "id": "Fa", "type": "figure", "anchor": None,
         "bbox": [0, 0, 100, 100]},          # top-left
        {"order": 1, "id": "Fb", "type": "figure", "anchor": None,
         "bbox": [0, 200, 100, 100]},        # mid-left
        {"order": 2, "id": "Fc", "type": "figure", "anchor": None,
         "bbox": [0, 400, 100, 100]},        # bottom-left
        {"order": 3, "id": "Fd", "type": "figure", "anchor": None,
         "bbox": [300, 0, 80, 90]},          # top-right plate
    ]
    det = [
        _db(0, 2, "figure", 2, 2, 98, 98),     # ro 2 -> top-left  (Fa)
        _db(1, 3, "figure", 300, 0, 80, 90),   # ro 3 -> plate     (Fd)  <- 2nd read
        _db(2, 4, "figure", 0, 200, 100, 100), # ro 4 -> mid-left  (Fb)
        _db(3, 5, "figure", 0, 400, 100, 100), # ro 5 -> bottom    (Fc)
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"Fa": 0, "Fd": 1, "Fb": 2, "Fc": 3}
    assert misses == []


def test_bbox_carrying_figure_with_no_overlap_is_honest_miss_no_rank_shift():
    # it_geo_07-left shape: the TOP diagram (G1) is undetected; only G2/G3 have
    # boxes. Rank would shift G1->G2's box and drop G3; bbox-overlap must flag G1
    # as the miss and match G2/G3 to their OWN boxes (no rank fallback for a
    # bbox-carrying figure that overlaps nothing).
    gt = [
        {"order": 0, "id": "G1", "type": "figure", "anchor": None,
         "bbox": [0, 0, 100, 80]},           # top -- NOT detected
        {"order": 1, "id": "G2", "type": "figure", "anchor": None,
         "bbox": [0, 200, 100, 100]},
        {"order": 2, "id": "G3", "type": "figure", "anchor": None,
         "bbox": [0, 400, 100, 100]},
    ]
    det = [
        _db(0, 5, "figure", 0, 200, 100, 100),  # overlaps G2
        _db(1, 6, "figure", 0, 400, 100, 100),  # overlaps G3
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"G2": 0, "G3": 1}
    assert misses == ["G1"]


def test_fragment_box_does_not_steal_whole_figure_match():
    # A partial-figure fragment (top slice, IoU ~0.3) and the whole-figure box
    # both overlap one GT figure. Greedy claims the whole box; the fragment,
    # overlapping no OTHER GT figure, stays unmatched rather than stealing.
    gt = [{"order": 0, "id": "F1", "type": "figure", "anchor": None,
           "bbox": [0, 0, 100, 300]}]
    det = [
        _db(0, 0, "figure", 0, 0, 100, 100),   # fragment: top third (IoU 1/3)
        _db(1, 1, "figure", 0, 0, 100, 300),   # whole figure (IoU 1.0)
    ]
    matched, misses = match_subpage(gt, det)
    assert matched == {"F1": 1}
    assert misses == []


# --- grouping -------------------------------------------------------------

def test_grouping_single_figure_is_association_not_discriminated():
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    matched = {"C1": 1, "F1": 0}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 9, "caption", 500, 800, 100, 100)]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is True            # only one figure -> trivially nearest
    assert g.caption_typed_ok is True
    assert g.n_figures == 1
    assert "NOT discriminated" in g.reason


def test_grouping_flags_mistyped_caption():
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "right"}]
    matched = {"C1": 1, "F1": 0}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 3, "paragraph", 100, 200, 100, 100)]  # caption block mistyped
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.caption_typed_ok is False
    assert "mistyped" in g.reason


def test_grouping_discriminates_with_two_figures():
    # caption sits under F2; nearest-figure must pick F2, not F1
    gt_pairs = [{"caption": "C1", "figure": "F2", "subpage": "left"}]
    matched = {"C1": 2, "F1": 0, "F2": 1}
    det = [_db(0, 0, "figure", 0, 0, 100, 100),
           _db(1, 1, "figure", 0, 1000, 100, 100),
           _db(2, 2, "caption", 0, 1120, 100, 40)]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is True
    assert g.n_figures == 2
    assert "NOT discriminated" not in g.reason

    # now the caption is nearer F1 -> pairing is WRONG
    matched_bad = {"C1": 2, "F1": 0, "F2": 1}
    det_bad = [_db(0, 0, "figure", 0, 0, 100, 100),
               _db(1, 1, "figure", 0, 1000, 100, 100),
               _db(2, 2, "caption", 0, 90, 100, 40)]
    (g2,) = grouping_eval(gt_pairs, matched_bad, det_bad)
    assert g2.nearest_ok is False


def test_grouping_uses_edge_gap_not_center_for_unequal_height_figures():
    """A caption sitting directly under a TALL figure's bottom edge must pair with
    that figure, not with a SHORT nearby figure whose center is closer. Center
    distance mis-attaches it (tall fig center is far up); edge gap fixes it. This
    is the ">=2 figures in one column" discrimination the Gate-3 grouping headline
    was blocked on, exercised on the pure metric (synthetic, detector-free)."""
    # Fig A tall (h=1000, center y=500); its caption directly under A's edge
    # (y=1010). Fig B short (h=100, center y=1150). Caption belongs to A.
    det = [_db(0, 0, "figure", 0, 0, 100, 1000),      # F1 (tall)
           _db(1, 2, "caption", 0, 1010, 100, 40),    # C1 under A's bottom edge
           _db(2, 1, "figure", 0, 1100, 100, 100)]    # F2 (short neighbor)
    matched = {"C1": 1, "F1": 0, "F2": 2}
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    (g,) = grouping_eval(gt_pairs, matched, det)
    # center distance would pick F2 (120 < 530) -> WRONG; edge gap picks F1
    # (10px < 50px) -> correct partner. n_figures==2 so it is DISCRIMINATED.
    assert g.nearest_ok is True
    assert g.n_figures == 2
    assert "NOT discriminated" not in g.reason


def test_edge_gap_does_not_encode_caption_above_below_known_limit():
    """BOUNDARY (documents a known limit, not a pass we want): edge-gap fixes the
    unequal-HEIGHT failure but does NOT encode the caption-above/below convention.
    Stacked figures with ASYMMETRIC spacing — a caption nearer the NEXT figure's
    top edge than its OWN figure's bottom edge — still mispair. No pure
    nearest-distance rule resolves above/below; a convention-aware rule is deferred
    until a real >=2-figure fixture exists to tune against (same discipline as the
    NMS near-miss). This test pins the current behavior so the boundary is explicit."""
    # cap1 belongs to Fig1 (above). But Fig2's top (y=135) is 5px below cap1's
    # bottom (y2=130), while Fig1's bottom (y2=100) is 10px above cap1 (y=110) ->
    # edge gap to Fig2 (5) < to Fig1 (10) -> edge-gap picks Fig2, the WRONG figure.
    det = [_db(0, 0, "figure", 0, 0, 100, 100),      # F1 (cap1's true partner)
           _db(1, 1, "caption", 0, 110, 100, 20),    # C1 (y2=130)
           _db(2, 2, "figure", 0, 135, 100, 100)]    # F2 (nearer below)
    matched = {"C1": 1, "F1": 0, "F2": 2}
    gt_pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"}]
    (g,) = grouping_eval(gt_pairs, matched, det)
    assert g.nearest_ok is False   # KNOWN LIMIT: edge-gap mispairs here (documented)


def test_two_figure_subpage_discriminates_both_captions_end_to_end():
    """Synthetic full subpage: TWO figures sharing one column, each with its own
    caption directly beneath it, plus a body paragraph. Drives the DRIVER-level
    path (match_subpage figures-by-ro-rank + text-by-anchor, then grouping_eval)
    so both captions must associate to the RIGHT figure with a wrong option
    present. This is the ">=2 figures / column" case that discriminates pairing —
    both pairs pass AND both count as discriminated (n_figures==2)."""
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},
        {"order": 1, "id": "C1", "type": "caption", "anchor": "figura uno alpha"},
        {"order": 2, "id": "F2", "type": "figure", "anchor": None},
        {"order": 3, "id": "C2", "type": "caption", "anchor": "figura due beta"},
        {"order": 4, "id": "P1", "type": "paragraph", "anchor": "corpo del testo gamma"},
    ]
    det = [
        _db(0, 0, "figure",    0,    0, 400, 600),                       # -> F1
        _db(1, 1, "caption",   0,  610, 400,  60, text="figura uno alpha foto"),  # -> C1 (under F1)
        _db(2, 2, "figure",    0,  700, 400, 600),                       # -> F2
        _db(3, 3, "caption",   0, 1310, 400,  60, text="figura due beta foto"),   # -> C2 (under F2)
        _db(4, 4, "paragraph", 0, 1400, 400, 200, text="corpo del testo gamma e altro"),
    ]
    matched, misses = match_subpage(gt, det)
    assert misses == []
    assert matched == {"F1": 0, "C1": 1, "F2": 2, "C2": 3, "P1": 4}

    pairs = [{"caption": "C1", "figure": "F1", "subpage": "left"},
             {"caption": "C2", "figure": "F2", "subpage": "left"}]
    groups = grouping_eval(pairs, matched, det)
    # both captions pair to the correct figure, both discriminated (2 figures)
    assert all(g.nearest_ok for g in groups)
    assert all(g.n_figures == 2 for g in groups)
    assert all(g.caption_typed_ok for g in groups)
    discriminated = sum(1 for g in groups if g.nearest_ok and g.n_figures >= 2)
    assert discriminated == 2


# --- figure-INCLUSIVE order (order_with_figures) ---------------------------

def _it06_right_gt():
    """it_geo_06-right's GT block set (the §10 fixture): F29, C29, F30, C30 over
    two paragraphs. Bboxes are the real GT figure boxes, scaled down for the test
    only in that the detected boxes below are made to coincide with them."""
    return [
        {"order": 0, "id": "F29", "type": "figure",    "bbox": [154, 279, 1554, 1000]},
        {"order": 1, "id": "C29", "type": "caption",   "anchor": "figura ventinove"},
        {"order": 2, "id": "F30", "type": "figure",    "bbox": [640, 1341, 1068, 842]},
        {"order": 3, "id": "C30", "type": "caption",   "anchor": "a lato figura trenta"},
        {"order": 4, "id": "P1",  "type": "paragraph", "anchor": "corpo del testo"},
    ]


def _it06_right_det(fig30_bbox, ro):
    """Detected blocks for the fixture above. ``fig30_bbox`` is F30's box and
    ``ro`` the Stage-04 reading_order per block id, so a test can express both the
    merged-box (pre-Phase-B) and tight-box (post) worlds."""
    return [
        _db(0, ro["F29"], "figure",    154,  279, 1554, 1000),
        _db(1, ro["C29"], "caption",   156, 1487,  440,  720,
            text="figura ventinove veduta"),
        _db(2, ro["F30"], "figure",    *fig30_bbox),
        _db(3, ro["C30"], "caption",   154, 2239,  439,  581,
            text="a lato figura trenta"),
        _db(4, ro["P1"],  "paragraph", 154, 2900,  439,  300,
            text="corpo del testo e altro"),
    ]


def test_order_with_figures_grades_what_text_only_tau_cannot():
    """The §10 defect in miniature. Stage 04 emits F29, **F30, C29**, C30 — the
    merged full-width F30 box got peeled as a band ABOVE its caption. Text-only tau
    sees C29 < C30 < P1 and reports a perfect +1.00; the figure-inclusive arm sees
    the transposition."""
    gt = _it06_right_gt()
    ro = {"F29": 0, "F30": 1, "C29": 2, "C30": 3, "P1": 4}
    det = _it06_right_det((154, 1341, 1554, 842), ro)
    matched, misses = match_subpage(gt, det)
    assert misses == []

    by_id = {g["id"]: g for g in gt}
    text_only = kendall_tau([(by_id[gid]["order"], det[di].ro)
                             for gid, di in matched.items()
                             if by_id[gid]["type"] != "figure"])
    assert text_only == 1.0          # blind to the figure being in the wrong place

    oa = order_with_figures(gt, matched, det)
    assert oa.n_fig_graded == 2 and oa.n_blocks == 5
    assert oa.seq_det == ["F29", "F30", "C29", "C30", "P1"]
    assert oa.seq_gt == ["F29", "C29", "F30", "C30", "P1"]
    assert oa.tau is not None and oa.tau < 1.0     # exactly one transposition


def test_order_with_figures_scores_the_corrected_order_perfect():
    """Same fixture, tight F30 box -> Stage 04 places it after C29 (the Phase B
    output, == GT). The metric must go to +1.00, else it can't credit the fix."""
    gt = _it06_right_gt()
    ro = {"F29": 0, "C29": 1, "F30": 2, "C30": 3, "P1": 4}
    det = _it06_right_det((640, 1341, 1068, 842), ro)
    matched, _ = match_subpage(gt, det)
    oa = order_with_figures(gt, matched, det)
    assert oa.tau == 1.0
    assert oa.seq_det == oa.seq_gt == ["F29", "C29", "F30", "C30", "P1"]


def test_order_with_figures_refuses_rank_matched_figures_as_circular():
    """A GT authored before figure bboxes (it_geo_04 / de_01) matches figures by
    reading-order RANK, which makes those pairs concordant BY CONSTRUCTION. Grading
    order off them would be circular, so they are dropped — and with no gradeable
    figure left the arm reports n/a, never a passing +1.00 that is really text."""
    gt = [
        {"order": 0, "id": "F1", "type": "figure", "anchor": None},   # no bbox
        {"order": 1, "id": "P1", "type": "paragraph", "anchor": "alpha beta gamma"},
        {"order": 2, "id": "P2", "type": "paragraph", "anchor": "delta epsilon zeta"},
    ]
    det = [
        _db(0, 0, "figure",    0,   0, 400, 300),
        _db(1, 1, "paragraph", 0, 320, 400, 100, text="alpha beta gamma testo"),
        _db(2, 2, "paragraph", 0, 440, 400, 100, text="delta epsilon zeta testo"),
    ]
    matched, _ = match_subpage(gt, det)
    assert matched == {"F1": 0, "P1": 1, "P2": 2}     # figure DID match, by rank
    oa = order_with_figures(gt, matched, det)
    assert oa.tau is None and not oa.gradeable
    assert oa.n_fig_graded == 0
    assert "no gradeable figure" in oa.note
    assert oa.seq_gt == ["P1", "P2"]                  # figure excluded from the set


def test_order_with_figures_goes_quiet_not_red_when_a_figure_is_lost():
    """The graded set is the MATCHED blocks, so a figure the detector loses leaves
    the set entirely. Pinned deliberately: this metric answers 'is the order right',
    NOT 'is everything there' — a segmentation regression makes it QUIETER. Read it
    beside seg recall."""
    gt = _it06_right_gt()
    ro = {"F29": 0, "C29": 1, "F30": 2, "C30": 3, "P1": 4}
    det = _it06_right_det((640, 1341, 1068, 842), ro)
    del det[2]                                   # F30 not detected at all
    matched, misses = match_subpage(gt, det)
    assert misses == ["F30"]
    oa = order_with_figures(gt, matched, det)
    assert oa.tau == 1.0                         # still +1.00 ...
    assert oa.n_fig_graded == 1                  # ... but on ONE figure, and it says so


def test_order_with_figures_needs_two_blocks():
    """it_geo_05-left: one figure + a caption that is a known segmentation MISS.
    One matched block cannot be ordered -> n/a with a reason, not 0.00."""
    gt = [
        {"order": 0, "id": "F2", "type": "figure", "bbox": [231, 331, 1806, 2658]},
        {"order": 1, "id": "C2", "type": "caption", "anchor": "mai rilevata"},
    ]
    det = [_db(0, 0, "figure", 231, 331, 1806, 2658)]
    matched, misses = match_subpage(gt, det)
    assert misses == ["C2"]
    oa = order_with_figures(gt, matched, det)
    assert oa.tau is None and "<2 matched blocks" in oa.note


# --- --set knob overrides --------------------------------------------------

def test_param_override_coerces_bool_not_truthy_string():
    """``--set fig_vsplit=False`` stored as the STRING "False" is truthy, so the
    knob stays ON and an A/B silently compares a run against itself. Pin the
    coercion, since a null result would otherwise read as 'the metric is blind'."""
    p = apply_param_overrides(dict(S4.DEFAULTS), ["fig_vsplit=False"])
    assert p["fig_vsplit"] is False
    assert apply_param_overrides(dict(S4.DEFAULTS), ["fig_split=0"])["fig_split"] is False
    assert apply_param_overrides(dict(S4.DEFAULTS), ["fig_vsplit=yes"])["fig_vsplit"] is True


def test_param_override_coerces_numbers_and_rejects_unknown_keys():
    p = apply_param_overrides(dict(S4.DEFAULTS), ["imgsz=1536",
                                                  "fig_eject_text_cover=0.75"])
    assert p["imgsz"] == 1536 and isinstance(p["imgsz"], int)
    assert p["fig_eject_text_cover"] == 0.75
    for bad in ["nope=1", "fig_vsplit", "fig_vsplit=maybe"]:
        try:
            apply_param_overrides(dict(S4.DEFAULTS), [bad])
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have raised")


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))


# --- the graded block set: Stage 05's blocks, not Stage 04's --------------
#
# These pin the view-building half of the 2026-08-26 change (the OCR half is
# exercised by actually running the tool; see docs/RESULTS.md). What matters
# here is WHICH words each number is computed from: the block's own final words
# for text, and the page pass's TSV order for the native-order arm.


def _tw(text, left, top, w=40, h=20, block_num=1, par_num=1, line_num=1,
        word_num=1):
    return M.TWord(text=text, conf=90.0, left=left, top=top, width=w, height=h,
                   block_num=block_num, par_num=par_num, line_num=line_num,
                   word_num=word_num)


def _blk(bid, btype, x, y, w, h, words=()):
    return Block(id=bid, type=btype, bbox=BBox(x=x, y=y, w=w, h=h),
                 reading_order=bid,
                 words=[Word(text=t, bbox=BBox(x=x + 1, y=y + 1, w=10, h=10),
                             conf=90.0, engine="tesseract", line_id=0,
                             block_id=bid, decision=None) for t in words])


def test_det_text_comes_from_the_blocks_final_words_not_the_page_pass():
    """A re-read block ships the words block_reocr put in it. Grading it on a
    page-pass routing instead is exactly the blind spot this arm closes: the
    starved read is what the OLD arm saw, the rescued read is what ships."""
    blocks = [_blk(0, BlockType.PARAGRAPH, 0, 0, 500, 200,
                   words=["rescued", "twenty", "one", "words"])]
    # The page pass starved this region: it recognized two garbled words there.
    twords = [_tw("rcscucd", 10, 10), _tw("wOrds", 60, 10)]
    det = det_from_blocks(blocks, twords, scale=1.0)
    assert det[0].text == "rescued twenty one words"
    assert "rcscucd" not in det[0].text


def test_native_ranks_stay_the_page_pass_tsv_order():
    """The Tesseract-native order arm asks what the PAGE PASS implied for a
    region. A rescued block's replacement words must not answer that question --
    otherwise the 'did Stage 04 improve on Tesseract' comparison silently starts
    grading Stage 05 against itself."""
    blocks = [_blk(0, BlockType.PARAGRAPH, 0, 0, 100, 100, words=["a", "b"]),
              _blk(1, BlockType.PARAGRAPH, 0, 200, 100, 100, words=["c"])]
    # TSV order deliberately disagrees with geometry: word 0 lands in the LOWER
    # block, words 1-2 in the upper one.
    twords = [_tw("x", 10, 210), _tw("y", 10, 10), _tw("z", 40, 10)]
    det = det_from_blocks(blocks, twords, scale=1.0)
    assert det[0].native_ranks == [1, 2]
    assert det[1].native_ranks == [0]
    assert det[0].native_key == 2 and det[1].native_key == 0


def test_det_from_blocks_routes_by_smallest_containing_box():
    """Same rule as the old arm -- a word inside a figure AND inside the caption
    nested in it belongs to the caption."""
    blocks = [_blk(0, BlockType.FIGURE, 0, 0, 400, 400),
              _blk(1, BlockType.CAPTION, 100, 300, 200, 60, words=["Figura", "7"])]
    det = det_from_blocks(blocks, [_tw("Figura", 110, 310)], scale=1.0)
    assert det[0].native_ranks == [] and det[1].native_ranks == [0]


def test_det_from_blocks_honours_the_upscale_factor():
    """Word boxes come back in OCR-image coords; blocks live at 1x. Getting this
    division wrong routes every word to the wrong block on an upscaled page."""
    blocks = [_blk(0, BlockType.PARAGRAPH, 0, 0, 100, 100)]
    # At scale 2 the word's box (300,300) maps back to (150,150): OUTSIDE.
    assert det_from_blocks(blocks, [_tw("w", 300, 300)], scale=2.0)[0].native_ranks == []
    # ...while (100,100) maps back to (50,50): inside.
    assert det_from_blocks(blocks, [_tw("w", 100, 100)], scale=2.0)[0].native_ranks == [0]


def test_orphan_rescued_block_is_matchable_but_typed_other():
    """The recall/type trade, pinned. An orphan-rescued block carries the right
    words -- so a GT block the old arm scored a MISS now matches -- but Stage 05
    types it `other`, so the same recovery costs a point of type accuracy. A
    reader must not see that drop as a regression."""
    gt = [{"id": "FN1", "type": "footnote", "order": 1,
           "anchor": "Reproduced by permission of the Trustees"}]
    orphan = _blk(0, BlockType.OTHER, 0, 900, 600, 60,
                  words="Reproduced by permission of the Trustees".split())
    det = det_from_blocks([orphan], [], scale=1.0)
    matched, misses = match_subpage(gt, det)
    assert matched == {"FN1": 0} and misses == []
    assert det[0].btype == "other" != gt[0]["type"]


def test_block_set_note_names_the_arm_in_both_directions():
    """RESULTS.md is append-only and its tables get read side by side. A row
    measured on the shipped block set and one measured on Stage 04 alone are
    different quantities, so each must say so in the row itself."""
    shipped, old = _block_set_note(True), _block_set_note(False)
    assert "what SHIPS" in shipped and "--no-stage05" in shipped
    assert "Stage 04 alone" in old and "does NOT grade the deliverable" in old
