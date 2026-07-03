"""Reproducibly build the Gate 1 tessdata directory.

``models/tessdata_best`` is gitignored, so a fresh clone has neither the
language data nor Tesseract's output-config files. This script rebuilds it:

  1. downloads eng/bul/ita/deu ``*.traineddata`` from tessdata_best, and
  2. copies ``configs/`` + ``tessconfigs/`` from the installed Tesseract's
     tessdata into the target dir.

Step 2 is NOT optional: when ``--tessdata-dir`` points at a custom folder,
Tesseract looks for output configs (``tsv``, ``hocr``, ...) there too. Without
them it silently ignores the ``tsv`` request and emits plain text — the harness
then parses zero words. (Learned the hard way.)

    python -m tools.setup_tessdata            # uses config.yaml
    python -m tools.setup_tessdata --force    # re-download even if present
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LANGS = ("eng", "bul", "ita", "deu")
# osd.traineddata is not a `-l` language, but Stage 00 (ingest) orientation
# detection runs Tesseract OSD (--psm 0), which needs it in the SAME
# --tessdata-dir the pipeline/harness point at. Fetch it alongside the langs so
# one tessdata dir serves recognition AND orientation. See tools/normalize.py.
OSD = "osd"
TESSDATA_BEST = "https://github.com/tesseract-ocr/tessdata_best/raw/main"


def load_cfg() -> dict:
    with open(REPO_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def target_dir(cfg: dict) -> Path:
    raw = cfg.get("tesseract", {}).get("tessdata_dir", "models/tessdata_best")
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


def install_tessdata(cfg: dict) -> Path | None:
    """Locate the installed Tesseract's tessdata dir (holds configs/)."""
    binary = cfg.get("tesseract", {}).get("binary")
    if binary:
        cand = Path(binary).parent / "tessdata"
        if cand.exists():
            return cand
    which = shutil.which("tesseract")
    if which:
        cand = Path(which).parent / "tessdata"
        if cand.exists():
            return cand
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build models/tessdata_best")
    ap.add_argument("--force", action="store_true",
                    help="re-download traineddata even if already present")
    args = ap.parse_args(argv)

    cfg = load_cfg()
    dst = target_dir(cfg)
    dst.mkdir(parents=True, exist_ok=True)
    print(f"target: {dst}")

    for lang in (*LANGS, OSD):
        out = dst / f"{lang}.traineddata"
        if out.exists() and not args.force:
            print(f"  keep {lang}.traineddata ({out.stat().st_size/1e6:.1f} MB)")
            continue
        url = f"{TESSDATA_BEST}/{lang}.traineddata"
        print(f"  download {lang} <- {url}")
        urllib.request.urlretrieve(url, out)
        print(f"    ok ({out.stat().st_size/1e6:.1f} MB)")

    install = install_tessdata(cfg)
    if not install:
        print("WARNING: could not locate installed Tesseract tessdata to copy "
              "configs/ — TSV output will fail. Install Tesseract first.",
              file=sys.stderr)
        return 1
    for sub in ("configs", "tessconfigs"):
        src = install / sub
        if src.exists():
            shutil.copytree(src, dst / sub, dirs_exist_ok=True)
            print(f"  copied {sub}/ from {src}")

    tsv_cfg = dst / "configs" / "tsv"
    if not tsv_cfg.exists():
        print("WARNING: configs/tsv missing after copy — TSV output will fail.",
              file=sys.stderr)
        return 1
    print("tessdata ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
