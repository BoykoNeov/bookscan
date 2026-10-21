"""Cut the nine hand-boxed close-ups (hand_boxes.json) and record them in
crops_manifest.json.

RUN ORDER (extraction rebuilds the manifest and drops these entries):
    python -X utf8 docs/data/panelread_20261021/coverage_census_v2.py
    python -X utf8 docs/data/panelread_20261021/extract_crops.py
    python -X utf8 docs/data/panelread_20261021/cut_hand.py [contact_sheet.jpg]
then read.py and score.py. The optional argument writes a contact sheet of every
close-up cut, which is how the cuts were inspected by eye before any reading.
"""
import json
import os
import sys

import cv2
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
from coverage_census import JOB  # noqa: E402

hb = json.load(open(os.path.join(D, "hand_boxes.json"), encoding="utf-8"))
man = json.load(open(os.path.join(D, "crops_manifest.json"), encoding="utf-8"))
thumbs = []
for e in man:
    h = hb.get(e["stem"])
    if h:
        spread = e["page"].split("__")[0]
        fr = cv2.imread(str(JOB / spread / "00_ingest" / h["frame"]))
        x0, y0, x1, y1 = h["box"]
        cv2.imwrite(os.path.join(D, "crops", e["stem"] + "__close.jpg"), fr[y0:y1, x0:x1],
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        e.update(close_crop=f"crops/{e['stem']}__close.jpg", close_frame=h["frame"],
                 close_box_in_frame=h["box"], close_method="hand")
    elif e.get("close_crop"):
        e["close_method"] = "auto"
    if e.get("close_crop"):
        c = cv2.imread(os.path.join(D, *e["close_crop"].split("/")))
        f = 300 / c.shape[0]
        thumbs.append(cv2.resize(c, (max(1, int(c.shape[1] * f)), 300)))
json.dump(man, open(os.path.join(D, "crops_manifest.json"), "w", encoding="utf-8"), indent=1)
if len(sys.argv) > 1:
    rows, cur, w = [], [], 0
    for t in thumbs:
        if w + t.shape[1] > 1800 and cur:
            rows.append(cur)
            cur, w = [], 0
        cur.append(t)
        w += t.shape[1] + 8
    rows.append(cur)
    W = max(sum(t.shape[1] + 8 for t in r) for r in rows)
    lines = []
    for r in rows:
        parts = []
        for t in r:
            parts += [t, np.full((300, 8, 3), 255, np.uint8)]
        rest = W - sum(t.shape[1] + 8 for t in r)
        if rest:
            parts.append(np.full((300, rest, 3), 255, np.uint8))
        lines.append(np.hstack(parts))
    cv2.imwrite(sys.argv[1], np.vstack(lines))
print(f"{len(thumbs)} close-up cuts in the manifest")
