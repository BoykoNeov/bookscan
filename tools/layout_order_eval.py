"""Gate 3 block-order eval — grade Stage 04 reading order + caption/figure
grouping against a BLOCK-ORDER ground truth (``gt/<id>.blocks.json``).

This is the sequence-order + grouping metric the Gate-3 headline was blocked on.
Unlike ``tools/layout_ab.py`` (which measures WER of reordered words, and so can
only show a reading-order WIN on a page where Tesseract's own order already
fails), this tool grades Stage 04's block structure DIRECTLY against a hand-typed
per-subpage block map — segmentation, type, caption<->figure grouping, and
linear order — on ``it_geo_04``, a genuine multi-column + figure-sidebar spread.

Grading follows the owner's priority (encoded in the GT ``primary_invariants``):
segmentation and type and caption<->figure grouping OUTRANK exact linear order.
So the report leads with those and treats Kendall-tau as secondary.

Method (per subpage — Stage 02 splits the spread, Stage 04 orders each half):
  1. split -> dewarp (auto/UVDoc) -> Stage 04 layout, exactly the Gate-2/3 path
     (reuses tools.dewarp_ab + tools.layout_ab helpers), so numbers stay
     comparable. OCR each half ONCE and route each word to the smallest block
     whose box contains its center (same routing as layout_ab).
  2. MATCH each GT block to a detected block:
       * FIGURE GT blocks: by reading_order rank within the subpage. Figures
         carry no bbox in the GT and their in-figure labels ("LAGAZUOI ...")
         do not OCR, so anchor text can't match them; the i-th GT figure pairs
         with the i-th detected figure top-to-bottom.
       * TEXT GT blocks (paragraph / caption / heading): by anchor-token
         overlap against the block's routed OCR text (greedy, highest score
         first, one detected block per GT block, threshold ``MATCH_TAU``).
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

N=1 spread. This proves reading-order CORRECTNESS on one genuine multi-column
page; it does NOT by itself prove grouping DISCRIMINATION (see the single-figure
caveat) — that needs a fixture with >=2 figures sharing one column.

Usage:
    python -m tools.layout_order_eval --image it_geo_04 [--report docs/RESULTS.md]
    python -m tools.layout_order_eval --image it_geo_04 --json-out out.json
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
from tools.layout_ab import ocr_words, _word_box, _center_in
from pipeline import stage04_layout as S4
from pipeline.page_model import BBox

# Fraction of a GT anchor's tokens that must be present in a detected block's
# routed OCR text to accept the match. Anchors are 6-12 distinctive first-words;
# even garbled OCR keeps well over half, and the argmax block is unambiguous.
MATCH_TAU = 0.5


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

    Figures match by reading-order rank (i-th GT figure -> i-th detected figure,
    top-to-bottom); text blocks match by greedy anchor-token overlap on the
    remaining detected blocks. Each detected block is claimed at most once.
    """
    matched: dict[str, int] = {}
    used: set[int] = set()

    # Figures first (by reading_order rank), so a figure box can't be stolen by
    # a stray text-anchor overlap.
    gt_figs = [g for g in gt_blocks if g["type"] == "figure"]
    det_figs = sorted((d for d in det if d.btype == "figure"), key=lambda d: d.ro)
    for g, d in zip(sorted(gt_figs, key=lambda g: g["order"]), det_figs):
        matched[g["id"]] = d.idx
        used.add(d.idx)

    # Text blocks (paragraph/caption/heading/...) by anchor overlap, greedy.
    text_gt = [g for g in gt_blocks if g["type"] != "figure" and g.get("anchor")]
    cand = [(anchor_score(g["anchor"], d.text), g["id"], d.idx)
            for g in text_gt for d in det if d.idx not in used]
    cand.sort(reverse=True)
    for score, gid, didx in cand:
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
    groups: list[GroupResult]
    n_det_blocks: int
    n_header_det: int                  # detected header+page_number blocks
    n_stripped_gt: int

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


