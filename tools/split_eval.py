"""Stage 02 gutter-split evaluation against testset/gt/gutter.json.

Runs the ACTUAL ``pipeline.stage02_split.detect_gutter`` on every labelled
testset spread and checks the resolved gutter column against ground truth
(within tolerance), or that a ``single`` page stays single. Prints a per-spread
table (method / ratio / pinch-depth / hit) and a pass/fail summary.

This is the non-regression guard for Finding 2 (curved spreads never split): it
proves the layered resolver (a) leaves the 13 flat spreads on their known-good
ink split and (b) rescues the curved spreads via the spine-pinch cue — WITHOUT
splitting anything it shouldn't.

    python -m tools.split_eval              # table + summary, exit 0 iff all pass
    python -m tools.split_eval --overlays   # also (re)write debug overlays under
                                            #   jobs/split_eval/<id>/ for eyeballing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from pipeline.stage02_split import DEFAULTS, detect_gutter, draw_overlay

REPO = Path(__file__).resolve().parent.parent
TESTSET = REPO / "testset"
GT_PATH = TESTSET / "gt" / "gutter.json"

# de_* need orientation normalization; the orient_fix jobs hold the landscape
# anchors Stage 00 produces. Everything else is read straight from testset/.
ANCHOR_OVERRIDE = {
    "de_01": REPO / "jobs/orient_fix_de1/page_001/01_fuse/anchor.png",
    "de_02": REPO / "jobs/orient_fix_de2/page_001/01_fuse/anchor.png",
}


def load_anchor(image_id: str) -> np.ndarray:
    p = ANCHOR_OVERRIDE.get(image_id) or (TESTSET / f"{image_id}.jpg")
    img = cv2.imread(str(p), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise FileNotFoundError(f"cannot read anchor for {image_id}: {p}")
    return img


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 02 gutter-split eval")
    ap.add_argument("--overlays", action="store_true",
                    help="also (re)write debug overlays under jobs/split_eval/")
    args = ap.parse_args(argv)

    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))["spreads"]
    overlay_dir = REPO / "jobs" / "split_eval"

    print(f"{'id':13} {'expect':>8} {'got':>6} {'method':>6} {'ratio':>6} "
          f"{'pinch':>6} {'hit':>4}")
    print("-" * 60)
    n_pass = 0
    for image_id, spec in gt.items():
        img = load_anchor(image_id)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gx, diag = detect_gutter(gray, DEFAULTS)

        if spec.get("single"):
            hit = gx is None
            expect = "single"
        else:
            expect = str(spec["gutter_x"])
            hit = gx is not None and abs(gx - spec["gutter_x"]) <= spec["tol"]
        n_pass += hit
        print(f"{image_id:13} {expect:>8} {str(gx):>6} {diag['method']:>6} "
              f"{diag['ratio']:>6.2f} {diag['pinch_depth']:>6.2f} "
              f"{'OK' if hit else 'FAIL':>4}")

        if args.overlays:
            d = overlay_dir / image_id / "debug"
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / "02_split.png"), draw_overlay(img, gx, diag))

    total = len(gt)
    print("-" * 60)
    print(f"{n_pass}/{total} spreads correct"
          + ("" if n_pass == total else "  <-- REGRESSION"))
    return 0 if n_pass == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
