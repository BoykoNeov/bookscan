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

It NEVER touches the job it is pointed at: the job is copied into ``--work``.

Usage::

    python -m tools.spread_refresh_check --job jobs/<id> --work DIR [--json-out J]

Exit code 0 only if every check holds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from pipeline import stage04_layout as S4
from pipeline import stage07_assemble as S7
from pipeline.page_model import Document

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assets(job: Path) -> dict[str, str]:
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted((job / S7.ASSETS_DIRNAME).iterdir())}


def _load(job: Path) -> Document:
    return Document.model_validate_json(
        (job / "document.json").read_text(encoding="utf-8"))


def run(job_src: Path, work: Path, cfg: dict) -> dict:
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
    out["ok"] = bool(
        out["edited_spread_refused"] and out["edit_survived"]
        and out["meta_keeps_full_record"]
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
    args = ap.parse_args(argv)

    args.work.mkdir(parents=True, exist_ok=True)
    res = run(args.job.resolve(), args.work.resolve(), S4.load_config(args.config))
    text = json.dumps(res, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
