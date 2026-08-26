"""Gate 3 block-order eval — grade the SHIPPED block set (Stage 04 + Stage 05)
against a BLOCK-ORDER ground truth (``gt/<id>.blocks.json``).

This is the sequence-order + grouping metric the Gate-3 headline was blocked on.
Unlike ``tools/layout_ab.py`` (which measures WER of reordered words, and so can
only show a reading-order WIN on a page where Tesseract's own order already
fails), this tool grades Stage 04's block structure DIRECTLY against a hand-typed
per-subpage block map — segmentation, type, caption<->figure grouping, and
linear order — on ``it_geo_04``, a genuine multi-column + figure-sidebar spread.

Grading follows the owner's priority (encoded in the GT ``primary_invariants``):
segmentation and type and caption<->figure grouping OUTRANK exact linear order.
So the report leads with those and treats Kendall-tau as secondary.

WHICH BLOCK SET (the 2026-08-26 change). This tool used to stop after Stage 04.
Three mechanisms that CREATE or REWRITE blocks run later, in Stage 05 —
orphan-word rescue (``attach_words``), caption ejection (``caption_eject``) and
the starved-block re-read (``block_reocr``) — so a GT block graded a segmentation
MISS here could already be present in the shipped ``document.json`` (measured:
two of the corpus's six misses were exactly that). It now runs those three passes
(``stage05_blocks``), so every number grades what ships. ``--no-stage05``
restores the old arm for reproducing pre-2026-08-26 rows; it does NOT grade the
deliverable. Two reading notes for the shipped arm: ``reading_order`` is Stage
05's (an orphan re-ranks the whole set through the same XY-Cut), so the tau
column is the SHIPPED order and is not comparable to an older row; and an
orphan-rescued block is typed ``other`` by construction, so recovering one raises
segmentation recall and LOWERS type accuracy.

Method (per subpage — Stage 02 splits the spread, Stage 04 orders each half):
  1. split -> dewarp (auto/UVDoc) -> Stage 04 layout, exactly the Gate-2/3 path
     (reuses tools.dewarp_ab + tools.layout_ab helpers), so numbers stay
     comparable. OCR each half ONCE, then run Stage 05's three block passes and
     grade the blocks they leave behind (``--no-stage05``: route each word to the
     smallest block whose box contains its center, same routing as layout_ab).
  2. MATCH each GT block to a detected block:
       * FIGURE GT blocks: by BBOX-OVERLAP when the GT figure carries a bbox
         (each GT figure claims the detected figure it overlaps most, global
         greedy by IoU >= ``FIG_IOU_MIN``; a bbox-carrying figure that overlaps
         nothing is an honest miss, no rank fallback). This is POSITION-matched,
         so a figure Stage 04 emits out of GT reading order still pairs with its
         own box — rank matching instead relabels it by order, which scored the
         it_geo_06 top-right plate's correct corner-label number a mispair.
         Figures WITHOUT a bbox (it_geo_04, authored before figure bboxes) fall
         back to reading_order rank (i-th GT figure -> i-th detected figure,
         top-to-bottom); their in-figure labels don't OCR so anchor text can't
         match them.
       * TEXT GT blocks (paragraph / caption / heading): by anchor-token
         overlap against the block's routed OCR text (greedy, highest score
         first, one detected block per GT block, threshold ``MATCH_TAU``).
         Equal scores are broken by the OTHER direction of the overlap
         (``anchor_precision``), so a short anchor cannot claim a long block it
         barely explains ahead of the block that is actually made of it.
  3. SCORE per subpage:
       * segmentation recall = matched GT blocks / GT blocks (lists the misses);
       * type accuracy over matched blocks (detected type == GT type);
       * caption<->figure grouping: each GT (caption, figure) pair passes if the
         detected figure nearest the caption's block (by EDGE GAP — box-to-box
         min distance, not center distance) IS the block matched to the partner
         figure. n_figures is reported so a single-figure subpage is
         flagged as association-possible-but-NOT-discriminated (a one-figure
         region can't get the pairing wrong). Also reports whether the caption
         was correctly TYPED (Gate-4 reflow floats caption-with-figure keyed on
         caption type, so a mistyped caption breaks grouping in practice).
       * order: Kendall-tau over matched blocks, GT reading_order vs Stage 04
         reading_order (SECONDARY). Also a Tesseract-NATIVE block order (blocks
         ranked by the median TSV index of their routed words) graded the same
         way, over the word-bearing matched blocks, so "did Stage 04 IMPROVE on
         Tesseract's implicit order" is measured, not asserted (figures excluded
         — Tesseract emits no order for imageless regions).
       * FIGURE-INCLUSIVE order (``tau_all``, Stage-04 arm only): the same
         Kendall-tau over text blocks PLUS the figures whose match is
         position-honest (matched by GT-bbox overlap). Rank-matched figures are
         excluded because rank matching pairs the i-th GT figure with the i-th
         detected figure BY ORDER — grading order off that is circular. There is
         deliberately no Tesseract-native counterpart (native has no order for
         imageless regions). See ``order_with_figures``.

N=1 spread. This proves reading-order CORRECTNESS on one genuine multi-column
page; it does NOT by itself prove grouping DISCRIMINATION (see the single-figure
caveat) — that needs a fixture with >=2 figures sharing one column.

SCOPE of the order numbers: they grade Stage 04's per-subpage ``reading_order``,
which is where the figure-order defect of FIGURE_SEPARATION_SCOPE.md §10 lived and
where its fix landed. They do NOT prove Stage 07 assemble carries that order
through into ``document.json`` — that end of the chain is still a by-hand check.

Usage:
    python -m tools.layout_order_eval --image it_geo_04 [--report docs/RESULTS.md]
    # the pre-2026-08-26 arm (Stage 04's blocks alone, NOT the deliverable):
    python -m tools.layout_order_eval --image it_geo_04 --no-stage05
    python -m tools.layout_order_eval --image it_geo_04 --json-out out.json
    # A/B a layout knob (types are coerced from stage04_layout.DEFAULTS):
    python -m tools.layout_order_eval --image it_geo_06 --set fig_vsplit=false
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from tools import normalize as NORM
from tools import ocr_metrics as M
from tools.gate1_harness import (
    REPO_ROOT, find_tesseract, load_config, resolve_tessdata_dir,
    tesseract_version,
)
from tools.dewarp_ab import split_halves, dewarp_halves, lang_code
# OCR + word routing come from production (Stage 05), not from a harness copy
# — see the note in tools/layout_ab.py. ``layout_ab`` re-exports the same
# objects under the same names; imported from the source module here.
from pipeline.stage05_ocr import (   # noqa: PLC2701  (deliberate: same code)
    _center_in, _word_box, ocr_subpage as ocr_words,
)
from pipeline import stage04_layout as S4
from pipeline import figure_grouping as FG
from pipeline import block_reocr as BR
from pipeline import caption_eject as CE
from pipeline import stage05_ocr as S5
from pipeline.page_model import BBox, Block

# Fraction of a GT anchor's tokens that must be present in a detected block's
# routed OCR text to accept the match. Anchors are 6-12 distinctive first-words;
# even garbled OCR keeps well over half, and the argmax block is unambiguous.
MATCH_TAU = 0.5

# Minimum IoU for a GT figure (that carries a bbox) to match a detected figure
# box. Lenient: correct figure matches on it_geo_06 land at IoU 0.91-1.00 while
# every wrong (opposite-column / non-overlapping) pairing is ~0, so 0.2 clears
# the wrong pairs with a wide margin yet tolerates GT-bbox truncation (the
# "sofa-shot" clipped cliff bottoms; the floor's original justifying case, F30 at
# IoU 0.63, rose to 0.91 when Phase B stopped its box swallowing the C29 caption
# column — 2026-08-09). A partial-figure
# fragment (top third of a tall figure, IoU ~0.33) can exceed this floor but is
# harmless: greedy claims the whole-figure match first, and the fragment overlaps
# no OTHER GT figure, so it stays unmatched rather than stealing a match.
FIG_IOU_MIN = 0.2


# --------------------------------------------------------------------------
# Text normalization for anchor matching (aggressive: OCR garbles this page)
# --------------------------------------------------------------------------

_DEHYPH = re.compile(r"-\s*")               # "clinostra- tificazioni" -> "clinostratificazioni"
_NONWORD = re.compile(r"[^0-9a-zÀ-ɏ]+")  # keep Latin + accented letters


def norm_tokens(s: str) -> list[str]:
    """Lowercase, de-hyphenate line-wraps, strip punctuation -> content tokens.
    Applied identically to GT anchors and routed block text so the comparison is
    fair regardless of OCR punctuation/hyphenation noise."""
    s = _DEHYPH.sub("", s.lower())
    s = _NONWORD.sub(" ", s)
    return [t for t in s.split(" ") if t]


def anchor_score(anchor: str, block_text: str) -> float:
    """Fraction of the anchor's (distinct) tokens present in the block's tokens.
    Set-based, so word repetition doesn't inflate it; the distinctive content
    words (place-names, ``clinostratificazioni``) carry the match."""
    a = set(norm_tokens(anchor))
    if not a:
        return 0.0
    b = set(norm_tokens(block_text))
    return len(a & b) / len(a)


def anchor_precision(anchor: str, block_text: str) -> float:
    """Fraction of the BLOCK's (distinct) tokens the anchor accounts for — the
    other direction of ``anchor_score``, used ONLY to break exact ties in it.

    ``anchor_score`` is recall of the anchor, so its denominator is the anchor's
    own token count: a ONE-TOKEN anchor scores a perfect 1.0 against every block
    on the page that happens to contain that token. On ``en_coins_03``-right the
    heading anchor ``"Honduras"`` scores 1.0 against six detected blocks — its own
    heading, the running header, both captions, and both body paragraphs — and the
    greedy loop below then handed it whichever the sort happened to reach first.
    Precision separates them without touching the acceptance threshold: the
    heading's own block is all anchor (1.0), the paragraph that merely mentions
    Honduras is almost none of it (~0.05).

    It is deliberately NOT part of the accept/reject test. GT anchors are the
    first 6-12 words of a block, so a correct match against a long paragraph has
    LOW precision by construction; used as a threshold it would reject the
    matches the metric exists to make."""
    b = set(norm_tokens(block_text))
    if not b:
        return 0.0
    a = set(norm_tokens(anchor))
    return len(a & b) / len(b)


# --------------------------------------------------------------------------
# Detected-block view (Stage 04 block + its routed OCR text + native order)
# --------------------------------------------------------------------------


@dataclass
class DetBlock:
    idx: int                 # index in the subpage block list
    ro: int                  # Stage 04 reading_order
    btype: str               # page_model BlockType value
    bbox: BBox
    text: str                # concatenated routed OCR words
    native_ranks: list[int]  # TSV indices of routed words (Tesseract's order)

    @property
    def cx(self) -> float:
        return self.bbox.x + self.bbox.w / 2.0

    @property
    def cy(self) -> float:
        return self.bbox.y + self.bbox.h / 2.0

    @property
    def native_key(self) -> float | None:
        if not self.native_ranks:
            return None
        s = sorted(self.native_ranks)
        return s[len(s) // 2]        # median TSV index


def _bbox_iou(gt_bbox: list[float], d: BBox) -> float:
    """Intersection-over-union between a GT figure bbox ``[x, y, w, h]`` and a
    detected block's BBox, both in dewarped-subpage pixel space (verified equal:
    the GT figure bboxes and Stage-04 block bboxes coincide to IoU 0.92-1.00 on
    the clean figures of it_geo_06). Symmetric IoU (not coverage-of-smaller) so a
    partial-figure FRAGMENT — a det box covering only a slice of a GT figure —
    scores low and cannot masquerade as the whole figure. Returns 0.0 on no
    overlap."""
    gx, gy, gw, gh = gt_bbox
    ix = max(gx, d.x)
    iy = max(gy, d.y)
    iX = min(gx + gw, d.x2)
    iY = min(gy + gh, d.y2)
    iw = max(0.0, iX - ix)
    ih = max(0.0, iY - iy)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = gw * gh + d.w * d.h - inter
    return inter / union if union > 0 else 0.0


def _box_gap(a: DetBlock, b: DetBlock) -> float:
    """Minimum edge-to-edge (box-to-box) distance between two blocks; 0 if they
    overlap. A better proxy than CENTER distance for "which figure is this caption
    attached to": center distance is unsound for unequal-height figures — a caption
    directly under a TALL figure's bottom edge is far from that figure's (high)
    center yet near a SHORT neighbor's center, so it mis-attaches (see the
    tall-figure test). Edge-gap fixes THAT case but does NOT encode the caption
    above/below convention: stacked figures with asymmetric spacing (caption nearer
    the NEXT figure's top than its OWN figure's bottom) still mispair (see the
    known-limit test). A convention-aware rule is deferred until a real >=2-figure
    fixture exists to tune against."""
    dx = max(0.0, a.bbox.x - b.bbox.x2, b.bbox.x - a.bbox.x2)
    dy = max(0.0, a.bbox.y - b.bbox.y2, b.bbox.y - a.bbox.y2)
    return (dx * dx + dy * dy) ** 0.5


# --------------------------------------------------------------------------
# Matching (pure): GT subpage blocks -> detected blocks
# --------------------------------------------------------------------------


def match_subpage(gt_blocks: list[dict], det: list[DetBlock]
                  ) -> tuple[dict[str, int], list[str]]:
    """Return (gt_id -> det.idx, list of unmatched gt_ids).

    Figures match by BBOX-OVERLAP when the GT figure carries a bbox: each GT
    figure claims the detected figure it overlaps most (global greedy by IoU,
    floor ``FIG_IOU_MIN``), a bbox-carrying GT figure with no overlapping det box
    is an honest MISS (no rank fallback). This is POSITION-matched, so a figure
    Stage 04 emits out of GT reading order (e.g. it_geo_06's top-right plate F26,
    which the split lands 2nd not last) still pairs with its own box — the earlier
    rank matcher instead relabelled it by order and scored its correct corner-label
    number a mispair. GT figures WITHOUT a bbox (it_geo_04, authored before figure
    bboxes existed) fall back to reading-order rank, unchanged. Text blocks match
    by greedy anchor-token overlap on the remaining detected blocks. Each detected
    block is claimed at most once.

    Equal-recall ties are broken by ``anchor_precision`` (see there). Without
    that, a one-token GT anchor ties at 1.0 against every block containing that
    token and the sort order decided the winner — on ``en_coins_03``-right the
    heading ``"Honduras"`` took the body paragraph P2's block, so P2 had nothing
    left and was reported a segmentation MISS while its text sat in the document.
    One-to-one assignment is kept: it is what makes a miss mean something.
    """
    matched: dict[str, int] = {}
    used: set[int] = set()

    # Figures first, so a figure box can't be stolen by a stray text-anchor
    # overlap. Bbox-carrying GT figures: global greedy by IoU.
    gt_figs = [g for g in gt_blocks if g["type"] == "figure"]
    det_figs = [d for d in det if d.btype == "figure"]
    gt_figs_bbox = [g for g in gt_figs if g.get("bbox")]
    fig_cand = [(_bbox_iou(g["bbox"], d.bbox), g["id"], d.idx)
                for g in gt_figs_bbox for d in det_figs]
    fig_cand.sort(key=lambda t: t[0], reverse=True)
    for iou_val, gid, didx in fig_cand:
        if iou_val < FIG_IOU_MIN or gid in matched or didx in used:
            continue
        matched[gid] = didx
        used.add(didx)

    # GT figures with no bbox (older fixtures): reading-order rank over the
    # detected figures not already claimed by an overlap match.
    gt_figs_norank = sorted((g for g in gt_figs if not g.get("bbox")),
                            key=lambda g: g["order"])
    det_rank = sorted((d for d in det_figs if d.idx not in used),
                      key=lambda d: d.ro)
    for g, d in zip(gt_figs_norank, det_rank):
        matched[g["id"]] = d.idx
        used.add(d.idx)

    # Text blocks (paragraph/caption/heading/...) by anchor overlap, greedy —
    # highest anchor RECALL first, ties broken by anchor PRECISION, then by a
    # stated deterministic order (gt id, then detected index ascending).
    text_gt = [g for g in gt_blocks if g["type"] != "figure" and g.get("anchor")]
    cand = [(anchor_score(g["anchor"], d.text),
             anchor_precision(g["anchor"], d.text), g["id"], d.idx)
            for g in text_gt for d in det if d.idx not in used]
    cand.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
    for score, _prec, gid, didx in cand:
        if score < MATCH_TAU or gid in matched or didx in used:
            continue
        matched[gid] = didx
        used.add(didx)

    misses = [g["id"] for g in gt_blocks if g["id"] not in matched]
    return matched, misses


# --------------------------------------------------------------------------
# Kendall-tau (pure) over matched blocks
# --------------------------------------------------------------------------


def kendall_tau(pairs: list[tuple[float, float]]) -> float | None:
    """Kendall-tau rank correlation between two orderings, given the matched
    (gt_rank, det_rank) pairs. +1 fully concordant, -1 fully reversed, None if
    < 2 pairs. O(n^2) — n is tiny (matched blocks per subpage)."""
    n = len(pairs)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = pairs[i][0] - pairs[j][0]
            b = pairs[i][1] - pairs[j][1]
            s = a * b
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
            # ties (s == 0) ignored — no GT/detector produces equal ranks here
    tot = conc + disc
    return (conc - disc) / tot if tot else None


# --------------------------------------------------------------------------
# Figure-INCLUSIVE order (pure) — the metric `tau_layout` deliberately omits
# --------------------------------------------------------------------------


@dataclass
class OrderAll:
    """Figure-inclusive order grade for one subpage (Stage-04 arm only)."""

    tau: float | None
    n_fig_graded: int      # figures included (bbox-matched only)
    n_blocks: int          # total blocks in the graded set
    seq_gt: list[str]      # graded block ids in GT order
    seq_det: list[str]     # the same ids in Stage 04's order
    note: str              # why tau is None, when it is

    @property
    def gradeable(self) -> bool:
        return self.tau is not None


def order_with_figures(gt_blocks: list[dict], matched: dict[str, int],
                       det: list[DetBlock]) -> OrderAll:
    """Kendall-tau over matched TEXT blocks **plus position-honest figures**.

    ``tau_layout`` excludes figures from both arms on purpose (the Tesseract-native
    arm cannot order an imageless region, so including them would compare unequal
    block sets). The cost was that figure order went **entirely ungraded**: Phase B
    of the figure split corrected it_geo_06-right from ``F29,F30,C29,C30`` to the GT
    ``F29,C29,F30,C30`` and no number in this harness moved
    (docs/FIGURE_SEPARATION_SCOPE.md §6/§10). This closes that gap as a THIRD,
    Stage-04-only number rather than by touching the two comparable arms.

    **A figure is graded only when its match is position-honest**, i.e. it was
    matched by GT-bbox overlap. Figures in GT files authored before figure bboxes
    existed (it_geo_04, de_01) are matched by reading-order RANK — the i-th GT
    figure to the i-th detected figure — so those pairs are concordant *by
    construction* and grading order off them would be circular. They are dropped,
    and ``n_fig_graded`` reports how many figures actually counted so an
    all-text-in-disguise ``+1.00`` cannot read as a figure-order pass.

    **Read this only alongside seg-recall.** The set is the MATCHED blocks, so a
    figure the detector loses (or false-splits until it no longer overlaps its GT
    box) leaves the graded set entirely: a segmentation regression makes this
    metric quieter, not worse.
    """
    by_id = {g["id"]: g for g in gt_blocks}
    by_idx = {d.idx: d for d in det}     # keyed on idx, like grouping_eval
    graded: list[tuple[str, float, float]] = []
    for gid, di in sorted(matched.items()):
        g = by_id[gid]
        if g["type"] == "figure" and not g.get("bbox"):
            continue                     # rank-matched -> circular, not gradeable
        graded.append((gid, g["order"], by_idx[di].ro))

    n_fig = sum(1 for gid, _, _ in graded if by_id[gid]["type"] == "figure")
    seq_gt = [gid for gid, _, _ in sorted(graded, key=lambda t: t[1])]
    seq_det = [gid for gid, _, _ in sorted(graded, key=lambda t: t[2])]

    if n_fig == 0:
        return OrderAll(None, 0, len(graded), seq_gt, seq_det,
                        "no gradeable figure — GT carries no figure bbox, so "
                        "figures are rank-matched (circular)")
    if len(graded) < 2:
        return OrderAll(None, n_fig, len(graded), seq_gt, seq_det,
                        "<2 matched blocks to order")
    return OrderAll(kendall_tau([(o, r) for _, o, r in graded]),
                    n_fig, len(graded), seq_gt, seq_det, "")


# --------------------------------------------------------------------------
# Grouping (pure): does each caption's nearest figure == its GT partner figure?
# --------------------------------------------------------------------------


@dataclass
class GroupResult:
    caption_id: str
    figure_id: str
    caption_typed_ok: bool     # detected block typed 'caption'? (Gate-4 relies on it)
    nearest_ok: bool           # caption's nearest detected figure == partner figure
    n_figures: int             # figures in the subpage (1 => association possible, not discriminated)
    reason: str


def grouping_eval(pairs: list[dict], matched: dict[str, int], det: list[DetBlock]
                  ) -> list[GroupResult]:
    by_idx = {d.idx: d for d in det}
    figs = [d for d in det if d.btype == "figure"]
    out: list[GroupResult] = []
    for pr in pairs:
        cid, fid = pr["caption"], pr["figure"]
        if cid not in matched or fid not in matched:
            out.append(GroupResult(cid, fid, False, False, len(figs),
                                   "caption or figure block not matched on this subpage"))
            continue
        cap = by_idx[matched[cid]]
        fig_idx = matched[fid]
        cap_typed = cap.btype == "caption"
        if not figs:
            out.append(GroupResult(cid, fid, cap_typed, False, 0,
                                   "no figure detected"))
            continue
        nearest = min(figs, key=lambda f: _box_gap(cap, f))
        ok = nearest.idx == fig_idx
        reason = ("nearest figure is the partner"
                  if ok else "nearest figure is NOT the partner")
        if len(figs) == 1:
            reason += " (single figure — association possible, NOT discriminated)"
        if not cap_typed:
            reason += f"; caption block mistyped '{cap.btype}' (breaks Gate-4 float)"
        out.append(GroupResult(cid, fid, cap_typed, ok, len(figs), reason))
    return out


# --------------------------------------------------------------------------
# Per-subpage / per-image grading result containers
# --------------------------------------------------------------------------


@dataclass
class SubpageGrade:
    name: str
    n_gt: int
    matched: dict[str, int]
    misses: list[str]
    type_ok: dict[str, bool]           # gt_id -> detected type == gt type
    tau_layout: float | None
    tau_native: float | None
    n_native: int                      # word-bearing matched blocks (native arm)
    order_all: OrderAll                # figure-INCLUSIVE order (Stage-04 arm only)
    groups: list[GroupResult]
    n_det_blocks: int
    n_header_det: int                  # detected header+page_number blocks
    n_stripped_gt: int
    # --- Figura-NN parser arm (additive; detector numbers above are untouched) ---
    type_ok_parser: dict[str, bool] = field(default_factory=dict)  # type_ok after re-typing
    caption_typed_parser: dict[str, bool] = field(default_factory=dict)  # caption_id -> typed ok
    n_promoted: int = 0                # paragraph/other blocks the parser re-typed caption
    n_fig_numbers: int = 0            # detected figures whose corner-label number OCR'd
    n_pairs_by_number: int = 0        # emitted pairs that match the GT partner (CORRECT)
    n_pairs_gt: int = 0               # GT pairs on this subpage (denominator)
    n_pairs_wrong: int = 0            # emitted pairs contradicting the GT — the bar is 0
    n_pairs_geometry: int = 0         # of the emitted pairs, how many came from geometry
    n_pairs_sole: int = 0             # ...and how many from the sole-figure arm
    n_abstained: int = 0              # captions deliberately left unpaired
    abstain_reasons: dict[str, str] = field(default_factory=dict)
    pairs_detail: list[dict] = field(default_factory=list)  # every emitted pair + verdict
    # --- Which BLOCK SET was graded (see stage05_blocks) ----------------------
    stage05_on: bool = True            # False = Stage 04's blocks alone (old arm)
    stage05: dict = field(default_factory=dict)   # orphan/eject/rescue counts
    # gt_id -> the matched block's bbox. Detected INDICES shift between the two
    # arms (Stage 05 adds blocks), so a before/after diff on indices cannot tell
    # "still matched, different block" from "matched the same block". The bbox
    # can: it is stable for a block neither pass touched.
    match_bbox: dict[str, list[int]] = field(default_factory=dict)

    @property
    def seg_recall(self) -> float:
        return len(self.matched) / self.n_gt if self.n_gt else 0.0

    @property
    def type_acc(self) -> float:
        vals = list(self.type_ok.values())
        return sum(vals) / len(vals) if vals else 0.0


@dataclass
class ImageGrade:
    image_id: str
    subpages: list[SubpageGrade] = field(default_factory=list)

    @property
    def stage05_on(self) -> bool:
        return all(s.stage05_on for s in self.subpages) if self.subpages else True


# --------------------------------------------------------------------------
# Driver — run the pipeline on one image and grade it
# --------------------------------------------------------------------------


def _route_words(pl: "S4.PageLayout", words: list, scale: float) -> list[DetBlock]:
    """Route each OCR word to the smallest block containing its center; build the
    DetBlock view (routed text + native TSV ranks per block)."""
    det = [DetBlock(idx=i, ro=b.reading_order, btype=b.type.value, bbox=b.bbox,
                    text="", native_ranks=[])
           for i, b in enumerate(pl.blocks)]
    texts: list[list[str]] = [[] for _ in pl.blocks]
    for wi, w in enumerate(words):
        wb = _word_box(w, scale)
        best, area = None, None
        for i, b in enumerate(pl.blocks):
            if _center_in(b.bbox, wb):
                a = b.bbox.w * b.bbox.h
                if area is None or a < area:
                    best, area = i, a
        if best is not None and w.text.strip():
            texts[best].append(w.text)
            det[best].native_ranks.append(wi)
    for i, d in enumerate(det):
        d.text = " ".join(texts[i])
    return det


def stage05_blocks(pl: "S4.PageLayout", img: np.ndarray, twords: list,
                   scale: float, cfg: dict, binary: str, lang: str, p: dict
                   ) -> tuple[list[Block], dict]:
    """Run Stage 05's three block-CREATING passes, in production order.

    This is the whole point of the ``--stage05`` arm. The eval used to stop after
    Stage 04, but three mechanisms that create or rewrite blocks run later, in
    Stage 05, before anything reaches ``document.json``:

      * **orphan-word rescue** (``attach_words``) — words inside no detected box
        are grouped by their TSV paragraph into synthetic blocks, and the whole
        set is re-ranked by the same XY-Cut Stage 04 uses;
      * **caption ejection** (``caption_eject``) — a caption printed INSIDE a
        figure box is moved out into its own CAPTION block;
      * **starved-block re-read** (``block_reocr``) — a block the page pass
        under-read is re-read from its own crop and replaced when the re-read
        wins on word count AND its own confidence.

    None of the three was visible here, so a GT block this eval called a
    segmentation MISS could already be in the shipped document (measured
    2026-08-26: two of six were). The calls below are the same functions
    ``stage05_ocr.run`` makes, in the same order, with the same params.
    """
    h, w = img.shape[:2]
    tessdata = resolve_tessdata_dir(cfg)
    oem = int((cfg.get("tesseract", {}) or {}).get("oem", 1))

    ordered, n_orphan = S5.attach_words(twords, pl.blocks, scale, w, h, p)
    n_after_attach = len(ordered)
    ordered, eject_notes = CE.eject_inline_captions(
        ordered, img, binary, tessdata, lang, p, w, h)
    ordered, rescues, n_dropped, n_added = BR.rescue_starved_blocks(
        ordered, img, binary, tessdata, lang, oem, scale,
        next_line_id=1 + max((wd.line_id for b in ordered for wd in b.words),
                             default=-1),
        p=(cfg.get("block_reocr", {}) or {}))

    # Production's word-conservation invariant, replicated VERBATIM. It is the
    # cheapest available proof that the three passes above are wired the way
    # stage05_ocr wires them and not merely approximately: if this eval ever
    # drifts from production here, every number it prints is measured on a block
    # set that does not ship, which is the exact defect this arm exists to fix.
    attached = sum(len(b.words) for b in ordered)
    expect = len(twords) - n_dropped + n_added
    if attached != expect:
        raise AssertionError(
            f"word conservation violated on {pl.name}: attached {attached} != "
            f"recognized {len(twords)} - rescue-dropped {n_dropped} + "
            f"rescue-added {n_added} = {expect}")

    return ordered, {
        "orphan_words": n_orphan,
        "n_orphan_blocks": n_after_attach - len(pl.blocks),
        "n_ejected": len(eject_notes),
        "n_rescued": len(rescues),
        "eject_notes": list(eject_notes),
        "rescue_notes": [f"{r.block_type} #{r.block_id}: {r.n_before}w@"
                         f"{r.conf_before} -> {r.n_after}w@{r.conf_after}"
                         for r in rescues],
    }


def det_from_blocks(blocks: list[Block], twords: list, scale: float
                    ) -> list[DetBlock]:
    """Build the DetBlock view from Stage 05's FINAL blocks.

    ``text`` is what the block actually carries after Stage 05 — so an ejected
    caption, an orphan-rescued block and a re-read paragraph are each graded on
    the words that reach ``document.json``, not on a page-pass routing of them.

    ``native_ranks`` deliberately stay the PAGE-PASS TSV indices, routed into
    these boxes by the same smallest-containing-box rule as before. The native
    arm asks "what order did Tesseract's own page pass imply for this region" —
    a question about the page pass, not about which words the block ended up
    owning — so a rescued block's replacement words must not answer it.
    """
    det = [DetBlock(idx=i, ro=b.reading_order, btype=b.type.value, bbox=b.bbox,
                    text=" ".join(w.text for w in b.words if w.text.strip()),
                    native_ranks=[])
           for i, b in enumerate(blocks)]
    for wi, tw in enumerate(twords):
        if not tw.text.strip():
            continue
        wb = _word_box(tw, scale)
        best, area = None, None
        for i, b in enumerate(blocks):
            if _center_in(b.bbox, wb):
                a = b.bbox.w * b.bbox.h
                if area is None or a < area:
                    best, area = i, a
        if best is not None:
            det[best].native_ranks.append(wi)
    return det


_BOOL_WORDS = {"true": True, "1": True, "yes": True, "on": True,
               "false": False, "0": False, "no": False, "off": False}


def apply_param_overrides(p: dict, sets: list[str]) -> dict:
    """Apply ``key=value`` layout-knob overrides, COERCED to the type of the
    ``stage04_layout.DEFAULTS`` entry, failing loudly on an unknown key.

    The coercion is the whole point: ``--set fig_vsplit=False`` naively stored the
    string ``"False"``, which is TRUTHY, so ``if not p["fig_vsplit"]`` never fired
    and the A/B silently compared a run against itself. A knob that appears to be
    off while being on turns a null result into a false conclusion."""
    out = dict(p)
    for item in sets:
        if "=" not in item:
            raise ValueError(f"--set expects key=value, got {item!r}")
        key, _, raw = item.partition("=")
        key, raw = key.strip(), raw.strip()
        if key not in S4.DEFAULTS:
            raise ValueError(f"--set: unknown layout knob {key!r} "
                             f"(known: {', '.join(sorted(S4.DEFAULTS))})")
        proto = S4.DEFAULTS[key]
        if isinstance(proto, bool):
            if raw.lower() not in _BOOL_WORDS:
                raise ValueError(f"--set {key}: expected a boolean, got {raw!r}")
            out[key] = _BOOL_WORDS[raw.lower()]
        elif isinstance(proto, int):
            out[key] = int(raw)
        elif isinstance(proto, float):
            out[key] = float(raw)
        else:
            out[key] = raw
    return out


def grade_image(image_id: str, testset: Path, cfg: dict, binary: str,
                param_sets: list[str] | None = None, stage05: bool = True
                ) -> tuple[ImageGrade, dict]:
    gt_path = testset / "gt" / f"{image_id}.blocks.json"
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    if gt.get("gt_type") != "block_reading_order":
        raise ValueError(f"{gt_path} is not a block_reading_order GT")

    img_file = testset / f"{image_id}.jpg"
    tessdata = resolve_tessdata_dir(cfg)
    bgr, _ = NORM.load_upright_bgr(img_file, binary, tessdata)
    lang = lang_code(gt.get("language", "eng"))

    p = apply_param_overrides(S4.resolve_params(cfg), param_sets or [])
    halves, _ = split_halves(bgr, cfg)
    dw = dewarp_halves(halves, cfg, "auto")

    pairs = gt.get("grading", {}).get("caption_figure_pairs", [])
    warns: list[str] = []
    det_model = S4.make_detector("auto", cfg, warns)
    grade = ImageGrade(image_id=image_id)
    try:
        for name, img, _pd in dw:
            sub = "left" if "left" in name else ("right" if "right" in name else name)
            gsub = gt["subpages"].get(sub)
            if gsub is None:
                continue
            words, scale = ocr_words(binary, cfg, img, lang)
            pl = S4.layout_page(img, cfg, p, warns, det_model)
            pl.name = name
            # The graded block set. With Stage 05 on this is what SHIPS; with it
            # off it is Stage 04 alone, reproducing rows written before
            # 2026-08-26. (`ocr_words` IS `stage05_ocr.ocr_subpage` since
            # 2026-08-26 — the harness copy that used to shadow it is gone — so
            # the two arms differ in the three Stage 05 passes and nothing else.)
            if stage05:
                blocks5, s5info = stage05_blocks(pl, img, words, scale, cfg,
                                                 binary, lang, p)
                det = det_from_blocks(blocks5, words, scale)
            else:
                s5info = {}
                det = _route_words(pl, words, scale)

            gt_blocks = gsub["reading_order"]
            matched, misses = match_subpage(gt_blocks, det)

            by_id = {g["id"]: g for g in gt_blocks}
            type_ok = {gid: det[di].btype == by_id[gid]["type"]
                       for gid, di in matched.items()}

            # Order: both arms over TEXT blocks only (GT type != figure), so the
            # layout-vs-native headline compares the SAME block set. Photos carry no
            # routed words (native_key None) and were already absent from native, but
            # text-bearing figures — diagrams/maps with embedded labels, e.g.
            # it_geo_04's B6R map or it_geo_07's diagrams — DO get routed words and
            # so leaked into the native arm (that leak, not a real order deficit, is
            # what pinned it_geo_04-right native at 0.33). Excluding figures by TYPE
            # from BOTH arms removes that asymmetry and keeps tau measuring TEXT
            # reading order; figure ORDER is owner-SECONDARY and, with bbox-overlap
            # matching now position-honest, would otherwise inject figure-placement
            # deviations (e.g. it_geo_06's out-of-order F26 plate) into it.
            lay_pairs = [(by_id[gid]["order"], det[di].ro)
                         for gid, di in matched.items()
                         if by_id[gid]["type"] != "figure"]
            nat = [(by_id[gid]["order"], det[di].native_key)
                   for gid, di in matched.items()
                   if by_id[gid]["type"] != "figure" and det[di].native_key is not None]
            tau_layout = kendall_tau([(g, d) for g, d in lay_pairs])
            tau_native = kendall_tau([(g, d) for g, d in nat]) if len(nat) >= 2 else None
            # Third arm: the same Stage-04 order WITH the position-honest figures
            # in it — what the two comparable arms above cannot grade.
            order_all = order_with_figures(gt_blocks, matched, det)

            sub_pairs = [pr for pr in pairs if pr.get("subpage") == sub]
            groups = grouping_eval(sub_pairs, matched, det)

            # ---- PRODUCTION grouping pass (pipeline.figure_grouping) --------
            # This is the SAME function Stage 07 runs on the editable document —
            # not a parallel "parser arm". The eval used to re-implement caption
            # promotion + number pairing here, which is precisely how the measured
            # win stayed outside the pipeline; the numbers below now grade
            # production code on real pixels.
            gr = FG.group_figures(
                [FG.BlockView(key=str(d.idx), btype=d.btype, bbox=d.bbox, text=d.text)
                 for d in det],
                page_h=img.shape[0], page_w=img.shape[1],
                lang=lang, page_bgr=img, tess_bin=binary)

            def eff_type(di: int) -> str:
                return "caption" if (det[di].btype == "caption"
                                     or str(di) in gr.promoted) else det[di].btype

            type_ok_parser = {gid: eff_type(di) == by_id[gid]["type"]
                              for gid, di in matched.items()}
            caption_typed_parser = {
                g.caption_id: (g.caption_id in matched
                               and eff_type(matched[g.caption_id]) == "caption")
                for g in groups}

            # Grade the pairs the pass actually emitted, translated from detected
            # block indices back to GT ids via the (bbox/anchor) match. The bar is
            # ZERO WRONG, so a pair whose GT partner disagrees is counted as
            # `wrong` — never rounded into the miss column.
            gt_pair_map = {pr["caption"]: pr["figure"] for pr in sub_pairs}
            det_to_gt = {di: gid for gid, di in matched.items()}
            pairs_ok = pairs_wrong = 0
            pairs_detail: list[dict] = []
            for cid_key, fid_key in gr.pairs.items():
                ci, fi = int(cid_key), int(fid_key)
                c_gt, f_gt = det_to_gt.get(ci), det_to_gt.get(fi)
                if c_gt is not None and c_gt in gt_pair_map:
                    verdict = "ok" if gt_pair_map[c_gt] == f_gt else "wrong"
                elif c_gt is not None and by_id[c_gt]["type"] != "caption":
                    # The pair is anchored on a block the GT says is NOT a caption
                    # (en_coins' run-in "Description:" labels, which the detector
                    # types 'caption'). Attaching one to a figure is a wrong pair by
                    # construction — grading it "ungraded" because the GT anchors no
                    # pair for a non-caption would hide exactly the failure the
                    # zero-wrong bar exists to catch.
                    verdict = "wrong"
                else:
                    # The GT anchors no pair for this caption. NOT silently dropped:
                    # a pair the GT cannot adjudicate is still a pair the renderer
                    # will act on, so it is surfaced as UNGRADED for a human to read.
                    verdict = "ungraded"
                pairs_ok += verdict == "ok"
                pairs_wrong += verdict == "wrong"
                pairs_detail.append({
                    "caption": c_gt or f"det{ci}", "figure": f_gt or f"det{fi}",
                    "caption_text": det[ci].text[:60], "source": gr.pair_source[cid_key],
                    "verdict": verdict,
                })

            n_header = sum(1 for d in det if d.btype in ("header", "page_number"))
            grade.subpages.append(SubpageGrade(
                stage05_on=stage05, stage05=s5info,
                match_bbox={gid: [det[di].bbox.x, det[di].bbox.y,
                                  det[di].bbox.w, det[di].bbox.h]
                            for gid, di in matched.items()},
                name=name, n_gt=len(gt_blocks), matched=matched, misses=misses,
                type_ok=type_ok, tau_layout=tau_layout, tau_native=tau_native,
                n_native=len(nat), order_all=order_all,
                groups=groups, n_det_blocks=len(det),
                n_header_det=n_header, n_stripped_gt=len(gsub.get("stripped", [])),
                type_ok_parser=type_ok_parser, caption_typed_parser=caption_typed_parser,
                n_promoted=len(gr.promoted),
                n_fig_numbers=len(gr.figure_numbers),
                n_pairs_by_number=pairs_ok, n_pairs_gt=len(sub_pairs),
                n_pairs_wrong=pairs_wrong, pairs_detail=pairs_detail,
                n_pairs_geometry=gr.n_by_geometry, n_pairs_sole=gr.n_by_sole_figure,
                n_abstained=len(gr.abstained),
                abstain_reasons={det_to_gt.get(int(k), f"det{k}"): v
                                 for k, v in gr.abstained.items()},
            ))
    finally:
        if det_model is not None:
            det_model.close()

    return grade, {"warns": warns}


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _tau_str(t: float | None) -> str:
    return "n/a" if t is None else f"{t:+.2f}"


def _block_set_note(stage05_on: bool) -> str:
    """The one line a pasted table cannot do without: WHICH block set was graded.

    RESULTS.md is append-only and its rows get read side by side across dates, so
    a row measured on the shipped block set and a row measured on Stage 04 alone
    must not be silently comparable \u2014 they are different quantities.
    """
    if stage05_on:
        return (
            "**Block set graded: Stage 04 + Stage 05 (what SHIPS).** Orphan-word "
            "rescue, caption ejection and the starved-block re-read all create or "
            "rewrite blocks after Stage 04, so every number below is measured on "
            "the block set that reaches `document.json`. Two things to read it "
            "with: (a) `reading_order` is Stage 05's \u2014 an orphan re-ranks the "
            "whole set through the same XY-Cut \u2014 so the tau column is the "
            "SHIPPED order, not Stage 04's, and is NOT comparable to a "
            "pre-2026-08-26 row; (b) an orphan-rescued block is typed `other` by "
            "construction, so recovering one raises seg recall and LOWERS type "
            "accuracy. `--no-stage05` reproduces the old arm.")
    return (
        "**Block set graded: Stage 04 alone (`--no-stage05`).** Reproduces rows "
        "written before 2026-08-26. This does NOT grade the deliverable: "
        "orphan-word rescue, caption ejection and the starved-block re-read run "
        "later, in Stage 05, and each creates or rewrites blocks \u2014 so a "
        "`miss` below may well be present in `document.json`.")


def build_report(grade: ImageGrade, tver: str, run_date: str) -> str:
    L: list[str] = []
    L.append(f"\n## Gate 3 block-order eval — {run_date}, tesseract {tver}, "
             f"image={grade.image_id}\n")
    L.append(_block_set_note(grade.stage05_on))
    L.append("")
    L.append("Block structure graded DIRECTLY against the per-subpage "
             f"block-order GT (`gt/{grade.image_id}.blocks.json`): segmentation, type, "
             "caption<->figure grouping, and linear order. Owner priority: "
             "segmentation/type/grouping OUTRANK exact order (tau is secondary). "
             "Tau is over TEXT blocks only (figures excluded from BOTH the Stage-04 "
             "and Tesseract-native arms, so the two arms compare the same block set); "
             "figures match by GT-bbox overlap. **tau+figures** is a third, "
             "Stage-04-only number over text PLUS the bbox-matched (position-honest) "
             "figures \u2014 rank-matched figures are excluded as circular, so "
             "`figs=0` prints `n/a`, never a passing score. It grades the "
             + ("per-subpage order Stage 05 leaves behind"
                if grade.stage05_on else "per-subpage order Stage 04 proposes")
             + ", not Stage 07's carrying of it into `document.json`. "
             "Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.\n")
    tau_col = "tau (shipped order)" if grade.stage05_on else "tau (Stage04)"
    L.append(f"| subpage | seg recall | type acc | {tau_col} | tau (Tess-native) | "
             "tau+figures | grouping | det blocks | misses |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in grade.subpages:
        grp = "; ".join(
            f"{g.caption_id}->{g.figure_id}:"
            f"{'assoc' if g.nearest_ok else 'MISS'}"
            f"{'' if g.caption_typed_ok else '/type!'}"
            f"{'/1fig' if g.n_figures == 1 else ''}"
            for g in s.groups) or "—"
        oa = s.order_all
        tau_all = (f"{_tau_str(oa.tau)} (figs={oa.n_fig_graded}/n={oa.n_blocks})"
                   if oa.gradeable else f"n/a ({oa.note})")
        L.append(
            f"| {s.name} | {len(s.matched)}/{s.n_gt} ({s.seg_recall:.0%}) | "
            f"{sum(s.type_ok.values())}/{len(s.type_ok)} ({s.type_acc:.0%}) | "
            f"{_tau_str(s.tau_layout)} | {_tau_str(s.tau_native)} (n={s.n_native}) | "
            f"{tau_all} | "
            f"{grp} | {s.n_det_blocks} | {', '.join(s.misses) or '—'} |")

    # Aggregate numbers.
    seg = sum(len(s.matched) for s in grade.subpages)
    seg_tot = sum(s.n_gt for s in grade.subpages)
    typ = sum(sum(s.type_ok.values()) for s in grade.subpages)
    typ_tot = sum(len(s.type_ok) for s in grade.subpages)
    all_groups = [g for s in grade.subpages for g in s.groups]
    assoc = sum(1 for g in all_groups if g.nearest_ok)
    typed = sum(1 for g in all_groups if g.caption_typed_ok)
    discriminated = sum(1 for g in all_groups if g.nearest_ok and g.n_figures >= 2)

    L.append("")
    L.append(f"**Segmentation** {seg}/{seg_tot} GT blocks matched. "
             f"**Type** {typ}/{typ_tot} matched blocks correctly typed. "
             f"**Grouping** {assoc}/{len(all_groups)} captions associate to their "
             f"partner figure ({typed}/{len(all_groups)} also typed 'caption'); "
             f"but only {discriminated}/{len(all_groups)} on a subpage with >=2 "
             f"figures (the rest are single-figure: association POSSIBLE, not "
             f"discriminated).")

    # --- What Stage 05 did to the graded block set ----------------------------
    if grade.stage05_on:
        L.append("")
        L.append("**Stage 05's contribution to the graded set** \u2014 the blocks "
                 "the old arm could not see. An `orphan` block is built from words "
                 "inside no detected box (typed `other` by construction); an "
                 "`eject` moves a caption printed inside a figure out into its own "
                 "CAPTION block; a `re-read` replaces a starved block's words with "
                 "a read of that block's own crop.")
        for sg in grade.subpages:
            d = sg.stage05
            L.append(f"- `{sg.name}`: {d.get('n_orphan_blocks', 0)} orphan block(s) "
                     f"from {d.get('orphan_words', 0)} orphan words, "
                     f"{d.get('n_ejected', 0)} caption ejection(s), "
                     f"{d.get('n_rescued', 0)} starved block(s) re-read.")
            for note in d.get("rescue_notes", []):
                L.append(f"  - re-read {note}")
            for note in d.get("eject_notes", []):
                L.append(f"  - eject {note}")

    # --- Figure-inclusive order detail -----------------------------------------
    gradeable = [s for s in grade.subpages if s.order_all.gradeable]
    L.append("")
    L.append("**Figure-inclusive reading order** (`tau+figures`, Stage-04 arm only). "
             "A scalar says something is wrong but not what, so the graded sequence is "
             "printed both ways. The graded set is the MATCHED blocks — a figure the "
             "detector loses drops OUT of it, so this number goes quiet on a "
             "segmentation regression rather than red: read it next to seg recall.")
    if not gradeable:
        L.append("- no subpage is gradeable on this image (see the `n/a` reasons above).")
    for s in gradeable:
        oa = s.order_all
        L.append(f"- `{s.name}` tau={_tau_str(oa.tau)} over {oa.n_blocks} blocks "
                 f"({oa.n_fig_graded} figures):")
        L.append(f"  - GT:       {', '.join(oa.seq_gt)}")
        L.append(f"  - Stage 04: {', '.join(oa.seq_det)}"
                 f"{'  ✓ identical' if oa.seq_det == oa.seq_gt else ''}")

    # --- Figura-NN parser arm --------------------------------------------------
    typ_p = sum(sum(s.type_ok_parser.values()) for s in grade.subpages)
    typ_p_tot = sum(len(s.type_ok_parser) for s in grade.subpages)
    typed_p = sum(1 for s in grade.subpages
                  for v in s.caption_typed_parser.values() if v)
    promoted = sum(s.n_promoted for s in grade.subpages)
    fig_nums = sum(s.n_fig_numbers for s in grade.subpages)
    pairs_by_num = sum(s.n_pairs_by_number for s in grade.subpages)
    pairs_gt = sum(s.n_pairs_gt for s in grade.subpages)
    pairs_wrong = sum(s.n_pairs_wrong for s in grade.subpages)
    pairs_geom = sum(s.n_pairs_geometry for s in grade.subpages)
    pairs_sole = sum(s.n_pairs_sole for s in grade.subpages)
    abstained = sum(s.n_abstained for s in grade.subpages)
    L.append("")
    L.append("**Caption↔figure grouping** (`pipeline.figure_grouping` — the SAME pass "
             "Stage 07 runs on the editable document, so these numbers grade production "
             "code, not a parallel eval arm). Captions are typed by the printed header "
             "(`Figura NN`, start-anchored, never demoting a block or touching figures), "
             "then paired: **printed number first** (a figure's number comes from its "
             "in-photo corner label, read from PIXELS by `pipeline.figure_label`), "
             "**guarded geometry second** (column overlap + gap limit + mutual-nearest + "
             "unambiguous, and suppressed entirely for a numbered caption on a subpage "
             "that prints figure numbers), and **sole-figure last** (no geometry at all: "
             "the subpage prints exactly one figure and exactly one block declaring "
             "itself its caption in print). Everything else ABSTAINS — the bar is **zero "
             "wrong pairs**, because a caption printed under the wrong photo is worse "
             "output than a caption standing alone.")
    L.append(f"- **Caption typing:** detector {typed}/{len(all_groups)} vs "
             f"**parser {typed_p}/{len(all_groups)}** captions typed `caption` "
             f"({promoted} paragraph blocks promoted). "
             f"**Type accuracy over matched blocks:** detector {typ}/{typ_tot} vs "
             f"**parser {typ_p}/{typ_p_tot}**.")
    L.append(f"- **Pairing:** figure corner labels recovered from pixels = {fig_nums}; "
             f"**{pairs_by_num}/{pairs_gt} GT pairs recovered, {pairs_wrong} WRONG** "
             f"({pairs_geom} of the emitted pairs came from the geometry arm, "
             f"{pairs_sole} from the sole-figure arm, the rest from the printed number); "
             f"{abstained} captions abstained. "
             f"Figures are matched to the GT's overlay bboxes by IoU overlap, which is "
             f"independent of the recovered number — so a wrong read is still caught "
             f"(the check is not circular).")
    for s in grade.subpages:
        for cid, why in sorted(s.abstain_reasons.items()):
            L.append(f"  - abstained `{cid}` ({s.name}): {why}")
    return "\n".join(L) + "\n"


def grade_to_json(grade: ImageGrade) -> dict:
    return {
        "image_id": grade.image_id,
        "stage05": grade.stage05_on,
        "subpages": [{
            "name": s.name, "n_gt": s.n_gt, "matched": s.matched,
            "match_bbox": s.match_bbox, "stage05_detail": s.stage05,
            "misses": s.misses, "type_ok": s.type_ok,
            "seg_recall": s.seg_recall, "type_acc": s.type_acc,
            "tau_layout": s.tau_layout, "tau_native": s.tau_native,
            "n_native": s.n_native,
            "order_all": {
                "tau": s.order_all.tau, "n_fig_graded": s.order_all.n_fig_graded,
                "n_blocks": s.order_all.n_blocks, "seq_gt": s.order_all.seq_gt,
                "seq_det": s.order_all.seq_det, "note": s.order_all.note,
            },
            "n_det_blocks": s.n_det_blocks,
            "n_header_det": s.n_header_det, "n_stripped_gt": s.n_stripped_gt,
            "type_ok_parser": s.type_ok_parser,
            "caption_typed_parser": s.caption_typed_parser,
            "n_promoted": s.n_promoted, "n_fig_numbers": s.n_fig_numbers,
            "n_pairs_by_number": s.n_pairs_by_number, "n_pairs_gt": s.n_pairs_gt,
            "n_pairs_wrong": s.n_pairs_wrong, "n_pairs_geometry": s.n_pairs_geometry,
            "n_pairs_sole": s.n_pairs_sole,
            "n_abstained": s.n_abstained, "abstain_reasons": s.abstain_reasons,
            "pairs_detail": s.pairs_detail,
            "groups": [{
                "caption": g.caption_id, "figure": g.figure_id,
                "caption_typed_ok": g.caption_typed_ok, "nearest_ok": g.nearest_ok,
                "n_figures": g.n_figures, "reason": g.reason,
            } for g in s.groups],
        } for s in grade.subpages],
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 3 block-order eval")
    ap.add_argument("--testset", type=Path, default=REPO_ROOT / "testset")
    ap.add_argument("--image", default="it_geo_04", help="image_id with a "
                    "gt/<id>.blocks.json block-order GT")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--report", type=Path, default=None,
                    help="append a dated section to this file (e.g. docs/RESULTS.md)")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--no-stage05", dest="stage05", action="store_false",
                    help="grade Stage 04's blocks ALONE, the pre-2026-08-26 arm: "
                         "skip orphan-word rescue, caption ejection and the "
                         "starved-block re-read. Reproduces older RESULTS rows; "
                         "does NOT grade the deliverable.")
    ap.set_defaults(stage05=True)
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="override a stage04_layout layout knob for this run "
                         "(value coerced to the DEFAULTS type), e.g. "
                         "--set fig_vsplit=false")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_config(args.config)
    binary = find_tesseract(cfg)
    if not binary:
        print("ERROR: Tesseract not found (set tesseract.binary in config.yaml).",
              file=sys.stderr)
        return 2
    tver = tesseract_version(binary)
    print(f"tesseract: {binary} (v{tver})")

    try:
        grade, extra = grade_image(args.image, args.testset, cfg, binary,
                                   args.sets, stage05=args.stage05)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    report = build_report(grade, tver, datetime.date.today().isoformat())
    if args.sets:
        report += f"\nLayout knobs overridden for this run: {', '.join(args.sets)}\n"
    print("\n" + report)
    for w in extra["warns"]:
        print(f"  [warn] {w}", file=sys.stderr)

    if args.json_out:
        args.json_out.write_text(json.dumps(grade_to_json(grade), indent=2,
                                            ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json_out}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "a", encoding="utf-8") as f:
            f.write(report)
        print(f"Appended to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
