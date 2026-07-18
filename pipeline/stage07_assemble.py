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

Usage:
    python -m pipeline.stage07_assemble jobs/<job>/ [--force] [--debug]
                                        [--order-mode auto|review]
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
    Block, Document, DocPage, DocSettings, StageMeta, Word,
)
from pipeline import stage04_layout as S4
from pipeline import stage06_uncertainty as S6

STAGE = "stage07_assemble"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIRNAME = "document_assets"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ocr_language(page_dir: Path, default: str = "eng") -> str:
    """Best-effort source language for the spread: the ``lang`` Stage 05 ran with,
    read from ``05_ocr/meta.json``. Per-document language DETECTION is a future
    seam; for now we faithfully carry the OCR language forward."""
    meta = page_dir / "05_ocr" / "meta.json"
    if meta.exists():
        try:
            params = json.loads(meta.read_text(encoding="utf-8")).get("params", {})
            lang = params.get("lang")
            if isinstance(lang, str) and lang:
                return lang
        except (ValueError, OSError):
            pass
    return default


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
    """Whether an existing document carries human edits worth protecting."""
    if doc.settings.target_language:
        return True
    for pg in doc.pages:
        for blk in pg.blocks:
            if blk.structure_edited or blk.order_confirmed or blk.text is not None:
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
        order_mode: str = "auto") -> Document:
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

    for pd in page_dirs:
        resolved = S6.UncertaintyResult.model_validate_json(
            (pd / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
        modes_seen.add(resolved.mode)
        langs_seen.add(_ocr_language(pd))
        dewarp_dir = pd / "03_dewarp"
        uncertain_dir = pd / "06_uncertain"

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

            blocks = [_enrich_block(blk, patch_map) for blk in rp.blocks]
            n_blocks += len(blocks)
            n_words += sum(bool(w.text.strip()) for blk in blocks for w in blk.words)

            dp = DocPage(
                page_id=f"{pd.name}__{stem}",
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
              order_mode=args.order_mode)
    nword = sum(bool(w.text.strip()) for pg in doc.pages for blk in pg.blocks
                for w in blk.words)
    nflag = sum(w.flag_visible for pg in doc.pages for blk in pg.blocks
                for w in blk.words)
    print(f"{args.job_dir}: document.json + {ASSETS_DIRNAME}/ "
          f"({doc.settings.source_language}, mode={doc.settings.uncertainty_mode}, "
          f"order={doc.settings.order_mode})")
    print(f"  pages={len(doc.pages)} words={nword} flagged-visible={nflag}")
    for pg in doc.pages:
        print(f"  {pg.page_id}: blocks={len(pg.blocks)} img={pg.image_asset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
