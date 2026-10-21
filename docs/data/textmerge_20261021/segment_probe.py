"""Part-line ceiling check (amendment 2 of textmerge_prereg_20261021.md).

usage: segment_probe.py <page_dir> <regions.json> <out_json>
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage04_layout as S4  # noqa: E402
from pipeline import stage05_ocr as S5  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from tools.gate1_harness import find_tesseract  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from line_probe import norm, ed, tess_lines, bands_from  # noqa: E402

EXCLUDED = {"R157": {"frame_03.png"}, "R156": {"frame_01.png"}}
MIN_FRAC, FLOOR = 0.30, 0.20


def held_interval(H, lo, hi, w, fw, fh):
    xs = np.linspace(0, w, 400)
    pts = np.float32([[x, y] for y in (lo, hi) for x in xs]).reshape(-1, 1, 2)
    q = cv2.perspectiveTransform(pts, H).reshape(2, len(xs), 2)
    mx, my = 0.01 * fw, 0.01 * fh
    ok = ((q[..., 0] >= mx) & (q[..., 0] <= fw - mx)
          & (q[..., 1] >= my) & (q[..., 1] <= fh - my)).all(0)
    best, s = (0, 0), None
    for i, v in enumerate(list(ok) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s > best[1] - best[0]:
                best = (s, i)
            s = None
    if best[1] - best[0] < 2:
        return None
    return float(xs[best[0]]), float(xs[best[1] - 1])


def position_gt(gt_tokens, anchor_words, w):
    """x centre per reference token, from the anchor's line reading."""
    a_tok = [t for _, t in anchor_words]
    pos = [None] * len(gt_tokens)
    sm = difflib.SequenceMatcher(a=gt_tokens, b=a_tok, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                pos[i1 + k] = anchor_words[j1 + k][0]
    known = [(i, p) for i, p in enumerate(pos) if p is not None]
    ext = [(-1, 0.0)] + known + [(len(gt_tokens), float(w))]
    for i in range(len(gt_tokens)):
        if pos[i] is None:
            lo = max((k for k in ext if k[0] < i), key=lambda k: k[0])
            hi = min((k for k in ext if k[0] > i), key=lambda k: k[0])
            pos[i] = lo[1] + (hi[1] - lo[1]) * (i - lo[0]) / (hi[0] - lo[0])
    return pos


def main(page: Path, regions_path: Path, out: Path) -> int:
    cfg = S4.load_config(Path(r"M:\claud_projects\bookscan\config.yaml"))
    binary = find_tesseract(cfg)
    params = FH.resolve_params(cfg)
    regions = json.loads(regions_path.read_text(encoding="utf-8"))
    page_img = cv2.imread(str(page / "03_dewarp" / "single.png"), cv2.IMREAD_COLOR)
    frames = [f for f in S7._capture_frames(page, params) if f.name != "frame_00.png"]
    res = {}
    for name, r in regions.items():
        gt_lines = [norm(l) for l in (regions_path.parent / r["gt"]).read_text(
            encoding="utf-8").splitlines() if l.strip()]
        x, y, w, h = r["box"]
        crop = page_img[y:y + h, x:x + w]
        aw, sc = S5.ocr_subpage(binary, cfg, crop, "eng")
        tl = tess_lines(aw)
        assert len(tl) == len(gt_lines), (name, len(tl), len(gt_lines))
        spans = [[min(t.top for t in g) / sc, max(t.top + t.height for t in g) / sc] for g in tl]
        bands = bands_from(spans, h)
        anchor = [sorted(((t.left + t.width / 2) / sc, t.text) for t in g) for g in tl]
        wordw = [np.mean([t.width / sc for t in g]) for g in tl]
        gt_tok = [l.split() for l in gt_lines]
        gt_pos = [position_gt(gt_tok[i], [(xx, norm(tt)) for xx, tt in anchor[i]], w)
                  for i in range(len(gt_lines))]
        covered = [np.zeros(len(t), bool) for t in gt_tok]
        segs = []
        for idx in frames:
            if idx.name in EXCLUDED.get(name, ()):
                continue
            got = FH._match(crop, idx, params)
            img = idx.image
            if got is None or img is None or not FH._sane(got[0]) \
                    or got[1] < int(params["min_inliers"]):
                continue
            H = got[0]
            fh, fw = img.shape[:2]
            inter = {}
            for i, (lo, hi) in enumerate(bands):
                iv = held_interval(H, lo, hi, w, fw, fh)
                if iv and iv[1] - iv[0] >= MIN_FRAC * w:
                    inter[i] = (iv[0] + wordw[i], iv[1] - wordw[i])
            if not inter:
                continue
            corners = cv2.perspectiveTransform(np.float32(
                [[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2), H).reshape(-1, 2)
            X0, Y0 = (int(max(0, v)) for v in corners.min(0))
            X1, Y1 = int(min(fw, corners[:, 0].max())), int(min(fh, corners[:, 1].max()))
            sub = img[Y0:Y1, X0:X1]
            dx, dy = corners[1] - corners[0]
            k = int(np.round(np.degrees(np.arctan2(dy, dx)) / 90.0)) % 4
            up = np.ascontiguousarray(np.rot90(sub, k))
            cw, csc = S5.ocr_subpage(binary, cfg, up, "eng")
            Hi = np.linalg.inv(H)
            mapped = []
            for t in cw:
                r_, c_ = (t.top + t.height / 2) / csc, (t.left + t.width / 2) / csc
                hh, ww = up.shape[:2]
                for _ in range(k):
                    r_, c_ = c_, hh - 1 - r_
                    hh, ww = ww, hh
                p = cv2.perspectiveTransform(np.float32([[[X0 + c_, Y0 + r_]]]), Hi)[0, 0]
                mapped.append((float(p[0]), float(p[1]), t.text))
            for i, (xl, xr) in inter.items():
                lo, hi = bands[i]
                c_txt = norm(" ".join(t for xx, yy, t in sorted(mapped)
                                      if lo <= yy < hi and xl <= xx <= xr))
                a_txt = norm(" ".join(t for xx, t in anchor[i] if xl <= xx <= xr))
                sel = [j for j, p in enumerate(gt_pos[i]) if xl <= p <= xr]
                g_txt = " ".join(gt_tok[i][j] for j in sel)
                covered[i][sel] = True
                if not g_txt:
                    continue
                segs.append({"frame": idx.name, "line": i, "x": [round(xl), round(xr)],
                             "gt": g_txt, "anchor": a_txt, "closeup": c_txt,
                             "n": len(g_txt), "a_ed": ed(g_txt, a_txt),
                             "c_ed": ed(g_txt, c_txt)})
            idx.release()
            print(name, idx.name, "segments", len(inter), flush=True)
        n_all = sum(len(" ".join(t)) for t in gt_tok)
        n_cov = sum(len(" ".join(t for t, c in zip(gt_tok[i], covered[i]) if c))
                    for i in range(len(gt_tok)))
        n = sum(s["n"] for s in segs)
        per_frame = {}
        for s in segs:
            f = per_frame.setdefault(s["frame"], {"n": 0, "a_ed": 0, "c_ed": 0, "segments": 0})
            f["n"] += s["n"]; f["a_ed"] += s["a_ed"]; f["c_ed"] += s["c_ed"]; f["segments"] += 1
        for f in per_frame.values():
            f["a_cer"] = round(100 * f["a_ed"] / f["n"], 2)
            f["c_cer"] = round(100 * f["c_ed"] / f["n"], 2)
        summ = {"segments": len(segs), "coverage": round(n_cov / n_all, 3),
                "a": round(100 * sum(s["a_ed"] for s in segs) / n, 2) if n else None,
                "m": round(100 * sum(s["c_ed"] for s in segs) / n, 2) if n else None,
                "per_frame": per_frame}
        print(name, json.dumps(summ), flush=True)
        res[name] = {"summary": summ, "segments": segs}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
