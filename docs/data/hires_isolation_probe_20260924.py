"""P7: does page_022__left block 5 upgrade when searched on its own, today?

RESULTS 2026-08-29 recorded it upgrading "reproducibly when run on its own"
(before RANSAC was seeded) while every batch assemble leaves it at the page crop.
This runs the SAME call Stage 07 makes (``_upgrade_figure`` with the config's
``figure_hires`` params, the spread's own frame index, the page image Stage 07
reads) on that one block, three times in one process and with the RNG seed
changed around it, and prints each candidate source the search admitted.

    python docs/data/hires_isolation_probe_20260924.py <job_dir>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from pipeline.page_model import Block  # noqa: E402

PAGE, SUB, BLOCK = "page_022", "left", 5


def trace(crop, frames, params) -> list[dict]:
    """Which gate each frame stops at - the same gates as FH.candidates, in order."""
    import numpy as np
    h, w = crop.shape[:2]
    rows = []
    for idx in frames:
        got = FH._match(crop, idx, params)
        if got is None:
            rows.append({"frame": idx.name, "stop": "no match"}); continue
        H, inl, good = got
        r = {"frame": idx.name, "inliers": inl, "good": good}
        if inl < int(params["min_inliers"]) or not FH._sane(H):
            rows.append({**r, "stop": "inliers/sane"}); continue
        img = idx.image
        fh, fw = img.shape[:2]
        cov = FH._coverage(H, w, h, fw, fh); r["coverage"] = round(cov, 3)
        if cov < float(params["min_piece"]):
            rows.append({**r, "stop": "min_piece"}); continue
        sc = FH.local_scale(H, w / 2.0, h / 2.0); r["scale"] = round(sc, 3)
        if not (float(params["min_scale"]) <= sc <= float(params["max_scale"])):
            rows.append({**r, "stop": "scale"}); continue
        Hi = np.linalg.inv(H)
        back = cv2.warpPerspective(img, Hi, (w, h))
        bm = cv2.warpPerspective(np.full((fh, fw), 255, np.uint8), Hi, (w, h))
        n = FH._ncc(crop, back, bm); r["ncc"] = round(n, 3)
        rows.append({**r, "stop": "ncc" if n < float(params["min_ncc"]) else "ADMITTED"})
    return rows


def main(job: Path) -> int:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    params = FH.resolve_params(cfg)
    doc = json.loads((job / "document.json").read_text(encoding="utf-8"))
    page = next(p for p in doc["pages"] if p["page_id"] == f"{PAGE}__{SUB}")
    blk = Block.model_validate(next(b for b in page["blocks"] if b["id"] == BLOCK))
    pd = job / PAGE
    img = cv2.imread(str(pd / "03_dewarp" / f"{SUB}.png"), cv2.IMREAD_COLOR)
    print("block", blk.type.value, blk.bbox.model_dump(), "page", img.shape)
    frames = S7._capture_frames(pd, params)
    print("frames", len(frames))
    b = blk.bbox
    crop = img[b.y:b.y2, b.x:b.x2]
    out = {"bbox": blk.bbox.model_dump(), "runs": []}
    for run in range(3):
        cands = FH.candidates(crop, frames, params)
        got = FH.compose(crop, cands, params)
        with tempfile.TemporaryDirectory() as td:
            up = S7._upgrade_figure(blk.model_copy(deep=True), img, frames,
                                    params, Path(td), "probe")
        row = {"n_candidates": len(cands),
               "candidates": [c.src.as_dict() for c in cands],
               "gate_trace": trace(crop, frames, params),
               "compose": None if got is None else {"size": list(got[0].shape[:2]),
                                                    "used": [s.frame for s in got[1]]},
               "upgrade": up,
               "decode_failed": [f.name for f in frames if f.decode_failed]}
        out["runs"].append(row)
        print(json.dumps(row, default=str)[:900])
    (REPO / "docs/data/hires_isolation_20260924.json").write_text(
        json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
