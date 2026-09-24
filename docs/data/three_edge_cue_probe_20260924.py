"""Probe for docs/data/three_edge_cue_prereg_20260924.md (P1 mode c).

Cue: refuse a crop whose emitted box touches >= 3 frame edges exactly.
G1 split_eval rows with the cue on; G2 the labelled books padded by emit_pad;
G3 phone anchors against eye labels written before this ran.

    python docs/data/three_edge_cue_probe_20260924.py
Writes docs/data/three_edge_cue_20260924.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import book_boundary as BB  # noqa: E402
from pipeline.stage02_split import DEFAULTS, detect_gutter  # noqa: E402
from tools.split_eval import _clipped_fraction, load_anchor  # noqa: E402

EDGES = ("left", "top", "right", "bottom")
PARAMS = BB.resolve_params({"book_crop": {"gc_draws": 3, "gc_max_jitter": None}})  # config.yaml


def touched(box, w, h) -> list[str]:
    x0, y0, x1, y1 = box
    return [e for e, t in zip(EDGES, (x0 <= 0, y0 <= 0, x1 >= w, y1 >= h)) if t]


def detect(img):
    h, w = img.shape[:2]
    book = BB.find_book(img, PARAMS)
    t = touched(book.emit, w, h) if book.applied else []
    fires = book.applied and len(t) >= 3
    gc = book.diag.get("gc_draws") or []
    gc_margin = None
    if gc:  # diagnostic: GrabCut union BEFORE the search-box union, as padded
        u = gc[0]
        for b in gc[1:]:
            u = [min(u[0], b[0]), min(u[1], b[1]), max(u[2], b[2]), max(u[3], b[3])]
        gc_margin = dict(zip(EDGES, (u[0], u[1], w - u[2], h - u[3])))
    return book, t, fires, gc_margin


def gutter(img, book, fires):
    h, w = img.shape[:2]
    sx0, sy0, sx1, sy1 = (0, 0, w, h) if fires else book.search
    gray = cv2.cvtColor(img[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)
    gx, _ = detect_gutter(gray, DEFAULTS)
    return None if gx is None else gx + sx0


def main() -> int:
    out: dict = {"prereg": "docs/data/three_edge_cue_prereg_20260924.md",
                 "params": {k: PARAMS[k] for k in ("gc_draws", "emit_pad", "search_pad")}}

    # ---- G1 -------------------------------------------------------------
    gt = json.loads((REPO / "testset/gt/gutter.json").read_text("utf-8"))["spreads"]
    box_gt = json.loads((REPO / "testset/gt/book_box.json").read_text("utf-8"))["spreads"]
    rows, n_pass_off, n_pass_on, worst_on, n_crop = [], 0, 0, 0.0, 0
    for rid, spec in gt.items():
        img = load_anchor(rid, spec)
        h, w = img.shape[:2]
        book, t, fires, gcm = detect(img)
        n_crop += book.applied
        res = {}
        for arm, f in (("off", False), ("on", fires)):
            gx = gutter(img, book, f)
            emit = (0, 0, w, h) if (f or not book.applied) else book.emit
            hit = (gx is None) if spec.get("single") else (
                gx is not None and abs(gx - spec["gutter_x"]) <= spec["tol"])
            clip = (_clipped_fraction((h, w), box_gt[rid], emit)
                    if rid in box_gt else None)
            res[arm] = {"gx": gx, "hit": hit, "clip": clip}
        n_pass_off += res["off"]["hit"]
        n_pass_on += res["on"]["hit"]
        if res["on"]["clip"] is not None:
            worst_on = max(worst_on, res["on"]["clip"])
        rows.append({"id": rid, "applied": book.applied, "emit": list(book.emit),
                     "touched": t, "fires": fires, "gc_margin": gcm,
                     "search_touched": touched(book.search, w, h), **res})
        print(f"G1 {rid:14} crop={'Y' if book.applied else 'n'} touched={','.join(t) or '-':22}"
              f" fires={fires!s:5} off={res['off']['hit']!s:5} on={res['on']['hit']!s:5}")
    out["G1"] = {"rows": rows, "n_crop": n_crop, "pass_off": n_pass_off,
                 "pass_on": n_pass_on, "worst_clip_on": worst_on,
                 "same_rows": [r["off"]["hit"] for r in rows] == [r["on"]["hit"] for r in rows],
                 "PASS": n_pass_on == n_pass_off == 19 and worst_on == 0.0
                         and all(r["off"]["hit"] == r["on"]["hit"] for r in rows)}
    print("G1", {k: v for k, v in out["G1"].items() if k != "rows"})

    # ---- G2 -------------------------------------------------------------
    g2 = []
    for rid, L in box_gt.items():
        img = load_anchor(rid, gt.get(rid, L))
        h, w = img.shape[:2]
        lab = (L["x0"], L["y0"], L["x1"], L["y1"])
        e = BB._pad_box(lab, PARAMS["emit_pad"], w, h)
        s = BB._pad_box(lab, PARAMS["search_pad"], w, h)
        g2.append({"id": rid, "frame": [w, h], "label": list(lab),
                   "padded_emit": list(e), "touched_emit_pad": touched(e, w, h),
                   "touched_search_pad": touched(s, w, h)})
        print(f"G2 {rid:14} emit_pad touches {touched(e, w, h)}  search_pad {touched(s, w, h)}")
    out["G2"] = {"rows": g2, "PASS": all(len(r["touched_emit_pad"]) < 3 for r in g2)}
    print("G2 PASS", out["G2"]["PASS"])

    # ---- G3 -------------------------------------------------------------
    labels = json.loads((REPO / "docs/data/three_edge_cue_labels_20260924.json")
                        .read_text("utf-8"))["frames"]
    g3, false_fires, true_fires = [], [], []
    for L in labels:
        img = cv2.imread(str(REPO / L["frame"]))
        book, t, fires, gcm = detect(img)
        reach = {e for e, v in L["reach"].items() if v in ("yes", "near")}
        verdict = None
        if fires:
            verdict = "false" if len(set(t) & reach) >= 3 else "true"
            (false_fires if verdict == "false" else true_fires).append(L["frame"])
        g3.append({"frame": L["frame"], "scene": L["scene"], "applied": book.applied,
                   "reason": book.reason, "emit": list(book.emit), "touched": t,
                   "fires": fires, "reach": sorted(reach), "verdict": verdict,
                   "gc_margin": gcm})
        print(f"G3 {L['frame'][5:40]:36} crop={'Y' if book.applied else 'n'} "
              f"touched={','.join(t) or '-':22} fires={fires!s:5} {verdict or ''}")
    out["G3"] = {"rows": g3, "false_fires": false_fires, "true_fires": true_fires,
                 "n_crop": sum(r["applied"] for r in g3),
                 "PASS": not false_fires}
    print("G3", {k: v for k, v in out["G3"].items() if k != "rows"})

    need = ["jobs/20260829-084115-de3c20d3/page_002/01_fuse/anchor.png",
            "jobs/20260829-084115-de3c20d3/page_004/01_fuse/anchor.png"]
    out["positives_fire"] = all(p in true_fires for p in need)
    print("required positives fire:", out["positives_fire"])

    (REPO / "docs/data/three_edge_cue_20260924.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
