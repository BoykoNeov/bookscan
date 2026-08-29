"""Stage 07 — Assemble (build the editable, job-level ``document.json``).

The owner changed the requirement: before finalizing to PDF, the pipeline must
save an **editable-by-the-program** document (to translate the text first, or to
auto-bake a PDF now and return later for edits). This stage produces that
artifact. Stage 08 (render) then turns it — and only it — into HTML/PDF, so the
render is a pure, re-runnable function of the editable document.

**This is the first JOB-LEVEL stage, deliberately OUTSIDE the per-page immutable
stage contract** (see ``docs/GATE4_SPEC.md``). Everything 00–06 is per-page and
never modified once written; the document is the whole job's mutable working
copy. The immutable per-page trace stays the source of record — assemble just
aggregates it into one editable file.

**Self-containment is a hard rule.** Stage 08 and the future visual editor read
ONLY ``document.json`` + ``document_assets/`` — never the per-page stage folders.
So a document saved months ago keeps rendering even after an upstream stage
re-runs (e.g. Stage 06 clears ``06_uncertain/patches/`` every run). Assemble
therefore COPIES into ``document_assets/``:
  * the dewarped page image of each subpage (``03_dewarp/<name>``) — needed so
    the editor can show each word in its original visual context, and word
    bboxes are already in this image's coordinate space (no transform);
  * every flag/patch crop named in Stage 06's patch manifest.
All references in ``document.json`` are relative paths into ``document_assets/``.

**Editable model** (types in ``page_model.py``). Reading unit is the PHYSICAL
page (subpage left/right/single), flattened in reading order across all spreads
of the job. Each word gets ``text_ocr`` set to its OCR read (provenance) so a
later edit/translation never destroys the source; each block records its
automatic ``type_auto``/``order_auto`` so a user override is reversible.

**Don't clobber edits.** If a ``document.json`` already exists AND carries edits
(any edited word, structure override, or a set target language), assemble
refuses to overwrite it unless ``--force`` — edits are precious; the per-stage
trace is always still there to re-assemble from.

Contract:
  * **Reads** every ``<job>/page_*/06_uncertain/resolved.json`` (+ the
    ``03_dewarp`` images and ``06_uncertain/patches`` crops they reference).
  * **Writes** ``<job>/document.json``, ``<job>/document_assets/`` (images),
    ``<job>/document.meta.json`` (StageMeta), and a job-level debug montage
    ``<job>/debug/07_assemble.png`` (assembled blocks + reading order per page).
  * Never modifies the per-page artifacts.

**Caption<->figure grouping happens here** (``pipeline/figure_grouping.py``).
CLAUDE.md requires a figure to be placed *with its caption as a single block in
reading order*, and that association cannot be derived at render time from
adjacency (it_geo_06's captions are a stack on the far side of the subpage whose
order does not track figure position). So assemble types the captions, reads the
printed numbers on both sides, pairs them — printed number first, guarded
geometry second, ABSTAIN when ambiguous — and records the result on the blocks
(``figure_ref``/``pair_source``). It runs BEFORE ``_enrich_block`` so an
automatic caption promotion lands in ``type_auto`` too and is never mistaken for
a user override. Stage 08 then floats the pair; the editor can correct it.

Usage:
    python -m pipeline.stage07_assemble jobs/<job>/ [--force] [--debug]
                                        [--order-mode auto|review]
                                        [--no-group-figures] [--no-figure-hires]
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from pipeline.page_model import (
    Block, BlockType, Document, DocPage, DocSettings, PairSource, StageMeta, Word,
)
from pipeline import figure_grouping as FG
from pipeline import figure_hires as FH
from pipeline import unreadable_panel as UP
from pipeline import stage04_layout as S4
from pipeline import stage06_uncertainty as S6
from tools.gate1_harness import find_tesseract

STAGE = "stage07_assemble"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIRNAME = "document_assets"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ocr_language(page_dir: Path, default: str = "eng") -> str:
    """Best-effort source language for the spread: the language Stage 05 ran with,
    read from ``05_ocr/meta.json``. Per-document language DETECTION is a future
    seam; for now we faithfully carry the OCR language forward.

    Stage 05 records this under ``params.language``; ``params.lang`` is accepted
    as a fallback for documents assembled from an older meta. (Reading only
    ``lang`` silently defaulted EVERY document to ``eng`` — caught by a real
    Italian run whose captions then failed to parse, since the caption keyword
    table is per-language.)"""
    meta = page_dir / "05_ocr" / "meta.json"
    if meta.exists():
        try:
            params = json.loads(meta.read_text(encoding="utf-8")).get("params", {})
            for key in ("language", "lang"):
                lang = params.get(key)
                if isinstance(lang, str) and lang:
                    return lang
        except (ValueError, OSError):
            pass
    return default


def _capture_frames(page_dir: Path, params: dict) -> list[FH.FrameIndex]:
    """This spread's captures, as searchable indices.

    STAGE-CONTRACT NOTE. Stage 07 otherwise reads ``03_dewarp`` and
    ``06_uncertain``; ``00_ingest`` is a third per-page folder, still upstream and
    still never written. It has to be this one: the extra pixels a figure needs
    exist ONLY in the frames as shot. Stage 01 folds them into ``anchor.png`` by
    warping them DOWN, which destroys exactly the resolution we came for, so
    reading the anchor instead would be reading the loss.
    """
    ing = page_dir / "00_ingest" / "ingest.json"
    if not ing.exists():
        return []
    try:
        frames = json.loads(ing.read_text(encoding="utf-8")).get("frames", [])
    except (ValueError, OSError):
        return []
    return [FH.FrameIndex(f["name"], page_dir / "00_ingest" / f["name"], params)
            for f in frames if (page_dir / "00_ingest" / f["name"]).exists()]


def _upgrade_figure(blk: Block, page_bgr: np.ndarray,
                    frames: list[FH.FrameIndex], params: dict,
                    assets_dir: Path, prefix: str) -> dict | None:
    """Point this figure at a sharper cut of itself, if one of the spread's own
    captures holds one. Returns the provenance it recorded, or None for "the page
    crop stays", which is the pre-existing behaviour and never an error."""
    if not frames:
        return None
    b = blk.bbox
    h, w = page_bgr.shape[:2]
    x0, y0, x1, y1 = max(0, b.x), max(0, b.y), min(w, b.x2), min(h, b.y2)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = page_bgr[y0:y1, x0:x1]
    got = FH.compose(crop, FH.candidates(crop, frames, params), params)
    if got is None:
        return None
    out, used = got
    name = f"{prefix}__fig{blk.id:03d}.png"
    if not cv2.imwrite(str(assets_dir / name), out):
        return None
    blk.figure_asset = f"{ASSETS_DIRNAME}/{name}"
    # The rectangle this asset is a picture OF. Stage 08 compares it against the
    # block's live bbox and falls back to the page crop when they differ — the
    # document is editable, and a resized figure must not be filled with a
    # high-resolution picture of its old outline.
    blk.figure_asset_box = b.model_copy()
    blk.figure_asset_scale = round(out.shape[1] / max(1, x1 - x0), 3)
    blk.figure_asset_source = ", ".join(s.frame for s in used)
    return {"scale": blk.figure_asset_scale,
            "size": [out.shape[1], out.shape[0]],
            "sources": [s.as_dict() for s in used]}


