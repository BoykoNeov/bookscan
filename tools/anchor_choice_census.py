"""Anchor-choice census — does a book-box-restricted sharpness score decide anything?

Stage 01 picks the anchor as the SHARPEST full-spread frame, and sharpness is
variance-of-Laplacian over the WHOLE frame. ``stage01_fuse``'s docstring and
``book_boundary``'s both carry the same open item: on the real lap captures
40-55 % of the frame is room, so that score rewards cluttered backgrounds
(chair edges, cables) over legible text, and the fix "rank by sharpness inside
the book box" was left for whoever had the crop. The crop shipped 2026-08-19
(``pipeline/book_boundary.py``), so this asks the question the item was waiting
on — and answers it before the change is written, not after.

Two arms, on every committed fixture that has more than one frame of the same
spread:

  * **Geometry.** Partition each set with ``stage01_fuse.partition_frames``,
    unmodified and imported, under three scores, and report where the picks
    differ: whole-frame sharpness (the incumbent), sharpness inside
    ``find_book``'s emit box (the naive challenger), and sharpness inside the
    UNGATED emit box (the same box computed for every frame, whether or not the
    abstain gate would let Stage 02 act on it).

    The third arm exists because the second is not a fair comparison. Variance
    of Laplacian rises when smooth pixels are removed, so a frame whose crop
    applied is scored on page-only pixels while a frame that abstained is still
    carrying its room. The abstain gate answers "should we CUT here", which has
    nothing to do with "which frame is the better photograph"; a set that mixes
    cropped and abstaining candidates would otherwise be decided by that
    asymmetry rather than by focus.
  * **OCR.** Tesseract on each frame standalone, conf >= 80 word count, same
    instrument as ``docs/data/stitch_and_orientation_20260819.json``. This says
    whether the incumbent's pick is even RIGHT — a selector that changes nothing
    is only good news if what it keeps is the better photograph.

Both arms are needed because either alone is misleading. "The metrics agree"
does not mean the selector is good, and "the pick is wrong" does not mean this
metric would fix it.

Frames are loaded through ``tools.normalize.load_upright_bgr`` — the pipeline's
own resolver — not by trusting EXIF. That is not a detail: these JPEGs carry a
MISLEADING pure-rotation tag (Stage 00's docstring says so, and the tags differ
WITHIN a set here — ``skewset_en_02`` is 8 and 6), so an EXIF-transposed load
feeds Tesseract sideways pixels. Measured while building this: on the
EXIF-transposed load ``zoomset_en_02_f01`` reads 30 words against the 160
recorded in ``stitch_and_orientation_20260819.json``. Neither sharpness nor OCR
is comparable across a 90-degree difference, so the whole OCR arm would have
been noise.

SUPERSEDED IN PART 2026-08-26. This tool's OCR arm scores the RAW FLAT FRAME,
which is why its "the selector picks a worse photograph on three sets" did not
survive contact with the pipeline's geometry: ``tools/anchor_downstream_census.py``
re-runs the same instrument after the book crop, the gutter cut and Stage 03, and
finds 0 of 9 incumbent errors at a pre-registered bar (flat 1, crop+split 2).
Keep using this tool for the WINDOW question and the sharpness arms; do not cite
its OCR arm as evidence about anchor quality. See ``docs/RESULTS.md`` 2026-08-26.

Usage:
    python -m tools.anchor_choice_census [--json docs/data/<name>.json] [--no-ocr]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

from pipeline.book_boundary import (
    find_book,
    grabcut_box,
    paper_mask,
    resolve_params as book_params,
    search_box,
)
from pipeline.stage00_ingest import sharpness
from pipeline.stage01_fuse import DEFAULTS as FUSE_DEFAULTS, partition_frames
from tools import normalize as N
from tools.gate1_harness import (
    find_tesseract,
    resolve_tessdata_dir,
    run_tesseract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTSET = REPO_ROOT / "testset"

LANG_CODE = {"english": "eng", "german": "deu", "italian": "ita",
             "bulgarian": "bul"}


# --------------------------------------------------------------------------
# The fixture sets (every committed group of frames showing the SAME spread)
# --------------------------------------------------------------------------


def discover_sets() -> dict[str, list[str]]:
    """Multi-frame sets, read from the committed manifests — never hard-coded.

    Three families: the multi-zoom sets, the multi-view (skew) pairs, and the
    re-shoots in ``manifest.csv``, which are named ``<base>_<HHMMSS>`` beside a
    plain ``<base>`` and are the same spread shot again seconds later.
    """
    sets: dict[str, list[str]] = {}

    zm = json.loads((TESTSET / "zoomset_manifest.json").read_text("utf-8"))
    for name, spec in zm.get("sets", {}).items():
        sets[name] = [f["image_id"] for f in spec["frames"]]

    sm = json.loads((TESTSET / "skewset_manifest.json").read_text("utf-8"))
    for name, spec in sm.items():
        if name == "_doc":
            continue
        sets[name] = [Path(f).stem for f in spec["frames"]]

    ids = [r["image_id"] for r in _manifest_rows()]
    grouped = set().union(*(set(v) for v in sets.values())) if sets else set()
    for i in ids:
        if i in grouped:
            continue
        base, _, stamp = i.rpartition("_")
        if base in ids and stamp.isdigit():
            sets.setdefault(base, [base]).append(i)
    return {k: v for k, v in sets.items() if len(v) > 1}


def _manifest_rows() -> list[dict]:
    with open(TESTSET / "manifest.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def languages() -> dict[str, str]:
    return {r["image_id"]: LANG_CODE.get(r["language"], "eng")
            for r in _manifest_rows()}


def load_upright(image_id: str, binary: str | None, tessdata: str | None,
                 cfg: dict) -> tuple[np.ndarray, N.OrientInfo]:
    """Upright BGR via the pipeline's own cascade — see the module docstring."""
    ing = (cfg.get("ingest", {}) or {})
    return N.load_upright_bgr(
        TESTSET / f"{image_id}.jpg", binary, tessdata,
        min_conf=float(ing.get("min_osd_conf", N.DEFAULT_MIN_OSD_CONF)),
        min_conf_180=float(ing.get("min_osd_conf_180",
                                   N.DEFAULT_MIN_OSD_CONF_180)))


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def ungated_emit_box(image: np.ndarray, p: dict):
    """``find_book``'s emit box with the abstain/plausibility gates removed.

    Same construction as ``find_book`` (GrabCut box, or the padded raw mask bbox
    if that collapses, unioned with the search box) — only the decision to ACT
    on it is dropped, because here the box is a scoring window, not a cut. Falls
    back to the whole frame when the paper mask finds nothing at all.
    """
    h, w = image.shape[:2]
    comp, sc = paper_mask(image, p)
    if comp is None:
        return (0, 0, w, h), "no_mask"
    sbox = search_box(comp, sc, p, w, h)
    ebox = grabcut_box(image, p) if p.get("grabcut", True) else None
    src = "grabcut"
    if ebox is None:
        ys, xs = np.nonzero(comp)
        raw = (int(xs.min() / sc), int(ys.min() / sc),
               int(xs.max() / sc), int(ys.max() / sc))
        bw, bh = raw[2] - raw[0], raw[3] - raw[1]
        pad = float(p["fallback_pad"])
        ebox = (max(0, int(raw[0] - bw * pad)), max(0, int(raw[1] - bh * pad)),
                min(w, int(raw[2] + bw * pad)), min(h, int(raw[3] + bh * pad)))
        src = "mask_bbox_fallback"
    box = (min(ebox[0], sbox[0]), min(ebox[1], sbox[1]),
           max(ebox[2], sbox[2]), max(ebox[3], sbox[3]))
    return box, src


