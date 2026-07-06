"""Stage 06 — Uncertainty (adaptive per-document decision: keep / flag / patch).

This is the load-bearing stage of the whole pipeline. Because the OCR output
BECOMES the visible re-typeset document (not an invisible layer under a photo),
every recognition error the user can't see is an error they can't fix — so the
job of Stage 06 is to decide, per word, whether Tesseract's read is trustworthy
enough to emit plainly, or must be surfaced as uncertain.

**Adaptive threshold (CLAUDE.md non-negotiable — never a single global cutoff).**
Over all scored words of the document::

    threshold = clip( percentile(confs, flag_rate*100), conf_floor, conf_ceiling )
    uncertain(word) := word.conf < threshold   (OR a second engine disagrees)

``flag_rate`` (config, default 0.10) is a TARGET that BENDS with the document:
in a clean doc the ceiling bites — you flag fewer than flag_rate, only the
genuine low-conf tail; in a garbage doc the floor bites — you flag MORE. The
operating point moves with the confidence distribution between the two rails, so
it is adaptive per document, not one hard-coded gate. The raw + clamped threshold
and the effective flag rate are recorded in ``meta.json`` — that record is the
proof the threshold adapted. Rails (``conf_floor``/``conf_ceiling``) live in
``config.yaml`` and are anchored to real testset conf histograms, not invented
here.

**Cross-engine disagreement** is a second, independent uncertainty trigger
(CLAUDE.md). The EasyOCR Cyrillic second opinion is DEFERRED at Stage 05, so no
second engine exists yet; the disagreement path is a wired seam (a per-word
``disagree`` flag OR-ed into ``uncertain``) that fires only once a second engine
lands. A warning makes the gap visible rather than silently pretending the
trigger is active.

**Mode is a thin policy layer** on top of the single ``uncertain`` decision
(user-selectable, all three must exist — CLAUDE.md):
  * ``best_guess`` — every word KEEP (emit plainly); uncertainty is still computed
    and shown in the debug overlay, just not acted on.
  * ``flag`` — uncertain -> FLAG (Stage 07 renders a highlighted span).
  * ``patch`` — uncertain -> PATCH: crop the word's box from the FULL-RES dewarp
    (03_dewarp, NOT a downscaled copy — CLAUDE.md) into ``patches/`` for Stage 07
    to inline as a tiny ``<img>``.

Scope discipline (kept lean, like the other v0.1 stages): Stage 06 ONLY assigns
the per-word keep/flag/patch decision and cuts patch crops. De-hyphenation on
reflow and running-header / page-number stripping are Stage 07's job (config puts
them under ``reconstruct``); Stage 05 already laid ``line_id`` for the de-hyphen
pass. Nothing here strips or joins.

Contract (CLAUDE.md):
  * **Reads** ``05_ocr/ocr.json`` (blocks with words + raw conf) for the
    decisions, and — patch mode only — the dewarped subpage images it names from
    ``03_dewarp/`` for the crop pixels (word bboxes are already in 1x full-res
    dewarp coords, so no coordinate transform is needed).
  * **Writes** ``06_uncertain/resolved.json`` (the same blocks with each
    ``Word.decision`` set, plus a per-page patch manifest), ``06_uncertain/
    meta.json`` (mode, raw/clamped threshold, counts, effective rate), and
    ``debug/06_uncertain.png`` (words colored by DECISION + the threshold shown).
    Patch mode also fills ``06_uncertain/patches/`` (cleared on rerun).
  * Never modifies earlier artifacts; re-running overwrites only ``06_uncertain/``.

Per-document scope: a page folder is one spread (up to two subpages). The
threshold is pooled over BOTH subpages of the spread — "spread ~= document" for
now. A true whole-job threshold is a real seam: ``--threshold`` overrides the
computed value (and a job-level pass can inject one), so it is not a TODO.

Usage:
    python -m pipeline.stage06_uncertainty jobs/<job>/<page>/ \
        [--mode flag|best_guess|patch] [--threshold N] [--debug]
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field

from pipeline.page_model import Block, StageMeta, Word, WordDecision
from pipeline import stage04_layout as S4
from pipeline import stage05_ocr as S5

STAGE = "stage06_uncertainty"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Below this many scored words the percentile is unreliable (a mostly-figure or
# near-empty spread); fall back to the floor rail — flag only clearly-bad words.
MIN_WORDS_FOR_PERCENTILE = 20

# Decision colors for the debug overlay (BGR): keep=green, flag=amber, patch=red.
DECISION_COLOR = {
    WordDecision.KEEP: (80, 200, 80),
    WordDecision.FLAG: (0, 190, 255),
    WordDecision.PATCH: (60, 60, 235),
}


# --------------------------------------------------------------------------
# Output schema (stage-local wrapper; blocks/words are page_model types)
# --------------------------------------------------------------------------


class PatchRef(BaseModel):
    """One patch crop written for a PATCH-decision word (patch mode only)."""

    file: str                 # path relative to resolved.json's dir (06_uncertain/),
                              # e.g. patches/left_b3_w07.png — Stage 07 joins it there
    text: str                 # the OCR text the crop replaces (for provenance/debug)
    conf: float
    block_id: int
    word_index: int           # index of the word within its block's word list
    bbox: S4.BBox             # 1x full-res dewarp coords (the crop's source box)


class ResolvedPage(BaseModel):
    """Per-subpage result: Stage 04/05 blocks with each word's decision set."""

    name: str                 # left.png | right.png | single.png
    width: int
    height: int
    counts: dict[str, int] = Field(default_factory=dict)  # keep/flag/patch/uncertain
    blocks: list[Block] = Field(default_factory=list)
    patches: list[PatchRef] = Field(default_factory=list)