def _enrich_block(blk: Block, patch_map: dict[tuple[int, int], str]) -> Block:
    """Copy a resolved Block into an editable one: seed each word's ``text_ocr``
    provenance and (patch mode) ``patch_asset``, and record the block's automatic
    type/order so a later user override is reversible. Nothing is marked edited —
    assemble produces the pristine, not-yet-touched document."""
    words: list[Word] = []
    for wi, w in enumerate(blk.words):
        words.append(w.model_copy(update={
            "text_ocr": w.text,                       # provenance = the OCR read
            "edited": False,
            "patch_asset": patch_map.get((blk.id, wi)),
        }))
    return blk.model_copy(update={
        "words": words,
        "type_auto": blk.type,
        "order_auto": blk.reading_order,
        "structure_edited": False,
        "order_confirmed": False,
    })


def _document_has_edits(doc: Document) -> bool:
    """Whether an existing document carries human edits worth protecting.

    ``pair_source is USER`` is the caption<->figure analogue of ``order_confirmed``:
    a pairing the human set (or deliberately CLEARED — an unpair keeps the USER
    provenance with ``figure_ref=None``) is real work, and it is the ONLY signal
    for it. Keying on ``figure_ref`` being non-None instead would be wrong in both
    directions: a pristine auto-grouped document would read as edited and could
    never be re-assembled without --force, and a deliberate unpair would read as
    untouched and be silently discarded."""
    if doc.settings.target_language:
        return True
    for pg in doc.pages:
        for blk in pg.blocks:
            if blk.structure_edited or blk.order_confirmed or blk.text is not None:
                return True
            if blk.pair_source is PairSource.USER:
                return True
            if any(w.edited for w in blk.words):
                return True
    return False


