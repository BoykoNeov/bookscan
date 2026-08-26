"""Where does a minimum-SIZE floor on "what counts as a figure block" belong?

``pipeline/figure_grouping.py``'s third arm (sole figure + sole printed caption)
pairs a caption when the subpage holds **exactly one figure block** and exactly
one eligible caption. Its docstring already carries the hole this tool measures:

    "One figure block" is not "one printed figure", and the difference is the
    detector. [...] A minimum-area floor on what counts as a figure block is the
    obvious guard and is deliberately NOT added here: nothing has measured where
    that floor would sit.

That is what this measures. Two questions, in order:

  A. **Is there a floor at all?** Census every ``figure`` block the production
     chain emits on the whole curated corpus, on four statistics, and ask whether
     any ONE of them separates detector noise from printed figures with an EMPTY
     GAP between the two populations. No gap -> no floor, and the guard is not
     added. (The same shape as ``side_min_yov_frac``'s comment: "both floors sit
     in the wide empty middle of that separation".)

  B. **What would a floor DO?** For every candidate value, re-run Stage 07's real
     grouping pass with the floor injected and enumerate every subpage whose
     figure-block count changes, whether arm 3 then fires, and on which pair.

Statistics measured per figure block (all scale-free, so they transfer between a
2052x3000 dewarp and any other):

  * ``area_frac``      -- w*h / (page_w*page_h)
  * ``min_dim_frac``   -- min(w/page_w, h/page_h); a 21x671px sliver is not
                          distinguished by being SMALL, it is degenerate in ONE
                          dimension, and area alone would also drop a genuinely
                          small plate (``en_coins`` is a coin book -- the corpus
                          most likely to print one).
  * ``aspect``         -- max(w,h)/min(w,h)
  * ``touches_edge``   -- box within 2px of a subpage border (the known sliver
                          sits at x=0)

**Real vs noise** is not eyeballed here: a figure block counts as REAL when it
overlaps a ground-truth figure bbox at IoU >= ``FIG_IOU_MIN`` (0.2, the same
floor ``tools/layout_order_eval.py`` matches figures with). Six fixtures carry
figure bboxes in dewarped half-page coords (``en_coins_01/02/03``,
``it_geo_05/06/07`` -- 25 figures); on those subpages a figure block matching
nothing is NOISE, because that GT enumerates every figure the page prints. The
other nine spreads have no figure bboxes, so their blocks are UNLABELLED and are
reported separately -- they can widen a gap but may never be used to justify one.

**Pre-registered before the numbers were looked at:**

  1. A floor is admissible only if it sits STRICTLY above every noise block and
     STRICTLY below every real block on the chosen statistic, with the whole
     labelled corpus in play (no fixture dropped). The value is placed in the
     middle of that empty gap, geometric-mean style, not on either edge.
  2. If more than one statistic separates, prefer the one whose gap is WIDEST in
     relative terms, and take exactly one knob. Two knobs only if no single one
     separates.
  3. The floor is scoped to arm 3's uniqueness COUNT only. It may not change what
     arm 2 pairs to, segmentation recall, or the order metric -- so it is applied
     inside ``_sole_figure_pair``, never to the detector's output.
  4. Bar, unchanged from the arm itself: zero wrong pairs. A floor that recovers
     a pair by dropping a real figure is a regression even if the recovered pair
     is right, and is reported as such.
  5. Every subpage whose figure-block count changes under the floor is listed by
     name with its before/after arm-3 outcome. Silence about a subpage means the
     count did not change -- that is a measurement, not an assumption. (The
     2026-08-26 addendum this tool descends from was written because a per-page
     claim was made about pages nothing had looked at.)

**WHAT IT FOUND, recorded after the numbers (the pre-registration above is left
exactly as written).**

  * **There is no noise population.** 50 figure blocks over 30 subpages, and not
    one of them is detector junk. The block this whole question started from --
    it_geo_05-left's "21x671px sliver" -- is not a figure block at all: it is an
    orphan junk-text region that Stage 07's ``unreadable_panel`` pass re-types
    FIGURE *after* ``group_figures`` runs, which is why this tool excludes
    ``type_promoted`` figures from the population. Rule 1's real-vs-noise
    dichotomy therefore has nothing to separate, and on its own terms no floor is
    admissible.
  * **What breaks the arm's count is OVER-SEGMENTATION, not noise.**
    ``it_geo_02``-right prints one photograph (the Cadini di Misurina) and the
    detector emits a 1202x81px sky strip above the 1202x628px body. Two boxes,
    one picture, and the uniqueness arm declines. That is a different question
    from the one pre-registered, and the floor is sized on it instead.
  * **Rule 2's tie-break does not arise: area does not separate at all.** The sky
    strip covers 0.0167 of its page; a WHOLE small printed figure --
    de_02-right's 231x175px pictogram -- covers 0.0092. Area puts the strip above
    the picture, so no area threshold orders them correctly. min(w,h) does:
    strip 0.0270, pictogram 0.0630. This is a measured inversion, not the
    hypothetical the knob comment first carried.
  * **Effect of the shipped 0.04, enumerated over all 30 subpages:** exactly one
    subpage changes -- it_geo_02-right gains the correct "Figura 1" pair -- and
    no wrong pair appears anywhere. The 8 graded fixtures stay at 16/19, 0 wrong.
  * **Rule 4's failure direction is NOT demonstrated by this corpus, and that is
    a limit rather than a reassurance.** The sweep goes on past the shipped
    value: at 0.065 the floor drops two WHOLE pictograms (de_02-right's 231x175
    and 233x179) and at 0.08 it drops a GT-confirmed figure (it_geo_07-left's
    829x222) -- and the pairing outcome is unchanged at every one of those arms,
    because none of those subpages has an eligible printed-number caption for the
    arm to act on. So "no wrong pair at 0.08" says nothing about 0.08 being safe.
    It says the corpus cannot exercise the harm. 0.04 is placed by the block
    geometry (1.5x above the strip, 1.6x below the smallest whole figure), not by
    the sweep being flat.
  * **Honest limit on the gain:** ``it_geo_02`` has no block GT, so the recovered
    pair is verified by reading the pixels, not by the metric.

Run (jobs must already exist -- this tool does not run the pipeline):

    python -m tools.sole_floor_census --json docs/data/sole_floor_census_<date>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline import stage07_assemble as S7
from pipeline.page_model import Document
from tools.gate1_harness import REPO_ROOT, load_config

# Same figure-match floor the block-order eval uses, so "is this block a printed
# figure" is answered by one instrument across the repo, not two.
FIG_IOU_MIN = 0.2

# The 15 curated spreads (testset/manifest.csv minus the skewset multi-view
# frames, which are duplicate views of pages already here and carry no block GT).
CORPUS: list[str] = [
    "en_coins_01", "en_coins_02", "en_coins_03",
    "bg_01", "bg_02", "bg_03",
    "it_geo_01", "it_geo_02", "it_geo_03", "it_geo_04",
    "it_geo_05", "it_geo_06", "it_geo_07",
    "de_01", "de_02",
]

EDGE_TOL_PX = 2


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (aw * ah + bw * bh - inter)


def gt_figures(testset: Path) -> dict[tuple[str, str], list[dict]]:
    """(image_id, subpage) -> GT figure blocks that carry a bbox.

    Only bbox-carrying figures are usable: ``it_geo_04``/``de_01`` predate figure
    bboxes, so their subpages stay UNLABELLED rather than being scored against a
    GT that cannot answer the question.
    """
    out: dict[tuple[str, str], list[dict]] = {}
    for gt_path in sorted((testset / "gt").glob("*.blocks.json")):
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        if gt.get("gt_type") != "block_reading_order":
            continue
        image_id = gt["image_id"]
        for sub, gsub in gt["subpages"].items():
            figs = [b for b in gsub["reading_order"]
                    if b["type"] == "figure" and b.get("bbox")]
            if figs:
                out[(image_id, sub)] = figs
    return out


def census_blocks(doc: Document, image_id: str,
                  gt: dict[tuple[str, str], list[dict]]) -> list[dict]:
    """Every ``figure`` block of one assembled document, measured and labelled.

    **Converted pictogram panels are excluded from the population.** Stage 07 runs
    ``unreadable_panel`` AFTER ``group_figures`` (assemble's per-page loop groups,
    the panel scan is a job-level pass afterwards), so a block re-typed FIGURE
    there was NOT a figure when the uniqueness arm counted and must not be
    measured as one. They are marked by ``type_promoted`` on a FIGURE block —
    ``unreadable_panel.apply_to_blocks`` raises it exactly as caption promotion
    does. Counting them would have put de_01-left's 235x233px Gehzeiten panel in
    the population as the corpus's smallest "figure"; it is a real region and it
    is rendered as pixels, but the arm never sees it as one.
    """
    rows: list[dict] = []
    for page in doc.pages:
        sub = page.subpage
        gt_figs = gt.get((image_id, sub))
        pw, ph = float(page.width), float(page.height)
        for blk in page.blocks:
            if blk.type.value != "figure" or blk.type_promoted:
                continue
            bb = blk.bbox
            box = (float(bb.x), float(bb.y), float(bb.w), float(bb.h))
            best_id, best_iou = None, 0.0
            for g in gt_figs or []:
                v = _iou(box, tuple(float(t) for t in g["bbox"]))
                if v > best_iou:
                    best_id, best_iou = g["id"], v
            text = (blk.text or " ".join(w.text for w in blk.words)).strip()
            rows.append({
                "image_id": image_id,
                "subpage": sub,
                "block_id": blk.id,
                "x": bb.x, "y": bb.y, "w": bb.w, "h": bb.h,
                "page_w": page.width, "page_h": page.height,
                "area_frac": (bb.w * bb.h) / (pw * ph),
                "min_dim_frac": min(bb.w / pw, bb.h / ph),
                "aspect": max(bb.w, bb.h) / max(1.0, min(bb.w, bb.h)),
                "touches_edge": bool(bb.x <= EDGE_TOL_PX or bb.y <= EDGE_TOL_PX
                                     or bb.x + bb.w >= page.width - EDGE_TOL_PX
                                     or bb.y + bb.h >= page.height - EDGE_TOL_PX),
                "n_routed_words": len(blk.words),
                "routed_text_head": text[:60],
                "gt_available": gt_figs is not None,
                "gt_match": best_id if best_iou >= FIG_IOU_MIN else None,
                "gt_iou": round(best_iou, 3),
                "label": ("real" if best_iou >= FIG_IOU_MIN else
                          ("noise" if gt_figs is not None else "unlabelled")),
            })
    return rows


def pairing_state(doc: Document) -> dict[str, dict]:
    """page_id -> what the grouping pass decided there (arm + partner per caption)."""
    out: dict[str, dict] = {}
    for page in doc.pages:
        pairs = {}
        for blk in page.blocks:
            if blk.figure_ref is not None:
                pairs[str(blk.id)] = {
                    "figure": blk.figure_ref.block_id,
                    "source": blk.pair_source.value if blk.pair_source else None,
                    "caption_number": blk.caption_number,
                }
        out[page.page_id] = {
            "n_figure_blocks": sum(1 for b in page.blocks
                                   if b.type.value == "figure" and not b.type_promoted),
            "pairs": pairs,
        }
    return out


def separation(rows: list[dict], stat: str) -> dict:
    """Gap between the labelled populations on one statistic (higher = more real)."""
    real = sorted(r[stat] for r in rows if r["label"] == "real")
    noise = sorted(r[stat] for r in rows if r["label"] == "noise")
    unlab = sorted(r[stat] for r in rows if r["label"] == "unlabelled")
    gap = None
    if real and noise:
        # A floor keeps blocks ABOVE it, so it must clear every noise block and
        # stay under every real one.
        lo, hi = max(noise), min(real)
        gap = {"noise_max": lo, "real_min": hi, "separates": hi > lo,
               "ratio": (hi / lo) if lo > 0 else None,
               "unlabelled_in_gap": [v for v in unlab if lo < v < hi]}
    return {
        "stat": stat,
        "real": {"n": len(real), "min": real[0] if real else None,
                 "max": real[-1] if real else None},
        "noise": {"n": len(noise), "values": noise},
        "unlabelled": {"n": len(unlab), "min": unlab[0] if unlab else None,
                       "max": unlab[-1] if unlab else None},
        "gap": gap,
    }


def sweep(job_dirs: dict[str, Path], cfg: dict, floors: list[float]) -> list[dict]:
    """Re-run Stage 07's grouping with each floor injected; report what MOVED.

    The floor is injected the way production would set it (``reconstruct.grouping``
    in ``config.yaml``), and Stage 07 is re-run in full, so this measures the
    shipped path rather than a re-implementation of it.

    The comparison baseline is the floor **0.0** arm computed here, not whatever
    is on disk: the jobs were assembled while the knob's default was being
    changed, so the documents in the folder are not a single arm and cannot be
    the control.
    """
    out: list[dict] = []
    baseline: dict[str, dict[str, dict]] = {}
    floors = [0.0] + [f for f in floors if f != 0.0]
    for f in floors:
        cfg_f = json.loads(json.dumps(cfg))
        cfg_f.setdefault("reconstruct", {}).setdefault("grouping", {})
        cfg_f["reconstruct"]["grouping"]["sole_min_fig_frac"] = f
        changes: list[dict] = []
        totals = {"pairs": 0, "by_sole_figure": 0}
        for image_id, job in job_dirs.items():
            doc = S7.run(job, cfg_f, force=True)
            state = pairing_state(doc)
            if f == 0.0:
                baseline[image_id] = state
            for page_id, st in state.items():
                totals["pairs"] += len(st["pairs"])
                totals["by_sole_figure"] += sum(
                    1 for p in st["pairs"].values() if p["source"] == "sole_figure")
                before = baseline[image_id][page_id]
                if before != st:
                    changes.append({"image_id": image_id, "page_id": page_id,
                                    "before": before, "after": st})
        out.append({"floor": f, "totals": totals, "changed_subpages": changes})
        print(f"  floor={f:<10} pairs={totals['pairs']} "
              f"sole={totals['by_sole_figure']} changed={len(changes)}", flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=Path, default=REPO_ROOT / "jobs")
    ap.add_argument("--prefix", default="floor_",
                    help="job folder prefix: <prefix><image_id>")
    ap.add_argument("--testset", type=Path, default=REPO_ROOT / "testset")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--json", type=Path, help="write the full record here")
    ap.add_argument("--floors", default="",
                    help="comma-separated candidate floors to sweep (min_dim_frac); "
                         "empty = census only")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_config(args.config)
    gt = gt_figures(args.testset)

    job_dirs: dict[str, Path] = {}
    rows: list[dict] = []
    baseline: dict[str, dict[str, dict]] = {}
    missing: list[str] = []
    for image_id in CORPUS:
        job = args.jobs / f"{args.prefix}{image_id}"
        if not (job / "document.json").exists():
            missing.append(image_id)
            continue
        job_dirs[image_id] = job
        doc = Document.model_validate_json(
            (job / "document.json").read_text(encoding="utf-8"))
        rows += census_blocks(doc, image_id, gt)
        baseline[image_id] = pairing_state(doc)

    if missing:
        print(f"MISSING jobs (run_all + stage07_assemble first): {', '.join(missing)}",
              file=sys.stderr)
    n_sub = sum(len(v) for v in baseline.values())
    print(f"census: {len(rows)} figure blocks over {n_sub} subpages "
          f"of {len(job_dirs)} spreads")

    seps = {s: separation(rows, s) for s in ("min_dim_frac", "area_frac")}
    for s, rep in seps.items():
        g = rep["gap"]
        print(f"  {s:14s} real n={rep['real']['n']} min={rep['real']['min']!r}  "
              f"noise n={rep['noise']['n']} max={g['noise_max'] if g else None!r}  "
              f"separates={g['separates'] if g else 'n/a'}")

    sweep_out: list[dict] = []
    floors = [float(x) for x in args.floors.split(",") if x.strip()]
    if floors:
        print("sweep (Stage 07 re-run per floor, real pairing pass):")
        sweep_out = sweep(job_dirs, cfg, floors)

    record = {
        "what": "Minimum-size floor for figure_grouping's sole-figure arm: census of "
                "every figure block the production chain emits on the curated corpus, "
                "labelled real/noise by GT figure bbox, plus what each candidate "
                "floor changes.",
        "population": {"spreads": sorted(job_dirs), "missing": missing,
                       "subpages": n_sub, "figure_blocks": len(rows)},
        "method": {"path": "run_all 00-06 + stage07_assemble (production)",
                   "real_label": f"IoU >= {FIG_IOU_MIN} with a GT figure bbox",
                   "gt_fixtures": sorted({k[0] for k in gt}),
                   "edge_tol_px": EDGE_TOL_PX},
        "separation": seps,
        "figure_blocks": rows,
        "pairing_on_disk_at_census_time": baseline,
        "sweep": sweep_out,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(record, indent=1, ensure_ascii=False),
                             encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
