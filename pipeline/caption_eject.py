"""Recover a caption that is PRINTED INSIDE a figure's bounding box, so it stops
being swallowed by the figure crop (docs/FIGURE_SEPARATION_SCOPE.md §5).

THE DEFECT, and what it actually was. On it_geo_05-left the whole page is one
hand-drawn map and its caption C2 is printed on the drawing's pale margin, well
inside the figure box. §5 recorded this as "the detector emits no text detection
there at all... with no text detection there is no evidence to eject on", and
concluded it needed the caption to be DETECTED first. Measured 2026-08-10, that
premise is false: Tesseract finds **60 words at conf ~96** in exactly that region
— 58% of the subpage's words — and they read as the caption verbatim. They are not
even orphans. `attach_words` routes a word to the smallest-area block containing
its centre, and the only block there is the figure, so the caption text is
attached to the FIGURE. Stage 08 then renders a figure from "the crop, NOT its OCR
words" — so the caption is dropped from the document as text while surviving
inside the crop as pixels. Nothing needed detecting; the words were in
`document.json` the whole time, on the wrong block.

WHY THE HEADER STILL NEEDS A RE-OCR. The one thing genuinely missing is the small
italic header ("In questa pagina: Figura 2"), which the full-subpage psm-3 pass
does not recognise at all — the first line it finds is the bold body text below.
Re-OCR'ing just the cluster's region as a uniform block recovers it on 4/4
settings. That header is the ONLY acceptance evidence used here.

CONSERVATISM, and the measurement that sets the bar. Ejecting is destructive twice
over: it moves text out of a figure AND (via Stage 08) paints that region out of
the artwork. A figure legitimately full of lettering — a topographic map, a
geological section — must never be cut. So acceptance is NUMBER-FIRST exactly like
`figure_grouping`: a cluster is ejected only if a caption header parses, never on
density or alignment alone (those are guards ON TOP of the header, never an
alternative path to acceptance). Gate measured over every figure block of all 15
testset images: **50 figure blocks -> 6 clusters dense enough to qualify -> 1
header parses**, and that one is the defect. The other five (de_02's topographic
lettering, it_geo_02's geological-section labels) abstain, which is the whole
point.

WORD CONSERVATION IS PRESERVED. Ejection MOVES existing `Word` objects from the
figure block to a new caption block; it never creates or drops one, so Stage 05's
asserted invariant still holds. The re-OCR'd header is used as evidence only and
is deliberately NOT added as words — see the honest limit in docs/RESULTS.md.
"""
from __future__ import annotations

import subprocess
from collections import defaultdict

import cv2
import numpy as np

from pipeline import caption_parser as CP
from pipeline import stage04_layout as S4
from pipeline.page_model import BBox, Block, BlockType

DEFAULTS = {
    # A caption is a PARAGRAPH. A map label is not. Both floors were set from the
    # gate run: the five abstaining clusters are 8..35 words, so these do not
    # separate anything on their own — they only keep the (subprocess) re-OCR off
    # obvious non-candidates. The header parse is what actually decides.
    "min_words": 8,
    "min_lines": 3,
    # Line grouping: lines join a cluster when they overlap horizontally and sit
    # within this many line-heights of each other.
    "x_overlap_frac": 0.35,
    "line_gap_lines": 2.0,
    # The header sits ABOVE the first line the subpage pass recognised (that is
    # precisely why it was missed), so the re-OCR region is extended upward.
    "up_pad_lines": 3.0,
    "side_pad_px": 12,
    "reocr_scale": 2,
    "reocr_psm": 6,          # a uniform block of text
}


def _cluster_lines(words: list, p: dict) -> list[tuple[BBox, list]]:
    """Group a block's words into paragraph-like clusters (lines, then columns)."""
    lines: dict[int, list] = defaultdict(list)
    for w in words:
        lines[w.line_id].append(w)
    boxes = []
    for _lid, ws in sorted(lines.items()):
        boxes.append([min(w.bbox.x for w in ws), min(w.bbox.y for w in ws),
                      max(w.bbox.x2 for w in ws), max(w.bbox.y2 for w in ws), list(ws)])
    boxes.sort(key=lambda b: b[1])
    clusters: list[list] = []
    for b in boxes:
        for c in clusters:
            x_ov = min(c[2], b[2]) - max(c[0], b[0])
            line_h = max(1, b[3] - b[1])
            if (x_ov > p["x_overlap_frac"] * min(c[2] - c[0], b[2] - b[0])
                    and (b[1] - c[3]) < p["line_gap_lines"] * line_h):
                c[0], c[1] = min(c[0], b[0]), min(c[1], b[1])
                c[2], c[3] = max(c[2], b[2]), max(c[3], b[3])
                c[4].extend(b[4])
                break
        else:
            clusters.append([b[0], b[1], b[2], b[3], list(b[4])])
    return [(BBox(x=c[0], y=c[1], w=max(1, c[2] - c[0]), h=max(1, c[3] - c[1])), c[4])
            for c in clusters]