# --------------------------------------------------------------------------
# Debug montage — assembled blocks + reading order per page (job-level)
# --------------------------------------------------------------------------


def _assemble_panel(bgr: np.ndarray, page: DocPage, panel_w: int = 1100) -> np.ndarray:
    """One assembled page: blocks outlined + numbered by reading order (type
    colored), words boxed amber where an uncertainty marker is still visible
    (owner's per-word rule) else green — the human-glance proof of what the
    editable document actually contains."""
    vis = bgr.copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    for blk in sorted(page.blocks, key=lambda b: b.reading_order):
        c = S4.TYPE_COLOR.get(blk.type, (200, 200, 200))
        cv2.rectangle(vis, (blk.bbox.x, blk.bbox.y), (blk.bbox.x2, blk.bbox.y2), c, 2)
        cv2.putText(vis, str(blk.reading_order), (blk.bbox.x + 4, blk.bbox.y + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, c, 3)
        for w in blk.words:
            if not w.text.strip():
                continue
            wc = (0, 190, 255) if w.flag_visible else (80, 200, 80)
            cv2.rectangle(vis, (w.bbox.x, w.bbox.y), (w.bbox.x2, w.bbox.y2), wc, 1)

    hh, ww = vis.shape[:2]
    s = panel_w / ww
    vis = cv2.resize(vis, (panel_w, max(1, int(hh * s))))
    banner = np.full((54, panel_w, 3), 30, np.uint8)
    nflag = sum(w.flag_visible for blk in page.blocks for w in blk.words)
    nword = sum(bool(w.text.strip()) for blk in page.blocks for w in blk.words)
    cv2.putText(banner,
                f"{page.page_id}: blocks={len(page.blocks)} words={nword} "
                f"flagged={nflag}  img={page.image_asset}",
                (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 220, 0), 2)
    return np.vstack([banner, vis])


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(job_dir: Path, cfg: dict, force: bool = False, debug: bool = False,
        order_mode: str = "auto", group_figures: bool = True,
        figure_hires: bool = True) -> Document:
    t0 = time.perf_counter()
    warnings: list[str] = []

    job_dir = job_dir.resolve()
    if not job_dir.is_dir():
        raise FileNotFoundError(f"job dir not found: {job_dir}")

    page_dirs = sorted(
        p for p in job_dir.iterdir()
        if p.is_dir() and (p / "06_uncertain" / "resolved.json").exists())
    if not page_dirs:
        raise RuntimeError(
            f"no page folders with 06_uncertain/resolved.json under {job_dir} — "
            f"run Stage 06 on this job's pages first.")

    doc_json = job_dir / "document.json"
    if doc_json.exists() and not force:
        existing = Document.model_validate_json(doc_json.read_text(encoding="utf-8"))
        if _document_has_edits(existing):
            raise RuntimeError(
                f"{doc_json} already exists and carries edits (translated / "
                f"reordered / corrected). Refusing to overwrite. Re-run with "
                f"--force to discard those edits and re-assemble from the pipeline.")

    assets_dir = job_dir / ASSETS_DIRNAME
    if assets_dir.exists():
        shutil.rmtree(assets_dir)      # rebuild is authoritative (edits already cleared)
    assets_dir.mkdir(parents=True)

    reco = cfg.get("reconstruct", {}) or {}
    modes_seen: set[str] = set()
    langs_seen: set[str] = set()
    pages: list[DocPage] = []
    panels: list[np.ndarray] = []
    n_blocks = n_words = n_patches = 0
    n_promoted = n_fig_numbers = n_pairs_number = n_pairs_geom = n_abstained = 0
    n_pairs_sole = 0

    # Corner-label OCR (figure_grouping's number arm) needs Tesseract; without it
    # the arm degrades to routed text and geometry still runs, so a missing binary
    # is a WARNING, never a failure — assemble must not become GPU/OCR-dependent.
    tess_bin = find_tesseract(cfg) if group_figures else None
    if group_figures and not tess_bin:
        warnings.append(
            "tesseract not found — caption<->figure grouping ran without the "
            "corner-label number arm (guarded geometry only). Set tesseract.binary "
            "in config.yaml to recover printed figure numbers.")

    hires_params = FH.resolve_params(cfg)
    hires_on = bool(figure_hires and hires_params.get("enabled", True))
    n_hires = 0
    hires_log: list[dict] = []

    for pd in page_dirs:
        resolved = S6.UncertaintyResult.model_validate_json(
            (pd / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
        modes_seen.add(resolved.mode)
        langs_seen.add(_ocr_language(pd))
        dewarp_dir = pd / "03_dewarp"
        uncertain_dir = pd / "06_uncertain"
        # The spread's own captures, indexed once and shared by both subpages —
        # SIFT detection is the cost here and a left/right pair asks the same
        # frames the same question. Built lazily: a page with no figure never
        # decodes a frame.
        frame_index = _capture_frames(pd, hires_params) if hires_on else []

        for rp in resolved.pages:                     # one per subpage (left/right/single)
            stem = Path(rp.name).stem                 # left | right | single
            # --- copy the dewarped page image (visual-context anchor) ---
            src_img = dewarp_dir / rp.name
            if not src_img.exists():
                raise RuntimeError(
                    f"missing dewarp image {src_img} for {pd.name}/{rp.name}; "
                    f"cannot make the document self-contained.")
            img_name = f"{pd.name}__{rp.name}"
            shutil.copy2(src_img, assets_dir / img_name)

            # --- copy patch crops, mapping (block_id, word_index) -> rel path ---
            patch_map: dict[tuple[int, int], str] = {}
            for pref in rp.patches:
                src_patch = uncertain_dir / pref.file
                if not src_patch.exists():
                    warnings.append(f"patch crop missing, skipped: {src_patch}")
                    continue
                dst_name = f"{pd.name}__{stem}__{Path(pref.file).name}"
                shutil.copy2(src_patch, assets_dir / dst_name)
                patch_map[(pref.block_id, pref.word_index)] = f"{ASSETS_DIRNAME}/{dst_name}"
                n_patches += 1

            # --- caption<->figure grouping (BEFORE _enrich_block) ------------
            # Order matters: _enrich_block seeds type_auto from type, so a
            # caption promoted here is recorded as the AUTOMATIC type and the
            # editor never mistakes it for a user override. Running it after
            # would leave type_auto='paragraph' next to type='caption'.
            page_id = f"{pd.name}__{stem}"
            grouped = rp.blocks
            if group_figures:
                page_bgr = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
                g = FG.group_figures(
                    FG.views_from_blocks(rp.blocks), page_h=rp.height,
                    page_w=rp.width,
                    lang=_ocr_language(pd), page_bgr=page_bgr, tess_bin=tess_bin,
                    params=(cfg.get("reconstruct", {}) or {}).get("grouping"))
                grouped = FG.apply_to_blocks(list(rp.blocks), g, page_id)
                n_promoted += len(g.promoted)
                n_fig_numbers += len(g.figure_numbers)
                n_pairs_number += g.n_by_number
                n_pairs_geom += g.n_by_geometry
                n_pairs_sole += g.n_by_sole_figure
                n_abstained += len(g.abstained)

            blocks = [_enrich_block(blk, patch_map) for blk in grouped]

            # --- higher-resolution figure assets (pipeline/figure_hires.py) ---
            # AFTER grouping, because grouping can re-type a block, and this pass
            # only ever looks at blocks that are FIGURE in the final document.
            if hires_on:
                page_bgr_h = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
                for blk in blocks:
                    if blk.type is not BlockType.FIGURE or page_bgr_h is None:
                        continue
                    up = _upgrade_figure(blk, page_bgr_h, frame_index,
                                         hires_params, assets_dir,
                                         f"{pd.name}__{stem}")
                    if up is None:
                        continue
                    n_hires += 1
                    hires_log.append({"page": page_id, "block": blk.id, **up})

            n_blocks += len(blocks)
            n_words += sum(bool(w.text.strip()) for blk in blocks for w in blk.words)

            dp = DocPage(
                page_id=page_id,
                source_spread=pd.name,
                subpage=stem,
                width=rp.width,
                height=rp.height,
                image_asset=f"{ASSETS_DIRNAME}/{img_name}",
                blocks=blocks,
            )
            pages.append(dp)
            if debug:
                bgr = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
                if bgr is not None:
                    panels.append(_assemble_panel(bgr, dp))

        # Both subpages are done with this spread's captures. Keep the SIFT
        # descriptors (cheap) but drop the decoded frames — a dozen 6 Mpx images
        # held across 25 spreads is gigabytes for nothing.
        for fi in frame_index:
            fi.release()

    # --- unreadable pictogram panels -> pictures (pipeline/unreadable_panel.py)
    # Runs here, over the WHOLE job, because its confidence reference is
    # "normal for this document" — a per-page reference would let a page that is
    # all panel declare itself normal. It only ever re-TYPES; block order is
    # untouched (de_01's panel is already correctly placed leftmost-first).
    panel_scan = UP.scan([dp.blocks for dp in pages],
                         params=(reco.get("unreadable_panels") or None))
    if panel_scan.converted:
        pages = [dp.model_copy(update={
                     "blocks": UP.apply_to_blocks(list(dp.blocks), panel_scan, pi)})
                 for pi, dp in enumerate(pages)]

    if len(modes_seen) > 1:
        warnings.append(
            f"pages were resolved under differing uncertainty modes {sorted(modes_seen)}; "
            f"the document records the first. Re-run Stage 06 uniformly if unintended.")
    if len(langs_seen) > 1:
        warnings.append(f"mixed OCR languages across pages {sorted(langs_seen)}; "
                        f"document source_language records the first.")

    settings = DocSettings(
        source_language=sorted(langs_seen)[0] if langs_seen else "eng",
        target_language=None,
        uncertainty_mode=sorted(modes_seen)[0] if modes_seen else "flag",
        order_mode=order_mode,
        strip_running_headers=bool(reco.get("strip_running_headers", True)),
        strip_page_numbers=bool(reco.get("strip_page_numbers", True)),
        fonts=list(reco.get("fonts", []) or []),
    )
    doc = Document(document_id=job_dir.name, job_id=job_dir.name,
                   settings=settings, pages=pages)
    doc_json.write_text(doc.model_dump_json(indent=2), encoding="utf-8")

    if debug and panels:
        debug_dir = job_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / "07_assemble.png"), S4.build_debug(panels))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={
            "pages": len(pages),
            "blocks": n_blocks,
            "words": n_words,
            "patches_copied": n_patches,
            "source_language": settings.source_language,
            "uncertainty_mode": settings.uncertainty_mode,
            "order_mode": settings.order_mode,
            "assets_dir": ASSETS_DIRNAME,
            # caption<->figure grouping (pipeline/figure_grouping.py). The bar is
            # ZERO WRONG pairs, so `abstained` is reported beside `pairs` — a
            # caption left unpaired is a deliberate outcome, not a silent gap.
            "group_figures": group_figures,
            # Higher-resolution figure assets (pipeline/figure_hires.py).
            # Every upgrade is listed with the gates that admitted it, so a
            # wrong picture can be traced to the frame it came from without
            # re-running anything.
            "figure_hires": hires_on,
            "figures_upgraded": n_hires,
            "figure_hires_sources": hires_log,
            "captions_promoted": n_promoted,
            "figure_numbers_read": n_fig_numbers,
            "pairs_by_number": n_pairs_number,
            "pairs_by_geometry": n_pairs_geom,
            "pairs_by_sole_figure": n_pairs_sole,
            "captions_abstained": n_abstained,
            # unreadable pictogram panels re-typed FIGURE so Stage 08 renders the
            # PIXELS instead of OCR noise. Adaptive: the cutoff is a fraction of
            # this job's own median text-block confidence, never a global number.
            "panel_reference_conf": panel_scan.reference_conf,
            "panels_considered": panel_scan.n_considered,
            "panels_as_pictures": panel_scan.n_converted,
            "reads": ["page_*/06_uncertain/resolved.json",
                      "page_*/03_dewarp/<subpage>", "page_*/06_uncertain/patches/"],
            "force": force,
        },
        timings_ms={"total": round(total_ms, 1)},
        warnings=warnings + [
            "document.json is JOB-LEVEL and MUTABLE — the user's editable working "
            "copy, deliberately outside the per-page immutable stage contract. "
            "Stage 08 render + the future editor read ONLY document.json + "
            f"{ASSETS_DIRNAME}/ (self-contained). Assemble refuses to overwrite an "
            "edited document without --force.",
        ],
    )
    (job_dir / "document.meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return doc


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage 07 — assemble the editable, job-level document.json")
    ap.add_argument("job_dir", type=Path, help="job folder, e.g. jobs/<job>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing document even if it carries edits")
    ap.add_argument("--order-mode", choices=["auto", "review"], default="auto",
                    help="reading-order handling: 'auto' trusts Stage 04's order; "
                         "'review' marks every block for editor confirm/correct before "
                         "reconstruction. Editor-review state only — no pipeline effect.")
    ap.add_argument("--no-figure-hires", action="store_true",
                    help="skip the higher-resolution figure pass; every figure is "
                         "then cropped from the dewarped page, as before it existed")
    ap.add_argument("--no-group-figures", action="store_true",
                    help="skip the caption<->figure grouping pass (caption typing + "
                         "printed-number/geometry pairing). Diagnostic escape hatch: "
                         "the document then carries no figure_ref and Stage 08 falls "
                         "back to adjacency-only grouping.")
    ap.add_argument("--debug", action="store_true",
                    help="also write debug/07_assemble.png (blocks + reading order)")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = S4.load_config(args.config)
    doc = run(args.job_dir, cfg, force=args.force, debug=args.debug,
              order_mode=args.order_mode, group_figures=not args.no_group_figures,
              figure_hires=not args.no_figure_hires)
    nword = sum(bool(w.text.strip()) for pg in doc.pages for blk in pg.blocks
                for w in blk.words)
    nflag = sum(w.flag_visible for pg in doc.pages for blk in pg.blocks
                for w in blk.words)
    print(f"{args.job_dir}: document.json + {ASSETS_DIRNAME}/ "
          f"({doc.settings.source_language}, mode={doc.settings.uncertainty_mode}, "
          f"order={doc.settings.order_mode})")
    print(f"  pages={len(doc.pages)} words={nword} flagged-visible={nflag}")
    for pg in doc.pages:
        caps = [b for b in pg.blocks if b.type is BlockType.CAPTION]
        paired = [b for b in caps if b.figure_ref is not None]
        print(f"  {pg.page_id}: blocks={len(pg.blocks)} img={pg.image_asset}")
        if caps:
            srcs = ",".join(sorted({b.pair_source.value for b in paired
                                    if b.pair_source})) or "-"
            print(f"      captions={len(caps)} paired={len(paired)} ({srcs}) "
                  f"unpaired={len(caps) - len(paired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
