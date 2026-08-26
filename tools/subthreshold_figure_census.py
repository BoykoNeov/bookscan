"""Census of SUB-THRESHOLD DocLayout-YOLO figure detections on the block-order
fixtures — the measurement behind ``docs/RESULTS.md``'s ``it_geo_07`` D1 entry.

Why it exists. RESULTS recorded D1 (a thin cross-section diagram) as a figure the
detector "never finds", IoU 0.000 against everything it emits. That is true of the
SHIPPED block set and false of the detector: re-run at ``conf_thresh`` 0.02, the
model puts a ``figure`` box over D1 at confidence **0.247** — three thousandths
under the shipped 0.25 floor. So the open question is not "why is the picture
invisible" but "is there a defensible rule that admits a sub-threshold figure box
without admitting junk". This tool measures the two populations so that question
is answered with a table instead of a threshold nudge.

For every graded subpage it runs the detector twice — once at the shipped params
(the ACCEPTED blocks, i.e. what Stage 04 actually emits, post NMS / figure-split /
XY-cut) and once at ``--low-conf`` — and for each raw ``figure``-label detection
records:

  * ``conf``;
  * ``iou_gt`` — best IoU against the subpage's GT figure bboxes (GT figures
    without a bbox are skipped: ``it_geo_04`` predates them);
  * ``covered`` — fraction of the detection's own area covered by the union of
    ACCEPTED blocks, via the SAME ``stage04_layout.covered_fraction`` the shipped
    rescue rule uses, so the measurement and the rule cannot drift apart. The junk in a low-conf dump is mostly duplicate boxes on
    already-accepted text and page-spanning blobs; both are highly covered. D1's
    box lands where no accepted block is.
  * ``area_frac`` — its area as a fraction of the subpage, to catch the
    page-spanning blobs directly;
  * ``text_cover`` — fraction of it covered by the union of the TEXT-labelled
    detections in the same low-confidence pass. A printed scale bar or a header
    strip is text the model also boxed as text; a photograph is not.

Usage:
    python -m tools.subthreshold_figure_census --json-out out.json
    python -m tools.subthreshold_figure_census --image it_geo_07 --low-conf 0.02
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from tools import normalize as NORM
from tools.gate1_harness import (
    REPO_ROOT, find_tesseract, load_config, resolve_tessdata_dir,
)
from tools.dewarp_ab import split_halves, dewarp_halves
from tools.layout_order_eval import _bbox_iou
from pipeline import stage04_layout as S4
from pipeline.stage04_layout import covered_fraction

FIXTURES = ["de_01", "en_coins_01", "en_coins_02", "en_coins_03",
            "it_geo_04", "it_geo_05", "it_geo_06", "it_geo_07"]


def census_image(image_id: str, testset: Path, cfg: dict, binary: str,
                 low_conf: float) -> list[dict]:
    gt_path = testset / "gt" / f"{image_id}.blocks.json"
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    img_file = testset / f"{image_id}.jpg"
    tessdata = resolve_tessdata_dir(cfg)
    bgr, _ = NORM.load_upright_bgr(img_file, binary, tessdata)

    p = S4.resolve_params(cfg)
    p_low = dict(p)
    p_low["conf_thresh"] = low_conf

    halves, _ = split_halves(bgr, cfg)
    dw = dewarp_halves(halves, cfg, "auto")

    warns: list[str] = []
    det_model = S4.make_detector("auto", cfg, warns)
    rows: list[dict] = []
    try:
        for name, img, _pd in dw:
            sub = "left" if "left" in name else ("right" if "right" in name else name)
            gsub = gt["subpages"].get(sub)
            if gsub is None:
                continue
            h, w = img.shape[:2]
            # what Stage 04 actually emits, at the shipped params
            pl = S4.layout_page(img, cfg, p, warns, det_model)
            accepted = [b.bbox for b in pl.blocks]
            gt_figs = [g for g in gsub["reading_order"]
                       if g["type"] == "figure" and g.get("bbox")]
            raw = det_model.detect(img, p_low)
            text_boxes = [d.bbox for d in raw if d.label != "figure"]
            for d in raw:
                if d.label != "figure":
                    continue
                best_iou, best_id = 0.0, None
                for g in gt_figs:
                    v = _bbox_iou(g["bbox"], d.bbox)
                    if v > best_iou:
                        best_iou, best_id = v, g["id"]
                rows.append({
                    "image": image_id, "subpage": sub,
                    "conf": round(d.conf, 4),
                    "bbox": [d.bbox.x, d.bbox.y, d.bbox.w, d.bbox.h],
                    "shipped": bool(d.conf >= float(p["conf_thresh"])),
                    "iou_gt": round(best_iou, 4),
                    "gt_id": best_id,
                    "covered": round(covered_fraction(d.bbox, accepted, w, h), 4),
                    "area_frac": round(d.bbox.w * d.bbox.h / float(w * h), 4),
                    "text_cover": round(covered_fraction(d.bbox, text_boxes, w, h), 4),
                    "n_gt_fig_bbox": len(gt_figs),
                })
    finally:
        det_model.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sub-threshold figure-detection census")
    ap.add_argument("--testset", type=Path, default=REPO_ROOT / "testset")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--image", action="append", default=[],
                    help="restrict to this image_id (repeatable)")
    ap.add_argument("--low-conf", type=float, default=0.02)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_config(args.config)
    binary = find_tesseract(cfg)
    if not binary:
        print("ERROR: Tesseract not found.", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for image_id in (args.image or FIXTURES):
        print(f"[census] {image_id}")
        rows.extend(census_image(image_id, args.testset, cfg, binary,
                                 args.low_conf))

    ship = [r for r in rows if r["shipped"]]
    subs = [r for r in rows if not r["shipped"]]
    hit = [r for r in subs if r["iou_gt"] >= 0.2]
    junk = [r for r in subs if r["iou_gt"] < 0.2]
    print(f"\nfigure dets: {len(rows)}  shipped(>=0.25): {len(ship)}  "
          f"sub-threshold: {len(subs)}  of which GT-hitting: {len(hit)}")

    def table(title: str, rs: list[dict]) -> None:
        print(f"\n--- {title} (n={len(rs)})")
        print("  image       subpage  conf   iou_gt  covered  area   txtcov  gt")
        for r in sorted(rs, key=lambda r: -r["conf"]):
            gid = r["gt_id"] or "-"
            print(f"  {r['image']:<12}{r['subpage']:<8}{r['conf']:>6.3f} "
                  f"{r['iou_gt']:>7.3f} {r['covered']:>7.3f} "
                  f"{r['area_frac']:>6.3f} {r['text_cover']:>7.3f}  {gid}")

    table("SUB-THRESHOLD, hits a GT figure (IoU>=0.2)", hit)
    table("SUB-THRESHOLD, hits nothing", junk)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({
            "generated": datetime.date.today().isoformat(),
            "low_conf": args.low_conf,
            "shipped_conf_thresh": S4.DEFAULTS["conf_thresh"],
            "rows": rows,
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
