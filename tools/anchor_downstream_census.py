"""Anchor-choice census, downstream arm — is the selector wrong AFTER dewarp?

``tools/anchor_choice_census.py`` (2026-08-19) established that ranking Stage 01
anchor candidates inside the book box changes nothing, and named what it could
not answer: on three sets the incumbent (sharpest full-spread frame) picks a
photograph that OCRs measurably worse. That finding rests on **Tesseract run on
the raw upright frame** — the whole flat spread, room and all, before the book
crop, before the gutter split, before Stage 03 flattens the page. Its own Limits
paragraph says so: *"OCR'd best is a proxy for is the better anchor that ignores
everything downstream of Stage 01."*

That matters here specifically, not in general, because of WHICH sets disagree:

  * ``de_02`` — the incumbent's margin is 669.9 vs 658.8, **1.7 %**. That is a
    tie in the selector's own units, not an error it committed.
  * ``skewset_de_01`` and ``skewset_it_01`` — both are the multi-VIEW fixture,
    i.e. deliberately oblique shots of the same spread. In each the loser is the
    *sharper* frame and what separates them is mean confidence (70.8 vs 73.0;
    70.6 vs 84.2). Depressed confidence on an obliquely-shot whole frame is
    exactly the defect Stage 03 exists to remove.

So the case that the selector is broken currently rests on an instrument that
skips the stage designed to fix the thing it is measuring. This tool re-asks the
question through the pipeline's own geometry — the same functions
``tools/dewarp_ab.py`` uses, which are the ones Stage 02 and Stage 03 run — and
scores with the SAME Tesseract instrument as the flat census (psm/oem from
config, no upscale, conf >= 80 word count + mean conf over all words). Only the
geometry differs between arms; that is the whole point.

Three arms per candidate frame:

  * ``flat``   — the upright frame, whole. Reproduces the earlier census, and is
                 kept as a self-check: if these numbers do not match
                 ``anchor_choice_census_20260819.json``, something in the load
                 path moved and nothing else here is believable.
  * ``split``  — book-boundary crop + gutter split, each subpage OCR'd, summed.
  * ``dewarp`` — the same subpages flattened by Stage 03 first, summed.

Only frames ``stage01_fuse.partition_frames`` admits as full-spread candidates
are measured. The close-ups are ineligible by the area gate and stay that way:
``fullspread_area_frac`` is load-bearing (``zoomset_de_01_f01`` is 2.4x sharper
than its own anchor at 0.39 coverage and reads half the words), and relaxing it
needs a coverage test, not a sharper score.

**Pre-registered before running (the point of writing it here).**

  1. A set counts as an incumbent ERROR only if, in the ``dewarp`` arm, a losing
     candidate beats the incumbent's pick on BOTH statistics: more words at
     conf >= 80 by a margin **> 60 words**, and higher mean confidence. The 60 is
     the churn floor this same instrument was measured to have under nothing but
     reframing (RESULTS 2026-08-19); it is a floor, not a matched estimate, so
     margins on both sides are reported for every set either way.
  2. ``skewset_orient_02`` reads 0 words on both frames flat — it is degenerate
     for this question and is EXCLUDED from the verdict. It is still measured and
     printed, because dropping a fixture quietly is how a corpus stops being one.
  3. A candidate on which Stage 02 fails to find a gutter (falls back to
     ``single.png``) is recorded as such. That is anchor quality the flat census
     could not see, and it is reported whether or not it changes a pick.
  4. Every arm's per-set winner is reported, not just the dewarp arm's, so the
     direction of any change between arms is visible rather than asserted.

**Why this may run on the skewset fixtures.** ``docs/plans/multiview-phase1-prereg.md``
freezes the *merge policies* (v1-v4 off-limits, v5 scored once) on those pages.
It does not freeze reading them: the prereg itself ran a GT-free headroom triage
over the same frames on the stated grounds that it "touches no merge policy, so
it does not spend the pre-registration". Anchor SELECTION is likewise not a merge
policy — nothing here merges two views, keys GT, or scores v1-v5 — so the same
justification applies, and is restated rather than assumed to carry silently.

No pipeline code changes here. ``partition_frames`` and ``fullspread_area_frac``
are imported and used exactly as they ship.

Usage:
    python -m tools.anchor_downstream_census [--json docs/data/<name>.json]
    python -m tools.anchor_downstream_census --sets de_02,skewset_it_01
    python -m tools.anchor_downstream_census --method classical   # dewarp arm
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

from pipeline import book_boundary as BB
from pipeline.stage00_ingest import sharpness
from pipeline.stage01_fuse import DEFAULTS as FUSE_DEFAULTS, partition_frames
from tools.anchor_choice_census import (
    REPO_ROOT,
    conf_ge_80,
    discover_sets,
    languages,
    load_upright,
)
from tools.dewarp_ab import dewarp_halves, split_halves
from tools.gate1_harness import (
    find_tesseract,
    resolve_tessdata_dir,
    run_tesseract,
)

# Both frames read 0 words at conf >= 80 in the flat census — see rule 2 above.
DEGENERATE = {"skewset_orient_02"}

# The word margin below which a difference is inside this instrument's own
# reframing churn (RESULTS 2026-08-19). A floor, not a matched estimate.
CHURN_WORDS = 60


def _ocr(binary: str, tessdata: str | None, cfg: dict, img: np.ndarray,
         lang: str) -> tuple[int, float, int]:
    """(words at conf >= 80, mean conf, n words) — the flat census's instrument."""
    tcfg = cfg.get("tesseract", {})
    tsv = run_tesseract(binary, img, lang, tessdata, int(tcfg.get("oem", 1)),
                        int(tcfg.get("psm", 3)))
    n_words = sum(
        1 for line in tsv.splitlines()[1:]
        if len(line.split("\t")) >= 12 and line.split("\t")[11].strip()
    )
    ge80, mean = conf_ge_80(tsv)
    return ge80, mean, n_words


