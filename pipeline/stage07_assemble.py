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

**Refreshing ONE spread (``--spread page_NNN``, v0.2.0).** Every repair the
operator has for a bad spread — a hand-drawn book box, a corrected page layout,
a re-run in another language — ends in re-running that page folder, and until
this existed the only way to get the new reading into the document was a full
re-assemble, which (with ``--force``) threw away every hand edit on EVERY page:
the fix for spread 2 cost the corrections on spreads 3-80. A refresh rebuilds
only the named spreads' pages and swaps them into the existing document; every
other page, the settings and the translation target are left exactly as saved.
The clobber guard narrows with it: it refuses only when the spreads BEING
REFRESHED carry edits (those refer to the old reading and cannot be carried
over), and ``--force`` then discards those and nothing else. A spread that is
not in the document yet (a page scanned after the first assemble) is inserted
in folder-name order. One honest difference from a full assemble: the
unreadable-panel pass still takes its "normal for this document" confidence
from the whole document, but from the document *as it now stands* (panels
already turned into pictures no longer count as text), and only the refreshed
pages are re-typed by it.

**Carrying hand edits across a refresh (``--carry-edits``, v0.3.0).** A refresh
of an edited spread used to be all or nothing: refuse, or ``--force`` and lose
every correction on it. That is right when the page was re-cropped (a new book
box moves every word box) and needlessly destructive when it was re-run and came
out the same (after a crash, or for a newer figure upgrade). ``carry`` copies
each edit onto the re-run page **only on an exact match** (``_carry_edits``):

* a page by ``page_id`` and only if its width and height are unchanged;
* a word edit when the re-run has a word with the same block box, the same word
  box and the same original reading (``text_ocr``);
* a block's edits (type, deleted, surface mark, text override, order
  confirmation, a hand-set caption pair) when the re-run has a block with the
  same box, the same automatic type and the same automatic order; a hand pair is
  carried only if the picture it names was matched too, and is re-pointed at
  that picture's new id;
* a hand-set reading order only when old and new pages match block for block —
  one drag renumbers the whole page, so it is one edit of the page, not of a
  block. Otherwise the page keeps the automatic order and that is reported.

