"""Stage 05 — OCR (words + confidence, Tesseract backbone).

Recognizes the WORDS of each dewarped half-page — text + bounding box + a raw
per-word confidence — and attaches them to the Stage 04 layout blocks in reading
order. This is the stage that turns pixels into the re-typeset document's actual
text; because that OCR output BECOMES the visible document (not an invisible
layer under a photo), the per-word confidence + geometry produced here are the
load-bearing signal every later stage rides on.

**Tesseract 5 is the confidence/bounding-box BACKBONE** (CLAUDE.md
non-negotiable): it is the sole source of word boxes and the calibratable
confidence. VLMs / Surya / EasyOCR may be layered on later as *second opinions*
for hard passages, but never as the sole text source or the confidence source
(no reliable word boxes, hallucination risk). The EasyOCR Cyrillic second
opinion is wired here only as a seam + note — deferred, not built (mirrors how
Stage 03/04 shipped the default arm first).

Stage 05 emits RAW confidence only. Adaptive per-document thresholds and the
keep/flag/patch decision are Stage 06's job (``Word.decision`` stays ``None``
here) — no confidence cutoff may leak into this stage.

Contract (CLAUDE.md). Stage 05 needs BOTH pixels and layout, so it reaches back
across two prior stages (unavoidable: OCR needs pixels; layout is pixel-free
metadata, and Stage 04 already set the reach-back precedent):
  * **Reads** ``04_layout/layout.json`` (blocks: type, bbox, reading_order) for
    the block structure, and the dewarped subpage images it names from
    ``03_dewarp/`` for the pixels. Image filenames come from the manifest — never
    hardcoded. Runs PER half-page.
  * **Writes** ``05_ocr/ocr.json`` (per subpage: the Stage 04 blocks with
    ``page_model.Word``s attached, plus synthetic OTHER blocks holding any words
    that fell outside every detected block), ``05_ocr/meta.json``, and
    ``debug/05_ocr.png`` (word boxes colored by confidence band + block
    outlines).
  * Never modifies earlier artifacts; re-running overwrites only ``05_ocr/``.

OCR path — the PROVEN probe-upscale path from Gate 1 / ``tools/layout_ab.py``,
reused so Stage 05 runs the SAME OCR path + params (oem/psm, probe threshold,
INTER_CUBIC upscale) as the Gate 3 A/B measurement — the words we ship track the
words we measured (Stage 05 reads Stage 03's persisted dewarp PNGs while the A/B
dewarps in-memory, so this is same-path, not bit-for-bit verified): OCR the whole
subpage once at 1x to measure median word height; if it is
under 20px, re-OCR at 2x (INTER_CUBIC) and map word boxes back to 1x. Word boxes
are stored in FULL-RES 1x dewarp coordinates — the same space as the Stage 04
blocks AND the space Stage 06 patch-mode crops from (CLAUDE.md: crop from the
full-res dewarp, NOT a downscaled copy); the ``/scale`` map-back therefore
happens before both routing and storage.

Word ROUTING + ORDER: each word routes to the smallest-area Stage 04 block whose
box contains the word's center; within a block words keep natural (line, word)
order. Stage 04's block ``reading_order`` is TRUSTED as-is when every word lands
in a block. Orphan words (in no block — a detection-coverage diagnostic) are
grouped into synthetic OTHER blocks and slotted into reading order by the SAME
recursive XY-Cut Stage 04 uses, so nothing is dropped and orphans land in their
geometric place. A word-conservation invariant is asserted: every recognized
word ends up in exactly one output block.

Usage:
    python -m pipeline.stage05_ocr jobs/<job>/<page>/ [--lang eng|bul|ita|deu] [--debug]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field

from pipeline.page_model import BBox, Block, BlockType, StageMeta, Word
from pipeline import stage04_layout as S4
from pipeline.second_opinion import (
    EasyOCRSecondOpinion, find_disagreements, load_lexicon)

# Pure, IO-free metrics + the Tesseract IO harness. Neither imports ``pipeline``,
# so there is no cycle and ``tools.gate1_harness`` stays independently runnable
# (CLAUDE.md). Reusing them (rather than re-implementing) keeps Stage 05's OCR on
# the same path as the Gate 1 / Gate 3 A/B — same oem/psm, same probe threshold,
# same INTER_CUBIC upscale — so shipped words track the measured words.
from tools import ocr_metrics as M
from tools.gate1_harness import (
    band_color, find_tesseract, lang_code, median_word_height,
    resolve_tessdata_dir, run_tesseract, tesseract_version, to_gray, upscale,
)

STAGE = "stage05_ocr"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Probe-upscale threshold: if median recognized word height (1x pass) is below
# this many pixels, re-OCR at 2x. Proven in Gate 1 / Gate 2 / layout_ab. Kept as
# a stage constant (a geometry heuristic), NOT an OCR-confidence threshold.
UPSCALE_MEDIAN_PX = 20.0
UPSCALE_FACTOR = 2.0


# --------------------------------------------------------------------------
# Output schema (stage-local wrapper; the blocks/words are page_model types)
# --------------------------------------------------------------------------


class OCRPage(BaseModel):
    """Per-subpage OCR: the Stage 04 blocks with words attached, in reading order.

    ``blocks`` includes the real Stage 04 blocks (empty-word blocks like FIGUREs
    are kept — Stage 07 crops them) plus any synthetic OTHER blocks holding
    orphan words. ``reading_order``/``id`` are 0-based and gapless over ALL blocks.
    """

    name: str                 # left.png | right.png | single.png
    width: int
    height: int
    language: str             # Tesseract lang code used (e.g. eng, bul, eng+bul)
    scale: float              # OCR upscale factor (1.0 or 2.0)
    engine: str = "tesseract"
    total_words: int = 0
    orphan_words: int = 0     # words that fell outside every Stage 04 block
    blocks: list[Block] = Field(default_factory=list)


class OCRResult(BaseModel):
    """Contents of ``05_ocr/ocr.json``."""

    source: str = "04_layout/layout.json"
    reads: list[str] = Field(
        default_factory=lambda: ["04_layout/layout.json", "03_dewarp/<subpage images>"])
    engine: str = "tesseract"
    pages: list[OCRPage] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Language resolution (explicit — never silently default to eng)
# --------------------------------------------------------------------------


def resolve_language(cfg: dict, override: str | None) -> str:
    """Pick the Tesseract lang code. ``--lang`` wins; else ``languages.default``
    from config.yaml. Unknown / already-code / multi-lang ("eng+bul") strings
    pass through unchanged. The pipeline has no per-page language label yet, so
    this is per-run; per-page language detection is a future seam."""
    if override:
        # Allow multi-lang like "eng+bul"; map each recognized part, keep the rest.
        return "+".join(lang_code(part) for part in override.split("+"))
    default = (cfg.get("languages", {}) or {}).get("default", "eng")
    return lang_code(default)


# --------------------------------------------------------------------------
# OCR one subpage — the proven probe-upscale path (identical to layout_ab)
# --------------------------------------------------------------------------


def ocr_subpage(binary: str, cfg: dict, bgr: np.ndarray, lang: str
                ) -> tuple[list[M.TWord], float]:
    """OCR a whole subpage once. Probe at 1x for median word height; if tiny text
    (< UPSCALE_MEDIAN_PX), re-OCR at 2x. Returns (words, scale). Word boxes are in
    the OCR image's coords (1x or upscaled) — callers map back via ``_word_box``."""
    tcfg = cfg.get("tesseract", {})
    tessdata = resolve_tessdata_dir(cfg)
    oem, psm = int(tcfg.get("oem", 1)), int(tcfg.get("psm", 3))
    gray = to_gray(bgr)
    probe = M.parse_tsv(run_tesseract(binary, gray, lang, tessdata, oem, psm))
    scale = (UPSCALE_FACTOR
             if 0 < median_word_height(probe) < UPSCALE_MEDIAN_PX else 1.0)
    words = M.parse_tsv(run_tesseract(binary, upscale(gray, scale), lang,
                                      tessdata, oem, psm))
    return words, scale


