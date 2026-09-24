"""PDF-import check: does a page that arrives as a PDF go through the pipeline, and
what differs from the same pixels arriving as a photograph?

``docs/plans/pdf-import.md`` Slice 1, done-when: an imported PDF's pages are
processed by ``run_all`` with no other change, down to the rendered document.
Two arms from ONE testset spread (default ``en_coins_01``):

* **control (spread).** The direct run's upright anchor is put in a PDF at its own
  pixel size (page points = px * 72 / dpi), imported at that dpi, and run. The
  import must hand the pipeline the SAME pixels, so every stage after it should
  read the same text. Anything else is the import's doing.
* **single page.** The direct run's LEFT page, cut from that anchor with the box
  Stage 02 wrote, as a portrait PDF page. The importer calls it single from its
  shape, Stage 02 emits it whole, and it is dewarped and read on its own. Compared
  with the direct run's left page by a word-level text diff. This is the single
  page's first run end to end; the page is synthetic (cut from a spread, with the
  spread cut's overlap margin), and it is one scene, so the diff says what
  differs, not which reads better.

Then Stage 07 + 08 on the imported job, to show ``__single`` survives into the
document and the render.

Writes only its own two jobs (wiped first) and a PDF under ``--work``.

Usage::

    python -m tools.pdf_import_check [--spread en_coins_01] [--lang eng] [--json-out J]
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
JOBS = REPO / "jobs"
DEFAULT_WORK = Path(r"W:\temp\claude\pdf_import\check")
DPI = 300


def _py(*args: str) -> None:
    r = subprocess.run([sys.executable, "-m", *args], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def _words(page_dir: Path, name: str) -> list[str]:
    ocr = json.loads((page_dir / "05_ocr" / "ocr.json").read_text(encoding="utf-8"))
    pg = next(p for p in ocr["pages"] if p["name"] == name)
    out = []
    for b in sorted(pg["blocks"], key=lambda b: b["reading_order"]):
        out.extend(w["text"] for w in b["words"] if w["text"].strip())
    return out


def _diff(a: list[str], b: list[str], keep: int = 25) -> dict:
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    return {
        "words_a": len(a), "words_b": len(b),
        "equal_words": sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal"),
        "ratio": round(sm.ratio(), 4),
        "changes": [{"op": t, "a": " ".join(a[i1:i2]), "b": " ".join(b[j1:j2])}
                    for t, i1, i2, j1, j2 in ops[:keep]],
        "n_changes": len(ops),
    }


def _pdf(pages: list[np.ndarray], path: Path) -> None:
    import fitz
    doc = fitz.open()
    for img in pages:
        h, w = img.shape[:2]
        page = doc.new_page(width=w * 72 / DPI, height=h * 72 / DPI)
        ok, buf = cv2.imencode(".png", img)
        page.insert_image(page.rect, stream=buf.tobytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def _warnings(page_dir: Path, stage: str) -> list[str]:
    return json.loads((page_dir / stage / "meta.json").read_text(encoding="utf-8"))["warnings"]


def run(spread: str, lang: str, work: Path) -> dict:
    from pipeline import pdf_import as PI

    direct_id, import_id = f"pdfimp_direct_{spread}", f"pdfimp_import_{spread}"
    for j in (direct_id, import_id):
        shutil.rmtree(JOBS / j, ignore_errors=True)

    # --- direct run: the photograph, as the phone path would deliver it -------
    src = REPO / "testset" / f"{spread}.jpg"
    direct = JOBS / direct_id / "page_001"
    _py("pipeline.run_all", "--input", str(src), "--job", direct_id, "--page",
        "page_001", "--lang", lang)
    anchor = cv2.imread(str(direct / "01_fuse" / "anchor.png"), cv2.IMREAD_COLOR)
    split = json.loads((direct / "02_split" / "split.json").read_text(encoding="utf-8"))
    names = [p["name"] for p in split["pages"]]
    if names != ["left.png", "right.png"]:
        raise RuntimeError(f"direct run did not split into two pages: {names}")
    lb = next(p["box"] for p in split["pages"] if p["name"] == "left.png")
    left = anchor[lb["y"]:lb["y"] + lb["h"], lb["x"]:lb["x"] + lb["w"]]

    # --- the same pixels as a PDF: page 1 the spread, page 2 its left page ----
    pdf = work / f"{spread}.pdf"
    _pdf([anchor, left], pdf)
    res = PI.import_pdf(pdf, JOBS, dpi=DPI, lang=lang, job_id=import_id,
                        staging_root=work / "staging")
    imp = JOBS / import_id
    for p in ("page_001", "page_002"):
        _py("pipeline.run_all", str(imp / p), "--lang", lang)
    _py("pipeline.stage07_assemble", str(imp), "--force")
    _py("pipeline.stage08_render", str(imp))

    raw1 = cv2.imread(str(imp / "page_001" / "raw" / "frame_00.png"), cv2.IMREAD_COLOR)
    raw2 = cv2.imread(str(imp / "page_002" / "raw" / "frame_00.png"), cv2.IMREAD_COLOR)
    s1 = json.loads((imp / "page_001" / "02_split" / "split.json").read_text(encoding="utf-8"))
    s2 = json.loads((imp / "page_002" / "02_split" / "split.json").read_text(encoding="utf-8"))
    doc = json.loads((imp / "document.json").read_text(encoding="utf-8"))
    html = (imp / "render" / "page.html").read_text(encoding="utf-8")

    return {
        "spread": spread, "lang": lang, "dpi": DPI, "pdf": str(pdf),
        "import": {"verdicts": [(p.page, p.layout, p.layout_source, p.aspect)
                                for p in res.pages],
                   "coverage": [p.image_coverage for p in res.pages]},
        "control_spread": {
            "rendered_equals_anchor": raw1.shape == anchor.shape
            and int(np.abs(raw1.astype(int) - anchor.astype(int)).max()) == 0,
            "gutter_direct": split["gutter_x"], "gutter_import": s1["gutter_x"],
            "left": _diff(_words(direct, "left.png"), _words(imp / "page_001", "left.png")),
            "right": _diff(_words(direct, "right.png"), _words(imp / "page_001", "right.png")),
        },
        "single_page": {
            "rendered_equals_crop": raw2.shape == left.shape
            and int(np.abs(raw2.astype(int) - left.astype(int)).max()) == 0,
            "crop_box_in_anchor": lb,
            "split_method": s2["method"], "split_pages": [p["name"] for p in s2["pages"]],
            "stage00_warnings": _warnings(imp / "page_002", "00_ingest"),
            "stage03_warnings": _warnings(imp / "page_002", "03_dewarp")[:6],
            "text_vs_direct_left": _diff(_words(direct, "left.png"),
                                         _words(imp / "page_002", "single.png")),
        },
        "document": {
            "page_ids": [p["page_id"] for p in doc["pages"]],
            "render_sections": html.count('<section class="page"'),
            "single_section_rendered": 'data-page="page_002__single"' in html,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PDF import end-to-end check (Slice 1)")
    ap.add_argument("--spread", default="en_coins_01")
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    res = run(args.spread, args.lang, args.work)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if args.json_out:
        args.json_out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    c, d = res["control_spread"], res["document"]
    ok = (c["rendered_equals_anchor"] and c["left"]["n_changes"] == 0
          and c["right"]["n_changes"] == 0 and d["single_section_rendered"]
          and res["single_page"]["split_method"] == "declared-single")
    print("CONTROL IDENTICAL, SINGLE PAGE RENDERED" if ok else "CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