def conf_ge_80(tsv: str) -> tuple[int, float]:
    """(words at conf >= 80, mean conf over all words) from Tesseract TSV."""
    confs: list[float] = []
    for line in tsv.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            confs.append(float(parts[10]))
        except ValueError:
            continue
    if not confs:
        return 0, 0.0
    return sum(1 for c in confs if c >= 80.0), round(float(np.mean(confs)), 1)


def measure_set(name: str, ids: list[str], cfg: dict, do_ocr: bool) -> dict:
    langs = languages()
    bp = book_params(cfg)
    tcfg = cfg.get("tesseract", {})
    binary = find_tesseract(cfg)
    tessdata = resolve_tessdata_dir(cfg)
    if binary is None:
        raise RuntimeError(
            "Tesseract not found — it resolves orientation here, so without it "
            "every number in this census would be measured on possibly-sideways "
            "pixels. Fix config.yaml tesseract.binary.")

    frames: list[dict] = []
    for i in ids:
        img, oinfo = load_upright(i, binary, tessdata, cfg)
        h, w = img.shape[:2]
        bb = find_book(img, bp)
        x0, y0, x1, y1 = bb.emit
        (u0, v0, u1, v1), ubox_src = ungated_emit_box(img, bp)
        row = {
            "id": i, "width": w, "height": h,
            "applied_rotate": oinfo.applied_rotate,
            "orient_method": oinfo.method,
            "crop_applied": bb.applied,
            "crop_reason": bb.reason,
            "emit_area_frac": bb.diag.get("emit_area_frac"),
            "box_is_frame": bb.emit == (0, 0, w, h),
            "sharp_whole_frame": round(sharpness(img), 1),
            "sharp_book_box": round(sharpness(img[y0:y1, x0:x1]), 1),
            "sharp_book_box_ungated": round(sharpness(img[v0:v1, u0:u1]), 1),
            "ungated_box_area_frac": round(((u1 - u0) * (v1 - v0)) / float(w * h), 3),
            "ungated_box_source": ubox_src,
            "ocr_conf_ge_80": None, "ocr_mean_conf": None,
        }
        if do_ocr:
            tsv = run_tesseract(binary, img, langs.get(i, "eng"), tessdata,
                                int(tcfg.get("oem", 1)), int(tcfg.get("psm", 3)))
            row["ocr_conf_ge_80"], row["ocr_mean_conf"] = conf_ge_80(tsv)
        frames.append(row)

    area_frac = float(FUSE_DEFAULTS["fullspread_area_frac"])

    def pick(key: str) -> tuple[str, list[str]]:
        rows = [{"name": f["id"], "width": f["width"], "height": f["height"],
                 "sharpness": f[key]} for f in frames]
        base, full, _ = partition_frames(rows, area_frac)
        return rows[base]["name"], [rows[i]["name"] for i in full]

    pick_whole, candidates = pick("sharp_whole_frame")
    pick_book, _ = pick("sharp_book_box")
    pick_ungated, _ = pick("sharp_book_box_ungated")

    cand_rows = [f for f in frames if f["id"] in candidates]
    ocr_best = None
    if do_ocr and all(f["ocr_conf_ge_80"] is not None for f in cand_rows):
        ocr_best = max(cand_rows, key=lambda f: f["ocr_conf_ge_80"])["id"]

    # Frames excluded from the race purely by the area gate. If one of these
    # out-scores the winner, relaxing that gate would elect a partial view of
    # the spread — the trap this census exists to document.
    excluded = [f for f in frames if f["id"] not in candidates]
    winner = next(f for f in frames if f["id"] == pick_whole)
    sharper_excluded = [
        f["id"] for f in excluded
        if f["sharp_whole_frame"] > winner["sharp_whole_frame"]
        or f["sharp_book_box"] > winner["sharp_book_box"]
    ]

    return {
        "frames": frames,
        "candidates": candidates,
        "n_candidates": len(candidates),
        "pick_whole_frame": pick_whole,
        "pick_book_box": pick_book,
        "pick_book_box_ungated": pick_ungated,
        "picks_differ": pick_whole != pick_book,
        "picks_differ_ungated": pick_whole != pick_ungated,
        "mixed_crop_candidates": len({f["crop_applied"] for f in frames
                                      if f["id"] in candidates}) > 1,
        "ocr_best_candidate": ocr_best,
        "pick_matches_ocr_best": (None if ocr_best is None
                                  else ocr_best == pick_whole),
        "book_box_pick_matches_ocr_best": (None if ocr_best is None
                                           else ocr_best == pick_book),
        "ungated_pick_matches_ocr_best": (None if ocr_best is None
                                          else ocr_best == pick_ungated),
        "excluded_by_area_gate": [f["id"] for f in excluded],
        "excluded_but_sharper_than_winner": sharper_excluded,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="write the full record here")
    ap.add_argument("--no-ocr", action="store_true",
                    help="geometry arm only (fast)")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text("utf-8")) or {}
    sets = discover_sets()
    out: dict[str, dict] = {}

    for name, ids in sorted(sets.items()):
        r = measure_set(name, ids, cfg, do_ocr=not args.no_ocr)
        out[name] = r
        flag = ""
        if r["picks_differ"]:
            flag += "  *** BOOK-BOX PICKS DIFFER ***"
        if r["picks_differ_ungated"]:
            flag += "  *** UNGATED PICKS DIFFER ***"
        print(f"== {name}: {r['n_candidates']} of {len(ids)} frames are anchor "
              f"candidates{flag}")
        for f in r["frames"]:
            mark = ("A" if f["id"] == r["pick_whole_frame"] else
                    " " if f["id"] in r["candidates"] else "-")
            print(f"  {mark} {f['id']:<26} crop={str(f['crop_applied']):<5} "
                  f"emit={str(f['emit_area_frac']):<6} "
                  f"sharp_frame={f['sharp_whole_frame']:<8} "
                  f"sharp_book={f['sharp_book_box']:<8} "
                  f"sharp_ungated={f['sharp_book_box_ungated']:<8} "
                  f"rot={f['applied_rotate']:<4} ocr80={f['ocr_conf_ge_80']}")
        if r["ocr_best_candidate"]:
            verdict = "AGREES" if r["pick_matches_ocr_best"] else "DISAGREES"
            print(f"    selector {verdict} with OCR "
                  f"(best candidate: {r['ocr_best_candidate']})")
        if r["excluded_but_sharper_than_winner"]:
            print(f"    area gate is holding back sharper frames: "
                  f"{r['excluded_but_sharper_than_winner']}")

    differ = [k for k, v in out.items() if v["picks_differ"]]
    differ_u = [k for k, v in out.items() if v["picks_differ_ungated"]]
    ok_u = [k for k, v in out.items() if v["ungated_pick_matches_ocr_best"]]
    bad_u = [k for k, v in out.items()
             if v["ungated_pick_matches_ocr_best"] is False]
    multi = [k for k, v in out.items() if v["n_candidates"] > 1]
    disagree = [k for k, v in out.items() if v["pick_matches_ocr_best"] is False]
    print(f"\nsets: {len(out)}   with a real anchor choice (>1 candidate): "
          f"{len(multi)} {multi}")
    print(f"book-box (gated) would change the anchor in:   {len(differ)} {differ}")
    print(f"book-box (ungated) would change the anchor in: {len(differ_u)} {differ_u}")
    print(f"incumbent picks the OCR-worse candidate in: {len(disagree)} {disagree}")
    print(f"ungated pick agrees with OCR in {len(ok_u)}, disagrees in "
          f"{len(bad_u)} {bad_u}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "_doc": [
                "Anchor-choice census (tools/anchor_choice_census.py).",
                "Question: now that pipeline/book_boundary.py exists, does ranking",
                "Stage 01 anchor candidates by sharpness INSIDE the book box change",
                "any decision on the committed corpus, and is the incumbent",
                "whole-frame ranking even picking the better photograph?",
                "sharp_* = variance of Laplacian (stage00_ingest.sharpness).",
                "ocr_conf_ge_80 = Tesseract psm 3, tessdata_best, per-frame",
                "standalone, same instrument as stitch_and_orientation_20260819.json.",
                "Frames are loaded through tools.normalize.load_upright_bgr,",
                "NOT by EXIF: these JPEGs carry a misleading pure-rotation tag.",
            ],
            "summary": {
                "n_sets": len(out),
                "sets_with_a_real_choice": multi,
                "book_box_gated_changes_anchor_in": differ,
                "book_box_ungated_changes_anchor_in": differ_u,
                "ungated_pick_agrees_with_ocr_in": ok_u,
                "ungated_pick_disagrees_with_ocr_in": bad_u,
                "incumbent_picks_ocr_worse_candidate_in": disagree,
            },
            "sets": out,
        }, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
