"""Bordered run (prereg docs/data/pdf_whiteborder_prereg_20260924.md): copy each
audited page's raw frame + page_layout.json (adding the importer's new
origin marker), and run the shipped run_all on the copy. No pdf_text_layer.json
is written, so Stage 06's decisions are the same kind as the audited run's."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
SRC = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")
DST = Path(sys.argv[1] if len(sys.argv) > 1 else r"W:\temp\claude\pdf_textlayer\border_run\jobs")

for page in sorted(SRC.glob("*/page_*")):
    out = DST / page.parent.name / page.name
    if (out / "06_uncertain" / "resolved.json").exists():
        continue
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(page / "raw", out / "raw")
    lay = json.loads((page / "page_layout.json").read_text(encoding="utf-8"))
    lay["origin"] = "pdf_import"
    (out / "page_layout.json").write_text(json.dumps(lay, indent=1), encoding="utf-8")
    extra = ["--config", sys.argv[2]] if len(sys.argv) > 2 else []
    r = subprocess.run([sys.executable, "-m", "pipeline.run_all", str(out),
                        "--mode", "flag", "--lang", "eng"] + extra, cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (out / "eval_run.log").write_text(f"exit {r.returncode}\n{r.stdout}\n{r.stderr}",
                                      encoding="utf-8")
    print(f"{page.parent.name}/{page.name}: exit {r.returncode}", flush=True)
