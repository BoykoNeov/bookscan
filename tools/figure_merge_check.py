"""Operator-merge check: does the editor's "merge with the picture below" rejoin the
eye-labelled split pictures exactly, and nothing else?

``docs/OPEN_PROBLEMS.md`` P3. Two automatic rejoin rules were refused (RESULTS
2026-09-24), so the rejoin became an editor action the operator clicks. The action
has one rule of its own that could go wrong unseen: when the joined box overlaps a
further picture, that picture is taken in by the same click (the owner's map has one
large detector box lying across all seven of its strips, so refusing instead would
deadlock). Detector boxes are known to spill 6-9 px past the printed edge, so the
question is whether that pull-in ever glues on a picture the labels call separate.

This drives the REAL editor page in headless Chromium, the way an operator would:
for each of the 13 labelled pictures (``docs/data/figure_split_vlm_groups_20260924.json``)
select the topmost piece and press the merge button until the picture is whole. It
records every button label and warning, whether any removed block lies outside the
labelled picture, the click count, then saves and renders.

It NEVER touches the job it is pointed at: ``document.json`` and
``document_assets/`` are copied into ``--work`` first, and everything happens there
(one Save on the owner's job would overwrite the working copy and its ``.bak``).

Usage::

    python -m tools.figure_merge_check [--job jobs/<id>] [--work DIR] [--json-out J]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWNER_JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
GROUPS = REPO / "docs" / "data" / "figure_split_vlm_groups_20260924.json"
DEFAULT_WORK = Path(r"W:\temp\claude\figure_merge\job_copy")
FIGURE_TAG = '<figure class="figure-block">'


def _copy_job(job: Path, work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy2(job / "document.json", work / "document.json")
    shutil.copytree(job / "document_assets", work / "document_assets")


def _want(keys: list[str]) -> set[int]:
    out: set[int] = set()
    for k in keys:
        a, b = map(int, k.split("#")[1].split("-"))
        out |= {a, b}
    return out


def run(job: Path, work: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from pipeline import editor as ED
    from pipeline import stage08_render as S8

    _copy_job(job, work)
    groups = json.loads(GROUPS.read_text(encoding="utf-8"))["pictures"]
    doc0 = ED.load_document(work)
    page_index = {p.page_id: i for i, p in enumerate(doc0.pages)}
    figs_before = S8.render_html(doc0, work).count(FIGURE_TAG)

    handler = type("_Bound", (ED._Handler,), {"job_dir": work.resolve()})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    pictures = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                pg = browser.new_page()
                pg.goto(url, wait_until="networkidle")
                pg.wait_for_selector("#blocklist .blockrow")
                for name, keys in groups.items():
                    pid = keys[0].split("#")[0]
                    want = _want(keys)
                    pg.evaluate(f"() => {{ state.pageIndex={page_index[pid]}; "
                                "state.selBlock=null; state.selWord=null; renderAll(); }")
                    blocks = {b["id"]: b for b in pg.evaluate("() => page().blocks")}
                    top = min(want, key=lambda i: (blocks[i]["bbox"]["y"], i))
                    pg.evaluate(f"() => selectBlock({top})")
                    clicks, removed_all = [], set()
                    while True:
                        ids = {b["id"] for b in pg.evaluate("() => page().blocks")}
                        if not (want - {top}) & ids:
                            break
                        btn = pg.query_selector("#inspector button.mergebtn")
                        if btn is None or btn.is_disabled():
                            break
                        label = btn.text_content()
                        warns = [w.text_content()
                                 for w in pg.query_selector_all("#inspector .mergewarn")]
                        btn.click()
                        gone = ids - {b["id"] for b in pg.evaluate("() => page().blocks")}
                        removed_all |= gone
                        clicks.append({"button": label, "removed": sorted(gone),
                                       "warnings": warns})
                    remaining = sorted((want - {top}) - removed_all)
                    outside = sorted(removed_all - want)
                    pictures.append({
                        "picture": name, "page_id": pid, "kept": top,
                        "labelled_blocks": sorted(want), "clicks": clicks,
                        "not_merged": remaining, "removed_outside_label": outside,
                        "exact": not remaining and not outside,
                    })
                pg.click("#save")
                pg.wait_for_function(
                    "() => document.querySelector('#status').textContent.includes('saved')")
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    doc1 = ED.load_document(work)
    html1 = S8.render_html(doc1, work)
    (work / "render").mkdir(exist_ok=True)
    (work / "render" / "page.html").write_text(html1, encoding="utf-8")
    return {
        "job": str(job.relative_to(REPO)) if job.is_relative_to(REPO) else str(job),
        "groups_file": str(GROUPS.relative_to(REPO)),
        "pictures": pictures,
        "summary": {
            "pictures": len(pictures),
            "exact": sum(p["exact"] for p in pictures),
            "clicks": sum(len(p["clicks"]) for p in pictures),
            "removed_outside_label": sum(len(p["removed_outside_label"]) for p in pictures),
            "figures_rendered_before": figs_before,
            "figures_rendered_after": html1.count(FIGURE_TAG),
            "saved_document_reads_as_edited": ED._document_has_edits(doc1),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Operator figure-merge check (P3)")
    ap.add_argument("--job", type=Path, default=OWNER_JOB)
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK,
                    help="scratch copy of the job (wiped and re-made)")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.work.resolve() == args.job.resolve():
        ap.error("--work must not be the job itself")
    res = run(args.job, args.work)
    for p in res["pictures"]:
        print(f"{p['picture']:15s} {p['page_id']:16s} clicks={len(p['clicks'])} "
              f"{'EXACT' if p['exact'] else 'WRONG'}"
              + (f" not_merged={p['not_merged']}" if p["not_merged"] else "")
              + (f" OUTSIDE={p['removed_outside_label']}" if p["removed_outside_label"] else ""))
        for c in p["clicks"]:
            print(f"    {c['button']}  -> removed {c['removed']}")
            for w in c["warnings"]:
                print(f"      {w}")
    print(json.dumps(res["summary"]))
    if args.json_out:
        args.json_out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    s = res["summary"]
    return 0 if s["exact"] == s["pictures"] and not s["removed_outside_label"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
