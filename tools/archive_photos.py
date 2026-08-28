"""Collect every photograph ever taken for bookscan into ONE folder.

Two populations:
  * `raw/` uploads under gitignored jobs/  -- the ORIGINAL phone bytes, EXIF
    intact, and the only copy that exists. These are what this archive is for.
  * testset/*.jpg -- already committed and canonical. Copied too, so the folder
    really is "all photos", but marked committed=yes in the manifest so nobody
    mistakes the archive copy for the fixture.

Deduplicated by SHA-256: identical bytes are stored once and every origin that
carried them is listed in the manifest.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS

REPO = Path(r"M:\claud_projects\bookscan")
DEST = Path(r"M:\claud_projects\bookscan_captures")

# What each server job actually was. Anything not listed is described generically.
JOB_NOTES = {
    "20260818-144545-7c21f083": ("server-smoke", "first FastAPI upload test; re-upload of a 2026-07-02 photo"),
    "20260818-144649-0d501ac9": ("server-smoke", "second FastAPI upload test; same photo, best_guess mode"),
    "20260819-064025-6b4cc4ac": ("zoomset", "FIRST real in-app multi-zoom captures; source of testset/zoomset_*"),
    "20260828-092505-15c41a76": ("pale-background", "THE BOOK-DETECTOR DEFECT: book on a pale sofa, neither spread split"),
    "20260828-094929-677fd774": ("pale-background", "patch-mode run, same session and background"),
    "20260828-095443-6f59677f": ("restart-test", "re-upload of testset bg_01/02/03 to test server-kill recovery"),
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(p: Path) -> dict:
    try:
        with Image.open(p) as im:
            w, h = im.size
            ex = im.getexif()
            tags = {TAGS.get(k, k): v for k, v in ex.items()}
        return {
            "width": w, "height": h,
            "camera": f"{tags.get('Make','')} {tags.get('Model','')}".strip(),
            "shot_at": str(tags.get("DateTime", "")),
        }
    except Exception as e:  # a corrupt or non-image file must not kill the run
        return {"width": "", "height": "", "camera": "", "shot_at": f"ERR {e}"}


def collect() -> list[dict]:
    items: list[dict] = []

    for raw in sorted((REPO / "jobs").glob("*/page_*/raw")):
        job, page = raw.parts[-3], raw.parts[-2]
        cat, note = JOB_NOTES.get(job, ("upload", "server upload"))
        for f in sorted(raw.iterdir()):
            if not f.is_file():
                continue
            items.append({
                "src": f,
                "name": f"upload_{job[:15]}_{page}_{f.stem}{f.suffix.lower()}",
                "category": cat, "note": note, "committed": "no",
            })

    for f in sorted((REPO / "testset").glob("*.jpg")):
        items.append({
            "src": f,
            "name": f"testset_{f.name}",
            "category": "testset",
            "note": "committed fixture (canonical copy lives in testset/)",
            "committed": "yes",
        })
    return items


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    rows, by_hash = [], {}
    copied = skipped = 0

    for it in collect():
        digest = sha256(it["src"])
        origin = str(it["src"].relative_to(REPO)).replace("\\", "/")

        if digest in by_hash:
            # Same bytes already archived -- record the extra origin, copy nothing.
            first = by_hash[digest]
            first["also_found_at"] = (first["also_found_at"] + " | " + origin).strip(" |")
            skipped += 1
            continue

        dst = DEST / it["name"]
        if not dst.exists() or dst.stat().st_size != it["src"].stat().st_size:
            shutil.copy2(it["src"], dst)
        copied += 1

        row = {
            "archive_file": it["name"], "category": it["category"],
            "origin": origin, "also_found_at": "",
            "bytes": it["src"].stat().st_size, "sha256": digest,
            "committed_in_repo": it["committed"], "note": it["note"],
            **probe(it["src"]),
        }
        by_hash[digest] = row
        rows.append(row)

    cols = ["archive_file", "category", "width", "height", "camera", "shot_at",
            "bytes", "sha256", "committed_in_repo", "origin", "also_found_at", "note"]
    with (DEST / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)

    total = sum(r["bytes"] for r in rows)
    print(f"archived {copied} files ({total/1e6:.1f} MB), {skipped} duplicate(s) skipped")
    for cat in sorted({r["category"] for r in rows}):
        sel = [r for r in rows if r["category"] == cat]
        print(f"  {cat:<16} {len(sel):>3} files  {sum(r['bytes'] for r in sel)/1e6:>7.1f} MB")


if __name__ == "__main__":
    main()
