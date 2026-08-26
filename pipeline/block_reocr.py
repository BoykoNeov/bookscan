"""Re-read a text block whose words the full-subpage OCR pass starved.

THE DEFECT. Stage 05 OCRs each dewarped half-page in one Tesseract pass at
``psm 3`` (automatic page segmentation) and routes the resulting words to the
Stage 04 blocks. On a multi-column page with figures between the columns, that
one pass sometimes mis-segments a region and returns a fraction of the words that
are plainly there. Measured on ``it_geo_07``-left, block #22 — the paragraph the
block-order GT calls ``T5right``, detected by Stage 04 at exactly its GT box:

    page pass (psm 3, whole subpage)  8 words  conf 77.5
        "In questo cont, esto acino Bellunese de el"
    this pass (psm 6, block crop)    21 words  conf 90.1
        "In questo contesto nel Bacino Bellunese si depone la Formazione di
         Igne (IGN), che include le peliti anossiche del Toarciano."

The pixels are sharp enough to read by eye, the block box is right, and the words
still did not reach the document. Because OCR output IS the visible document here
(CLAUDE.md), that is text a reader simply loses.

IT IS NOT A PARAMETER. Re-running the whole subpage at psm 4/6/11/12 does not
recover it (21/31/25/25 words in that region, all garbled — psm 6 on a
three-column page duplicates fragments). The win comes from the PAIR: the block's
own crop, read as one uniform block. So it needs a per-block pass, not a
different page-level setting.

ACCEPTANCE — a comparison, never a cutoff. A block's re-read replaces its routed
words only when it is better on BOTH counts at once: **more words AND mean
confidence no lower than the page pass gave**. There is no fixed confidence floor
anywhere in this module — Stage 05 must emit raw confidence and leave every
threshold to Stage 06 (CLAUDE.md), so the test is relative to what this same
block already scored. "More words" alone would be wrong: on ``de_01``-left #1 the
re-read returns 149 words at conf 93.3 against the page pass's 165 at 71.4 — a
clearly better read that this rule REJECTS because the count fell. That is a
deliberate scope limit, stated rather than hidden: this pass rescues STARVATION,
not GARBLING.

A block the page pass read as EMPTY (``conf_page`` 0.0) therefore accepts any
re-read at all. Three of the four such accepts in the corpus are real recoveries
(a caption reading "Piattaforma di Trento (in annegamento)" at conf 96.3, two page
numbers); the fourth is two junk tokens at conf 33.3. That is not silent: a
low-confidence word is exactly what Stage 06's flag/patch machinery exists to
act on, whereas a block with no words at all is invisible to it.

MEASURED (2026-08-26), graded against the block-order GT anchors — not against
this module's own opinion of itself. Over the 80 GT text blocks of all eight
fixtures, mean anchor recall rises **0.9202 -> 0.9423**, with **five blocks up and
zero down**; four of the five cross the harness's 0.5 match threshold, so
``it_geo_07`` T5right stops being a segmentation "miss". The rule was fitted and
graded on the same 163 blocks — see docs/RESULTS.md.

ORDER. This runs AFTER ``caption_eject``, deliberately: the caption that pass
recovers from inside a figure is itself starved (its italic "In questa pagina:
Figura N" header is the very line the subpage pass misses), and re-reading the
ejected block recovers it as WORDS. That closes ``caption_eject``'s own stated
limit, which used the header as acceptance evidence only.

WORD CONSERVATION. Unlike ejection, this pass does NOT preserve the invariant
"every recognized word ends in exactly one block" — it REPLACES a block's words
with a different read of the same pixels. Stage 05 asserts the amended invariant
(recognized - dropped + added) and records every rescued block in ``meta.json``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pipeline.page_model import BBox, Block, BlockType, Word
from tools import ocr_metrics as M
from tools.gate1_harness import run_tesseract, to_gray, upscale

DEFAULTS = {
    # On by default: measured a strict improvement against ground truth (five
    # blocks up, none down). The switch exists so the A/B behind that claim stays
    # runnable, not because the default is in doubt.
    "enabled": True,
    # Read the crop as ONE uniform block of text. This is the whole mechanism:
    # the page pass already tried automatic segmentation and that is what failed.
    "reocr_psm": 6,
    # No padding. Measured both ways over all 163 text blocks: pad 12 manufactures
    # two accepts that pad 0 does not make (both junk from a neighbour bleeding
    # in), and costs nothing real — every genuine recovery survives at pad 0,
    # including the it_geo_05 caption header, which looked like it might be a
    # bbox-tightness artifact and is not.
    "pad_px": 0,
    # Below this the crop is not a block of text and Tesseract's own guards are
    # unreliable on it. A geometry floor, not a confidence one.
    "min_side_px": 12,
    # Hand Tesseract the COLOUR crop, not the grayscale one the subpage pass
    # uses. This is a deliberate divergence from "same path as the page pass",
    # and it is measured: on it_geo_05-left's ejected caption the grayscale crop
    # reads 67 words at conf 90.9 and opens "?n questa pagina: Foa 2 pag", while
    # the colour crop reads 66 at 92.6 and opens "In questa pagina: Figura 2" —
    # so grayscale falls BELOW that block's page-pass confidence and the rescue
    # is refused, taking the caption header with it. Over the whole corpus the
    # colour crop rescues 5 GT-graded blocks against grayscale's 2, with no
    # regression either way (docs/RESULTS.md). Tesseract does its own
    # binarization and can use the colour channels to do it; the page pass
    # cannot benefit the same way because it was measured grayscale end-to-end.
    "colour_crop": True,
}

# Blocks this pass never touches. FIGURE words are labels printed inside artwork
# (or a caption ``caption_eject`` has already had its say about); replacing them
# with a uniform-block read of a picture is not what this measured.
SKIP_TYPES = frozenset({BlockType.FIGURE})


@dataclass
class RescueNote:
    """One accepted rescue, for ``meta.json`` provenance."""

    block_id: int
    block_type: str
    n_before: int
    n_after: int
    conf_before: float
    conf_after: float


def _mean_conf(words: list[Word]) -> float:
    return float(np.mean([w.conf for w in words])) if words else 0.0


def _reocr_block(img: np.ndarray, box: BBox, tess_bin: str, tessdata: str,
                 lang: str, oem: int, scale: float, p: dict) -> list[M.TWord]:
    """Read one block's crop as a uniform text block. Returns [] on any failure —
    a rescue that cannot run must leave the page exactly as it was."""
    h, w = img.shape[:2]
    pad = int(p["pad_px"])
    x0, y0 = max(0, box.x - pad), max(0, box.y - pad)
    x1, y1 = min(w, box.x2 + pad), min(h, box.y2 + pad)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0 or min(crop.shape[:2]) < int(p["min_side_px"]):
        return []
    src = crop if p["colour_crop"] else to_gray(crop)
    src = upscale(src, scale)
    try:
        tsv = run_tesseract(tess_bin, src, lang, tessdata, oem,
                            int(p["reocr_psm"]))
    except Exception:
        return []
    return M.parse_tsv(tsv)


def rescue_starved_blocks(blocks: list[Block], img: np.ndarray, tess_bin: str,
                          tessdata: str, lang: str, oem: int, scale: float,
                          next_line_id: int, p: dict | None = None
                          ) -> tuple[list[Block], list[RescueNote], int, int]:
    """Re-read every text block; keep the re-read only where it beats the page
    pass on word count AND mean confidence.

    ``scale`` is the subpage pass's own upscale factor, so a rescued word's box
    maps back to 1x full-res dewarp coords the same way ``_word_box`` does — the
    space Stage 04 blocks live in and Stage 06 patch-mode crops from.

    Returns ``(blocks, notes, n_dropped, n_added)``; ``blocks`` is mutated in
    place (the caller already owns fresh copies). ``next_line_id`` seeds line ids
    for rescued words so they cannot collide with the page pass's.
    """
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    notes: list[RescueNote] = []
    n_dropped = n_added = 0
    if not pp["enabled"]:
        return blocks, notes, 0, 0
    lid = next_line_id
    for blk in blocks:
        if blk.type in SKIP_TYPES:
            continue
        before_n = len(blk.words)
        before_conf = _mean_conf(blk.words)
        tw = _reocr_block(img, blk.bbox, tess_bin, tessdata, lang, oem, scale, pp)
        if len(tw) <= before_n:
            continue
        after_conf = float(np.mean([max(0.0, min(100.0, w.conf)) for w in tw]))
        if after_conf < before_conf:
            continue

        pad = int(pp["pad_px"])
        ox = max(0, blk.bbox.x - pad)
        oy = max(0, blk.bbox.y - pad)
        line_map: dict[tuple[int, int, int], int] = {}
        rescued: list[Word] = []
        for w in tw:
            key = (w.block_num, w.par_num, w.line_num)
            if key not in line_map:
                line_map[key] = lid
                lid += 1
            rescued.append(Word(
                text=w.text,
                bbox=BBox(x=int(w.left / scale) + ox, y=int(w.top / scale) + oy,
                          w=max(1, int(w.width / scale)),
                          h=max(1, int(w.height / scale))),
                conf=max(0.0, min(100.0, w.conf)), engine="tesseract",
                line_id=line_map[key], block_id=blk.id, decision=None))
        blk.words = rescued
        n_dropped += before_n
        n_added += len(rescued)
        notes.append(RescueNote(
            block_id=blk.id, block_type=blk.type.value, n_before=before_n,
            n_after=len(rescued), conf_before=round(before_conf, 1),
            conf_after=round(after_conf, 1)))
    return blocks, notes, n_dropped, n_added
