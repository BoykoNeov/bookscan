"""Does Stage 03 push text off the edge of imported flat scans?

For every imported page: Tesseract words whose box touches an edge of the
03_dewarp image (left/right, and top/bottom), and the ink in a 1 % border strip
of the page before (02_split) and after (03_dewarp) flattening. Ink that appears
at the border only after flattening was pushed there (and likely beyond it).

A LOWER BOUND: a word pushed wholly off the image leaves no box and no ink to
count, so "0 words at the edge" does not prove nothing was lost.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

W = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")


def edge_ink(img: np.ndarray) -> tuple[float, float]:
    """(left+right strip, top+bottom strip) share of dark pixels."""
    h, w = img.shape
    b = max(2, w // 100)
    lr = np.concatenate([img[:, :b], img[:, -b:]], axis=1)
    tb = np.concatenate([img[:b, :], img[-b:, :]], axis=0)
    return float((lr < 110).mean()), float((tb < 110).mean())


for page in sorted(W.glob("*/page_*")):
    res = json.loads((page / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
    touching = vtouch = total = 0
    for sp in res["pages"]:
        wmax, hmax = sp["width"], sp["height"]
        for b in sp["blocks"]:
            for w in b.get("words") or []:
                total += 1
                x, ww = w["bbox"]["x"], w["bbox"]["w"]
                y, hh = w["bbox"]["y"], w["bbox"]["h"]
                touching += x <= 1 or x + ww >= wmax - 1
                vtouch += y <= 1 or y + hh >= hmax - 1
    before = np.asarray(Image.open(next((page / "02_split").glob("*.png"))).convert("L"))
    after = np.asarray(Image.open(next((page / "03_dewarp").glob("*.png"))).convert("L"))
    (lr0, tb0), (lr1, tb1) = edge_ink(before), edge_ink(after)
    print(f"{page.parent.name}/{page.name}: of {total:4d} words {touching:3d} touch left/right, "
          f"{vtouch:3d} top/bottom; ink left/right {lr0:.4f} -> {lr1:.4f}, "
          f"top/bottom {tb0:.4f} -> {tb1:.4f}")
