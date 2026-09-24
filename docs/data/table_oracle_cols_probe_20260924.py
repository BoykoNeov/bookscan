"""Probe for docs/data/table_oracle_cols_prereg_20260924.md (P6).

Every TABLE block (plus text_panel-promoted paragraphs, which the gridder also
offers) in the owner's job and one it_geo_07 job, gridded from the STORED Stage 05
words and the 03_dewarp image, arm off vs arm on. Prints each grid as a table so
it can be checked by eye against the page. Writes
docs/data/table_oracle_cols_20260924.json.

    python docs/data/table_oracle_cols_probe_20260924.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import table_grid as TG  # noqa: E402
from pipeline.page_model import Block  # noqa: E402
from pipeline.stage05_ocr import find_tesseract, resolve_tessdata_dir  # noqa: E402

JOBS = [REPO / "jobs/20260829-084115-de3c20d3", REPO / "jobs/figtext_it_geo_07"]


def grid_text(blk: Block) -> list[str]:
    cells: dict[tuple[int, int], list[str]] = defaultdict(list)
    for w in blk.words:
        if w.table_row is not None:
            cells[(w.table_row, w.table_col)].append(w.text)
    if not cells:
        return []
    nr = max(r for r, _ in cells) + 1
    nc = max(c for _, c in cells) + 1
    return ["| " + " | ".join(f"{' '.join(cells.get((r, c), []))[:28]:28}"
                              for c in range(nc)) for r in range(nr)]


def main() -> int:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    binary = find_tesseract(cfg)
    tessdata = resolve_tessdata_dir(cfg)
    oem = int((cfg.get("tesseract", {}) or {}).get("oem", 1))
    base = dict(cfg.get("table_grid", {}) or {})
    out = []
    for job in JOBS:
        for ocr in sorted(job.glob("page_*/05_ocr/ocr.json")):
            d = json.loads(ocr.read_text(encoding="utf-8"))
            for pg in d["pages"]:
                blocks = [Block.model_validate(b) for b in pg["blocks"]]
                if not any(TG._candidates(b) for b in blocks):
                    continue
                img = cv2.imread(str(ocr.parent.parent / "03_dewarp" / pg["name"]))
                lang, scale = pg["language"], float(pg["scale"])
                res = {}
                for arm in (False, True):
                    bl = [b.model_copy(deep=True) for b in blocks]
                    for b in bl:
                        for w in b.words:
                            w.table_row = w.table_col = None
                    _, notes, skips = TG.grid_table_blocks(
                        bl, img, binary, tessdata, lang, oem, scale,
                        p={**base, "oracle_columns": arm})
                    res[arm] = (bl, {n.block_id: vars(n) for n in notes},
                                {s.block_id: s.reason for s in skips})
                for b in blocks:
                    if not TG._candidates(b):
                        continue
                    bo = next(x for x in res[False][0] if x.id == b.id)
                    bn = next(x for x in res[True][0] if x.id == b.id)
                    key = f"{job.name[-14:]}/{ocr.parent.parent.name}/{pg['name']} #{b.id}"
                    same = ([(w.table_row, w.table_col) for w in bo.words]
                            == [(w.table_row, w.table_col) for w in bn.words])
                    row = {"block": key, "type": b.type.value, "words": len(b.words),
                           "off": res[False][1].get(b.id) or res[False][2].get(b.id),
                           "on": res[True][1].get(b.id) or res[True][2].get(b.id),
                           "unchanged": same, "grid_on": grid_text(bn)}
                    out.append(row)
                    print(f"\n===== {key} ({b.type.value}, {len(b.words)} words)"
                          f"  unchanged={same}")
                    print("  off:", row["off"])
                    print("  on: ", row["on"])
                    if not same:
                        print("\n".join("  " + ln for ln in row["grid_on"]))
    (REPO / "docs/data/table_oracle_cols_20260924.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
