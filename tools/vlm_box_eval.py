"""Does a vision-model book box survive Stage 02? Graded on gutter correctness.

This is the experiment ``docs/notes/2026-08-29-local-llm-available.md``
deliberately did NOT run. That note measured a local vision model's book box
against ``testset/gt/book_box.json`` and got IoU 0.905/0.940 on the two pale
frames the detector fails on. It then said, correctly, that IoU is not the
load-bearing metric: RESULTS 2026-08-28 measured that **asymmetric** box error
breaks the split, because the spine is searched in the middle 30-70% of the box,
so extra width on one edge slides the book sideways until the spine leaves the
band. 8/8 at 5% one-edge excess, 7/8 at 10%, 5/8 at 20% - and the model's
``paleset_01`` box carries a ~5-point excess on its right edge, sitting exactly
on the boundary of the 8/8 row.

So this tool asks the only question that settles it: feed the model's box in
through the SAME path ``tools/book_box_editor`` uses for a hand-drawn one
(``book_boundary.user_box`` - validated, refused when degenerate, padded
``search_pad`` outward), run the real ``detect_gutter``, and read gutter
correctness against ``testset/gt/gutter.json``.

It grades the model, it does not change the pipeline. Nothing here is imported
by any stage.

WHAT THIS RUN IS NOT A REPRODUCTION OF
--------------------------------------
``localLLM/book_box_probe.py`` parses the model's answer under BOTH coordinate
orderings and reports whichever fits the label better. That is a selection made
using the ground truth, so its IoU numbers are an upper bound, not what shipping
would experience. Here the ordering is FIXED a priori to the model's own
documented convention and never chosen per image. A row that only parses under
the other ordering counts as a failure, because that is what the pipeline would
get. Expect numbers at or below the note's.

THE THREE ARMS
--------------
  A  detector      the shipped ``find_book`` - the 19/21 baseline
  B  vlm           the model's box on EVERY row, via ``user_box``
  C  vlm-on-abstain  the model's box only where the detector abstains,
                     the detector's own box otherwise

C is the shape the note proposed (a third box source alongside ``detector`` and
``operator``, consumed where the detector cannot answer) and costs no extra model
calls. Read B as "is the box any good" and C as "would this ship".

Measured before the first model call, and it matters: the shipped detector
ABSTAINS on 17 of the 21 graded rows - all 13 flat fixtures, both de_* spreads,
and both paleset rows. Only the 4 zoomset rows crop today. Two consequences:

  * The 15 currently-correct abstaining rows have NEVER been run through an
    applied crop. That is the real risk surface of this experiment, not the two
    pale rows, whose answer is half known already (a hand-drawn box splits 8/8).
  * "Where the detector abstains" is therefore NOT a narrow trigger. Arms B and
    C differ on 4 rows only. If C regresses, abstain is not a usable gate and
    that is a finding in itself.

THE BAR, PRE-REGISTERED (written before any model was called)
-------------------------------------------------------------
The metric is knife-edge and the box source is stochastic, so the passing
condition is fixed in advance and no pass may be chosen after the fact:

  1. A row counts as CORRECT only if ALL ``--passes`` passes land within the
     row's ``tol`` of its labelled gutter. 2 of 3 is a FAIL. The per-pass spread
     of the gutter column is itself reported.
  2. The two open rows must move to correct:
       paleset_01  gutter 1680 +-200 -> [1480, 1880]   (shipped today: 2741)
       paleset_02  gutter 1778 +-200 -> [1578, 1978]   (shipped today: none)
     Prior art for scale, from a HAND-DRAWN box (RESULTS 2026-08-28):
     1699 and 1749.
  3. The 19 rows that are correct today must still be correct in arm C.
     Arm B is allowed to regress - it is the honest measurement of the box, not
     a proposed design - but every regression must be reported by name.

Clipping is reported and is expected to read 0.0% by construction: ``user_box``
pads 8% outward and unions emit with search, so the emitted crop is generous on
purpose. Do NOT present that 0.0% as evidence of anything. Gutter correctness is
the whole signal.

CEILING. Two pale frames are two SCENES, not two examples. Whatever this run
says, it can only support "this box source is / is not worth pursuing". It
cannot say the pale-background defect is fixed, and it is not a reason to touch
``split_eval``'s deliberate 19/21 - a passing experiment is a reason to build the
fix, not to relabel the rows. See ``docs/plans/pale-background-fixture-shoot.md``.

    python -m tools.vlm_box_eval --model qwen3.6:27b --passes 3
    python -m tools.vlm_box_eval --only paleset_01,paleset_02 --overlays
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

from pipeline import book_boundary as BB
from pipeline.stage02_split import DEFAULTS, detect_gutter, draw_overlay_full
from tools.split_eval import GT_PATH, BOX_GT_PATH, REPO, TESTSET, load_anchor

OLLAMA = "http://127.0.0.1:11434"
CACHE = REPO / "docs" / "data" / "vlm_box_split_20260829.json"

# Fixed a priori to the model's own documented convention. NEVER selected per
# image against the label - see the module docstring.
ORDER = "xyxy"
PROMPT = (
    "This photograph shows an open book lying on a surface. "
    "Return the bounding box of the book itself - the two visible facing pages, "
    "including their printed area and margins. Exclude the surface, the table, "
    "the photographer's hands and the room. "
    'Answer with JSON only, exactly: {"bbox_2d": [x1, y1, x2, y2], "label": "book"} '
    "with coordinates normalised to 0-1000. No other text."
)


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


def encode(img: np.ndarray, max_side: int) -> str:
    """Downscale a BGR array to ``max_side`` and return base64 JPEG."""
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ask(model: str, b64: str, num_ctx: int, timeout: int) -> tuple[str, float]:
    t0 = time.time()
    r = requests.post(
        f"{OLLAMA}/api/generate",
        json={"model": model, "prompt": PROMPT, "images": [b64],
              "stream": False, "think": False,
              # Ollama defaults num_ctx to 4096 whatever the model advertises,
              # and truncates silently. Always set it.
              "options": {"temperature": 0, "num_ctx": num_ctx}},
        timeout=timeout)
    r.raise_for_status()
    return r.json()["response"], time.time() - t0


def parse_box(text: str, w: int, h: int) -> tuple[list[int] | None, str]:
    """First 4-number list in the answer -> pixel box under the FIXED order.

    Returns ``(box, how_read)``. Values are read as 0-1000 normalised, the
    convention the prompt asks for. Anything above 1000 is REFUSED rather than
    reinterpreted as pixels: rescuing an off-convention answer is exactly the
    per-image selection this tool exists to avoid, and the pipeline would not
    rescue it either. Both rules are fixed in advance and neither consults the
    label.
    """
    import re
    vals: list[float] | None = None
    for blob in re.findall(r"\[[^\[\]]*\]", text):
        nums = re.findall(r"-?\d+(?:\.\d+)?", blob)
        if len(nums) == 4:
            vals = [float(n) for n in nums]
            break
    if vals is None:
        return None, "unparseable"
    x0, y0, x1, y1 = vals            # ORDER == "xyxy", never flipped
    if max(vals) > 1000.0:
        return None, "out-of-range"  # not 0-1000; refuse rather than guess
    box = [int(round(x0 / 1000 * w)), int(round(y0 / 1000 * h)),
           int(round(x1 / 1000 * w)), int(round(y1 / 1000 * h))]
    return [min(box[0], box[2]), min(box[1], box[3]),
            max(box[0], box[2]), max(box[1], box[3])], "norm1000"


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------


def gutter_of(img: np.ndarray, book: BB.BookBoundary) -> tuple[int | None, dict]:
    """Run the real Stage 02 gutter search inside a boundary's search window."""
    sx0, sy0, sx1, sy1 = book.search
    gray = cv2.cvtColor(img[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)
    gx, diag = detect_gutter(gray, DEFAULTS)
    return (None if gx is None else gx + sx0), diag


def hit_of(gx: int | None, spec: dict) -> bool:
    if spec.get("single"):
        return gx is None
    return gx is not None and abs(gx - spec["gutter_x"]) <= spec["tol"]


def clipped_fraction(shape: tuple[int, int], label: dict,
                     emit: tuple[int, int, int, int]) -> float:
    """Percent of the labelled book that falls OUTSIDE the emitted crop."""
    h, w = shape
    book = np.zeros((h, w), bool)
    book[label["y0"]:label["y1"], label["x0"]:label["x1"]] = True
    kept = np.zeros((h, w), bool)
    kept[emit[1]:emit[3], emit[0]:emit[2]] = True
    total = int(book.sum())
    return 0.0 if total == 0 else 100.0 * float((book & ~kept).sum()) / total


def edge_excess(pred: list[int], label: dict) -> dict[str, float]:
    """Per-edge excess as a fraction of the labelled book, in percent.

    Positive = the box sits OUTSIDE the book on that edge (safe for clipping,
    but this is exactly the asymmetry RESULTS 2026-08-28 measured as
    split-breaking). Negative = the box cuts into the book.
    """
    bw = float(label["x1"] - label["x0"])
    bh = float(label["y1"] - label["y0"])
    return {"left": 100.0 * (label["x0"] - pred[0]) / bw,
            "right": 100.0 * (pred[2] - label["x1"]) / bw,
            "top": 100.0 * (label["y0"] - pred[1]) / bh,
            "bottom": 100.0 * (pred[3] - label["y1"]) / bh}


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="qwen3.6:27b")
    ap.add_argument("--passes", type=int, default=3,
                    help="model calls per image; ALL must hit for a row to pass")
    ap.add_argument("--max-side", type=int, default=1120)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", default="", help="comma-separated spread ids")
    ap.add_argument("--refresh", action="store_true",
                    help="re-query the model even for cached passes")
    ap.add_argument("--overlays", action="store_true",
                    help="write arm-B overlays under M:/claud_projects/temp")
    args = ap.parse_args(argv)

    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))["spreads"]
    box_gt = json.loads(BOX_GT_PATH.read_text(encoding="utf-8"))["spreads"]
    only = {s for s in args.only.split(",") if s}
    ids = [i for i in gt if not only or i in only]
    params = BB.resolve_params({})

    cache: dict = (json.loads(CACHE.read_text(encoding="utf-8"))
                   if CACHE.exists() and not args.refresh else {})
    boxes: dict = cache.setdefault("boxes", {})
    rows: dict = {}

    print(f"model={args.model} passes={args.passes} max_side={args.max_side} "
          f"order={ORDER}")
    print(f"{'id':13} {'expect':>7} {'A:det':>7} {'B:vlm passes':>26} "
          f"{'C':>7} {'A':>4} {'B':>4} {'C':>4}")
    print("-" * 84)

    for image_id in ids:
        spec = gt[image_id]
        img = load_anchor(image_id, spec)
        h, w = img.shape[:2]

        # --- arm A: the shipped detector -----------------------------------
        det = BB.find_book(img, params)
        gx_a, _ = gutter_of(img, det)
        hit_a = hit_of(gx_a, spec)

        # --- the model's box, once per pass, cached -------------------------
        per = boxes.setdefault(image_id, [])
        b64 = None
        while len(per) < args.passes:
            if b64 is None:
                b64 = encode(img, args.max_side)
            text, secs = ask(args.model, b64, args.num_ctx, args.timeout)
            box, how = parse_box(text, w, h)
            per.append({"box": box, "read_as": how, "secs": round(secs, 1),
                        "raw": text.strip()[:400]})
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")

        # --- arms B and C ---------------------------------------------------
        gx_b: list[int | None] = []
        hits_b: list[bool] = []
        clips_b: list[float] = []
        for p in per[:args.passes]:
            if p["box"] is None:
                gx_b.append(None)
                hits_b.append(False)
                continue
            ub = BB.user_box(img, tuple(p["box"]), params)
            g, _ = gutter_of(img, ub)
            gx_b.append(g)
            hits_b.append(hit_of(g, spec))
            if image_id in box_gt:
                clips_b.append(clipped_fraction((h, w), box_gt[image_id], ub.emit))

        # C uses the detector wherever it did NOT abstain.
        gx_c = [gx_a] * args.passes if det.applied else gx_b
        hits_c = [hit_a] * args.passes if det.applied else hits_b

        ok_b = all(hits_b) and len(hits_b) == args.passes
        ok_c = all(hits_c) and len(hits_c) == args.passes
        expect = "single" if spec.get("single") else str(spec["gutter_x"])
        print(f"{image_id:13} {expect:>7} {str(gx_a):>7} "
              f"{','.join(str(g) for g in gx_b):>26} "
              f"{('det' if det.applied else 'vlm'):>7} "
              f"{('OK' if hit_a else 'FAIL'):>4} "
              f"{('OK' if ok_b else 'FAIL'):>4} "
              f"{('OK' if ok_c else 'FAIL'):>4}")

        rows[image_id] = {
            "expect": spec.get("gutter_x"), "tol": spec.get("tol"),
            "detector_abstained": not det.applied,
            "A_gutter": gx_a, "A_hit": hit_a,
            "B_gutters": gx_b, "B_hits": hits_b, "B_ok": ok_b,
            "C_source": "detector" if det.applied else "vlm",
            "C_gutters": gx_c, "C_ok": ok_c,
            "B_worst_clip_pct": round(max(clips_b), 3) if clips_b else None,
            "boxes": [p["box"] for p in per[:args.passes]],
            "read_as": [p["read_as"] for p in per[:args.passes]],
            "edge_excess_pct": (
                [None if p["box"] is None else
                 {k: round(v, 2) for k, v in
                  edge_excess(p["box"], box_gt[image_id]).items()}
                 for p in per[:args.passes]] if image_id in box_gt else None),
        }

        if args.overlays and per[0]["box"] is not None:
            ub = BB.user_box(img, tuple(per[0]["box"]), params)
            g, dg = gutter_of(img, ub)
            d = Path(r"M:\claud_projects\temp\bookscan_vlm_box")
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / f"{image_id}_vlm.png"),
                        draw_overlay_full(img, ub, g, dg))

    n_a = sum(r["A_hit"] for r in rows.values())
    n_b = sum(r["B_ok"] for r in rows.values())
    n_c = sum(r["C_ok"] for r in rows.values())
    total = len(rows)
    print("-" * 84)
    print(f"A detector      {n_a}/{total}")
    print(f"B vlm everywhere {n_b}/{total}")
    print(f"C vlm on abstain {n_c}/{total}")
    regressed = [i for i, r in rows.items() if r["A_hit"] and not r["C_ok"]]
    fixed = [i for i, r in rows.items() if not r["A_hit"] and r["C_ok"]]
    print(f"C fixed:     {', '.join(fixed) or '(none)'}")
    print(f"C regressed: {', '.join(regressed) or '(none)'}")

    cache["run"] = {
        "date": "2026-08-29", "model": args.model, "passes": args.passes,
        "max_side": args.max_side, "num_ctx": args.num_ctx, "order": ORDER,
        "prompt": PROMPT,
        "summary": {"A": n_a, "B": n_b, "C": n_c, "total": total,
                    "C_fixed": fixed, "C_regressed": regressed},
        "rows": rows,
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    print(f"\nwrote {CACHE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