def _word_box(w: M.TWord, scale: float) -> BBox:
    """Map an OCR word box back to 1x full-res dewarp coords — the space of the
    Stage 04 blocks AND of Stage 06's patch crops. This ``/scale`` division is the
    load-bearing coordinate map: get it wrong and every patch-mode crop is offset.
    """
    return BBox(x=int(w.left / scale), y=int(w.top / scale),
                w=max(1, int(w.width / scale)), h=max(1, int(w.height / scale)))


def _center_in(box: BBox, wb: BBox) -> bool:
    cx, cy = wb.x + wb.w / 2.0, wb.y + wb.h / 2.0
    return box.x <= cx <= box.x2 and box.y <= cy <= box.y2


def _union(boxes: list[BBox]) -> BBox:
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x2 for b in boxes)
    y1 = max(b.y2 for b in boxes)
    return BBox(x=x0, y=y0, w=max(1, x1 - x0), h=max(1, y1 - y0))


# --------------------------------------------------------------------------
# Route words -> blocks, build page_model.Word, slot orphans (pure/testable)
# --------------------------------------------------------------------------


def attach_words(twords: list[M.TWord], blocks: list[Block], scale: float,
                 page_w: int, page_h: int, p: dict
                 ) -> tuple[list[Block], int]:
    """Attach recognized words to Stage 04 blocks in reading order.

    Each word routes to the smallest-area block containing its center; within a
    block words keep natural (line, word) TSV order. Orphans (no block) group by
    their TSV (block, par) paragraph into synthetic OTHER blocks. If there are no
    orphans, Stage 04's block ``reading_order`` is trusted verbatim; otherwise all
    blocks (real + synthetic) are re-ranked by the SAME XY-Cut Stage 04 uses, so
    real blocks keep their relative order and orphans land in geometric place.

    Returns ``(ordered_blocks, orphan_word_count)``. Word-conservation invariant:
    every input word ends up in exactly one output block (asserted by the caller).
    Emits RAW confidence + engine only — ``Word.decision`` stays None (Stage 06).
    """
    wboxes = [_word_box(w, scale) for w in twords]

    # Stable per-subpage line ids from the TSV (block, par, line) hierarchy —
    # useful for Stage 06 de-hyphenation (join line-end hyphen with next line).
    line_ids: dict[tuple[int, int, int], int] = {}

    def line_id_of(tw: M.TWord) -> int:
        key = (tw.block_num, tw.par_num, tw.line_num)
        return line_ids.setdefault(key, len(line_ids))

    def make_word(idx: int, block_id: int | None) -> Word:
        tw = twords[idx]
        return Word(text=tw.text, bbox=wboxes[idx],
                    conf=max(0.0, min(100.0, tw.conf)), engine="tesseract",
                    line_id=line_id_of(tw), block_id=block_id, decision=None)

    # Route each word -> smallest-area containing block index, or -1 (orphan).
    assign: list[int] = []
    for wb in wboxes:
        best, best_area = -1, None
        for bi, blk in enumerate(blocks):
            if _center_in(blk.bbox, wb):
                area = blk.bbox.w * blk.bbox.h
                if best_area is None or area < best_area:
                    best, best_area = bi, area
        assign.append(best)

    # Fresh copies of the real blocks (never mutate Stage 04's objects), each
    # collecting its routed words in original TSV order (== reading order).
    real: list[Block] = [
        Block(id=b.id, type=b.type, bbox=b.bbox, reading_order=b.reading_order,
              words=[])
        for b in blocks
    ]
    for wi, bi in enumerate(assign):
        if bi >= 0:
            real[bi].words.append(make_word(wi, blocks[bi].id))

    # Orphans -> synthetic OTHER blocks, grouped by TSV (block, par) paragraph.
    orphan_idx = [wi for wi, bi in enumerate(assign) if bi < 0]
    groups: dict[tuple[int, int], list[int]] = {}
    for wi in orphan_idx:
        tw = twords[wi]
        groups.setdefault((tw.block_num, tw.par_num), []).append(wi)
    synth: list[Block] = []
    for members in groups.values():
        members.sort()  # TSV order
        synth.append(Block(id=-1, type=BlockType.OTHER,
                           bbox=_union([wboxes[wi] for wi in members]),
                           reading_order=-1,
                           words=[make_word(wi, None) for wi in members]))

    # Order all blocks. No orphans -> trust Stage 04 exactly. Orphans -> re-rank
    # real+synthetic together by the same XY-Cut (real relative order preserved).
    if not synth:
        ordered = sorted(real, key=lambda b: b.reading_order)
    else:
        combined = real + synth
        order = S4.xy_cut_order([b.bbox for b in combined], p, page_w, page_h)
        ordered = [combined[i] for i in order]

    # Renumber id + reading_order gaplessly; sync each word's block_id.
    for rank, b in enumerate(ordered):
        b.id = rank
        b.reading_order = rank
        for w in b.words:
            w.block_id = rank

    return ordered, len(orphan_idx)


