"""Which tables and unreadable panels on the owner's book already have a close-up?

Census only, no reader. The population is every block in the owner's document
(job 20260829-084115-de3c20d3) that is a TABLE, or a FIGURE that
``unreadable_panel`` promoted from text (``type_promoted``): the blocks where the
book loses its text today. For each, ``figure_hires.candidates`` searches the
spread's own captures with the shipped gates (min_inliers, min_ncc, scale band),
except ``min_figure_px``, which is set to 0 here: it is a "nothing to see" floor
for picture upgrades, and several icon-sidebar panels sit just under it.

Every frame of this job was uploaded BEFORE the 2026-10-21 phone change, so each
close-up was shrunk to half its area on the phone; the scales below are of the
shrunk frames.

Run:  python -X utf8 docs/data/panelread_20261021/coverage_census.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH  # noqa: E402
from pipeline.stage07_assemble import _capture_frames  # noqa: E402

JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
OUT = Path(__file__).with_name("coverage_census.json")


def population(doc: dict) -> list[tuple[dict, dict]]:
    out = []
    for p in doc["pages"]:
        for b in p["blocks"]:
            if b["type"] == "table" or (b["type"] == "figure" and b.get("type_promoted")):
                out.append((p, b))
    return out


def main() -> None:
    import yaml
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    params = FH.resolve_params(cfg)
    params["min_figure_px"] = 0
    cv2.setRNGSeed(0)
    doc = json.loads((JOB / "document.json").read_text(encoding="utf-8"))
    pop = population(doc)
    frames_by_spread: dict[str, list] = {}
    rows = []
    for p, b in pop:
        spread = p["source_spread"]
        if spread not in frames_by_spread:
            frames_by_spread[spread] = _capture_frames(JOB / spread, params)
            for fi in frames_by_spread[spread]:
                fi.build()
        frames = frames_by_spread[spread]
        anchor = json.loads((JOB / spread / "01_fuse" / "fuse.json")
                            .read_text(encoding="utf-8"))["anchor_source"]
        page = cv2.imread(str(JOB / p["image_asset"]), cv2.IMREAD_COLOR)
        bb = b["bbox"]
        crop = page[bb["y"]:bb["y"] + bb["h"], bb["x"]:bb["x"] + bb["w"]]
        cands = FH.candidates(crop, frames, params)
        # Second pass with no scale floor: a close-up that holds the block but
        # adds no resolution (shrunk on the phone) is "aimed, too small", which
        # is a different capture problem from "never aimed there".
        loose = dict(params, min_scale=0.0)
        any_cov = [c.src.as_dict() for c in FH.candidates(crop, frames, loose)]
        srcs = sorted((c.src.as_dict() for c in cands), key=lambda s: -s["scale"])
        closeups = [s for s in srcs if s["frame"] != anchor]
        best_cov = max((s["coverage"] for s in closeups), default=0.0)
        row = {"page": p["page_id"], "block": b["id"], "type": b["type"],
               "promoted": bool(b.get("type_promoted")), "bbox": bb,
               "n_words": len(b["words"]), "anchor": anchor,
               "n_frames": len(frames), "sources": srcs,
               "any_scale_sources": any_cov,
               "closeup_best_coverage": best_cov,
               "closeup_whole": best_cov >= 0.90}
        rows.append(row)
        print(f"{p['page_id']:16s} #{b['id']:<3d} {b['type']:6s} "
              f"{bb['w']:>4d}x{bb['h']:<4d} frames={len(frames):2d} "
              f"close-ups found={len(closeups)} best_cov={best_cov:.2f} "
              + " ".join(f"{s['frame']}@{s['scale']}x/{s['coverage']}" for s in closeups[:4])
              + " | any-scale: " + " ".join(f"{s['frame']}@{s['scale']}x/{s['coverage']}"
                                          for s in any_cov if s['frame'] != anchor),
              flush=True)
        for fi in frames:
            fi.release()
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    n = len(rows)
    any_c = sum(1 for r in rows if r["closeup_best_coverage"] > 0)
    whole = sum(1 for r in rows if r["closeup_whole"])
    print(f"\n{n} blocks; {any_c} have a close-up holding part of them; "
          f"{whole} have one close-up holding >= 90 %")


if __name__ == "__main__":
    main()
