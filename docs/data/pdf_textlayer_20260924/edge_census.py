"""Does Stage 03 push text off the edge of imported flat scans?

For every imported page: Tesseract words whose box touches the left or right
edge of the 03_dewarp image, and the ink in a 1 % border strip of the page
before (02_split) and after (03_dewarp) flattening. Ink that appears at the
border only after flattening was pushed there (and likely beyond it).
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

W = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")


def edge_ink(img: np.ndarray) -> float:
    h, w = img.shape
    b = max(2, w // 100)
    strip = np.concatenate([img[:, :b], img[:, -b:]], axis=1)
    return float((strip < 110).mean())


for page in sorted(W.glob("*/page_*")):
    res = json.loads((page / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
    touching = total = 0
    for sp in res["pages"]:
        wmax = sp["width"]
        for b in sp["blocks"]:
            for w in b.get("words") or []:
                total += 1
                x, ww = w["bbox"]["x"], w["bbox"]["w"]
                touching += x <= 1 or x + ww >= wmax - 1
    before = np.asarray(Image.open(next((page / "02_split").glob("*.png"))).convert("L"))
    after = np.asarray(Image.open(next((page / "03_dewarp").glob("*.png"))).convert("L"))
    print(f"{page.parent.name}/{page.name}: {touching:3d} of {total:4d} words touch the edge; "
          f"edge ink {edge_ink(before):.4f} -> {edge_ink(after):.4f}")