def _reocr(img: np.ndarray, box: BBox, tess_bin: str, tessdata: str,
           lang: str, up_pad: int, p: dict) -> str:
    """Re-read a cluster's region as one uniform text block, to recover the header
    the full-subpage pass missed. Returns "" on any failure — never raises."""
    h, w = img.shape[:2]
    x0 = max(0, box.x - p["side_pad_px"])
    x1 = min(w, box.x2 + p["side_pad_px"])
    y0 = max(0, box.y - up_pad)
    y1 = min(h, box.y2 + p["side_pad_px"])
    crop = img[y0:y1, x0:x1]
    if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
        return ""
    s = p["reocr_scale"]
    big = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY) if big.ndim == 3 else big
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        return ""
    cmd = [tess_bin, "stdin", "stdout", "-l", lang, "--psm", str(p["reocr_psm"])]
    if tessdata:
        cmd += ["--tessdata-dir", tessdata]
    try:
        proc = subprocess.run(cmd, input=buf.tobytes(), capture_output=True)
    except Exception:
        return ""
    return proc.stdout.decode("utf-8", "replace")


def header_number(text: str, lang: str) -> int | None:
    """The caption number, if the re-OCR'd text OPENS with a caption header.

    Anchored to the first few lines on purpose: 'Figura 12' occurring deep inside
    a paragraph is a cross-reference, not this block's own header.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i in range(min(4, len(lines))):
        for j in (1, 2, 3):            # the header may wrap over up to 3 short lines
            if i + j > len(lines):
                continue
            ref = CP.parse_caption(" ".join(lines[i:i + j]), lang)
            if ref is not None:
                return ref.number
    return None


def eject_inline_captions(blocks: list[Block], img: np.ndarray, tess_bin: str,
                          tessdata: str, lang: str, layout_p: dict,
                          page_w: int, page_h: int,
                          p: dict | None = None) -> tuple[list[Block], list[str]]:
    """Move captions printed inside a figure box out into their own CAPTION blocks.

    Returns ``(blocks, notes)``. ``blocks`` is re-ranked by the SAME XY-Cut Stage 04
    uses, so an ejected caption lands in geometric reading order rather than being
    appended. Words are MOVED, never created or dropped.
    """
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    notes: list[str] = []
    new_blocks: list[Block] = []
    changed = False

    for blk in blocks:
        if blk.type is not BlockType.FIGURE or len(blk.words) < pp["min_words"]:
            continue
        for box, ws in _cluster_lines(blk.words, pp):
            if len(ws) < pp["min_words"]:
                continue
            if len({w.line_id for w in ws}) < pp["min_lines"]:
                continue
            line_h = max(8, int(np.median([w.bbox.h for w in ws])))
            up_pad = int(pp["up_pad_lines"] * line_h)
            text = _reocr(img, box, tess_bin, tessdata, lang, up_pad, pp)
            num = header_number(text, lang)
            if num is None:
                continue
            # The ejected block spans the region the header was READ FROM, not just
            # the words: the header is above the first recognised line (that is why
            # the subpage pass missed it) and has no word boxes to union in. Take
            # the same upward extension the evidence came from — otherwise Stage 08
            # masks the caption body out of the figure crop and leaves "In questa
            # pagina: Figura 2" stranded on the artwork, which is the defect again.
            cap_box = BBox(x=box.x, y=max(0, box.y - up_pad),
                           w=box.w, h=box.h + min(box.y, up_pad))
            keep = {id(w) for w in ws}
            blk.words = [w for w in blk.words if id(w) not in keep]
            new_blocks.append(Block(id=-1, type=BlockType.CAPTION, bbox=cap_box,
                                    reading_order=-1, words=list(ws)))
            notes.append(
                f"ejected caption (Figura {num}) printed inside figure "
                f"{blk.bbox.x},{blk.bbox.y} {blk.bbox.w}x{blk.bbox.h}: "
                f"{len(ws)} words at {box.x},{box.y} {box.w}x{box.h}")
            changed = True

    if not changed:
        return blocks, notes

    combined = list(blocks) + new_blocks
    order = S4.xy_cut_order([b.bbox for b in combined], layout_p, page_w, page_h)
    ordered = [combined[i] for i in order]
    for rank, b in enumerate(ordered):
        b.id = rank
        b.reading_order = rank
        for w in b.words:
            w.block_id = rank
    return ordered, notes