def _combine(parts: list[tuple[int, float, int]]) -> tuple[int, float]:
    """Sum words over subpages; mean conf weighted by word count (so a
    two-word subpage cannot drag the page mean around)."""
    ge80 = sum(p[0] for p in parts)
    n = sum(p[2] for p in parts)
    if n == 0:
        return ge80, 0.0
    mean = sum(p[1] * p[2] for p in parts) / n
    return ge80, round(float(mean), 1)


def measure_frame(image_id: str, img: np.ndarray, oinfo, cfg: dict,
                  binary: str, tessdata: str | None, lang: str,
                  method: str) -> dict:
    t0 = time.perf_counter()
    h, w = img.shape[:2]

    flat = _ocr(binary, tessdata, cfg, img, lang)

    halves, gutter_x = split_halves(img, cfg)
    split_parts = [_ocr(binary, tessdata, cfg, im, lang) for _, im in halves]

    dw = dewarp_halves(halves, cfg, method)
    dw_parts = [_ocr(binary, tessdata, cfg, im, lang) for _, im, _ in dw]

    bb = BB.find_book(img, BB.resolve_params(cfg))

    split_ge80, split_mean = _combine(split_parts)
    dw_ge80, dw_mean = _combine(dw_parts)
    return {
        "id": image_id,
        "width": w, "height": h,
        "applied_rotate": oinfo.applied_rotate,
        "orient_method": oinfo.method,
        "sharp_whole_frame": round(sharpness(img), 1),
        "crop_applied": bb.applied,
        "crop_reason": bb.reason,
        "gutter_found": gutter_x is not None,
        "subpages": [name for name, _ in halves],
        "dewarp_note": "; ".join(
            f"{pd.name}:{pd.method}/{pd.max_disp_px:.0f}px" for _, _, pd in dw),
        "flat_conf_ge_80": flat[0], "flat_mean_conf": flat[1],
        "split_conf_ge_80": split_ge80, "split_mean_conf": split_mean,
        "dewarp_conf_ge_80": dw_ge80, "dewarp_mean_conf": dw_mean,
        "seconds": round(time.perf_counter() - t0, 1),
    }


def _verdict(frames: list[dict], pick: str, arm: str) -> dict:
    """Does any loser beat the incumbent's pick on BOTH statistics, by more than
    the churn floor in words? Pre-registered rule 1."""
    w_key, c_key = f"{arm}_conf_ge_80", f"{arm}_mean_conf"
    winner = next(f for f in frames if f["id"] == pick)
    best = max(frames, key=lambda f: f[w_key])
    challengers = [
        {
            "id": f["id"],
            "d_words": f[w_key] - winner[w_key],
            "d_mean_conf": round(f[c_key] - winner[c_key], 1),
        }
        for f in frames if f["id"] != pick
    ]
    errors = [c for c in challengers
              if c["d_words"] > CHURN_WORDS and c["d_mean_conf"] > 0]
    return {
        "arm": arm,
        "best_by_words": best["id"],
        "pick_is_best_by_words": best["id"] == pick,
        "challengers": sorted(challengers, key=lambda c: -c["d_words"]),
        "incumbent_error": bool(errors),
        "error_by": [c["id"] for c in errors],
    }


