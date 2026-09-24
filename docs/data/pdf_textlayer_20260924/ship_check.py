"""End-to-end: on a COPY of the measured pages, write each page's text layer the
way the importer now does, re-run the shipped Stage 05 + 06, and check that the
words marked layer_disagree are exactly the replay's marks (and that Stage 06
flags every one of them)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import fitz  # noqa: E402

from pipeline import pdf_text_layer as L  # noqa: E402

SRC = Path(r"W:\temp\claude\pdf_textlayer\work")
DST = Path(r"W:\temp\claude\pdf_textlayer\ship_check")
manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
if not DST.exists():
    shutil.copytree(SRC / "jobs", DST / "jobs")

bad = 0
for d in manifest["docs"]:
    src = fitz.open(d["file"])
    producer = (src.metadata or {}).get("producer", "")
    for k, pno in enumerate(d["pages_1based"]):
        page_dir = DST / "jobs" / d["id"] / f"page_{k + 1:03d}"
        # expected marks from the audited Stage 06 output (before re-run)
        before = json.loads((SRC / "jobs" / d["id"] / f"page_{k + 1:03d}" / "06_uncertain"
                             / "resolved.json").read_text(encoding="utf-8"))
        layer = L.layer_words(src[pno - 1])
        exp = L.check(L.page_words(before["pages"]), layer)
        exp_texts = sorted(L.page_words(before["pages"])[i]["text"] for i in exp.marked)
        L.write_layer(page_dir, layer, pdf_name=Path(d["file"]).name, pdf_page=pno,
                      producer=producer)
        for stage in ("stage05_ocr", "stage06_uncertainty"):
            r = subprocess.run([sys.executable, "-m", f"pipeline.{stage}", str(page_dir)]
                               + (["--lang", "eng"] if stage == "stage05_ocr" else [])
                               + (["--mode", "flag"] if stage == "stage06_uncertainty" else []),
                               cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
            if r.returncode:
                print(page_dir, stage, r.stderr[-2000:])
                raise SystemExit(1)
        after = json.loads((page_dir / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
        aw = L.page_words(after["pages"])
        got = sorted(w["text"] for w in aw if w.get("layer_disagree"))
        unflagged = [w["text"] for w in aw if w.get("layer_disagree") and w["decision"] == "keep"]
        same_words = [w["text"] for w in aw] == [w["text"] for w in L.page_words(before["pages"])]
        m5 = json.loads((page_dir / "05_ocr" / "meta.json").read_text(encoding="utf-8"))
        tl = m5["params"]["pdf_text_layer"]
        ok = got == exp_texts and not unflagged and same_words
        bad += not ok
        print(f"{d['id']} p{pno}: marked {len(got)} (expected {len(exp_texts)}), "
              f"left unflagged {len(unflagged)}, words identical {same_words}, "
              f"abstained {tl['abstained'][:50]!r} -> {'OK' if ok else 'DIFFERENT'}")
    src.close()
print("ALL OK" if not bad else f"{bad} page(s) differ")