class UncertaintyResult(BaseModel):
    """Contents of ``06_uncertain/resolved.json``."""

    source: str = "05_ocr/ocr.json"
    mode: str                 # flag | best_guess | patch
    threshold: float          # clamped per-document threshold actually applied
    threshold_raw: float      # pre-clamp percentile (or -1 if the fallback was used)
    flag_rate_target: float
    conf_floor: float
    conf_ceiling: float
    scored_words: int         # words that fed the percentile
    counts: dict[str, int] = Field(default_factory=dict)  # doc-level totals
    pages: list[ResolvedPage] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Pure decision logic (IO-free — unit-tested directly)
# --------------------------------------------------------------------------


def is_scored(w: Word) -> bool:
    """Whether a word feeds the adaptive-threshold percentile.

    Empty/whitespace tokens and the conf<=0 Tesseract sentinel would skew the
    distribution, so they are excluded from the percentile — but they are STILL
    assigned a decision downstream (a real-text conf<=0 word is maximally
    uncertain and the ``conf < threshold`` rule flags it naturally).
    """
    return bool(w.text.strip()) and w.conf > 0.0


def adaptive_threshold(confs: list[float], flag_rate: float,
                       lo: float, hi: float) -> tuple[float, float]:
    """The adaptive per-document threshold.

    Returns ``(threshold, threshold_raw)`` where ``threshold_raw`` is the raw
    percentile before clamping (or -1.0 when the small-sample fallback fired).
    With too few scored words the percentile is unreliable -> fall back to the
    floor rail (flag only clearly-bad words). ``lo <= threshold <= hi`` always.
    """
    n = len(confs)
    if n < MIN_WORDS_FOR_PERCENTILE:
        return lo, -1.0
    raw = float(np.percentile(np.asarray(confs, dtype=float), flag_rate * 100.0))
    return float(min(max(raw, lo), hi)), raw


def is_uncertain(w: Word, threshold: float) -> bool:
    """A word is uncertain iff its confidence is below the adaptive threshold OR a
    second engine disagreed. The disagreement term is a wired seam: Stage 05 emits
    no second-engine field yet, so it is always False here — but the OR keeps the
    trigger structurally present for when EasyOCR (or a VLM) lands.
    """
    disagree = getattr(w, "engine_disagree", False)  # future second-engine seam
    return w.conf < threshold or bool(disagree)


def decide(w: Word, threshold: float, mode: str) -> WordDecision:
    """Map a word to its keep/flag/patch decision under the chosen mode.

    Mode is a thin policy layer over the single ``is_uncertain`` decision. Empty
    tokens are inert KEEP (Stage 07 drops them); nothing to flag or crop.
    """
    if not w.text.strip():
        return WordDecision.KEEP
    if not is_uncertain(w, threshold):
        return WordDecision.KEEP
    if mode == "best_guess":
        return WordDecision.KEEP
    if mode == "patch":
        return WordDecision.PATCH
    return WordDecision.FLAG  # "flag" (default)


