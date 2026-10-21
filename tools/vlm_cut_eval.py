"""May the vision model's book box CUT the frame? Graded as pre-registered.

``docs/data/vlm_cut_prereg_20261021.md`` fixed the rule, the populations and
the gates before any answer existed; this tool computes them and nothing else.
The owner allowed a model box to cut on 2026-10-21; the cut is made only when a
second question about the crop (``vlm_box.CHECK_PROMPT``) says no moved edge
runs through the book.

Model boxes are the RECORDED ones (the model is deterministic at temperature 0,
RESULTS 2026-08-29): the 21 testset rows from ``vlm_box_split_20260829.json``,
the owner's spreads from their ``split.json``, and spread 4's box from RESULTS
2026-09-24 (it was never written to a ``split.json``: the detector crops there).
Only the check question is asked, once per frame, and cached in
``docs/data/vlm_cut_check_20261021.json`` so a re-run grades the same answers.

    python -m tools.vlm_cut_eval                 # G1, G2, the check table
    python -m tools.vlm_cut_eval --text          # + G3 (split, dewarp, OCR both arms)

G4 (Stages 02-06 on a copy of the owner's spreads) is run with the stage CLIs
and read by eye; this tool prints only which owner frames the rule cuts.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

from pipeline import book_boundary as BB
from pipeline import stage02_split as S2
from pipeline import vlm_box as VLM
from tools import ocr_metrics as M
from tools.dewarp_ab import dewarp_halves
from tools.gate1_harness import (
    LANG_CODES, find_tesseract, load_config, median_word_height,
    resolve_tessdata_dir, run_tesseract, to_gray, upscale)
from tools.split_eval import (
    BOX_GT_PATH, GT_PATH, REPO, TESTSET, _clipped_fraction, load_anchor)

BOX_CACHE = REPO / "docs" / "data" / "vlm_box_split_20260829.json"
CHECK_CACHE = REPO / "docs" / "data" / "vlm_cut_check_20261021.json"
OWNER_JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
# The one owner box no split.json holds (RESULTS 2026-09-24, "three frame edges").
SPREAD4_BOX = (465, 624, 2709, 2368)
OWNER_LANG = "deu"          # the job's own job.json
PRIMARY_TARGETS = ("paleset_01", "paleset_02", "owner_01", "owner_03")


# --------------------------------------------------------------------------
# Frames and boxes
# --------------------------------------------------------------------------


def _owner_frame(n: int) -> np.ndarray:
    p = OWNER_JOB / f"page_{n:03d}" / "01_fuse" / "anchor.png"
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(p)
    return img


def _owner_box(n: int) -> tuple[int, int, int, int]:
    if n == 4:
        return SPREAD4_BOX
    d = json.loads((OWNER_JOB / f"page_{n:03d}" / "02_split" / "split.json")
                   .read_text(encoding="utf-8"))
    return tuple(d["vlm_box"]["box"])


def frames() -> list[dict]:
    """Every frame of populations T, O and O' with its recorded model box."""
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))["spreads"]
    boxes = json.loads(BOX_CACHE.read_text(encoding="utf-8"))["boxes"]
    out = [{"id": i, "pop": "T", "spec": spec,
            "load": (lambda i=i, spec=spec: load_anchor(i, spec)),
            "box": tuple(boxes[i][0]["box"]) if boxes.get(i) and boxes[i][0]["box"]
            else None, "cue": False}
           for i, spec in gt.items()]
    for n, pop in ((1, "O"), (3, "O"), (2, "O'"), (4, "O'")):
        out.append({"id": f"owner_{n:02d}", "pop": pop, "spec": None,
                    "load": (lambda n=n: _owner_frame(n)),
                    "box": _owner_box(n), "cue": pop == "O'"})
    return out


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------


def decide(img: np.ndarray, fr: dict, cache: dict, vp: dict
           ) -> tuple[BB.BookBoundary, BB.BookBoundary, dict]:
    """(shipped boundary, today's boundary, record) for one frame.

    Today's boundary is what ships without the cut: the detector, or the
    model-aimed search where it abstained. The shipped one adds the cut.
    """
    bp = BB.resolve_params({"book_crop": {"three_edge_abstain": True}}
                           if fr["cue"] else {})
    h, w = img.shape[:2]
    det = BB.find_book(img, bp)
    rec: dict = {"detector_applied": det.applied, "detector_reason": det.reason}
    box = fr["box"]
    if det.applied or box is None or VLM.plausible(box, w, h, vp):
        rec["route"] = "detector crops" if det.applied else "no usable model box"
        return det, det, rec
    today = BB.search_only(img, box, det, bp)
    cand = BB.model_cut(img, box, det, bp)
    rec["candidate"] = list(cand.emit) if cand.applied else None
    if not cand.applied:
        rec["route"] = "padded box reaches every frame edge; nothing to cut"
        return today, today, rec
    key = fr["id"]
    if key not in cache:
        ok, diag = VLM.check_cut(img, cand.emit, vp)
        if "refused" in diag and "edges" not in diag and "answer" not in diag:
            raise RuntimeError(f"{key}: the check could not be asked: {diag['refused']}")
        cache[key] = diag
        CHECK_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    diag = cache[key]
    rec["check"] = diag
    ok = "refused" not in diag
    rec["route"] = "CUT" if ok else f"check refused: {diag['refused']}"
    return (cand if ok else today), today, rec