def grade_image(image_id: str, testset: Path, cfg: dict, binary: str
                ) -> tuple[ImageGrade, dict]:
    gt_path = testset / "gt" / f"{image_id}.blocks.json"
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    if gt.get("gt_type") != "block_reading_order":
        raise ValueError(f"{gt_path} is not a block_reading_order GT")

    img_file = testset / f"{image_id}.jpg"
    tessdata = resolve_tessdata_dir(cfg)
    bgr, _ = NORM.load_upright_bgr(img_file, binary, tessdata)
    lang = lang_code(gt.get("language", "eng"))

    p = S4.resolve_params(cfg)
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
            det = _route_words(pl, words, scale)

            gt_blocks = gsub["reading_order"]
            matched, misses = match_subpage(gt_blocks, det)

            by_id = {g["id"]: g for g in gt_blocks}
            type_ok = {gid: det[di].btype == by_id[gid]["type"]
                       for gid, di in matched.items()}

            # Order: Stage 04 arm (all matched) + Tesseract-native arm (word-bearing).
            lay_pairs = [(by_id[gid]["order"], det[di].ro)
                         for gid, di in matched.items()]
            nat = [(by_id[gid]["order"], det[di].native_key)
                   for gid, di in matched.items() if det[di].native_key is not None]
            tau_layout = kendall_tau([(g, d) for g, d in lay_pairs])
            tau_native = kendall_tau([(g, d) for g, d in nat]) if len(nat) >= 2 else None

            sub_pairs = [pr for pr in pairs if pr.get("subpage") == sub]
            groups = grouping_eval(sub_pairs, matched, det)

            n_header = sum(1 for d in det if d.btype in ("header", "page_number"))
            grade.subpages.append(SubpageGrade(
                name=name, n_gt=len(gt_blocks), matched=matched, misses=misses,
                type_ok=type_ok, tau_layout=tau_layout, tau_native=tau_native,
                n_native=len(nat), groups=groups, n_det_blocks=len(det),
                n_header_det=n_header, n_stripped_gt=len(gsub.get("stripped", [])),
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


def build_report(grade: ImageGrade, tver: str, run_date: str) -> str:
    L: list[str] = []
    L.append(f"\n## Gate 3 block-order eval — {run_date}, tesseract {tver}, "
             f"image={grade.image_id}\n")
    L.append("Stage 04 block structure graded DIRECTLY against the per-subpage "
             f"block-order GT (`gt/{grade.image_id}.blocks.json`): segmentation, type, "
             "caption<->figure grouping, and linear order. Owner priority: "
             "segmentation/type/grouping OUTRANK exact order (tau is secondary). "
             "Split+dewarp = UVDoc auto (Gate-2 path). N=1 spread — read the rows.\n")
    L.append("| subpage | seg recall | type acc | tau (Stage04) | tau (Tess-native) | "
             "grouping | det blocks | misses |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in grade.subpages:
        grp = "; ".join(
            f"{g.caption_id}->{g.figure_id}:"
            f"{'assoc' if g.nearest_ok else 'MISS'}"
            f"{'' if g.caption_typed_ok else '/type!'}"
            f"{'/1fig' if g.n_figures == 1 else ''}"
            for g in s.groups) or "—"
        L.append(
            f"| {s.name} | {len(s.matched)}/{s.n_gt} ({s.seg_recall:.0%}) | "
            f"{sum(s.type_ok.values())}/{len(s.type_ok)} ({s.type_acc:.0%}) | "
            f"{_tau_str(s.tau_layout)} | {_tau_str(s.tau_native)} (n={s.n_native}) | "
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
    return "\n".join(L) + "\n"


def grade_to_json(grade: ImageGrade) -> dict:
    return {
        "image_id": grade.image_id,
        "subpages": [{
            "name": s.name, "n_gt": s.n_gt, "matched": s.matched,
            "misses": s.misses, "type_ok": s.type_ok,
            "seg_recall": s.seg_recall, "type_acc": s.type_acc,
            "tau_layout": s.tau_layout, "tau_native": s.tau_native,
            "n_native": s.n_native, "n_det_blocks": s.n_det_blocks,
            "n_header_det": s.n_header_det, "n_stripped_gt": s.n_stripped_gt,
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

    grade, extra = grade_image(args.image, args.testset, cfg, binary)
    report = build_report(grade, tver, datetime.date.today().isoformat())
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
