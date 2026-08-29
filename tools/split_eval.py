"""Stage 02 gutter-split evaluation against testset/gt/gutter.json.

Runs the ACTUAL ``pipeline.stage02_split.detect_gutter`` on every labelled
testset spread and checks the resolved gutter column against ground truth
(within tolerance), or that a ``single`` page stays single. Prints a per-spread
table (method / ratio / pinch-depth / hit) and a pass/fail summary.

This is the non-regression guard for Finding 2 (curved spreads never split): it
proves the layered resolver (a) leaves the 13 flat spreads on their known-good
ink split and (b) rescues the curved spreads via the spine-pinch cue — WITHOUT
splitting anything it shouldn't.

Since v0.3.0 it runs the book-boundary crop too, exactly as ``stage02_split.run``
does — search inside the detected book, report the column in ORIGINAL spread
coordinates. Grading the bare detector would grade something the pipeline no
longer does. Where ``testset/gt/book_box.json`` has a label, it also reports how
much of the labelled book the EMITTED crop would cut away; that column must stay
0.0 %, because losing text is the one failure Stage 02 treats as real.

THIS EVAL IS RED ON PURPOSE since 2026-08-28, and that is not a broken harness.
``paleset_01``/``paleset_02`` are the two real pale-background captures the book
detector fails on; the owner chose to bank them as ordinary graded rows rather
than mark them expected-fail or move them to a second arm, so the run reads
**19/21, exit 1** until the detector is fixed. The 19 pre-existing spreads must
stay correct and worst clipping must stay 0.0 % — that is the non-regression bar.
Do NOT restore a green run by deleting, excusing or re-labelling those two rows.
See ``docs/plans/book-detector-pale-background.md`` and RESULTS 2026-08-28.

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

from pipeline import book_boundary as BB
from pipeline import vlm_box as VLM
from pipeline.stage02_split import (
    DEFAULTS, detect_gutter, draw_overlay_full)

REPO = Path(__file__).resolve().parent.parent
TESTSET = REPO / "testset"
GT_PATH = TESTSET / "gt" / "gutter.json"
BOX_GT_PATH = TESTSET / "gt" / "book_box.json"

# de_* need orientation normalization; the orient_fix jobs hold the landscape
# anchors Stage 00 produces. Everything else is read straight from testset/.
ANCHOR_OVERRIDE = {
    "de_01": REPO / "jobs/orient_fix_de1/page_001/01_fuse/anchor.png",
    "de_02": REPO / "jobs/orient_fix_de2/page_001/01_fuse/anchor.png",
}


def load_anchor(image_id: str, spec: dict | None = None) -> np.ndarray:
    """Resolve a spread id to the image Stage 02 would actually see.

    A GT entry may name its own ``anchor`` file under ``testset/``; the zoomset
    rows do, and their anchors were verified pixel-identical to the Stage 01
    output, so those rows are reproducible from the repo alone. ``ANCHOR_OVERRIDE``
    (de_01/de_02) still reaches into gitignored ``jobs/`` — see gutter.json's _doc.
    """
    named = (spec or {}).get("anchor")
    p = (TESTSET / named) if named else (
        ANCHOR_OVERRIDE.get(image_id) or (TESTSET / f"{image_id}.jpg"))
    img = cv2.imread(str(p), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise FileNotFoundError(f"cannot read anchor for {image_id}: {p}")
    return img


def _clipped_fraction(shape: tuple[int, int], label: dict,
                      emit: tuple[int, int, int, int]) -> float:
    """Percent of the labelled book area that falls OUTSIDE the emitted crop."""
    h, w = shape
    book = np.zeros((h, w), bool)
    book[label["y0"]:label["y1"], label["x0"]:label["x1"]] = True
    kept = np.zeros((h, w), bool)
    kept[emit[1]:emit[3], emit[0]:emit[2]] = True
    total = int(book.sum())
    return 0.0 if total == 0 else 100.0 * float((book & ~kept).sum()) / total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 02 gutter-split eval")
    ap.add_argument("--overlays", action="store_true",
                    help="also (re)write debug overlays under jobs/split_eval/")
    # Grades the SHIPPED fallback, not a variant of it: same module, same
    # params, same "only when the detector abstained" trigger as
    # pipeline/stage02_split. Off here so the guard stays reproducible without
    # a local model server running; config.yaml turns it on for real runs.
    ap.add_argument("--vlm", action="store_true",
                    help="when the detector abstains, aim the gutter search "
                         "with pipeline/vlm_box (needs Ollama running)")
    args = ap.parse_args(argv)

    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))["spreads"]
    box_gt = (json.loads(BOX_GT_PATH.read_text(encoding="utf-8"))["spreads"]
              if BOX_GT_PATH.exists() else {})
    bb_params = BB.resolve_params({})
    overlay_dir = REPO / "jobs" / "split_eval"

    print(f"{'id':13} {'expect':>8} {'got':>6} {'method':>6} {'ratio':>6} "
          f"{'pinch':>6} {'crop':>5} {'clip':>6} {'hit':>4}")
    print("-" * 78)
    n_pass = 0
    worst_clip = 0.0
    for image_id, spec in gt.items():
        img = load_anchor(image_id, spec)
        book = BB.find_book(img, bb_params)
        if args.vlm and not book.applied:
            vbox, _vdiag = VLM.find_box(img, VLM.resolve_params({}))
            if vbox is not None:
                book = BB.search_only(img, vbox, book, bb_params)
        sx0, sy0, sx1, sy1 = book.search
        gray = cv2.cvtColor(img[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)
        gx, diag = detect_gutter(gray, DEFAULTS)
        # Second rung, same as Stage 02's: the book was found but no spine was.
        # No row in this set reaches it today (nothing has a crop AND no
        # gutter), but the harness must run the shipped path, not a subset of
        # it — otherwise the rung ships ungraded.
        if args.vlm and gx is None and book.applied:
            vbox, _ = VLM.find_box(img, VLM.resolve_params({}))
            if vbox is not None:
                retry = BB.search_only(img, vbox, book, bb_params)
                rx0, ry0, rx1, ry1 = retry.search
                r, _rd = detect_gutter(
                    cv2.cvtColor(img[ry0:ry1, rx0:rx1], cv2.COLOR_BGR2GRAY), DEFAULTS)
                if r is not None:
                    book, gx, sx0, sy0, sx1, sy1 = retry, r, rx0, ry0, rx1, ry1
        gx = None if gx is None else gx + sx0   # -> original spread coordinates

        clip = ""
        if image_id in box_gt:
            L = box_gt[image_id]
            ex0, ey0, ex1, ey1 = book.emit
            lost = _clipped_fraction(img.shape[:2], L, (ex0, ey0, ex1, ey1))
            worst_clip = max(worst_clip, lost)
            clip = f"{lost:.1f}%"

        if spec.get("single"):
            hit = gx is None
            expect = "single"
        else:
            expect = str(spec["gutter_x"])
            hit = gx is not None and abs(gx - spec["gutter_x"]) <= spec["tol"]
        n_pass += hit
        print(f"{image_id:13} {expect:>8} {str(gx):>6} {diag['method']:>6} "
              f"{diag['ratio']:>6.2f} {diag['pinch_depth']:>6.2f} "
              f"{('YES' if book.applied else 'no'):>5} {clip:>6} "
              f"{'OK' if hit else 'FAIL':>4}")

        if args.overlays:
            d = overlay_dir / image_id / "debug"
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / "02_split.png"),
                        draw_overlay_full(img, book, gx, diag))

    total = len(gt)
    print("-" * 78)
    print(f"{n_pass}/{total} spreads correct"
          + ("" if n_pass == total else "  <-- REGRESSION"))
    if box_gt:
        print(f"worst clipping of a labelled book by the emitted crop: "
              f"{worst_clip:.1f}%" + ("" if worst_clip == 0.0 else
                                      "  <-- PAGE CONTENT LOST"))
    ok = n_pass == total and worst_clip == 0.0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