def measure_set(name: str, ids: list[str], cfg: dict, binary: str,
                tessdata: str | None, method: str) -> dict:
    langs = languages()
    # Which frames are even eligible: partition_frames as it ships, on the real
    # UPRIGHT frame sizes. Close-ups are excluded by the area gate and stay
    # excluded. Loaded once and kept — load_upright pays an OSD Tesseract call
    # per frame, so re-loading for the measurement would double it.
    loaded = {i: load_upright(i, binary, tessdata, cfg) for i in ids}
    dims = []
    for i in ids:
        img, _ = loaded[i]
        h, w = img.shape[:2]
        dims.append({"name": i, "width": w, "height": h,
                     "sharpness": sharpness(img)})
    base, full, _ = partition_frames(
        dims, float(FUSE_DEFAULTS["fullspread_area_frac"]))
    candidates = [dims[i]["name"] for i in full]
    pick = dims[base]["name"]

    frames = [
        measure_frame(i, loaded[i][0], loaded[i][1], cfg, binary, tessdata,
                      langs.get(i, "eng"), method)
        for i in candidates
    ]
    rotates = {f["applied_rotate"] for f in frames}
    return {
        "candidates": candidates,
        "excluded_by_area_gate": [i for i in ids if i not in candidates],
        "incumbent_pick": pick,
        "orientation_confound": len(rotates) > 1,
        "degenerate": name in DEGENERATE,
        "frames": frames,
        "verdicts": {arm: _verdict(frames, pick, arm)
                     for arm in ("flat", "split", "dewarp")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="write the full record here")
    ap.add_argument("--sets", help="comma-separated subset of set names")
    ap.add_argument("--method", default="auto",
                    help="Stage 03 dewarp arm: auto | classical | uvdoc")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text("utf-8")) or {}
    binary = find_tesseract(cfg)
    if binary is None:
        raise SystemExit(
            "Tesseract not found — it resolves orientation here, so without it "
            "every number would be measured on possibly-sideways pixels. Fix "
            "config.yaml tesseract.binary.")
    tessdata = resolve_tessdata_dir(cfg)

    sets = {k: v for k, v in discover_sets().items()}
    if args.sets:
        want = {s.strip() for s in args.sets.split(",")}
        sets = {k: v for k, v in sets.items() if k in want}

    out: dict[str, dict] = {}
    for name, ids in sorted(sets.items()):
        rec = measure_set(name, ids, cfg, binary, tessdata, args.method)
        if len(rec["candidates"]) < 2:
            continue          # no choice to make; nothing to say about it
        out[name] = rec
        v = rec["verdicts"]["dewarp"]
        tag = ("DEGENERATE" if rec["degenerate"]
               else ("ERROR" if v["incumbent_error"] else "ok"))
        print(f"\n{name}  [{tag}]  pick={rec['incumbent_pick']}")
        for f in rec["frames"]:
            mark = "*" if f["id"] == rec["incumbent_pick"] else " "
            print(f"  {mark} {f['id']:<24s} sharp={f['sharp_whole_frame']:>7.1f} "
                  f"flat={f['flat_conf_ge_80']:>4d}/{f['flat_mean_conf']:>5.1f} "
                  f"split={f['split_conf_ge_80']:>4d}/{f['split_mean_conf']:>5.1f} "
                  f"dewarp={f['dewarp_conf_ge_80']:>4d}/{f['dewarp_mean_conf']:>5.1f} "
                  f"gutter={'y' if f['gutter_found'] else 'N'} "
                  f"crop={'y' if f['crop_applied'] else 'n'} {f['seconds']}s")
        sys.stdout.flush()

    verdict_sets = [k for k, r in out.items() if not r["degenerate"]]
    errors = {arm: [k for k in verdict_sets
                    if out[k]["verdicts"][arm]["incumbent_error"]]
              for arm in ("flat", "split", "dewarp")}
    print("\n=== incumbent errors by arm (degenerate sets excluded) ===")
    for arm, ks in errors.items():
        print(f"  {arm:<7s} {len(ks)}/{len(verdict_sets)}: {', '.join(ks) or '-'}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "_doc": [
                "Anchor-choice census, downstream arm "
                "(tools/anchor_downstream_census.py).",
                "Question: does the flat census's 'the selector picks a worse "
                "photograph' survive the book crop, the gutter split and the "
                "Stage 03 dewarp — the geometry the pipeline actually applies?",
                "Same Tesseract instrument as anchor_choice_census_20260819.json "
                "(psm/oem from config, no upscale); only the geometry differs.",
                "Pre-registered rule: an incumbent ERROR needs a loser ahead on "
                f"BOTH statistics, by > {CHURN_WORDS} words and positive mean conf.",
                "skewset_orient_02 is degenerate (0 words both frames, flat) and "
                "is measured but excluded from the verdict.",
                "Frames load via tools.normalize.load_upright_bgr, NOT by EXIF: "
                "these JPEGs carry a misleading pure-rotation tag.",
            ],
            "params": {"dewarp_method": args.method,
                       "churn_words": CHURN_WORDS,
                       "fullspread_area_frac": FUSE_DEFAULTS["fullspread_area_frac"]},
            "summary": {"n_sets_with_a_choice": len(out),
                        "sets_in_verdict": verdict_sets,
                        "incumbent_errors_by_arm": errors},
            "sets": out,
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
