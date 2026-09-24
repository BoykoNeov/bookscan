"""Delete-block check: does deleting a junk block inside a merged picture remove it
from the render AND give the picture its own pixels back?

``docs/OPEN_PROBLEMS.md`` P3's known wart. After the operator merges the map on the
owner's ``page_023__right`` (pieces #14, #16, #17), a junk OCR block read off the
map's lettering (#15, "N are,") lies inside the joined box, so Stage 08 printed it as
text AND painted a pale patch over that spot of the map. The editor's "Delete block"
(``Block.deleted``, a reversible hide) is the fix. This grades the RENDER, not the flag:

1. copy the owner's job and do every labelled merge through the real editor page
   (``tools/figure_merge_check.run``, which saves the result);
2. render that document ("before");
3. drive the real editor again: select #15 on ``page_023__right``, press Delete block,
   Save; render ("after");
4. compare. #15's words must be gone from the page's section; inside #15's box the
   merged map must equal the page image's own pixels exactly (before: it must not —
   that is the patch); outside #15's box the map must be unchanged; every other page
   section must be byte-identical.

It NEVER touches the job it is pointed at (everything happens in ``--work``).

Usage::

    python -m tools.delete_block_check [--job jobs/<id>] [--work DIR] [--json-out J]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from tools import figure_merge_check as FMC

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WORK = Path(r"W:\temp\claude\delete_block\job_copy")
PAGE_ID = "page_023__right"
JUNK_ID = 15
MAP_ID = 14            # the topmost piece keeps its id through the merge


def _sections(html_str: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'<section class="page" data-page="([^"]+)">(.*?)</section>',
                         html_str, re.S):
        out[m.group(1)] = m.group(2)
    return out


def _imgs(section: str) -> list[np.ndarray]:
    out = []
    for m in re.finditer(r'<img class="figure" src="data:image/png;base64,([^"]+)"', section):
        buf = np.frombuffer(base64.b64decode(m.group(1)), np.uint8)
        out.append(cv2.imdecode(buf, cv2.IMREAD_COLOR))
    return out


def _delete_in_editor(work: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from pipeline import editor as ED

    doc = ED.load_document(work)
    page_index = [p.page_id for p in doc.pages].index(PAGE_ID)
    handler = type("_Bound", (ED._Handler,), {"job_dir": work.resolve()})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                pg = browser.new_page()
                pg.goto(url, wait_until="networkidle")
                pg.wait_for_selector("#blocklist .blockrow")
                pg.evaluate(f"() => {{ state.pageIndex={page_index}; "
                            "state.selBlock=null; state.selWord=null; renderAll(); }")
                pg.evaluate(f"() => selectBlock({MAP_ID})")
                merge_text = pg.text_content("#inspector .mergefield") or ""
                pg.evaluate(f"() => selectBlock({JUNK_ID})")
                note = pg.text_content("#inspector .deletefield")
                pg.click("#inspector button.deletebtn")
                pg.click("#save")
                pg.wait_for_function(
                    "() => document.querySelector('#status').textContent.includes('saved')")
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return {"delete_note": note, "map_panel_before_delete": merge_text}


def run(job: Path, work: Path) -> dict:
    from pipeline import editor as ED
    from pipeline import stage08_render as S8

    merge = FMC.run(job, work)                   # copies the job, merges, saves
    doc0 = ED.load_document(work)
    html0 = S8.render_html(doc0, work)
    ui = _delete_in_editor(work)
    doc1 = ED.load_document(work)
    html1 = S8.render_html(doc1, work)
    (work / "render").mkdir(exist_ok=True)
    (work / "render" / "page.html").write_text(html1, encoding="utf-8")

    pg0 = next(p for p in doc0.pages if p.page_id == PAGE_ID)
    blocks = {b.id: b for b in pg0.blocks}
    mp, junk = blocks[MAP_ID].bbox, blocks[JUNK_ID].bbox
    junk_text = " ".join(w.text for w in blocks[JUNK_ID].words)
    page_bgr = cv2.imread(str(work / pg0.image_asset), cv2.IMREAD_COLOR)
    ref = page_bgr[mp.y:mp.y + mp.h, mp.x:mp.x + mp.w]

    s0, s1 = _sections(html0), _sections(html1)

    def the_map(sec: str) -> np.ndarray:
        hits = [im for im in _imgs(sec) if im.shape[:2] == (mp.h, mp.w)]
        assert len(hits) == 1, f"expected one {mp.w}x{mp.h} picture, got {len(hits)}"
        return hits[0]

    m0, m1 = the_map(s0[PAGE_ID]), the_map(s1[PAGE_ID])
    ys, xs = slice(junk.y - mp.y, junk.y - mp.y + junk.h), slice(junk.x - mp.x, junk.x - mp.x + junk.w)
    inside = np.zeros(ref.shape[:2], bool)
    inside[ys, xs] = True

    def diff(a: np.ndarray, b: np.ndarray, where: np.ndarray) -> int:
        return int(np.abs(a.astype(int) - b.astype(int))[where].max()) if where.any() else 0

    def word_hits(sec: str) -> int:
        # the page's visible text only: image data (base64 holds any letter) and tags out
        text = re.sub(r'src="data:[^"]*"', "", sec)
        text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
        return text.count(junk_text)

    junk_after = {b.id: b for b in next(p for p in doc1.pages if p.page_id == PAGE_ID).blocks}[JUNK_ID]
    others_same = all(s0[k] == s1[k] for k in s0 if k != PAGE_ID)

    return {
        "job": str(job.relative_to(REPO)) if job.is_relative_to(REPO) else str(job),
        "page_id": PAGE_ID, "junk_block": JUNK_ID, "junk_text": junk_text,
        "junk_bbox": junk.model_dump(), "merged_map_block": MAP_ID, "merged_map_bbox": mp.model_dump(),
        "merge_summary": merge["summary"],
        "editor": ui,
        "saved": {"deleted": junk_after.deleted, "structure_edited": junk_after.structure_edited,
                  "words_kept": len(junk_after.words),
                  "reads_as_edited": ED._document_has_edits(doc1)},
        "before_delete": {
            "junk_word_occurrences_in_page": word_hits(s0[PAGE_ID]),
            "map_vs_page_pixels_inside_junk_box_maxdiff": diff(m0, ref, inside),
            "map_vs_page_pixels_outside_junk_box_maxdiff": diff(m0, ref, ~inside),
        },
        "after_delete": {
            "junk_word_occurrences_in_page": word_hits(s1[PAGE_ID]),
            "map_vs_page_pixels_inside_junk_box_maxdiff": diff(m1, ref, inside),
            "map_vs_page_pixels_outside_junk_box_maxdiff": diff(m1, ref, ~inside),
        },
        "map_changed_outside_junk_box_maxdiff": diff(m0, m1, ~inside),
        "other_page_sections_identical": others_same,
        "figures_rendered_before_after": [html0.count(FMC.FIGURE_TAG), html1.count(FMC.FIGURE_TAG)],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Delete-block render check (P3 wart)")
    ap.add_argument("--job", type=Path, default=FMC.OWNER_JOB)
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
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if args.json_out:
        args.json_out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    b, a = res["before_delete"], res["after_delete"]
    ok = (a["junk_word_occurrences_in_page"] == 0
          and a["map_vs_page_pixels_inside_junk_box_maxdiff"] == 0
          and b["map_vs_page_pixels_inside_junk_box_maxdiff"] > 0
          and res["map_changed_outside_junk_box_maxdiff"] == 0
          and res["other_page_sections_identical"]
          and res["saved"]["deleted"] and res["saved"]["reads_as_edited"])
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