def gutter(img: np.ndarray, book: BB.BookBoundary) -> tuple[int | None, dict]:
    sx0, sy0, sx1, sy1 = book.search
    g, d = S2.detect_gutter(cv2.cvtColor(img[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY),
                            S2.DEFAULTS)
    return (None if g is None else g + sx0), d


def edge_truth(cut: list[int], label: dict) -> dict[str, bool]:
    """Does the labelled book extend past each edge of the cut?"""
    x0, y0, x1, y1 = cut
    return {"left": label["x0"] < x0, "right": label["x1"] > x1,
            "top": label["y0"] < y0, "bottom": label["y1"] > y1}


# --------------------------------------------------------------------------
# G3: text, both arms, the same instrument
# --------------------------------------------------------------------------


def _ocr(binary: str, cfg: dict, bgr: np.ndarray, lang: str) -> list[M.TWord]:
    """``tools.dewarp_ab.ocr_text``'s path, keeping the words for their conf."""
    tcfg = cfg.get("tesseract", {})
    tessdata = resolve_tessdata_dir(cfg)
    oem, psm = int(tcfg.get("oem", 1)), int(tcfg.get("psm", 3))
    gray = to_gray(bgr)
    probe = M.parse_tsv(run_tesseract(binary, gray, lang, tessdata, oem, psm))
    scale = 2.0 if 0 < median_word_height(probe) < 20 else 1.0
    return M.parse_tsv(run_tesseract(binary, upscale(gray, scale), lang,
                                     tessdata, oem, psm))


def read_arm(img: np.ndarray, book: BB.BookBoundary, cfg: dict, binary: str,
             lang: str) -> dict:
    gx, _ = gutter(img, book)
    ex0, ey0, ex1, ey1 = book.emit
    emit = img[ey0:ey1, ex0:ex1]
    p = S2.resolve_params(cfg)
    pieces = S2.cut_pages(emit, None if gx is None else gx - ex0,
                          int(emit.shape[1] * p["margin_frac"]))
    halves = [(name, im) for name, im, _ in pieces]
    texts, n80, n = [], 0, 0
    for _name, im, _pd in dewarp_halves(halves, cfg, "auto"):
        words = _ocr(binary, cfg, im, lang)
        texts.append(M.tsv_words_to_text(words))
        n80 += sum(1 for w in words if w.conf >= 80)
        n += len(words)
    return {"gutter": gx, "text": "\n".join(texts), "conf_ge_80": n80, "words": n}


def _langs() -> dict[str, str]:
    with (TESTSET / "manifest.csv").open(encoding="utf-8") as f:
        return {r["image_id"]: (r["language"], r["gt_file"])
                for r in csv.DictReader(f)}


def token_diff(a: str, b: str) -> dict[str, list[str]]:
    from collections import Counter
    ca, cb = Counter(M.tokenize(a)), Counter(M.tokenize(b))
    return {"only_uncut": sorted((ca - cb).elements()),
            "only_cut": sorted((cb - ca).elements())}


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--text", action="store_true", help="also run G3")
    ap.add_argument("--json", type=Path,
                    default=REPO / "docs" / "data" / "vlm_cut_eval_20261021.json")
    args = ap.parse_args(argv)

    vp = VLM.resolve_params(load_config(REPO / "config.yaml"))
    box_gt = json.loads(BOX_GT_PATH.read_text(encoding="utf-8"))["spreads"]
    cache = (json.loads(CHECK_CACHE.read_text(encoding="utf-8"))
             if CHECK_CACHE.exists() else {})
    cfg = load_config(REPO / "config.yaml")
    binary = find_tesseract(cfg) if args.text else ""
    langs = _langs()

    rows: dict = {}
    print(f"{'id':14} {'pop':3} {'route':52} {'gutter':>6} {'hit':>4} {'clip':>6}")
    print("-" * 92)
    for fr in frames():
        img = fr["load"]()
        ship, today, rec = decide(img, fr, cache, vp)
        gx, _ = gutter(img, ship)
        rec["gutter"] = gx
        rec["emit"] = list(ship.emit)
        if fr["spec"] is not None:
            spec = fr["spec"]
            rec["hit"] = (gx is None if spec.get("single") else
                          gx is not None and abs(gx - spec["gutter_x"]) <= spec["tol"])
        if fr["id"] in box_gt:
            L = box_gt[fr["id"]]
            rec["clip_pct"] = round(_clipped_fraction(img.shape[:2], L, ship.emit), 3)
            if rec.get("candidate") and rec.get("check", {}).get("edges"):
                truth = edge_truth(rec["candidate"], L)
                rec["check_vs_truth"] = {
                    e: {"said": rec["check"]["edges"][e], "truth": truth[e]}
                    for e in rec["check"]["moved_edges"]}
        if args.text and rec["route"] == "CUT" and fr["pop"] == "T":
            lang_name, gt_file = langs.get(fr["id"], ("english", ""))
            lang = LANG_CODES.get(lang_name, "eng")
            a = read_arm(img, today, cfg, binary, lang)
            b = read_arm(img, ship, cfg, binary, lang)
            g3 = {"lang": lang,
                  "uncut": {k: a[k] for k in ("gutter", "conf_ge_80", "words")},
                  "cut": {k: b[k] for k in ("gutter", "conf_ge_80", "words")},
                  "d_conf_ge_80": b["conf_ge_80"] - a["conf_ge_80"],
                  "diff": token_diff(a["text"], b["text"])}
            if gt_file and gt_file.endswith(".txt"):
                gt_text = (TESTSET / gt_file).read_text(encoding="utf-8")
                gtt = M.tokenize(gt_text)
                for arm, r in (("uncut", a), ("cut", b)):
                    g3[arm]["word_acc"] = round(100 * M.word_accuracy(gtt, M.tokenize(r["text"])), 2)
                    g3[arm]["cer"] = round(100 * M.cer(gt_text, r["text"]), 2)
                g3["d_word_acc_pp"] = round(g3["cut"]["word_acc"] - g3["uncut"]["word_acc"], 2)
            rec["g3"] = g3
        rows[fr["id"]] = {"pop": fr["pop"], "box": list(fr["box"]) if fr["box"] else None,
                          **rec}
        clip = f"{rec['clip_pct']:.2f}%" if "clip_pct" in rec else ""
        hit = "" if "hit" not in rec else ("OK" if rec["hit"] else "FAIL")
        print(f"{fr['id']:14} {fr['pop']:3} {rec['route'][:52]:52} "
              f"{str(gx):>6} {hit:>4} {clip:>6}")
        if "g3" in rec:
            g = rec["g3"]
            extra = (f"  word acc {g['uncut']['word_acc']} -> {g['cut']['word_acc']}"
                     if "d_word_acc_pp" in g else "")
            print(f"{'':19}conf>=80 {g['uncut']['conf_ge_80']} -> "
                  f"{g['cut']['conf_ge_80']} ({g['d_conf_ge_80']:+d}){extra}")

    T = {k: r for k, r in rows.items() if r["pop"] == "T"}
    n_hit = sum(bool(r.get("hit")) for r in T.values())
    worst = max((r.get("clip_pct", 0.0) for r in T.values()), default=0.0)
    cut_targets = [k for k in PRIMARY_TARGETS if rows.get(k, {}).get("route") == "CUT"]
    g1 = n_hit == len(T) and worst == 0.0
    g2 = bool(cut_targets)
    g3_fail = []
    for k, r in T.items():
        g = r.get("g3")
        if not g:
            continue
        if g.get("d_word_acc_pp", 0.0) < -1.0 or g["d_conf_ge_80"] < -60:
            g3_fail.append(k)
    summary = {
        "G1": {"gutters": f"{n_hit}/{len(T)}", "worst_clip_pct": worst, "pass": g1},
        "G2": {"targets_cut": cut_targets, "pass": g2},
        "G3": ({"rows": [k for k, r in T.items() if r.get("g3")],
                "fail": g3_fail, "pass": not g3_fail} if args.text else "not run"),
        "cut_rows": [k for k, r in rows.items() if r["route"] == "CUT"],
    }
    print("-" * 92)
    print(json.dumps(summary, indent=1))
    args.json.write_text(json.dumps({"prereg": "docs/data/vlm_cut_prereg_20261021.md",
                                     "check_prompt": VLM.CHECK_PROMPT,
                                     "summary": summary, "rows": rows},
                                    indent=1), encoding="utf-8")
    print(f"wrote {args.json.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
