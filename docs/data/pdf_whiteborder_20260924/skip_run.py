"""Skip-flattening arm (prereg addendum): on a copy, 03_dewarp = 02_split unchanged,
then the shipped Stages 04-06."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
SRC = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")
DST = Path(r"W:\temp\claude\pdf_textlayer\skip_run\jobs")
for page in sorted(SRC.glob("*/page_*")):
    out = DST / page.parent.name / page.name
    if (out / "06_uncertain" / "resolved.json").exists():
        continue
    if out.exists():
        shutil.rmtree(out)
    for sub in ("raw", "00_ingest", "01_fuse", "02_split"):
        shutil.copytree(page / sub, out / sub)
    shutil.copy2(page / "page_layout.json", out / "page_layout.json")
    split = json.loads((out / "02_split" / "split.json").read_text(encoding="utf-8"))
    (out / "03_dewarp").mkdir()
    pages = []
    for sp in split["pages"]:
        shutil.copy2(out / "02_split" / sp["name"], out / "03_dewarp" / sp["name"])
        pages.append({"name": sp["name"], "method": "identity", "applied": False,
                      "note": "imported page: flattening skipped (measurement arm)"})
    (out / "03_dewarp" / "dewarp.json").write_text(json.dumps(
        {"source": "02_split/split.json", "engine": "skip", "pages": pages}), encoding="utf-8")
    for args in (["pipeline.stage04_layout"], ["pipeline.stage05_ocr", "--lang", "eng"],
                 ["pipeline.stage06_uncertainty", "--mode", "flag"]):
        r = subprocess.run([sys.executable, "-m", args[0], str(out)] + args[1:], cwd=REPO,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(f"{page.parent.name}/{page.name}: {args[0]} exit {r.returncode}\n{r.stderr[-1500:]}")
            break
    print(f"{page.parent.name}/{page.name}: exit {r.returncode}", flush=True)