def resolve_mode(cfg: dict, override: str | None) -> str:
    valid = {"flag", "best_guess", "patch"}
    if override:
        if override not in valid:
            raise ValueError(f"unknown --mode {override!r}; choose one of {sorted(valid)}")
        return override
    return (cfg.get("uncertainty", {}) or {}).get("default_mode", "flag")


def resolve_rails(cfg: dict) -> tuple[float, float, float]:
    """(flag_rate, conf_floor, conf_ceiling) from config, with safe defaults."""
    u = cfg.get("uncertainty", {}) or {}
    flag_rate = float(u.get("flag_rate", 0.10))
    lo = float(u.get("conf_floor", 45.0))
    hi = float(u.get("conf_ceiling", 75.0))
    if lo > hi:
        lo, hi = hi, lo
    return flag_rate, lo, hi


# --------------------------------------------------------------------------
# Patch crops — cut from the FULL-RES dewarp (CLAUDE.md), NOT a downscaled copy
# --------------------------------------------------------------------------

# A few px of padding so ascenders/descenders aren't clipped from the word crop.
PATCH_PAD = 3


def crop_patch(bgr: np.ndarray, box: S4.BBox, pad: int = PATCH_PAD) -> np.ndarray:
    """Crop a word box (1x full-res dewarp coords) with a little padding, clamped
    to the image. The word bbox comes from Stage 05 already in this exact space,
    so patch mode is the FIRST real exercise of that coordinate contract."""
    h, w = bgr.shape[:2]
    x0 = max(0, box.x - pad)
    y0 = max(0, box.y - pad)
    x1 = min(w, box.x2 + pad)
    y1 = min(h, box.y2 + pad)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), np.uint8)
    return bgr[y0:y1, x0:x1].copy()


# --------------------------------------------------------------------------
# Apply decisions to one subpage (pure over the block list; IO only for patches)
# --------------------------------------------------------------------------


def apply_decisions(page: S5.OCRPage, threshold: float, mode: str,
                    bgr: np.ndarray | None, patch_dir: Path | None
                    ) -> ResolvedPage:
    """Set every word's decision on a fresh copy of the blocks and, in patch mode,
    write the crop for each PATCH word. Returns the resolved page with counts and
    (patch mode) a patch manifest. Never mutates the Stage 05 objects."""
    # ``scored_flagged`` counts non-KEEP decisions restricted to SCORED words, so
    # the effective-rate diagnostic shares the percentile's denominator (conf<=0
    # words are flagged unconditionally at any threshold — they don't measure the
    # threshold's action, so mixing them into the rate would skew it).
    counts = {"keep": 0, "flag": 0, "patch": 0, "uncertain": 0, "scored_flagged": 0}
    out_blocks: list[Block] = []
    patches: list[PatchRef] = []
    stem = Path(page.name).stem

    for blk in page.blocks:
        words: list[Word] = []
        for wi, w in enumerate(blk.words):
            d = decide(w, threshold, mode)
            if w.text.strip() and is_uncertain(w, threshold):
                counts["uncertain"] += 1
                if is_scored(w):
                    counts["scored_flagged"] += 1
            nw = w.model_copy(update={"decision": d})
            words.append(nw)
            counts[d.value] += 1
            if d is WordDecision.PATCH and bgr is not None and patch_dir is not None:
                rel = f"patches/{stem}_b{blk.id}_w{wi:02d}.png"
                crop = crop_patch(bgr, w.bbox)
                cv2.imwrite(str(patch_dir / f"{stem}_b{blk.id}_w{wi:02d}.png"), crop)
                patches.append(PatchRef(file=rel, text=w.text, conf=w.conf,
                                        block_id=blk.id, word_index=wi, bbox=w.bbox))
        out_blocks.append(blk.model_copy(update={"words": words}))

    return ResolvedPage(name=page.name, width=page.width, height=page.height,
                        counts=counts, blocks=out_blocks, patches=patches)


# --------------------------------------------------------------------------
# Debug overlay — words colored by DECISION + the chosen threshold annotated
# --------------------------------------------------------------------------


