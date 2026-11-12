"""Spread-refresh check: does refreshing ONE spread inside an assembled document
leave everything else exactly as the operator saved it — and give that spread
exactly what a full assemble would?

``stage07_assemble --spread page_NNN`` (v0.2.0) rebuilds only the named spread's
pages and swaps them into the existing ``document.json``. The claim has two
halves, and the second is the control:

1. **nothing else moves** — after a hand edit on one spread and a translation
   target on the document, refreshing a *different* spread leaves every other
   page, the settings and every other asset identical;
2. **the refreshed spread is what a full assemble gives** — the trace did not
   change, so the refresh must reproduce the full assemble's pages for that
   spread field for field, and the asset folder must end byte-identical. A
   difference here would be the refresh computing something a full assemble
   does not (the unreadable-panel pass is the one place it could: on a refresh
   its reference confidence comes from the document as it stands).

Also checked: a refresh of the spread that carries the hand edit is REFUSED
without ``force``, and the refresh is appended to ``document.meta.json`` rather
than replacing the full assemble's record.

**Carrying the edits (``--carry-edits``, v0.3.0;
``docs/data/carry_edits_prereg_20261112.md``).** The edited spread then gets
one edit of every kind the editor makes (a text override, a type change, a
delete — on a panel the unreadable-panel pass turned into a picture when the
spread has one — a hand caption unpair, a reorder), saved through the editor's
own ``normalize_edits``. Gate A, the control: refreshing that spread with
``carry`` must give back the saved document field for field, drop nothing, and
leave the assets byte-identical (the trace did not change, so everything must
carry). Gate B, the negative: with the edited word's box moved 1 px in that
spread's ``resolved.json``, ``carry`` alone must refuse and leave every file
byte-identical, and ``carry`` + ``force`` must drop exactly that word and
nothing else.

It NEVER touches the job it is pointed at: the job is copied into ``--work``.

Usage::

    python -m tools.spread_refresh_check --job jobs/<id> --work DIR [--json-out J]

Exit code 0 only if every check holds.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from pipeline import stage04_layout as S4
from pipeline import stage06_uncertainty as S6
from pipeline import stage07_assemble as S7
from pipeline.editor import normalize_edits
from pipeline.page_model import BlockType, Document, PairSource

_TEXT_TYPES = (BlockType.PARAGRAPH, BlockType.HEADING, BlockType.LIST)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assets(job: Path) -> dict[str, str]:
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted((job / S7.ASSETS_DIRNAME).iterdir())}


def _load(job: Path) -> Document:
    return Document.model_validate_json(
        (job / "document.json").read_text(encoding="utf-8"))


def _disk(job: Path) -> dict[str, str]:
    out = _assets(job)
    for name in ("document.json", "document.meta.json"):
        out[name] = hashlib.sha1((job / name).read_bytes()).hexdigest()
    return out


def _edit_every_kind(job: Path, spread: str, whole_spread: bool = False) -> dict:
    """Edits 2-6 of the pre-registration on the first page of ``spread`` (the
    word correction and the translation target are already there). Chosen by
    rule; returns what was edited so the row can say so.

    ``whole_spread`` (the supplementary, NOT pre-registered run): text blocks,
    panels and captions are taken from every page of the spread, in page order,
    and a word correction is added on the spread itself — for a spread chosen
    because it holds the block kinds the registered rule found none of."""
    doc = _load(job)
    pages = [pg for pg in doc.pages if pg.source_spread == spread]
    pg = pages[0]
    seq = sorted(pg.blocks, key=lambda b: b.reading_order)
    pool = ([b for p in pages for b in sorted(p.blocks, key=lambda b: b.reading_order)]
            if whole_spread else seq)
    made: dict = {"page": pg.page_id, "whole_spread": whole_spread}
    if whole_spread:
        w = next(w for b in pool for w in b.words if w.text.strip() and not w.edited)
        w.text, w.edited = w.text + "_EDIT", True
        made["word"] = w.text_ocr
    text_blocks = [b for b in pool if b.type in _TEXT_TYPES and not b.deleted]
    if text_blocks:
        text_blocks[0].text = "CARRY CHECK OVERRIDE"
        made["text_override"] = text_blocks[0].id
    if len(text_blocks) > 1:
        b = text_blocks[1]
        b.type = (BlockType.PARAGRAPH if b.type is BlockType.HEADING
                  else BlockType.HEADING)
        made["type_change"] = b.id
    panels = [b for b in pool if b.type_promoted and b.type_auto is BlockType.FIGURE]
    victim = panels[0] if panels else seq[-1]
    victim.deleted = True
    made["deleted"] = {"block": victim.id, "panel": bool(panels)}
    caps = [b for p in pages for b in p.blocks if b.type is BlockType.CAPTION]
    if caps:
        caps[0].figure_ref, caps[0].pair_source = None, PairSource.USER
        made["caption_unpaired"] = caps[0].id
    if len(seq) >= 2:
        seq[0].reading_order, seq[1].reading_order = (seq[1].reading_order,
                                                      seq[0].reading_order)
        made["reordered"] = [seq[0].id, seq[1].id]
    doc = normalize_edits(doc)
    (job / "document.json").write_text(doc.model_dump_json(indent=2),
                                       encoding="utf-8")
    return made


def carry_check(job: Path, cfg: dict, spread: str, assets_full: dict,
                whole_spread: bool = False) -> dict:
    out: dict = {"spread": spread,
                 "edits": _edit_every_kind(job, spread, whole_spread)}
    saved = _load(job)

    # --- gate A: the trace did not change, so everything must carry ---------
    got = S7.run(job, cfg, only_spreads=[spread], carry=True)
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    rep_a = meta["params"]["refreshes"][-1]["params"]["carry_edits"]
    out["A_report"] = rep_a
    out["A_document_identical"] = got == saved and _load(job) == saved
    out["A_nothing_dropped"] = rep_a["dropped"] == []
    out["A_assets_identical_to_full"] = _assets(job) == assets_full
    out["A_pass"] = bool(out["A_document_identical"] and out["A_nothing_dropped"]
                         and out["A_assets_identical_to_full"])

    # --- gate B: the edited word's box moves 1 px in the trace --------------
    word_at = next((pg.page_id, b.id, i) for pg in saved.pages
                   if pg.source_spread == spread for b in pg.blocks
                   for i, w in enumerate(b.words) if w.edited)
    page_id, block_id, wi = word_at
    rpath = job / spread / "06_uncertain" / "resolved.json"
    res = S6.UncertaintyResult.model_validate_json(rpath.read_text(encoding="utf-8"))
    rpage = next(rp for rp in res.pages
                 if f"{spread}__{Path(rp.name).stem}" == page_id)
    rword = next(b for b in rpage.blocks if b.id == block_id).words[wi]
    rword.bbox.x += 1
    rpath.write_text(res.model_dump_json(indent=2), encoding="utf-8")

    before = _disk(job)
    try:
        S7.run(job, cfg, only_spreads=[spread], carry=True)
        out["B_refused"] = False
        refused_report = None
    except S7.EditsWouldBeDropped as e:
        out["B_refused"] = True
        refused_report = e.report
    out["B_refusal_changed_nothing"] = _disk(job) == before
    out["B_staging_removed"] = not (job / S7.STAGING_DIRNAME).exists()
    out["B_refusal_report"] = refused_report

    got = S7.run(job, cfg, only_spreads=[spread], carry=True, force=True)
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    rep_b = meta["params"]["refreshes"][-1]["params"]["carry_edits"]
    out["B_force_report"] = rep_b
    dropped = rep_b["dropped"]
    out["B_exactly_that_word_dropped"] = (
        len(dropped) == 1 and dropped[0]["kind"] == "word"
        and dropped[0]["page_id"] == page_id and dropped[0]["block_id"] == block_id)
    expected = copy.deepcopy(saved)
    ew = next(b for pg in expected.pages if pg.page_id == page_id
              for b in pg.blocks if b.id == block_id).words[wi]
    ew.text, ew.edited = ew.text_ocr, False
    ew.bbox.x += 1
    out["B_rest_identical"] = got == expected
    out["B_pass"] = bool(out["B_refused"] and out["B_refusal_changed_nothing"]
                         and out["B_staging_removed"]
                         and out["B_exactly_that_word_dropped"]
                         and out["B_rest_identical"])
    if not out["B_rest_identical"]:
        out["B_diff_pages"] = [g.page_id for g, e in zip(got.pages, expected.pages)
                               if g != e]
    return out


def run(job_src: Path, work: Path, cfg: dict,
        carry_spread: str | None = None) -> dict:
    job = work / "job"
    if job.exists():
        shutil.rmtree(job)
    shutil.copytree(job_src, job)

    t0 = time.perf_counter()
    full = S7.run(job, cfg, force=True)
    out: dict = {"job": job_src.name, "pages": len(full.pages),
                 "full_assemble_s": round(time.perf_counter() - t0, 1),
                 "refreshes": []}
    assets_full = _assets(job)
    spreads = list(dict.fromkeys(p.source_spread for p in full.pages))
    if len(spreads) < 2:
        raise SystemExit("need a job with at least two spreads")

    # The operator corrects a word on the FIRST spread and sets a translation
    # target — the two kinds of work a full re-assemble would discard.
    doc = _load(job)
    word = next(w for pg in doc.pages if pg.source_spread == spreads[0]
                for b in pg.blocks for w in b.words if w.text.strip())
    word.text, word.edited = word.text + "_EDIT", True
    doc.settings.target_language = "deu"
    (job / "document.json").write_text(doc.model_dump_json(indent=2),
                                       encoding="utf-8")
    saved = _load(job)

    for spread in spreads[1:]:
        t0 = time.perf_counter()
        got = S7.run(job, cfg, only_spreads=[spread])
        row = {
            "spread": spread,
            "seconds": round(time.perf_counter() - t0, 1),
            "page_order_kept": [p.page_id for p in got.pages]
                               == [p.page_id for p in full.pages],
            "other_pages_identical": all(
                g == s for g, s in zip(got.pages, saved.pages)
                if g.source_spread != spread),
            "refreshed_pages_equal_full_assemble": all(
                g == f for g, f in zip(got.pages, full.pages)
                if g.source_spread == spread),
            "settings_kept": got.settings == saved.settings,
            "assets_identical_to_full": _assets(job) == assets_full,
            "on_disk_equals_returned": _load(job) == got,
        }
        out["refreshes"].append(row)
        saved = got

    try:
        S7.run(job, cfg, only_spreads=[spreads[0]])
        out["edited_spread_refused"] = False
    except RuntimeError:
        out["edited_spread_refused"] = True
    out["edit_survived"] = any(
        w.text.endswith("_EDIT") for pg in _load(job).pages
        for b in pg.blocks for w in b.words)

    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    out["meta_keeps_full_record"] = meta["params"].get("pages") == len(full.pages)
    out["meta_refreshes"] = [r["params"]["refreshed_spreads"]
                             for r in meta["params"].get("refreshes", [])]
    out["panel_reference_conf"] = {
        "full": meta["params"].get("panel_reference_conf"),
        "refreshes": [r["params"].get("panel_reference_conf")
                      for r in meta["params"].get("refreshes", [])]}
    out["asset_files"] = len(assets_full)
    t0 = time.perf_counter()
    out["carry"] = carry_check(job, cfg, spreads[0], assets_full)
    if carry_spread:
        # Supplementary, NOT pre-registered: the same two gates on a spread
        # chosen for the block kinds the registered rule did not reach. Its
        # assets must still equal the full assemble's.
        t1 = time.perf_counter()
        out["carry_supplementary"] = carry_check(
            job, cfg, carry_spread, assets_full, whole_spread=True)
        out["carry_supplementary"]["seconds"] = round(time.perf_counter() - t1, 1)
    out["carry"]["seconds"] = round(time.perf_counter() - t0, 1)
    out["ok"] = bool(
        out["edited_spread_refused"] and out["edit_survived"]
        and out["meta_keeps_full_record"]
        and out["carry"]["A_pass"] and out["carry"]["B_pass"]
        and all(out[k]["A_pass"] and out[k]["B_pass"]
                for k in ("carry_supplementary",) if k in out)
        and all(all(v for k, v in r.items() if k not in ("spread", "seconds"))
                for r in out["refreshes"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--job", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True,
                    help="scratch folder; the job is copied here, never edited in place")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--carry-spread", default=None, metavar="page_NNN",
                    help="also run the carry gates on this spread, with edits "
                         "taken from all its pages (supplementary run)")
    args = ap.parse_args(argv)

    args.work.mkdir(parents=True, exist_ok=True)
    res = run(args.job.resolve(), args.work.resolve(), S4.load_config(args.config),
              carry_spread=args.carry_spread)
    text = json.dumps(res, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
