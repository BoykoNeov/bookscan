"""Downscaled anchors of sofa spreads 1-4 with the emitted box (green) and the
GrabCut draw (red) drawn on, for looking. Output stays in this folder."""
import json
from pathlib import Path
import cv2
REPO = Path(r"M:\claud_projects\bookscan")
HERE = Path(__file__).parent
rec = json.loads((HERE / "gc_jitter_sofa_20260924.json").read_text())
job = REPO / "jobs/20260829-084115-de3c20d3"
for i in range(1, 5):
    img = cv2.imread(str(job / f"page_{i:03d}/01_fuse/anchor.png"))
    r = rec[f"sofa_{i}"]
    d = r["draws_8"][0]
    if d:
        cv2.rectangle(img, (d[0] + 6, d[1] + 6), (d[2] - 6, d[3] - 6), (0, 0, 255), 14)
    e = r["emit"]
    cv2.rectangle(img, (e[0] + 20, e[1] + 20), (e[2] - 20, e[3] - 20), (0, 255, 0), 10)
    s = cv2.resize(img, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(HERE / f"gc_jitter_sofa_{i}_20260924.jpg"), s)