def _decision_panel(bgr: np.ndarray, page: ResolvedPage, threshold: float,
                    mode: str, panel_w: int = 1100) -> np.ndarray:
    """One subpage: block outlines + every word box colored by its DECISION
    (green keep / amber flag / red patch), so where Stage 06 acted is visible at a
    glance. Contrast the Stage 05 overlay, which shows raw conf bands."""
    vis = bgr.copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    for blk in sorted(page.blocks, key=lambda b: b.reading_order):
        c = S4.TYPE_COLOR.get(blk.type, (200, 200, 200))
        cv2.rectangle(vis, (blk.bbox.x, blk.bbox.y),
                      (blk.bbox.x2, blk.bbox.y2), c, 1)
        for w in blk.words:
            if not w.text.strip():
                continue
            wc = DECISION_COLOR.get(w.decision or WordDecision.KEEP, (200, 200, 200))
            thick = 2 if (w.decision and w.decision is not WordDecision.KEEP) else 1
            cv2.rectangle(vis, (w.bbox.x, w.bbox.y),
                          (w.bbox.x2, w.bbox.y2), wc, thick)

    hh, ww = vis.shape[:2]
    s = panel_w / ww
    vis = cv2.resize(vis, (panel_w, max(1, int(hh * s))))
    banner = np.full((54, panel_w, 3), 30, np.uint8)
    cc = page.counts
    cv2.putText(banner,
                f"{page.name}: mode={mode} thr={threshold:.0f}  "
                f"keep={cc.get('keep', 0)} flag={cc.get('flag', 0)} "
                f"patch={cc.get('patch', 0)} (uncertain={cc.get('uncertain', 0)})",
                (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 220, 0), 2)
    return np.vstack([banner, vis])


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, mode: str | None = None,
        threshold_override: float | None = None, debug: bool = False
        ) -> UncertaintyResult:
    t0 = time.perf_counter()
    warnings: list[str] = []

    ocr_json = page_dir / "05_ocr" / "ocr.json"
    if not ocr_json.exists():
        raise FileNotFoundError(
            f"missing {ocr_json} — Stage 06 reads Stage 05's words. Run "
            f"stage05_ocr on this page first.")
    ocr = S5.OCRResult.model_validate_json(ocr_json.read_text(encoding="utf-8"))
    if not ocr.pages:
        raise RuntimeError(f"no pages in {ocr_json}; nothing to resolve.")

    mode_used = resolve_mode(cfg, mode)
    flag_rate, lo, hi = resolve_rails(cfg)

    # Pool scored confidences across BOTH subpages of the spread ("document").
    confs = [w.conf for pg in ocr.pages for blk in pg.blocks for w in blk.words
             if is_scored(w)]
    if threshold_override is not None:
        threshold, raw = float(threshold_override), -1.0
    else:
        threshold, raw = adaptive_threshold(confs, flag_rate, lo, hi)

    if len(confs) < MIN_WORDS_FOR_PERCENTILE and threshold_override is None:
        warnings.append(
            f"only {len(confs)} scored words (< {MIN_WORDS_FOR_PERCENTILE}) — "
            f"percentile unreliable, fell back to conf_floor={lo:g}.")

    # Disagreement trigger is a wired seam only — no second engine at Stage 05 yet.
    if (cfg.get("uncertainty", {}) or {}).get("disagreement_is_trigger", True):
        warnings.append(
            "cross-engine disagreement is configured as an uncertainty trigger, "
            "but no second engine runs yet (EasyOCR is deferred at Stage 05); the "
            "disagreement path is a wired seam that fires only once a second "
            "opinion lands. v0.1 uncertainty = confidence-vs-threshold alone.")

    # Patch mode needs pixels + a clean patches/ dir; other modes touch neither.
    out_dir = page_dir / "06_uncertain"
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_dir = out_dir / "patches"
    if patch_dir.exists():
        shutil.rmtree(patch_dir)          # clear stale crops on rerun
    dewarp_dir = page_dir / "03_dewarp"
    want_pixels = mode_used == "patch"
    if want_pixels:
        patch_dir.mkdir(parents=True, exist_ok=True)

    pages: list[ResolvedPage] = []
    panels: list[np.ndarray] = []
    totals = {"keep": 0, "flag": 0, "patch": 0, "uncertain": 0, "scored_flagged": 0}
    for pg in ocr.pages:
        bgr = None
        if want_pixels:
            src = dewarp_dir / pg.name
            bgr = cv2.imread(str(src), cv2.IMREAD_COLOR)
            if bgr is None:
                raise RuntimeError(
                    f"unreadable dewarp image for patch crop: {src}")
        rp = apply_decisions(pg, threshold, mode_used, bgr, patch_dir)
        for k in totals:
            totals[k] += rp.counts.get(k, 0)
        pages.append(rp)
        # Overlay pixels: reuse the dewarp if already loaded, else load for debug.
        vis_src = bgr
        if vis_src is None:
            vis_src = cv2.imread(str(dewarp_dir / pg.name), cv2.IMREAD_COLOR)
        if vis_src is not None:
            panels.append(_decision_panel(vis_src, rp, threshold, mode_used))

    result = UncertaintyResult(
        mode=mode_used, threshold=round(threshold, 2), threshold_raw=round(raw, 2),
        flag_rate_target=flag_rate, conf_floor=lo, conf_ceiling=hi,
        scored_words=len(confs), counts=totals, pages=pages)
    (out_dir / "resolved.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    if panels:
        debug_dir = page_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / "06_uncertain.png"), S4.build_debug(panels))

    total_ms = (time.perf_counter() - t0) * 1000.0
    # Effective rate = fraction of SCORED words the threshold flagged (same
    # denominator as the percentile; conf<=0 words excluded from both — see
    # apply_decisions). This is the honest "how hard did the threshold bite" number.
    eff_rate = totals["scored_flagged"] / len(confs) if confs else 0.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={
            "mode": mode_used,
            "flag_rate_target": flag_rate,
            "conf_floor": lo,
            "conf_ceiling": hi,
            "threshold_raw": round(raw, 2),
            "threshold_applied": round(threshold, 2),
            "threshold_override": threshold_override,
            "scored_words": len(confs),
            "effective_flag_rate": round(eff_rate, 4),
            "reads": ["05_ocr/ocr.json", "03_dewarp/<subpage images> (patch mode)"],
        },
        timings_ms={"total": round(total_ms, 1)},
        warnings=warnings + [
            "Adaptive per-document threshold = clip(percentile(conf, flag_rate*100), "
            "conf_floor, conf_ceiling), pooled over both subpages of the spread "
            "(spread ~= document; --threshold injects a true whole-job value). "
            "flag_rate is a bending target: clean doc -> ceiling bites (flag "
            "fewer); garbage doc -> floor bites (flag more). Raw + clamped "
            "threshold and effective rate are recorded above = the adaptation proof.",
            "Mode is a thin policy layer over one 'uncertain' decision: best_guess "
            "-> all KEEP; flag -> FLAG; patch -> crop from 03_dewarp full-res (NOT "
            "downscaled) into patches/. De-hyphenation + header/page-number "
            "stripping are Stage 07 (reconstruct), not here.",
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
        description="Stage 06 — uncertainty (adaptive keep/flag/patch decision)")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--mode", default=None, choices=["flag", "best_guess", "patch"],
                    help="uncertainty output mode; default from config "
                         "uncertainty.default_mode")
    ap.add_argument("--threshold", type=float, default=None,
                    help="inject a fixed confidence threshold (e.g. a whole-job "
                         "value), bypassing the per-spread adaptive computation")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = S4.load_config(args.config)
    result = run(args.page_dir, cfg, mode=args.mode,
                 threshold_override=args.threshold, debug=args.debug)
    c = result.counts
    print(f"{args.page_dir}: mode={result.mode} threshold={result.threshold:g} "
          f"(raw={result.threshold_raw:g}, floor={result.conf_floor:g}, "
          f"ceil={result.conf_ceiling:g}) over {result.scored_words} scored words")
    print(f"  keep={c.get('keep', 0)} flag={c.get('flag', 0)} "
          f"patch={c.get('patch', 0)} (uncertain={c.get('uncertain', 0)})")
    for pg in result.pages:
        extra = f" patches={len(pg.patches)}" if pg.patches else ""
        print(f"  {pg.name}: {pg.counts}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