A split or a merged picture changes a block's box, so it does not match and is
reported as not carried — never replayed. Nothing is matched by text alone, by
"a few pixels", or by position in a list: a carried edit on the wrong word is a
silent wrong correction, a dropped one is a visible loss the operator can redo.
Pipeline fields (picture assets, plate numbers, ...) are never copied — picking
up a newer picture is one reason to refresh. ``carry`` REFUSES if anything would
be dropped, and changes nothing on disk; ``carry`` with ``--force`` carries what
matches and drops the rest. The report goes into this refresh's record in
``document.meta.json``. One deviation from the hand-off plan
(``docs/plans/handoff-2026-11-12.md`` item 1, which said "before
``_merge_pages``"): the carry runs AFTER the unreadable-panel pass, because that
pass rewrites ``type``/``type_auto`` and clears a pair on the blocks it converts
— carried first, an edit there would be wiped; matched first, every converted
panel would look changed.

**A failed assemble leaves the old document whole.** Assets are built in a
staging folder and swapped in only after every page assembled; ``document.json``
is written to a temp file and renamed. Before v0.2.0 ``document_assets/`` was
deleted first, so an assemble that died on page 40 left the previous
``document.json`` pointing at images that no longer existed.

**Pages that are not in the document are named, not silently dropped**
(``page_readiness``): a page folder with no Stage 06 output is listed as
missing, and a page whose LAST run failed but which still has an earlier run's
Stage 06 output is listed as stale (it is still assembled — a flag, not a
deletion — but its image and its word boxes may come from different runs).

Usage:
    python -m pipeline.stage07_assemble jobs/<job>/ [--force] [--debug]
                                        [--order-mode auto|review]
                                        [--spread page_NNN ... [--carry-edits]]
                                        [--no-group-figures] [--no-figure-hires]
                                        [--no-figure-surface]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from pipeline.page_model import (
    Block, BlockRef, BlockType, Document, DocPage, DocSettings, PairSource,
    StageMeta, Word, page_dir_sort_key,
)
from pipeline import figure_grouping as FG
from pipeline import figure_hires as FH
from pipeline import figure_surface as FS
from pipeline import unreadable_panel as UP
from pipeline import stage04_layout as S4
from pipeline import stage06_uncertainty as S6
from tools.gate1_harness import find_tesseract

STAGE = "stage07_assemble"
VERSION = "0.3.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIRNAME = "document_assets"
STAGING_DIRNAME = "document_assets.staging"
_PAGE_DIR_RE = re.compile(r"^page_\d+$")


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
    return any(_page_has_edits(pg) for pg in doc.pages)


def _page_has_edits(pg: DocPage) -> bool:
    """The per-page half of ``_document_has_edits`` — what a refresh of this
    page's spread would discard. Keep in lockstep with ``pipeline.editor``."""
    for blk in pg.blocks:
        if blk.structure_edited or blk.order_confirmed or blk.text is not None:
            return True
        if blk.pair_source is PairSource.USER:
            return True
        if any(w.edited for w in blk.words):
            return True
    return False


class EditsWouldBeDropped(RuntimeError):
    """A ``carry`` refresh found hand edits it cannot place exactly on the re-run
    page; nothing was written. ``report`` is what ``_carry_edits`` returned."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def _box(b) -> tuple[int, int, int, int]:
    return (b.x, b.y, b.w, b.h)


def _block_has_edits(blk: Block) -> bool:
    """The block-level half of ``_page_has_edits`` (words are counted apart)."""
    return bool(blk.structure_edited or blk.order_confirmed or blk.text is not None
                or blk.pair_source is PairSource.USER)


def _block_key(blk: Block) -> tuple:
    return (_box(blk.bbox), blk.type_auto, blk.order_auto)


def _unique(items: list, key) -> dict:
    """``key(item) -> item`` for keys held by exactly ONE item. An ambiguous key
    matches nothing: two candidates is not an exact match."""
    idx: dict = {}
    dup: set = set()
    for it in items:
        k = key(it)
        if k in idx:
            dup.add(k)
        idx[k] = it
    for k in dup:
        del idx[k]
    return idx


def _order_edited(pg: DocPage) -> bool:
    return any(b.order_auto is None or b.reading_order != b.order_auto
               for b in pg.blocks)


def _describe_block_edit(blk: Block) -> str:
    what = []
    if blk.text is not None:
        what.append("text override")
    if blk.type_auto is not None and blk.type != blk.type_auto:
        what.append(f"type {blk.type_auto.value} -> {blk.type.value}")
    if blk.type_auto is None:
        what.append("block made by a split")
    if blk.deleted:
        what.append("deleted")
    if blk.structure_edited and blk.is_surface:
        what.append("marked as surface")
    if blk.order_confirmed:
        what.append("order confirmed")
    if blk.pair_source is PairSource.USER:
        what.append("caption paired by hand" if blk.figure_ref
                    else "caption unpaired by hand")
    return ", ".join(what) or "structure edited (box, order or merge)"


def _only_an_order_edit(blk: Block, rerun: Block) -> bool:
    """A block whose sole edit is its place in a hand-set order: its loss is the
    page's order item, not a block item of its own.

    Judged against its matched RE-RUN block: the surface mark has no automatic
    copy to compare with, and the pipeline sets it too, so "not marked" does
    not mean "untouched" — an operator who cleared the pipeline's mark leaves
    ``is_surface`` False, and only the re-run's True shows that was an edit."""
    return (blk.type_auto is not None and blk.type == blk.type_auto
            and not blk.deleted and blk.is_surface == rerun.is_surface
            and blk.text is None and not blk.order_confirmed
            and blk.pair_source is not PairSource.USER)


def _carry_edits(old_pages: list[DocPage], pages: list[DocPage],
                 refresh: list[str]) -> tuple[list[DocPage], dict]:
    """Copy the hand edits of the refreshed spreads' OLD pages onto their re-run
    pages, on an exact match only (module docstring). Walks the OLD edits, so an
    edit whose page vanished (``single`` re-split into ``left``/``right``) is
    reported, never lost in silence. Returns the page list with the refreshed
    pages replaced by edited copies, and the report."""
    report: dict = {"words_carried": 0, "words_dropped": 0, "blocks_carried": 0,
                    "blocks_dropped": 0, "orders_carried": 0, "orders_dropped": 0,
                    "dropped": []}
    old_ref = [p for p in old_pages if p.source_spread in refresh]
    new_by_id = {p.page_id: p.model_copy(deep=True) for p in pages
                 if p.source_spread in refresh}

    def page_problem(op: DocPage) -> str | None:
        np_ = new_by_id.get(op.page_id)
        if np_ is None:
            return "this page is not in the re-run (the spread was cut differently)"
        if (np_.width, np_.height) != (op.width, op.height):
            return (f"the page image changed size ({op.width}x{op.height} -> "
                    f"{np_.width}x{np_.height}), so every box moved")
        return None

    # Old block id -> its re-run block, per old page; built for every page first
    # because a hand pair may name a picture on the facing page.
    match: dict[str, dict[int, Block]] = {}
    for op in old_ref:
        if page_problem(op):
            match[op.page_id] = {}
            continue
        new_idx = _unique(new_by_id[op.page_id].blocks, _block_key)
        old_idx = _unique(op.blocks, _block_key)
        match[op.page_id] = {
            ob.id: new_idx[_block_key(ob)] for ob in op.blocks
            if ob.type_auto is not None and ob.order_auto is not None
            and _block_key(ob) in new_idx and _block_key(ob) in old_idx}

    def map_ref(ref: BlockRef | None) -> tuple[bool, BlockRef | None]:
        if ref is None:
            return True, None                          # a deliberate unpair
        if ref.page_id not in match:                   # a page this refresh keeps
            return True, ref
        nb = match[ref.page_id].get(ref.block_id)
        return (False, None) if nb is None else (
            True, BlockRef(page_id=ref.page_id, block_id=nb.id))

    def drop(kind: str, op: DocPage, why: str, **extra) -> None:
        report[f"{kind}s_dropped"] += 1
        report["dropped"].append({"kind": kind, "page_id": op.page_id, **extra,
                                  "why": why})

    for op in old_ref:
        problem = page_problem(op)
        m = match[op.page_id]
        np_ = new_by_id.get(op.page_id)

        # -- reading order: one edit of the whole page ----------------------
        order_carried = False
        if _order_edited(op):
            if problem is None and len(m) == len(op.blocks) == len(np_.blocks):
                for ob in op.blocks:
                    m[ob.id].reading_order = ob.reading_order
                order_carried = True
                report["orders_carried"] += 1
            else:
                drop("order", op, problem or (
                    "the page's blocks changed (a split, a merged picture, or a "
                    "different layout), so a hand-set order cannot be replayed"))

        # -- block-level edits ------------------------------------------------
        for ob in op.blocks:
            if not _block_has_edits(ob):
                continue
            nb = m.get(ob.id)
            if (problem is None and nb is not None and _order_edited(op)
                    and _only_an_order_edit(ob, nb)):
                # Its only edit is its place in the page's order: carried with
                # the order, or reported once as the page's order item. On a
                # page that is lost as a whole every edited block is listed.
                if order_carried:
                    nb.structure_edited = True
                continue
            if problem or nb is None:
                drop("block", op, problem or (
                    "no block with the same box, automatic type and automatic "
                    "order in the re-run (it moved, or was split or merged by hand)"),
                    block_id=ob.id, what=_describe_block_edit(ob))
                continue
            if ob.pair_source is PairSource.USER:
                ok, ref = map_ref(ob.figure_ref)
                if not ok:
                    drop("block", op, "the picture it is paired with is not in the "
                         "re-run", block_id=ob.id, what=_describe_block_edit(ob))
                    continue
                nb.figure_ref, nb.pair_source = ref, PairSource.USER
            if ob.text is not None:
                nb.text = ob.text
            if ob.order_confirmed:
                nb.order_confirmed = True
            if ob.structure_edited:
                nb.type, nb.deleted, nb.is_surface = ob.type, ob.deleted, ob.is_surface
                nb.structure_edited = True
            report["blocks_carried"] += 1

        # -- word edits -------------------------------------------------------
        def wkey(blk: Block, w: Word) -> tuple:
            return (_box(blk.bbox), _box(w.bbox), w.text_ocr)
        if problem:
            new_words: dict = {}
            old_words: dict = {}
        else:
            new_words = _unique([(nb, w) for nb in np_.blocks for w in nb.words],
                                lambda t: wkey(*t))
            old_words = _unique([(ob, w) for ob in op.blocks for w in ob.words],
                                lambda t: wkey(*t))
        for ob in op.blocks:
            for w in ob.words:
                if not w.edited:
                    continue
                k = wkey(ob, w)
                hit = (new_words.get(k)
                       if (w.text_ocr is not None and k in old_words) else None)
                if hit is None:
                    drop("word", op, problem or (
                        "no word with the same box and the same original reading "
                        "in the re-run"),
                        block_id=ob.id, text_ocr=w.text_ocr, text=w.text)
                    continue
                hit[1].text, hit[1].edited = w.text, True
                report["words_carried"] += 1

    out = [new_by_id.get(p.page_id, p) if p.source_spread in refresh else p
           for p in pages]
    return out, report


def page_readiness(job_dir: Path) -> dict[str, list[dict]]:
    """Which page folders an assemble would leave out, or take in stale.

    ``missing``: a ``page_NNN`` folder with no ``06_uncertain/resolved.json`` —
    never finished, or failed before Stage 06. Assemble skips it, and before
    this function existed it did so without a word: a 200-spread book with
    three failed pages produced a document that was simply three spreads short.

    ``stale``: the page HAS Stage 06 output but its last ``run_all.json`` says
    the run failed. ``run_all`` stops at the first failing stage and (by the
    stage contract) touches nothing else, so the later folders still hold an
    EARLIER run's output — possibly word boxes measured on a page image that
    Stage 03 has since replaced. Such a page is still assembled (a flag is not
    a deletion); the caller is told so it can say so.

    Reads only ``run_all.json`` — the pipeline's own summary. Whether a page is
    queued or running right now is the server's knowledge (``worker.json``),
    and the server adds it."""
    missing: list[dict] = []
    stale: list[dict] = []
    for pd in sorted((p for p in job_dir.iterdir()
                      if p.is_dir() and _PAGE_DIR_RE.match(p.name)),
                     key=lambda p: page_dir_sort_key(p.name)):
        failed_stage = None
        try:
            ra = json.loads((pd / "run_all.json").read_text(encoding="utf-8"))
            if isinstance(ra, dict) and ra.get("ok") is False:
                failed_stage = ra.get("failed_stage") or "unknown stage"
        except (OSError, ValueError):
            pass
        if not (pd / "06_uncertain" / "resolved.json").exists():
            missing.append({"page": pd.name, "failed_stage": failed_stage})
        elif failed_stage is not None:
            stale.append({"page": pd.name, "failed_stage": failed_stage})
    return {"missing": missing, "stale": stale}


def _most_common(values: list[str], default: str) -> str:
    """The value most pages carry; ties go to the alphabetically first so the
    answer never depends on folder iteration order."""
    if not values:
        return default
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda k: (-counts[k], k))[0]


