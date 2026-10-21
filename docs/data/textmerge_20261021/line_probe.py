"""Line-level ceiling check (amendment of textmerge_prereg_20261021.md): on each
printed line a close-up holds whole, does the close-up read it better than the
whole-spread photograph?

usage: line_probe.py <page_dir> <regions.json> <out_json>
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


def norm(s: str) -> str:
    return " ".join(s.translate(TRANS).split())


def ed(a: str, b: str) -> int:
    """character edit distance"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tess_lines(words):
    groups: dict = {}
    for t in words:
        groups.setdefault((t.block_num, t.par_num, t.line_num), []).append(t)
    return sorted(groups.values(), key=lambda g: min(t.top for t in g))


def proj_lines(crop, n):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    rows = (b > 0).mean(1) > 0.01
    runs, s = [], None
    for y, on in enumerate(list(rows) + [False]):
        if on and s is None:
            s = y
        elif not on and s is not None:
            runs.append([s, y])
            s = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 4:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] >= 10]
    return merged if len(merged) == n else None


def bands_from(spans, h):
    """[top, bottom] per line -> bands running halfway to the neighbours."""
    cs = [(a + b) / 2 for a, b in spans]
    out = []
    for i, (a, b) in enumerate(spans):
        lo = 0 if i == 0 else (spans[i - 1][1] + a) / 2
        hi = h if i == len(spans) - 1 else (b + spans[i + 1][0]) / 2
        out.append((lo, hi))
    return out


def assign(points_words, bands):
    """[(x, y, text)] in region coords -> list of line texts (x order)."""
    lines = [[] for _ in bands]
    for x, y, txt in points_words:
        for i, (lo, hi) in enumerate(bands):
            if lo <= y < hi:
                lines[i].append((x, txt))
                break
    return [" ".join(t for _, t in sorted(l)) for l in lines]


def main(page: Path, regions_path: Path, out: Path) -> int:
    cfg = S4.load_config(Path(r"M:\claud_projects\bookscan\config.yaml"))
    binary = find_tesseract(cfg)
    params = FH.resolve_params(cfg)
    regions = json.loads(regions_path.read_text(encoding="utf-8"))
    page_img = cv2.imread(str(page / "03_dewarp" / "single.png"), cv2.IMREAD_COLOR)
    frames = [f for f in S7._capture_frames(page, params) if f.name != "frame_00.png"]
    res = {}
    for name, r in regions.items():
        gt = [norm(l) for l in (regions_path.parent / r["gt"]).read_text(
            encoding="utf-8").splitlines() if l.strip()]
        x, y, w, h = r["box"]
        crop = page_img[y:y + h, x:x + w]
        aw, sc = S5.ocr_subpage(binary, cfg, crop, "eng")
        tl = tess_lines(aw)
        if len(tl) == len(gt):
            spans = [[min(t.top for t in g) / sc, max(t.top + t.height for t in g) / sc]
                     for g in tl]
            how = "tesseract lines"
        else:
            spans = proj_lines(crop, len(gt))
            how = f"projection (tesseract gave {len(tl)})"
        if spans is None:
            res[name] = {"dropped": f"no line count match (tesseract {len(tl)}, gt {len(gt)})"}
            print(name, res[name], flush=True)
            continue
        bands = bands_from(spans, h)
        anchor_lines = assign([((t.left + t.width / 2) / sc, (t.top + t.height / 2) / sc,
                                t.text) for t in aw], bands)
        per_line = [{"gt": gt[i], "anchor": norm(anchor_lines[i]),
                     "anchor_ed": ed(gt[i], norm(anchor_lines[i])), "closeups": {}}
                    for i in range(len(gt))]
        for idx in frames:
            got = FH._match(crop, idx, params)
            img = idx.image
            if got is None or img is None or not FH._sane(got[0]) \
                    or got[1] < int(params["min_inliers"]):
                continue
            H = got[0]
            fh, fw = img.shape[:2]
            mx, my = 0.01 * fw, 0.01 * fh
            held = []
            for i, (lo, hi) in enumerate(bands):
                q = cv2.perspectiveTransform(np.float32(
                    [[0.01 * w, lo], [0.99 * w, lo], [0.99 * w, hi], [0.01 * w, hi]]
                ).reshape(-1, 1, 2), H).reshape(-1, 2)
                if ((q[:, 0] >= mx) & (q[:, 0] <= fw - mx)
                        & (q[:, 1] >= my) & (q[:, 1] <= fh - my)).all():
                    held.append(i)
            if not held:
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
            pts = []
            for t in cw:
                r_, c_ = (t.top + t.height / 2) / csc, (t.left + t.width / 2) / csc
                hh, ww = up.shape[:2]
                for _ in range(k):
                    r_, c_ = c_, hh - 1 - r_
                    hh, ww = ww, hh
                p = cv2.perspectiveTransform(np.float32([[[X0 + c_, Y0 + r_]]]), Hi)[0, 0]
                if 0 <= p[0] <= w:
                    pts.append((float(p[0]), float(p[1]), t.text))
            lines = assign(pts, bands)
            for i in held:
                hyp = norm(lines[i])
                per_line[i]["closeups"][idx.name] = {"text": hyp, "ed": ed(per_line[i]["gt"], hyp)}
            idx.release()
            print(name, idx.name, "holds", len(held), "lines", flush=True)
        held_lines = [p for p in per_line if p["closeups"]]
        n = sum(len(p["gt"]) for p in held_lines)
        if n:
            a = 100 * sum(p["anchor_ed"] for p in held_lines) / n
            m = 100 * sum(statistics.median(c["ed"] for c in p["closeups"].values())
                          for p in held_lines) / n
            b = 100 * sum(min(c["ed"] for c in p["closeups"].values())
                          for p in held_lines) / n
        else:
            a = m = b = None
        summ = {"lines": how, "n_lines": len(gt), "held_lines": len(held_lines),
                "gt_chars_held": n, "a": a and round(a, 2), "m": m and round(m, 2),
                "b": b and round(b, 2),
                "anchor_all_lines_cer": round(100 * sum(p["anchor_ed"] for p in per_line)
                                              / sum(len(p["gt"]) for p in per_line), 2)}
        print(name, summ, flush=True)
        res[name] = {"summary": summ, "lines": per_line}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
