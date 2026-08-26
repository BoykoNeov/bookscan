"""Per-page frame selection — is there anything to win, and can a cheap rule win it?

Today one photograph becomes both halves of a spread: Stage 01 elects the
sharpest full-spread frame as ``anchor.png`` and Stage 02 cuts THAT frame into
``left.png`` + ``right.png``. Every anchor question asked so far has been asked
per SPREAD. This tool asks the per-PAGE version, which is the one thing
``tools/anchor_choice_census.py`` and ``tools/anchor_downstream_census.py`` left
open and named as the bigger lever: a handheld capture can hold one page flat
and in focus while the other curls into shadow, and nothing in the pipeline can
take the good half of frame A and the good half of frame B.

It answers three questions that have different next steps, in one pass, so that
none of them needs a second run:

  1. **Is per-page selection even a distinguishable operation?** If on every set
     the frame that wins the left page also wins the right page, per-page
     selection is a no-op BY CONSTRUCTION and no margin anywhere else matters.
     This is the primary result and it is reported first — the same shape of
     refutation as the book-box census (on 6 of 10 sets the crop abstained on
     every candidate, so any windowing variant was a no-op by construction).
  2. **If the winners differ, is the difference worth having?** Measured through
     this pipeline's own geometry — book crop, gutter split, Stage 03 dewarp —
     and scored with the census's Tesseract instrument, per SIDE.
  3. **Could a Stage 02 rule reach it?** The cheap statistics such a rule would
     have to decide on (variance of Laplacian, ink density, median glyph height)
     are logged per side per candidate, on the flat half AND on the dewarped
     half, so the correlation between a proxy and the OCR answer can be read off
     afterwards. These are LOGGED, NOT part of the verdict: "there is headroom"
     and "a criterion can reach it" are separate claims, and the flat census
     already showed that judgements made on flat frames reverse after dewarp.

No pipeline code is changed or re-implemented here. ``partition_frames``,
``find_book``, ``detect_gutter``, ``cut_pages`` and Stage 03 are imported and
run as they ship.

**Pre-registered before running (the point of writing it here).**

  1. **Eligibility.** A candidate can only be a per-page source if the shipped
     split actually yields ``left.png`` + ``right.png`` on it. A candidate that
     falls to ``single.png`` has no left/right to contribute; it is measured and
     recorded, and excluded from that set's per-page race. (Two frames in the
     corpus do this — RESULTS 2026-08-26 — and in both cases the selector keeps
     a frame that splits correctly.)
  2. **Primary result: the same-winner count.** Per set, in the ``dewarp`` arm,
     by words at conf >= 80: does the frame that wins ``left`` also win
     ``right``? Reported as a count over the eligible sets before any margin is
     discussed.
  3. **A per-page GAIN** counts only if, in the ``dewarp`` arm, on at least one
     side, some challenger beats the frame the incumbent selector picked on BOTH
     statistics — more words at conf >= 80 by a margin **> 60 words**, and higher
     mean confidence. That 60 is the census's reframing-churn floor, applied
     **unchanged per side**. A side holds roughly half a spread's words, so the
     same floor is a STRICTER bar here; it is deliberately not rescaled, because
     halving it would be inventing a number this instrument has never been
     measured against.
  4. **``de_01`` is reported SEPARATELY and excluded from the headline.**
     RESULTS 2026-08-26 pinned that set's +43-word disagreement as a Stage 03
     defect — UVDoc loses 18 words and 12.7 confidence on the frame the selector
     picks while gaining +58 and +104 on the two losers, the only frame in the
     corpus dewarp makes worse — and says explicitly that it must not be chased
     with an anchor criterion. Per-page accounting will re-surface exactly that
     instability as an apparent per-page "gain", so it is quarantined in advance
     rather than explained away afterwards.
  5. **``skewset_orient_02`` is degenerate** (0 words at conf >= 80 on both
     frames, flat) and is excluded from the verdict, as in the census. It is
     still measured and printed — dropping a fixture quietly is how a corpus
     stops being one.
  6. **The close-up arm gets one measurement and a bar stated in advance.** A
     close-up is a candidate per-page source only if it covers **>= 98 % of a
     page's box**. Stage 01's ``fullspread_area_frac`` is load-bearing and its
     documented lesson is that relaxing it needs a COVERAGE test, not a sharper
     score (``zoomset_de_01_f01`` is 2.4x sharper than its anchor at 0.39
     coverage and reads half the words). The five correctly-registered close-ups
     in the corpus cover 0.25-0.44 of the SPREAD, and a page with margins is
     about half a spread, so this bar is expected to reject them; the point is to
     reject them on the measured page-coverage number rather than on that
     inference. Registration is recomputed with ``stage01_fuse.stitch_closeup``
     at shipped parameters, and its NCC gate decides which close-ups are
     correctly located in the first place.

**Instrument, and why it is the census's.** ``_ocr`` is imported from
``tools.anchor_downstream_census`` rather than copied, so this tool cannot drift
from the numbers it is being compared against (psm/oem from config, no upscale,
words at conf >= 80 + mean conf over all words). Frames load through
``tools.normalize.load_upright_bgr``, never by EXIF: these testset JPEGs carry a
spurious pure-rotation tag, and loading them transposed feeds Tesseract sideways
pixels (``zoomset_en_02_f01`` read 30 words against the 160 on record).

**One deliberate difference from ``tools/dewarp_ab.split_halves``.** That helper
always cuts with ``margin_frac``; the shipped stage widens to
``pinch_margin_frac`` when the gutter came from the Layer-2 spine-pinch cue. This
tool follows the STAGE, because the question here is what the pipeline would
produce, not what an older harness produced. Where the pinch path fires the sums
will therefore differ slightly from ``anchor_downstream_census_20260826.json``;
the committed census numbers are loaded and reported alongside as a self-check so
any difference is visible instead of assumed.

**Why this may run on the skewset fixtures.** ``docs/plans/multiview-phase1-prereg.md``
freezes the *merge policies* on those pages (v1-v4 off-limits, v5 scored once).
Nothing here merges two views, keys ground truth, or scores v1-v5 — it selects
one existing photograph per page — so it spends no pre-registration, the same
grounds on which the downstream census read the same frames.

Usage:
    python -m tools.perpage_choice_probe [--json docs/data/<name>.json]
    python -m tools.perpage_choice_probe --sets de_02,skewset_it_01
    python -m tools.perpage_choice_probe --no-closeups
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from pipeline import book_boundary as BB
from pipeline import stage01_fuse as S1
from pipeline import page_source as PS
from pipeline import stage02_split as S2
from pipeline.stage00_ingest import sharpness
from pipeline.stage01_fuse import DEFAULTS as FUSE_DEFAULTS, partition_frames
from tools.anchor_choice_census import (
    REPO_ROOT,
    discover_sets,
    languages,
    load_upright,
)
from tools.anchor_downstream_census import CHURN_WORDS, DEGENERATE, _ocr
from tools.dewarp_ab import dewarp_halves
from tools.gate1_harness import find_tesseract, resolve_tessdata_dir

# Pre-registration rule 4: measured, printed, excluded from the headline.
QUARANTINED = {"de_01"}

# Pre-registration rule 6: a close-up must cover essentially the whole page box.
MIN_PAGE_COVERAGE = 0.98

CENSUS_JSON = REPO_ROOT / "docs" / "data" / "anchor_downstream_census_20260826.json"


# --------------------------------------------------------------------------
# Geometry — the shipped stage, with the boxes kept
# --------------------------------------------------------------------------


def split_with_boxes(bgr: np.ndarray, cfg: dict):
    """``stage02_split.run``'s geometry, in memory, keeping every box.

    Same three steps in the same order as the stage: find the book, detect the
    gutter inside the SEARCH box, cut the EMIT box with the margin the stage
    would use for that detector layer. Returns
    ``(pieces, gutter_x, book, method)`` where ``pieces`` is
    ``[(name, img, box_in_original_frame_coords), ...]`` in reading order.

    Since the selector shipped (``pipeline/page_source.py``), this delegates to
    the production geometry rather than restating it, so the probe cannot drift
    away from the thing it licensed. The measured numbers are unchanged: that
    function is this function's former body, moved.
    """
    pieces, gutter_x, book, method, _diag = PS.split_geometry(bgr, cfg)
    return pieces, gutter_x, book, method


# --------------------------------------------------------------------------
# Proxies — what a Stage 02 selector could decide on, without OCR
# --------------------------------------------------------------------------


def proxies(bgr: np.ndarray, cfg: dict) -> dict:
    """Cheap per-page statistics, no OCR involved.

    Three, because they fail differently:

    * ``sharp`` — variance of the Laplacian, the incumbent selector's own
      criterion (``stage00_ingest.sharpness``), here restricted to one page
      instead of a whole frame that is 40-55 % room.
    * ``ink_frac`` — fraction of pixels the adaptive text mask calls ink
      (``stage02_split.ink_profile``'s mask). A page lost to shadow or blur
      loses ink; a page full of fabric texture gains it, which is why this one
      is not trusted alone.
    * ``glyph_px`` — median height of glyph-sized connected components in that
      mask: a direct estimate of PIXELS PER TEXT LINE, which is the mechanism
      every close-up finding in this repo turned out to be about ("roughly
      double the pixels per text line"). ``n_glyphs`` is reported with it so a
      median over four components is visibly not a measurement.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    p = S2.resolve_params(cfg)
    block = int(p["adaptive_block"])
    block = block if block % 2 == 1 else block + 1
    ink = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, blockSize=block,
                                C=int(p["adaptive_C"]))
    h, w = gray.shape[:2]
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    hs = stats[1:, cv2.CC_STAT_HEIGHT]
    ws = stats[1:, cv2.CC_STAT_WIDTH]
    ar = stats[1:, cv2.CC_STAT_AREA]
    # Glyph-sized: tall enough to be a letter, short enough not to be a rule,
    # a figure edge or a shadow seam; and solid enough not to be speckle.
    keep = (hs >= 4) & (hs <= max(8, h // 20)) & (ws >= 2) & (ar >= 8)
    glyphs = hs[keep]
    return {
        "sharp": round(sharpness(gray), 1),
        "ink_frac": round(float(ink.sum()) / float(h * w), 5),
        "glyph_px": round(float(np.median(glyphs)), 1) if glyphs.size else 0.0,
        "n_glyphs": int(glyphs.size),
        "px": int(h * w),
    }


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def measure_frame(image_id: str, img: np.ndarray, oinfo, cfg: dict, binary: str,
                  tessdata: str | None, lang: str, method: str) -> dict:
    """One candidate frame, split into sides, each side scored and profiled."""
    t0 = time.perf_counter()
    h, w = img.shape[:2]
    pieces, gutter_x, book, split_method = split_with_boxes(img, cfg)
    halves = [(name, im) for name, im, _ in pieces]
    dw = dewarp_halves(halves, cfg, method)

    sides = {}
    for (name, flat_img, box), (_, dw_img, pd) in zip(pieces, dw):
        s_ge80, s_mean, s_n = _ocr(binary, tessdata, cfg, flat_img, lang)
        d_ge80, d_mean, d_n = _ocr(binary, tessdata, cfg, dw_img, lang)
        sides[name] = {
            "box": [int(v) for v in box],
            "split_conf_ge_80": s_ge80, "split_mean_conf": s_mean, "split_words": s_n,
            "dewarp_conf_ge_80": d_ge80, "dewarp_mean_conf": d_mean, "dewarp_words": d_n,
            "dewarp_method": pd.method, "dewarp_max_disp_px": round(pd.max_disp_px, 1),
            "proxy_flat": proxies(flat_img, cfg),
            "proxy_dewarp": proxies(dw_img, cfg),
        }

    return {
        "id": image_id,
        "width": w, "height": h,
        "applied_rotate": oinfo.applied_rotate,
        "sharp_whole_frame": round(sharpness(img), 1),
        "crop_applied": book.applied,
        "gutter_found": gutter_x is not None,
        "gutter_x": gutter_x,
        "split_method": split_method,
        "subpages": [name for name, _, _ in pieces],
        "two_sided": sorted(s for s in sides) == ["left.png", "right.png"],
        "sides": sides,
        # Sums, directly comparable to the census's per-frame numbers.
        "split_conf_ge_80": sum(s["split_conf_ge_80"] for s in sides.values()),
        "dewarp_conf_ge_80": sum(s["dewarp_conf_ge_80"] for s in sides.values()),
        "seconds": round(time.perf_counter() - t0, 1),
    }


def _side_race(frames: list[dict], pick: str, side: str) -> dict:
    """Who wins one side, and by how much over the incumbent's frame."""
    have = [f for f in frames if f["two_sided"]]
    if not have or pick not in {f["id"] for f in have}:
        return {"side": side, "measurable": False, "winner": None, "challengers": []}
    inc = next(f for f in have if f["id"] == pick)["sides"][side]
    best = max(have, key=lambda f: f["sides"][side]["dewarp_conf_ge_80"])
    # A TIE on the primary statistic is not a difference of opinion between the
    # sides, and reporting it as one inflates the count this probe exists to
    # produce: on zoomset_en_02 both frames read 142 words at conf >= 80 on the
    # right page, and ``max`` handed the side to whichever happened to be first
    # in the list. Ties are named, not broken — breaking one on mean confidence
    # would be choosing a second statistic only where the first is silent.
    tied = [f["id"] for f in have
            if f["sides"][side]["dewarp_conf_ge_80"]
            == best["sides"][side]["dewarp_conf_ge_80"]]
    challengers = [
        {
            "id": f["id"],
            "d_words": f["sides"][side]["dewarp_conf_ge_80"] - inc["dewarp_conf_ge_80"],
            "d_mean_conf": round(f["sides"][side]["dewarp_mean_conf"]
                                 - inc["dewarp_mean_conf"], 1),
        }
        for f in have if f["id"] != pick
    ]
    gains = [c for c in challengers
             if c["d_words"] > CHURN_WORDS and c["d_mean_conf"] > 0]
    return {
        "side": side,
        "measurable": True,
        "winner": None if len(tied) > 1 else best["id"],
        "tie": len(tied) > 1,
        "tied_between": tied if len(tied) > 1 else [],
        "incumbent_words": inc["dewarp_conf_ge_80"],
        "incumbent_mean_conf": inc["dewarp_mean_conf"],
        "challengers": sorted(challengers, key=lambda c: -c["d_words"]),
        "gain": bool(gains),
        "gain_by": [c["id"] for c in gains],
    }


def verdict(frames: list[dict], pick: str) -> dict:
    """Pre-registered rules 1-3, in that order."""
    eligible = [f["id"] for f in frames if f["two_sided"]]
    ineligible = [f["id"] for f in frames if not f["two_sided"]]
    races = {side: _side_race(frames, pick, side)
             for side in ("left.png", "right.png")}
    winners = {r["winner"] for r in races.values() if r["measurable"]}
    both_measurable = all(r["measurable"] for r in races.values())
    any_tie = any(r.get("tie") for r in races.values() if r["measurable"])
    return {
        "eligible": eligible,
        "ineligible_single_page": ineligible,
        "per_page_measurable": both_measurable and len(eligible) >= 2,
        # Rule 2 — the primary result. A tie on either side means the sides do
        # not disagree; it is its own bucket, counted with neither.
        "same_winner_both_sides": (both_measurable and not any_tie
                                   and len(winners) == 1),
        "tie_on_a_side": bool(both_measurable and any_tie),
        "side_winners": {s: r["winner"] for s, r in races.items()},
        # Rule 3.
        "per_page_gain": any(r.get("gain") for r in races.values()),
        "races": races,
    }


# --------------------------------------------------------------------------
# The close-up arm (pre-registration rule 6)
# --------------------------------------------------------------------------


def _poly_page_coverage(corners: list[list[float]], box: tuple[int, int, int, int],
                        shape: tuple[int, int]) -> float:
    """Fraction of the PAGE box covered by the close-up's warped footprint."""
    h, w = shape
    fp = np.zeros((h, w), np.uint8)
    cv2.fillPoly(fp, [np.int32(corners).reshape(-1, 1, 2)], 1)
    x, y, bw, bh = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + bw), min(h, y + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    sub = fp[y0:y1, x0:x1]
    return round(float(sub.sum()) / float(sub.size), 3)


def measure_closeups(name: str, rec: dict, loaded: dict, cfg: dict) -> list[dict]:
    """For each close-up the area gate excluded: where does it land, and does it
    cover a whole PAGE? Registration is ``stage01_fuse.stitch_closeup`` at
    shipped parameters — its NCC gate is what says 'correctly located'."""
    if not rec["closeups_by_area_gate"]:
        return []
    anchor_id = rec["incumbent_pick"]
    anchor = loaded[anchor_id][0]
    aframe = next(f for f in rec["frames"] if f["id"] == anchor_id)
    boxes = {s: tuple(v["box"]) for s, v in aframe["sides"].items()}
    p = S1.resolve_params(cfg)
    out = []
    for cid in rec["closeups_by_area_gate"]:
        cu = loaded[cid][0]
        _, r, note = S1.stitch_closeup(anchor, cu, p)
        row = {
            "id": cid, "anchor": anchor_id, "ncc": r.ncc, "inliers": r.inliers,
            "located": bool(r.corners) and r.ncc >= float(p["min_ncc"]),
            "note": note, "page_coverage": {},
        }
        if r.corners:
            row["page_coverage"] = {
                s: _poly_page_coverage(r.corners, b, anchor.shape[:2])
                for s, b in boxes.items()
            }
            row["best_page_coverage"] = max(row["page_coverage"].values())
            row["eligible_as_page_source"] = bool(
                row["located"] and row["best_page_coverage"] >= MIN_PAGE_COVERAGE)
        else:
            row["best_page_coverage"] = 0.0
            row["eligible_as_page_source"] = False
        out.append(row)
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


PROXIES = (("proxy_flat", "sharp"), ("proxy_flat", "glyph_px"),
           ("proxy_flat", "ink_frac"), ("proxy_dewarp", "sharp"),
           ("proxy_dewarp", "glyph_px"))


def proxy_agreement(out: dict) -> dict:
    """Question 3: could a cheap rule have picked the side races correctly?

    For every side race with an unambiguous OCR winner, ask which frame each
    cheap statistic would have chosen, and whether that is the same frame. The
    number to compare against is NOT zero, it is CHANCE: a race between k
    candidates is won by a coin flip 1/k of the time, so the expectation is
    summed per race and reported beside the hit count. A proxy that scores 11 of
    15 against an expectation of 7.5 has demonstrated nothing on a corpus this
    size, and printing "11 of 15" without the 7.5 would imply it had.

    Quarantined and degenerate sets are included here on purpose. This is a
    question about an INSTRUMENT — does statistic X rank frames the way
    Tesseract does — not about whether the pipeline should change, so the reason
    ``de_01`` is quarantined from the gain verdict does not apply to it.
    """
    hits = {f"{key}@{grp[6:]}": 0 for grp, key in PROXIES}
    races, chance = 0, 0.0
    detail = []
    for name, r in out.items():
        frames = [f for f in r["frames"] if f["two_sided"]]
        if len(frames) < 2:
            continue
        for side in ("left.png", "right.png"):
            top = max(f["sides"][side]["dewarp_conf_ge_80"] for f in frames)
            best = [f for f in frames
                    if f["sides"][side]["dewarp_conf_ge_80"] == top]
            if len(best) > 1:
                continue                    # tie: no answer to agree with
            races += 1
            chance += 1.0 / len(frames)
            row = {"set": name, "side": side, "ocr_winner": best[0]["id"]}
            for grp, key in PROXIES:
                pick = max(frames, key=lambda f: f["sides"][side][grp][key])
                ok = pick["id"] == best[0]["id"]
                hits[f"{key}@{grp[6:]}"] += int(ok)
                row[f"{key}@{grp[6:]}"] = ok
            detail.append(row)
    return {"races": races, "expected_by_chance": round(chance, 1),
            "hits": hits, "detail": detail}


def headline(out: dict) -> dict:
    """Print the pre-registered results in order and return the summary."""
    scored = [k for k, r in out.items()
              if r["verdict"] and r["verdict"]["per_page_measurable"]
              and not r["degenerate"] and not r["quarantined"]]
    same = [k for k in scored if out[k]["verdict"]["same_winner_both_sides"]]
    tied = [k for k in scored if out[k]["verdict"]["tie_on_a_side"]]
    diff = [k for k in scored if k not in same and k not in tied]
    gains = [k for k in scored if out[k]["verdict"]["per_page_gain"]]
    quarantined = [k for k, r in out.items() if r["quarantined"] and r["verdict"]]

    print("\n=== 1. is per-page selection distinguishable at all? ===")
    print(f"  same frame wins BOTH sides: {len(same)}/{len(scored)}  "
          f"({', '.join(same) or '-'})")
    print(f"  winners DIFFER by side:     {len(diff)}/{len(scored)}  "
          f"({', '.join(diff) or '-'})")
    print(f"  a side is TIED (no opinion): {len(tied)}/{len(scored)}  "
          f"({', '.join(tied) or '-'})")
    print(f"\n=== 2. does any side clear the {CHURN_WORDS}-word bar (both stats)? ===")
    print(f"  sets with a per-page gain:  {len(gains)}/{len(scored)}  "
          f"({', '.join(gains) or '-'})")
    for k in quarantined:
        v = out[k]["verdict"]
        print(f"  [quarantined, rule 4] {k}: winners={v['side_winners']} "
              f"gain={v['per_page_gain']}")
    cands = [c for r in out.values() for c in r.get("closeup_arm", [])
             if c["eligible_as_page_source"]]
    n_cu = sum(len(r.get("closeup_arm", [])) for r in out.values())
    pa = proxy_agreement(out)
    print(f"\n=== 3. could a cheap rule pick the winner? "
          f"({pa['races']} decided side races, chance = "
          f"{pa['expected_by_chance']}) ===")
    for k, v in sorted(pa["hits"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18s} agrees with OCR on {v}/{pa['races']}")
    print(f"\n=== 4. close-up arm (bar: page coverage >= {MIN_PAGE_COVERAGE}) ===")
    print(f"  close-ups measured: {n_cu}   eligible as a page source: {len(cands)}"
          f"  ({', '.join(c['id'] for c in cands) or '-'})")
    return {
        "sets_scored": scored,
        "same_winner_both_sides": same,
        "winners_differ_by_side": diff,
        "a_side_is_tied": tied,
        "sets_with_per_page_gain": gains,
        "quarantined": quarantined,
        "closeups_eligible_as_page_source": [c["id"] for c in cands],
        "proxy_agreement": pa,
    }


def _census_selfcheck() -> dict:
    if not CENSUS_JSON.exists():
        return {}
    d = json.loads(CENSUS_JSON.read_text("utf-8"))
    return {f["id"]: {"split": f["split_conf_ge_80"], "dewarp": f["dewarp_conf_ge_80"]}
            for r in d["sets"].values() for f in r["frames"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="write the full record here")
    ap.add_argument("--sets", help="comma-separated subset of set names")
    ap.add_argument("--method", default="auto",
                    help="Stage 03 dewarp arm: auto | classical | uvdoc")
    ap.add_argument("--no-closeups", action="store_true",
                    help="skip the close-up page-coverage arm (rule 6)")
    ap.add_argument("--rescore", type=Path,
                    help="re-derive the verdicts and the headline from an "
                         "existing record, without re-measuring a pixel. The "
                         "per-frame numbers ARE the measurement; the verdict is "
                         "arithmetic over them, so a scoring rule that changes "
                         "(ties, here) must not cost a re-run — and re-running "
                         "would risk quietly reporting different pixels under "
                         "the same date.")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    args = ap.parse_args(argv)

    if args.rescore:
        rec = json.loads(args.rescore.read_text("utf-8"))
        for r in rec["sets"].values():
            two = [f for f in r["frames"] if f["two_sided"]]
            r["verdict"] = (verdict(r["frames"], r["incumbent_pick"])
                            if len(two) >= 2 else None)
        rec["summary"] = headline(rec["sets"])
        args.rescore.write_text(
            json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nrescored {args.rescore}")
        return 0

    cfg = yaml.safe_load(args.config.read_text("utf-8")) or {}
    binary = find_tesseract(cfg)
    if binary is None:
        raise SystemExit(
            "Tesseract not found — it resolves orientation here, so without it "
            "every number would be measured on possibly-sideways pixels. Fix "
            "config.yaml tesseract.binary.")
    tessdata = resolve_tessdata_dir(cfg)

    sets = discover_sets()
    if args.sets:
        want = {s.strip() for s in args.sets.split(",")}
        sets = {k: v for k, v in sets.items() if k in want}

    census = _census_selfcheck()
    out: dict[str, dict] = {}
    for name, ids in sorted(sets.items()):
        langs = languages()
        loaded = {i: load_upright(i, binary, tessdata, cfg) for i in ids}
        dims = [{"name": i, "width": loaded[i][0].shape[1],
                 "height": loaded[i][0].shape[0],
                 "sharpness": sharpness(loaded[i][0])} for i in ids]
        base, full, closeups = partition_frames(
            dims, float(FUSE_DEFAULTS["fullspread_area_frac"]))
        if len(full) < 2 and not (closeups and not args.no_closeups):
            continue          # no choice to make; nothing to say about it

        candidates = [dims[i]["name"] for i in full]
        pick = dims[base]["name"]
        frames = [
            measure_frame(i, loaded[i][0], loaded[i][1], cfg, binary, tessdata,
                          langs.get(i, "eng"), args.method)
            for i in candidates
        ]
        rec = {
            "candidates": candidates,
            "closeups_by_area_gate": [dims[i]["name"] for i in closeups],
            "incumbent_pick": pick,
            "degenerate": name in DEGENERATE,
            "quarantined": name in QUARANTINED,
            "frames": frames,
            "verdict": verdict(frames, pick) if len(full) >= 2 else None,
        }
        if not args.no_closeups:
            rec["closeup_arm"] = measure_closeups(name, rec, loaded, cfg)
        out[name] = rec

        v = rec["verdict"]
        tag = ("DEGENERATE" if rec["degenerate"] else
               "QUARANTINED" if rec["quarantined"] else
               "n/a" if v is None else
               "SAME WINNER" if v["same_winner_both_sides"] else
               "TIED SIDE" if v["tie_on_a_side"] else
               "SPLIT WINNERS" + (" +GAIN" if v["per_page_gain"] else ""))
        print(f"\n{name}  [{tag}]  pick={rec['incumbent_pick']}")
        for f in frames:
            mark = "*" if f["id"] == rec["incumbent_pick"] else " "
            cens = census.get(f["id"])
            chk = (f" census={cens['split']}/{cens['dewarp']}" if cens else "")
            per_side = "  ".join(
                f"{s.split('.')[0]}={v2['dewarp_conf_ge_80']:>4d}/"
                f"{v2['dewarp_mean_conf']:>5.1f} "
                f"(sharp={v2['proxy_flat']['sharp']:.0f} "
                f"glyph={v2['proxy_flat']['glyph_px']:.0f}px)"
                for s, v2 in f["sides"].items())
            print(f"  {mark} {f['id']:<24s} split={f['split_conf_ge_80']:>4d} "
                  f"dewarp={f['dewarp_conf_ge_80']:>4d}{chk}  {per_side}")
        if v is not None:
            print(f"    winners: {v['side_winners']}  "
                  f"gain={v['per_page_gain']}  "
                  f"ineligible(single-page)={v['ineligible_single_page']}")
        for c in rec.get("closeup_arm", []):
            print(f"    close-up {c['id']:<22s} ncc={c['ncc']:>6.3f} "
                  f"located={'y' if c['located'] else 'n'} "
                  f"page_cover={c.get('best_page_coverage', 0.0):.3f} "
                  f"-> {'CANDIDATE' if c['eligible_as_page_source'] else 'no'}")
        sys.stdout.flush()

    summary = headline(out)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "_doc": [
                "Per-page frame selection probe (tools/perpage_choice_probe.py).",
                "Question: can the pipeline do better by choosing a DIFFERENT "
                "photograph for each half of a spread than by cutting one frame "
                "in two, as it does today?",
                "Primary result is the SAME-WINNER COUNT: if the frame that wins "
                "the left page also wins the right page on every set, per-page "
                "selection is a no-op by construction.",
                "Same Tesseract instrument as anchor_downstream_census_20260826 "
                "(_ocr imported, not copied); geometry follows the SHIPPED stage, "
                "including pinch_margin_frac, so pinch splits may differ slightly "
                "from that census — its numbers are echoed per frame as a check.",
                f"A gain needs BOTH statistics, > {CHURN_WORDS} words, PER SIDE — "
                "the census's spread-level churn floor applied unchanged, which "
                "on a half-spread is a stricter bar. Not rescaled on purpose.",
                "de_01 is QUARANTINED (RESULTS 2026-08-26: its disagreement is a "
                "UVDoc per-frame instability, a Stage 03 defect explicitly not to "
                "be chased with an anchor criterion).",
                "skewset_orient_02 is degenerate (0 words both frames, flat).",
                "proxy_flat / proxy_dewarp are LOGGED, not part of any verdict: "
                "'there is headroom' and 'a cheap rule can reach it' are separate "
                "claims and the second is only worth asking if the first holds.",
                "Frames load via tools.normalize.load_upright_bgr, NOT by EXIF.",
            ],
            "params": {"dewarp_method": args.method,
                       "churn_words": CHURN_WORDS,
                       "min_page_coverage": MIN_PAGE_COVERAGE,
                       "fullspread_area_frac": FUSE_DEFAULTS["fullspread_area_frac"]},
            "summary": summary,
            "sets": out,
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