def _merge_pages(existing: list[DocPage], fresh: list[DocPage],
                 spreads: list[str]) -> list[DocPage]:
    """Swap the refreshed spreads' pages into the existing page list.

    A spread already in the document is replaced where it stands (so a page
    order the document already has is never disturbed); a spread that is new to
    the document is inserted before the first spread whose folder name sorts
    after it — the order a full assemble would have given it."""
    fresh_by: dict[str, list[DocPage]] = {s: [] for s in spreads}
    for dp in fresh:
        fresh_by[dp.source_spread].append(dp)
    out: list[DocPage] = []
    placed: set[str] = set()
    for dp in existing:
        if dp.source_spread in fresh_by:
            if dp.source_spread not in placed:
                out.extend(fresh_by[dp.source_spread])
                placed.add(dp.source_spread)
            continue
        out.append(dp)
    for s in sorted(set(spreads) - placed, key=page_dir_sort_key):
        at = next((i for i, dp in enumerate(out)
                   if page_dir_sort_key(dp.source_spread) > page_dir_sort_key(s)),
                  len(out))
        out[at:at] = fresh_by[s]
    return out


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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
        figure_hires: bool = True,
        figure_surface: bool = True,
        only_spreads: list[str] | None = None,
        carry: bool = False) -> Document:
    """Assemble the whole job, or — with ``only_spreads`` — refresh just those
    ``page_NNN`` folders inside the existing document (module docstring).

    ``carry`` (refresh only) copies the refreshed spreads' hand edits onto the
    re-run pages where they match exactly, and raises ``EditsWouldBeDropped``
    — writing nothing — if any would be lost, unless ``force`` is also set."""
    t0 = time.perf_counter()
    warnings: list[str] = []

    job_dir = job_dir.resolve()
    if not job_dir.is_dir():
        raise FileNotFoundError(f"job dir not found: {job_dir}")

    page_dirs = sorted(
        (p for p in job_dir.iterdir()
         if p.is_dir() and (p / "06_uncertain" / "resolved.json").exists()),
        key=lambda p: page_dir_sort_key(p.name))
    if not page_dirs:
        raise RuntimeError(
            f"no page folders with 06_uncertain/resolved.json under {job_dir} — "
            f"run Stage 06 on this job's pages first.")

    doc_json = job_dir / "document.json"
    existing: Document | None = None
    refresh = sorted(set(only_spreads)) if only_spreads else []
    if refresh:
        if not doc_json.exists():
            raise RuntimeError(
                f"no {doc_json} to refresh a spread in — assemble the whole "
                f"job first (without --spread).")
        ready = {p.name for p in page_dirs}
        absent = [s for s in refresh if s not in ready]
        if absent:
            raise RuntimeError(
                f"cannot refresh {absent}: no 06_uncertain/resolved.json there "
                f"— run those pages through the pipeline first.")
        existing = Document.model_validate_json(doc_json.read_text(encoding="utf-8"))
        edited = sorted({pg.source_spread for pg in existing.pages
                         if pg.source_spread in refresh and _page_has_edits(pg)})
        if edited and not force and not carry:
            raise RuntimeError(
                f"{edited} carry edits in {doc_json} (corrected / reordered / "
                f"paired by hand). Refreshing them discards those edits — and "
                f"only those; the rest of the document is kept. Re-run with "
                f"--carry-edits to keep every edit that still matches the "
                f"re-run page exactly, or --force to discard them.")
        page_dirs = [p for p in page_dirs if p.name in refresh]
    elif carry:
        raise RuntimeError("--carry-edits applies to a refresh (--spread) only.")
    elif doc_json.exists() and not force:
        existing_full = Document.model_validate_json(
            doc_json.read_text(encoding="utf-8"))
        if _document_has_edits(existing_full):
            raise RuntimeError(
                f"{doc_json} already exists and carries edits (translated / "
                f"reordered / corrected). Refusing to overwrite. Re-run with "
                f"--force to discard those edits and re-assemble from the pipeline.")

    readiness = page_readiness(job_dir)
    for m in readiness["missing"]:
        if refresh:
            continue                    # a refresh makes no claim about other pages
        why = (f"its run failed at {m['failed_stage']}" if m["failed_stage"]
               else "it has not finished the pipeline")
        warnings.append(f"{m['page']} is NOT in the document: {why}.")
    for st in readiness["stale"]:
        if refresh and st["page"] not in refresh:
            continue
        warnings.append(
            f"{st['page']}: its last run FAILED at {st['failed_stage']}; the "
            f"document uses what an earlier run left, and the page image and "
            f"the word boxes may come from different runs. Re-run the page.")

    # Everything is built in a staging folder and swapped in only once every
    # page assembled, so a failure below leaves the previous document whole.
    live_assets_dir = job_dir / ASSETS_DIRNAME
    assets_dir = job_dir / STAGING_DIRNAME
    if assets_dir.exists():
        shutil.rmtree(assets_dir)      # a previous run died mid-build
    assets_dir.mkdir(parents=True)

    reco = cfg.get("reconstruct", {}) or {}
    modes_seen: set[str] = set()
    langs_seen: set[str] = set()
    page_modes: list[str] = []
    page_langs: list[str] = []
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
    surface_params = FS.resolve_params(cfg)
    surface_on = bool(figure_surface and surface_params.get("enabled", False))
    surface_log: list[dict] = []
    n_surface = 0
    n_hires = 0
    hires_log: list[dict] = []
    decode_failures: list[str] = []

    for pd in page_dirs:
        resolved = S6.UncertaintyResult.model_validate_json(
            (pd / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
        modes_seen.add(resolved.mode)
        langs_seen.add(_ocr_language(pd))
        page_modes.append(resolved.mode)
        page_langs.append(_ocr_language(pd))
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
            # Stage 06's boxes are in this image's pixels. If the sizes differ,
            # 03_dewarp was rewritten after 06_uncertain (a re-run that failed in
            # between) and every word box is in the wrong place.
            probe = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
            if probe is not None and (probe.shape[1], probe.shape[0]) != (rp.width, rp.height):
                warnings.append(
                    f"{pd.name}/{rp.name}: the flattened page is "
                    f"{probe.shape[1]}x{probe.shape[0]} px but its words were "
                    f"read on a {rp.width}x{rp.height} px page — the two come "
                    f"from different runs. Re-run the page.")

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

            # --- blocks that are not the book (pipeline/figure_surface.py) ---
            # AFTER the hires pass, so a block that is about to be dropped has
            # not also been rebuilt at close-up resolution first.
            if surface_on:
                page_bgr_s = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
                for blk in blocks:
                    if blk.type is not BlockType.FIGURE or page_bgr_s is None:
                        continue
                    flagged, sdiag = FS.is_surface(
                        page_bgr_s, blk.bbox.model_dump(), surface_params)
                    if not flagged:
                        continue
                    blk.is_surface = True
                    n_surface += 1
                    surface_log.append({"page": page_id, "block": blk.id,
                                        **sdiag})

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

        # A frame that failed to decode was skipped by every figure on this
        # spread. Say so: a missing candidate is invisible in the upgrade log
        # (refusing is the normal outcome), so without this line a decode
        # failure and "no capture holds this figure" read the same.
        for fi in frame_index:
            if fi.decode_failed:
                decode_failures.append(f"{pd.name}/00_ingest/{fi.name}")
                warnings.append(
                    f"figure_hires: {pd.name}/00_ingest/{fi.name} could not be "
                    f"decoded and was skipped for every figure on that spread")
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
    # On a refresh the reference comes from the whole document as it stands and
    # only the refreshed pages are re-typed (module docstring).
    if existing is not None:
        pages = _merge_pages(existing.pages, pages, refresh)
    panel_scan = UP.scan([dp.blocks for dp in pages],
                         params=(reco.get("unreadable_panels") or None))
    if panel_scan.converted:
        pages = [dp if (existing is not None and dp.source_spread not in refresh)
                 else dp.model_copy(update={
                     "blocks": UP.apply_to_blocks(list(dp.blocks), panel_scan, pi)})
                 for pi, dp in enumerate(pages)]

    # --- hand edits onto the re-run pages (after the panel pass: module docstring)
    carry_report: dict | None = None
    if existing is not None and carry:
        pages, carry_report = _carry_edits(existing.pages, pages, refresh)
        lost = carry_report["dropped"]
        if lost and not force:
            shutil.rmtree(assets_dir, ignore_errors=True)
            raise EditsWouldBeDropped(
                f"{len(lost)} hand edit(s) on {refresh} do not match the re-run "
                f"page exactly and would be lost "
                f"({carry_report['words_carried']} word and "
                f"{carry_report['blocks_carried']} block edit(s) would be kept). "
                f"Nothing was changed. Re-run with --force as well to keep what "
                f"matches and drop the rest.", carry_report)

    if len(modes_seen) > 1:
        warnings.append(
            f"pages were resolved under differing uncertainty modes {sorted(modes_seen)}; "
            f"the document records the one most pages used. Re-run Stage 06 "
            f"uniformly if unintended.")
    if len(langs_seen) > 1:
        warnings.append(f"mixed OCR languages across pages {sorted(langs_seen)}; "
                        f"document source_language records the one most pages used.")

    if existing is not None:
        # A refresh never touches the settings: the translation target, the
        # review mode and the strip toggles are the operator's.
        settings = existing.settings
        if modes_seen - {settings.uncertainty_mode}:
            warnings.append(
                f"refreshed spread(s) were resolved in mode {sorted(modes_seen)} "
                f"but the document is '{settings.uncertainty_mode}'.")
        doc = existing.model_copy(update={"pages": pages})
    else:
        settings = DocSettings(
            source_language=_most_common(page_langs, "eng"),
            target_language=None,
            uncertainty_mode=_most_common(page_modes, "flag"),
            order_mode=order_mode,
            strip_running_headers=bool(reco.get("strip_running_headers", True)),
            strip_page_numbers=bool(reco.get("strip_page_numbers", True)),
            fonts=list(reco.get("fonts", []) or []),
        )
        doc = Document(document_id=job_dir.name, job_id=job_dir.name,
                       settings=settings, pages=pages)

    # --- commit: assets first, then the document that points at them --------
    if existing is None:
        if live_assets_dir.exists():
            shutil.rmtree(live_assets_dir)
        os.replace(assets_dir, live_assets_dir)
    else:
        live_assets_dir.mkdir(parents=True, exist_ok=True)
        prefixes = tuple(f"{s}__" for s in refresh)
        for old in live_assets_dir.iterdir():
            if old.is_file() and old.name.startswith(prefixes):
                old.unlink()
        for new in assets_dir.iterdir():
            os.replace(new, live_assets_dir / new.name)
        shutil.rmtree(assets_dir, ignore_errors=True)
    _write_text_atomic(doc_json, doc.model_dump_json(indent=2))

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
            # Blocks the vision model twice called the surface the book was
            # lying on. Flagged, not deleted — see pipeline/figure_surface.py.
            "figure_surface": surface_on,
            "figure_surface_flagged": n_surface,
            "figure_surface_log": surface_log,
            "figures_upgraded": n_hires,
            "figure_hires_sources": hires_log,
            # Frames figure_hires could not decode. Each one was skipped for
            # every figure on its spread; an empty list is the claim that no
            # candidate went missing that way.
            "frame_decode_failures": decode_failures,
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
            # Page folders left out of the document, and ones taken in from an
            # earlier run because the last run failed (page_readiness).
            "pages_missing": readiness["missing"],
            "pages_stale": readiness["stale"],
            # Non-empty = this run REFRESHED these spreads inside an existing
            # document; every count above is then for those spreads only.
            "refreshed_spreads": refresh,
            # What --carry-edits kept and dropped (None: not asked to carry).
            "carry_edits": carry_report,
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
    meta_path = job_dir / "document.meta.json"
    if refresh:
        # Keep the full assemble's record (it is what traces a wrong picture to
        # its frame for every OTHER spread) and append this refresh to it.
        try:
            base = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(base, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            base = {"stage": STAGE, "version": VERSION, "params": {},
                    "timings_ms": {}, "warnings": []}
        base.setdefault("params", {}).setdefault("refreshes", []).append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": VERSION,
            "params": meta.params, "warnings": warnings,
        })
        _write_text_atomic(meta_path, json.dumps(base, indent=2, ensure_ascii=False))
    else:
        _write_text_atomic(meta_path, meta.model_dump_json(indent=2))
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
    ap.add_argument("--no-figure-surface", action="store_true",
                    help="skip the 'is this block the sofa?' pass, even if "
                         "config enables it; every block is then kept, as "
                         "before it existed")
    ap.add_argument("--no-group-figures", action="store_true",
                    help="skip the caption<->figure grouping pass (caption typing + "
                         "printed-number/geometry pairing). Diagnostic escape hatch: "
                         "the document then carries no figure_ref and Stage 08 falls "
                         "back to adjacency-only grouping.")
    ap.add_argument("--spread", action="append", default=None, metavar="page_NNN",
                    help="refresh only this spread inside the EXISTING document, "
                         "keeping every other page and its edits (repeatable). "
                         "--force then discards edits on these spreads only.")
    ap.add_argument("--carry-edits", action="store_true",
                    help="with --spread: keep each hand edit whose word or block "
                         "is exactly where it was in the re-run page; refuse "
                         "(changing nothing) if any would be lost, unless --force")
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
              figure_hires=not args.no_figure_hires,
              figure_surface=not args.no_figure_surface,
              only_spreads=args.spread, carry=args.carry_edits)
    if args.carry_edits:
        meta = json.loads((args.job_dir / "document.meta.json").read_text(encoding="utf-8"))
        cr = meta["params"]["refreshes"][-1]["params"]["carry_edits"] or {}
        print(f"  edits carried: {cr.get('words_carried', 0)} word(s), "
              f"{cr.get('blocks_carried', 0)} block(s), "
              f"{cr.get('orders_carried', 0)} page order(s); "
              f"dropped: {len(cr.get('dropped', []))}")
        for d in cr.get("dropped", []):
            print(f"    DROPPED {d['kind']} on {d['page_id']}: {d['why']}")
    for label, rows in page_readiness(args.job_dir.resolve()).items():
        for r in rows:
            print(f"  WARNING {r['page']}: "
                  + ("not in the document" if label == "missing"
                     else "assembled from an earlier run")
                  + (f" (last run failed at {r['failed_stage']})"
                     if r["failed_stage"] else " (pipeline not finished)"))
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
