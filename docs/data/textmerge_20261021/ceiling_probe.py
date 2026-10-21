"""Ceiling check: does a full-size close-up read a region better than the
whole-spread photograph? Pre-registration: docs/data/textmerge_prereg_20261021.md.

usage: ceiling_probe.py <page_dir> <regions.json> <out_json>

regions.json: {"<name>": {"box": [x, y, w, h], "gt": "<file next to regions.json>"}}
with the box in 03_dewarp/single.png pixels.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage04_layout as S4  # noqa: E402
from pipeline import stage05_ocr as S5  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from tools import ocr_metrics as M  # noqa: E402
from tools.gate1_harness import find_tesseract  # noqa: E402

TRANS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                       "\u2013": "-", "\u2014": "-"})


def norm(text: str) -> str:
    return M.normalize_text(text.translate(TRANS))


def read(binary, cfg, bgr):
    words, scale = S5.ocr_subpage(binary, cfg, bgr, "eng")
    return words, scale


def score(gt: str, words) -> dict:
    hyp = norm(M.tsv_words_to_text(words))
    g = norm(gt)
    gt_tok, hyp_tok = g.split(), hyp.split()
    import difflib
    sm = difflib.SequenceMatcher(a=gt_tok, b=hyp_tok, autojunk=False)
    diffs = [{"op": op, "gt": " ".join(gt_tok[i1:i2]), "ocr": " ".join(hyp_tok[j1:j2])}
             for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return {"cer": round(100 * M.cer(g, hyp), 2), "wer": round(100 * M.wer(gt_tok, hyp_tok), 2),
            "n_words": len(hyp_tok), "diffs": diffs, "text": hyp}


def main(page: Path, regions_path: Path, out: Path) -> int:
    cfg = S4.load_config(Path(r"M:\claud_projects\bookscan\config.yaml"))
    binary = find_tesseract(cfg)
    params = FH.resolve_params(cfg)
    regions = json.loads(regions_path.read_text(encoding="utf-8"))
    page_img = cv2.imread(str(page / "03_dewarp" / "single.png"), cv2.IMREAD_COLOR)
    frames = [f for f in S7._capture_frames(page, params) if f.name != "frame_00.png"]
    res = {}
    for name, r in regions.items():
        gt = (regions_path.parent / r["gt"]).read_text(encoding="utf-8")
        x, y, w, h = r["box"]
        crop = page_img[y:y + h, x:x + w]
        words, _ = read(binary, cfg, crop)
        row = {"anchor": score(gt, words), "closeups": {}, "partial": [], "absent": []}
        for idx in frames:
            got = FH._match(crop, idx, params)
            img = idx.image
            if got is None or img is None or not FH._sane(got[0]):
                row["absent"].append(idx.name)
                continue
            H, inl, good = got
            fh, fw = img.shape[:2]
            cov = FH._coverage(H, w, h, fw, fh)
            corners = cv2.perspectiveTransform(
                np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2), H).reshape(-1, 2)
            if inl < int(params["min_inliers"]):
                row["absent"].append(idx.name)
                continue
            if cov < 1.0:
                row["partial"].append({"frame": idx.name, "coverage": round(cov, 3)})
                continue
            bx0, by0 = corners.min(0)
            bx1, by1 = corners.max(0)
            mx, my = 0.02 * (bx1 - bx0), 0.02 * (by1 - by0)
            X0, Y0 = int(max(0, bx0 - mx)), int(max(0, by0 - my))
            X1, Y1 = int(min(fw, bx1 + mx)), int(min(fh, by1 + my))
            sub = img[Y0:Y1, X0:X1]
            # quarter turns k (np.rot90, counter-clockwise) that make the region's
            # top edge (corner 0 -> 1) point right
            dx, dy = corners[1] - corners[0]
            ang = np.degrees(np.arctan2(dy, dx))          # image coords, y down
            k = int(np.round(ang / 90.0)) % 4             # rot90 by k undoes it
            up = np.ascontiguousarray(np.rot90(sub, k))
            cw, sc = read(binary, cfg, up)
            poly = corners.astype(np.float32).reshape(-1, 1, 2)

            def to_frame(px, py):
                # np.rot90(a, k): k=1 maps (r, c) -> (W-1-c, r); invert step by step
                r, c = py, px
                hh, ww = up.shape[:2]
                for _ in range(k):
                    # inverse of one CCW quarter turn on an array of shape (hh, ww)
                    r, c = c, hh - 1 - r
                    hh, ww = ww, hh
                return X0 + c, Y0 + r

            kept = []
            for t in cw:
                fx, fy = to_frame((t.left + t.width / 2) / sc, (t.top + t.height / 2) / sc)
                if cv2.pointPolygonTest(poly, (float(fx), float(fy)), False) >= 0:
                    kept.append(t)
            s = score(gt, kept)
            s.update(scale=round(FH.local_scale(H, w / 2, h / 2), 3), inliers=inl)
            row["closeups"][idx.name] = s
            idx.release()
            print(name, idx.name, "cer", s["cer"], "scale", s["scale"], flush=True)
        cers = [c["cer"] for c in row["closeups"].values()]
        row["summary"] = {"anchor_cer": row["anchor"]["cer"],
                          "n_whole": len(cers), "n_partial": len(row["partial"]),
                          "n_absent": len(row["absent"]),
                          "median_cer": statistics.median(cers) if cers else None,
                          "best_cer": min(cers) if cers else None}
        print(name, row["summary"], flush=True)
        res[name] = row
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