# --------------------------------------------------------------------------
# Debug overlay — word boxes by confidence band + block outlines
# --------------------------------------------------------------------------


def _ocr_panel(bgr: np.ndarray, page: OCRPage, panel_w: int = 1100) -> np.ndarray:
    """One subpage: block outlines (thin, numbered by reading order) + every word
    box colored by confidence band (green >=80, yellow >=50, red <50 — same bands
    as the Gate 1 overlay). Visual triage: red boxes are where Stage 06 will act."""
    vis = bgr.copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    for blk in sorted(page.blocks, key=lambda b: b.reading_order):
        c = S4.TYPE_COLOR.get(blk.type, (200, 200, 200))
        cv2.rectangle(vis, (blk.bbox.x, blk.bbox.y),
                      (blk.bbox.x2, blk.bbox.y2), c, 2)
        cv2.putText(vis, f"{blk.reading_order}:{blk.type.value[:4]}",
                    (blk.bbox.x + 6, blk.bbox.y + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, c, 3)
        for w in blk.words:
            wc = band_color(w.conf)
            cv2.rectangle(vis, (w.bbox.x, w.bbox.y),
                          (w.bbox.x2, w.bbox.y2), wc, 2)

    hh, ww = vis.shape[:2]
    s = panel_w / ww
    vis = cv2.resize(vis, (panel_w, max(1, int(hh * s))))
    banner = np.full((54, panel_w, 3), 30, np.uint8)
    cv2.putText(banner,
                f"{page.name}: {page.total_words} words "
                f"(orphans {page.orphan_words}) lang={page.language} scale={page.scale:g}",
                (14, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 220, 0), 2)
    return np.vstack([banner, vis])


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, lang: str | None = None, debug: bool = False
        ) -> OCRResult:
    t0 = time.perf_counter()
    p = S4.resolve_params(cfg)
    warnings: list[str] = []

    binary = find_tesseract(cfg)
    if not binary:
        raise RuntimeError(
            "Tesseract not found (set tesseract.binary in config.yaml, or install "
            "it + eng/bul/ita/deu traineddata via `python -m tools.setup_tessdata`)."
        )

    layout_json = page_dir / "04_layout" / "layout.json"
    if not layout_json.exists():
        raise FileNotFoundError(
            f"missing {layout_json} — Stage 05 reads Stage 04's blocks. Run "
            f"stage04_layout on this page first."
        )
    layout = S4.LayoutResult.model_validate_json(
        layout_json.read_text(encoding="utf-8"))
    if not layout.pages:
        raise RuntimeError(f"no pages in {layout_json}; nothing to OCR.")

    lang_code_used = resolve_language(cfg, lang)
    dewarp_dir = page_dir / "03_dewarp"     # pixels live here (layout is pixel-free)
    out_dir = page_dir / "05_ocr"
    out_dir.mkdir(parents=True, exist_ok=True)

    # EasyOCR second opinion — cross-engine disagreement is a CLAUDE.md
    # non-negotiable uncertainty trigger. Tesseract stays the sole text +
    # confidence source; EasyOCR only NOMINATES a valid dictionary word in place
    # of a Tesseract non-word (see second_opinion module doc + RESULTS.md
    # 2026-07-18: the raw diff was measured at ~0 precision on Cyrillic — the
    # dictionary tiebreaker is what makes the trigger usable). The trigger needs
    # BOTH (a) an enabled language and (b) a per-language lexicon. The lexicon
    # does not yet ship in the repo, so in production this seam is currently INERT
    # — and we do not load EasyOCR at all when it can flag nothing (wasted GPU).
    easy_cfg = (cfg.get("engines", {}) or {}).get("easyocr", {}) or {}
    easy_for = set(easy_cfg.get("enabled_for", []))
    lang_enabled = any(lc in easy_for for lc in lang_code_used.split("+"))
    lex_cfg = easy_cfg.get("lexicon", {}) or {}
    lex_paths = [REPO_ROOT / lex_cfg[lc] for lc in lang_code_used.split("+")
                 if lc in lex_cfg]
    lexicon = load_lexicon(lex_paths) if lex_paths else None
    run_second = lang_enabled and lexicon is not None
    second: EasyOCRSecondOpinion | None = None
    min_region_conf = float(easy_cfg.get("min_region_conf", 0.30))
    n_disagree = 0
    if run_second:
        second = EasyOCRSecondOpinion(
            easy_cfg.get("langs", ["en"]), gpu=bool(easy_cfg.get("gpu", True)))

    pages: list[OCRPage] = []
    panels: list[np.ndarray] = []
    t_ocr = time.perf_counter()
    for pl in layout.pages:
        src = dewarp_dir / pl.name
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"unreadable subpage image: {src}")
        h, w = img.shape[:2]

        twords, scale = ocr_subpage(binary, cfg, img, lang_code_used)
        ordered, n_orphan = attach_words(twords, pl.blocks, scale, w, h, p)

        # Word-conservation invariant: every recognized word in exactly one block.
        attached = sum(len(b.words) for b in ordered)
        if attached != len(twords):
            raise AssertionError(
                f"word conservation violated on {pl.name}: attached {attached} "
                f"!= recognized {len(twords)}")

        page = OCRPage(name=pl.name, width=w, height=h, language=lang_code_used,
                       scale=scale, total_words=len(twords),
                       orphan_words=n_orphan, blocks=ordered)

        # Second opinion: flag Tesseract words EasyOCR reads differently. Runs on
        # the SAME dewarp image as the words (coords already aligned). EasyOCR
        # regions are line-level, so alignment is token-sequence (see module doc).
        if second is not None:
            sub_words = [wd for b in page.blocks for wd in b.words]
            regions = second.regions(str(src))
            boxes = [(wd.bbox.x, wd.bbox.y, wd.bbox.w, wd.bbox.h) for wd in sub_words]
            texts = [wd.text for wd in sub_words]
            flagged = find_disagreements(
                boxes, texts, regions, min_region_conf, lexicon)
            for idx in flagged:
                sub_words[idx].engine_disagree = True
            n_disagree += len(flagged)

        pages.append(page)
        panels.append(_ocr_panel(img, page))
    if second is not None:
        second.close()
    ocr_ms = (time.perf_counter() - t_ocr) * 1000.0

    result = OCRResult(engine="tesseract", pages=pages)
    (out_dir / "ocr.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "05_ocr.png"), S4.build_debug(panels))

    total_ms = (time.perf_counter() - t0) * 1000.0
    tcfg = cfg.get("tesseract", {})
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={
            "language": lang_code_used,
            "tesseract_version": tesseract_version(binary),
            "oem": int(tcfg.get("oem", 1)),
            "psm": int(tcfg.get("psm", 3)),
            "upscale_median_px": UPSCALE_MEDIAN_PX,
            "upscale_factor": UPSCALE_FACTOR,
            "xy_gap_frac": p["xy_gap_frac"],
            "reads": ["04_layout/layout.json", "03_dewarp/<subpage images>"],
            "second_opinion": (
                {"engine": "easyocr", "langs": easy_cfg.get("langs", ["en"]),
                 "min_region_conf": min_region_conf,
                 "gate": "dictionary (norm(T) not in lexicon AND norm(E) in lexicon)",
                 "lexicon_words": len(lexicon), "words_flagged": n_disagree}
                if run_second else None),
        },
        timings_ms={"ocr": round(ocr_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + (
            [f"EasyOCR second opinion ran ({easy_cfg.get('langs', ['en'])}, region "
             f"conf floor {min_region_conf}, {len(lexicon)}-word lexicon): "
             f"{n_disagree} word(s) flagged engine_disagree — a Tesseract non-word "
             f"that EasyOCR replaced with a valid dictionary word (second, "
             f"independent Stage-06 trigger). Tesseract remains the sole text + "
             f"confidence source."]
            if run_second else
            [f"No second opinion: EasyOCR enabled_for={sorted(easy_for)} includes "
             f"this page's language ({lang_code_used}), but no per-language lexicon "
             f"is available (engines.easyocr.lexicon). The disagreement trigger's "
             f"dictionary gate is inert without it — EasyOCR was NOT loaded (its "
             f"pass would flag nothing). engine_disagree stays False. OWNER "
             f"DEPENDENCY: supply a lexicon to activate (see RESULTS.md 2026-07-18)."]
            if lang_enabled else
            [f"No second opinion: EasyOCR is enabled_for={sorted(easy_for)}, which "
             f"does not include this page's language ({lang_code_used}). "
             f"engine_disagree stays False (inert), not a dead seam."]
        ) + [
            "v0.1: Tesseract 5 backbone (TSV word rows). Word boxes stored in 1x "
            "full-res dewarp coords (== Stage 04 block coords == Stage 06 patch "
            "crop coords). Same OCR path + params as the Gate 3 A/B "
            "(probe-upscale, oem/psm) so shipped words track the measured words. "
            "The 2x-upscale coord map-back is unit-tested; both GT-set pages ran "
            "at scale=1 (word height >= 20px), so it is not yet exercised on real "
            "small-text pixels.",
            "RAW confidence only — adaptive thresholds + keep/flag/patch are "
            "Stage 06 (Word.decision is None here). Orphan words (outside every "
            "Stage 04 block) are kept in synthetic OTHER blocks slotted by XY-Cut; "
            "word conservation is asserted (no drops).",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage 05 — OCR (words + confidence, Tesseract backbone)")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--lang", default=None,
                    help="Tesseract lang code (eng|bul|ita|deu, or eng+bul); "
                         "default from config languages.default")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = S4.load_config(args.config)
    result = run(args.page_dir, cfg, lang=args.lang, debug=args.debug)
    print(f"{args.page_dir}: OCR engine={result.engine}")
    for pg in result.pages:
        print(f"  {pg.name}: {pg.total_words} words in {len(pg.blocks)} blocks "
              f"(orphans {pg.orphan_words}) lang={pg.language} scale={pg.scale:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
