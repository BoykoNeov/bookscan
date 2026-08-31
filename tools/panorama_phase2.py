"""Panorama Phase 2 - does a page assembled from close-ups READ better?

``docs/plans/panorama-and-next-steps.md`` section 1, Phase 2. Phase 0 measured
**placement** and passed (RESULTS 2026-08-31): a raw close-up registered onto the
*flattened* page, corrected over its own footprint, sits 1.39 px from where it
belongs against a 0.09 px floor. Placement is not the deliverable. This asks the
question that is: put the well-placed close-ups down and read the page.

The gate, the population, the displacement threshold, the canvas rule and the
statistic are all pre-registered in
``docs/data/panorama_phase2_prereg_20260831.md`` and are not to be moved after
the fact. Three of them are worth repeating here because they are what make a
number readable:

  * **10 anchor px, not 5.** Read off Phase 0's committed data *before* the
    pre-registration was written: a 5 px rule admits ZERO sources on all three
    spreads, so it could only ever return a null.
  * **The statistic is confident words INSIDE the painted union**, not
    whole-page. A seven-source paint diluted across a whole spread is a
    statistic that cannot see its own subject.
  * **The control is not the spread that paints nothing.** ``page_024`` admits
    no source, so its composite is byte-identical to its control - that is an
    assertion that the rule fires, not an OCR arm. The control is arm **X**,
    painting the sources the rule REJECTS, which must LOSE. If it does not, the
    instrument cannot see the failure it exists to prevent and the result is
    uninterpretable rather than a pass. Same role as Phase 0's 0.09 px floor.

**Placement is Phase 0's arm D, imported rather than re-implemented** - the
registration, its thresholds and its statistic all come from
``tools.panorama_phase0``, so "unchanged" is true by construction and cannot
drift.

Usage::

    python -m tools.panorama_phase2 [--job jobs/<id>] [--pages page_021 ...]
                                    [--out docs/data/panorama_phase2.json]
                                    [--dump DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH          # noqa: E402
from pipeline import stage03_dewarp as S3        # noqa: E402
from pipeline import stage04_layout as S4        # noqa: E402
from pipeline import stage05_ocr as S5           # noqa: E402
from tools import panorama_phase0 as P0          # noqa: E402

DEFAULT_JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
DEFAULT_PAGES = ("page_021", "page_013", "page_024")

# --- pre-registered, docs/data/panorama_phase2_prereg_20260831.md -----------
MAX_FLOW_P95_ANCHOR = 10.0   # worst-twentieth leftover displacement, anchor px
MIN_OWN_SCALE = 1.0          # a source may not paint pixels it does not have
FEATHER_PX = 2.0             # hard narrow seam (figure_hires uses 24 for figures)
HIGH_CONF = 80.0             # this repo's existing convention
MIN_UNION_WORDS = 50         # below this a subpage reports no verdict
LANG = "deu"                 # this book is German
# Placement is NOT reproducible run to run: cv::theRNG() feeds both RANSAC and
# FLANN's randomised index, and three draws of one source straddled the 10 px
# bar (9.76 / 10.25 / 14.34). Seeding pins a draw, but picking one seed would
# only hide it, so a source must clear the bar on its WORST draw. Amendment 9 of
# the pre-registration, written before any composite existed; the alternatives
# and why they lose are recorded there.
SEEDS = (0, 1, 2)
# "text" means every block type that is not a picture. Stage 04's own words are
# the vocabulary; the deliverable renders a FIGURE as pixels, so words OCR'd off
# a map are not text the re-typeset PDF will ever contain, and counting them
# would be measuring something the reader never sees.
NON_TEXT_TYPES = {"figure"}


# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------

def own_scale(H: np.ndarray, w: int, h: int) -> float:
    """Source pixels per TARGET pixel at the source's centre.

    ``FH.local_scale`` answers the other way round (target px per source px), so
    a close-up carrying more detail than the page reads < 1 there and > 1 here.
    """
    s = FH.local_scale(H, w / 2.0, h / 2.0)
    return 1.0 / max(1e-6, s)


def seed(sd: int) -> None:
    """Pin one draw. Both halves matter: ``setRNGSeed`` fixes what RANSAC and
    FLANN's index construction consume, and the cached matcher carries state of
    its own, so it is rebuilt too. Verified byte-reproducible over three runs."""
    cv2.setRNGSeed(int(sd))
    P0._flann._i = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5),
                                         dict(checks=64))


def measure_source(img, base, kd_src, kd_base, params) -> dict | None:
    """Register a raw close-up onto ONE native dewarped subpage, exactly as
    Phase 0's arm D, once per seed.

    ``flow_p95`` is the WORST of the draws - a source that is only sometimes
    well placed will sometimes double the text, and a paint is not re-rolled per
    reader. A draw that fails to register or fails the photometric bar
    disqualifies the source outright rather than being averaged away.
    """
    draws, H0 = [], None
    for sd in SEEDS:
        seed(sd)
        r = P0.register(kd_src, kd_base)
        if not r or r["inliers"] < P0.MIN_INLIERS:
            return None
        st = P0.arm(img, base, r["H"], params)             # homography alone
        if not st or st.get("ncc", 0.0) < P0.MIN_NCC:
            return None
        d = P0.arm(img, base, r["H"], params, "footprint")  # + local bend = arm D
        if not d:
            return None
        draws.append({"seed": sd, "inliers": r["inliers"], "ncc": st["ncc"],
                      "flow_med": d.get("flow_med"),
                      "flow_p95": d.get("flow_p95"),
                      "resid_med": d.get("resid_med"),
                      "degenerate": d.get("degenerate")})
        if H0 is None:
            H0 = r["H"]
    fp = [d["flow_p95"] for d in draws if d["flow_p95"] is not None]
    return {"H": H0, "draws": draws, "inliers": draws[0]["inliers"],
            "ncc": draws[0]["ncc"], "flow_med": draws[0]["flow_med"],
            "flow_p95": max(fp) if len(fp) == len(SEEDS) else None,
            "flow_p95_draws": [round(v, 2) for v in fp],
            "degenerate": draws[0]["degenerate"],
            "own_scale": own_scale(H0, img.shape[1], img.shape[0])}


# --------------------------------------------------------------------------
# the paint
# --------------------------------------------------------------------------

def paint(canvas: np.ndarray, sources: list[dict], params: dict) -> tuple:
    """Sharpest-first, each source painting only pixels no better source has
    claimed, hard narrow seam.

    Both halves of that ordering rule are measured, in ``figure_hires``: painting
    every source repaints the same middle so the LAST one applied wins it, and
    ordering by coverage instead of resolution hands every overlap to the source
    with least detail to offer. The only departure is the seam - 2 px against
    that module's 24, because a wide feather is what smeared two disagreeing
    sources across the under-covered composite, and here the sources are
    deliberately few and far apart.
    """
    out = canvas.copy()
    union = np.zeros(canvas.shape[:2], np.uint8)
    laid = []
    for s in sorted(sources, key=lambda z: -z["own_scale"]):
        warped, m = P0.place(s["img"], s["Hc"], canvas.shape[:2])
        box = P0.footprint(m)
        if box is None:
            laid.append({"frame": s["frame"], "painted_px": 0,
                         "why": "footprint too small on canvas"})
            continue
        x0, y0, x1, y1 = box
        w = warped[y0:y1, x0:x1]
        mm = m[y0:y1, x0:x1]
        ref = canvas[y0:y1, x0:x1]          # the BASE, never the running paint:
        got = FH._mesh_refine(w, mm, ref, params)   # registration is to the base
        mesh_ok = got is not None
        if mesh_ok:
            w, mm = got
        w = FH._harmonise(w, ref, mm)
        claim = ((mm > 0) & (union[y0:y1, x0:x1] == 0)).astype(np.uint8)
        n = int(claim.sum())
        if n < 1000:
            laid.append({"frame": s["frame"], "painted_px": n,
                         "why": "nothing left unclaimed"})
            continue
        dist = cv2.distanceTransform(claim, cv2.DIST_L2, 5)
        alpha = np.clip(dist / FEATHER_PX, 0.0, 1.0)[..., None]
        sub = out[y0:y1, x0:x1]
        out[y0:y1, x0:x1] = (w.astype(np.float32) * alpha +
                             sub.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
        u = union[y0:y1, x0:x1]
        u[claim > 0] = 255
        laid.append({"frame": s["frame"], "painted_px": n,
                     "own_scale": round(s["own_scale"], 3),
                     "flow_p95_anchor": s["flow_p95_anchor"],
                     "mesh_applied": mesh_ok,
                     "box_canvas": [x0, y0, x1, y1]})
    return out, union, laid


# --------------------------------------------------------------------------
# the instrument
# --------------------------------------------------------------------------

def read(binary: str, cfg: dict, img: np.ndarray) -> list[dict]:
    """One whole-canvas Tesseract pass, mapped back to canvas coordinates.

    The pipeline reads a subpage in one pass and then attaches words to blocks,
    so this is the pipeline's own instrument rather than a per-crop stand-in.
    Every arm is the same canvas size, so the probe's upscale decision is the
    same on all of them and cannot become a hidden difference.
    """
    twords, scale = S5.ocr_subpage(binary, cfg, img, LANG)
    out = []
    for tw in twords:
        t = (tw.text or "").strip()
        if not t:
            continue
        b = S5._word_box(tw, scale)
        out.append({"text": t, "conf": float(tw.conf),
                    "x": b.x, "y": b.y, "w": b.w, "h": b.h})
    return out


def inside(mask: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    H, W = mask.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return False
    return bool(mask[y0:y1, x0:x1].all())


def in_block(word: dict, box) -> bool:
    cx, cy = word["x"] + word["w"] / 2.0, word["y"] + word["h"] / 2.0
    return (box[0] <= cx < box[2]) and (box[1] <= cy < box[3])


def score(words: list[dict], boxes: list) -> dict:
    sel = [w for w in words if any(in_block(w, b) for b in boxes)]
    hi = [w for w in sel if w["conf"] >= HIGH_CONF]
    return {"words": len(sel), "high_conf": len(hi),
            "mean_conf": (round(float(np.mean([w["conf"] for w in sel])), 1)
                          if sel else None),
            "text": " ".join(w["text"] for w in sel)}


def diff(a: list[dict], b: list[dict], boxes: list) -> dict:
    """What arm A reads confidently and arm B does not, and the reverse.

    A multiset difference over the confident words, which is what the gate needs:
    'more confident words' can hide a swap of correct text for wrong text, and
    per plan section 0 a count is not allowed to decide this on its own.
    """
    from collections import Counter
    ca = Counter(w["text"] for w in a
                 if w["conf"] >= HIGH_CONF and any(in_block(w, x) for x in boxes))
    cb = Counter(w["text"] for w in b
                 if w["conf"] >= HIGH_CONF and any(in_block(w, x) for x in boxes))
    lost = sorted((ca - cb).elements())
    gained = sorted((cb - ca).elements())
    return {"lost": lost, "gained": gained,
            "n_lost": len(lost), "n_gained": len(gained)}


# --------------------------------------------------------------------------

def run_subpage(name: str, sub: str, base: np.ndarray, blocks: list,
                srcs: list[dict], binary: str, cfg: dict, params: dict,
                dump: Path | None) -> dict:
    admitted = [s for s in srcs if s["admitted"]]
    rejected = [s for s in srcs if not s["admitted"]]
    rec = {"subpage": sub, "native": [base.shape[1], base.shape[0]],
           "registered": len(srcs), "admitted": len(admitted),
           "rejected": len(rejected),
           "admitted_frames": [s["frame"] for s in admitted],
           "near_min_scale": sum(1 for s in admitted
                                 if 1.0 <= s["own_scale"] < 1.15)}
    if not admitted and not rejected:
        rec["verdict"] = "no source registered"
        return rec
    # A subpage where the rule admits NOTHING still runs the control arm: E vs
    # X is the failure demonstration the whole measurement rests on, and on this
    # book those subpages are where the running text is. The canvas rule is the
    # same rule applied to the set that is actually painted.
    rec["control_only"] = not admitted
    ref_set = admitted or rejected

    # --- canvas: pre-registered as the median own-scale of the ADMITTED set --
    S = round(float(np.median([s["own_scale"] for s in ref_set])), 2)
    rec["canvas_scale"] = S
    canvas = cv2.resize(base, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
    rec["canvas"] = [canvas.shape[1], canvas.shape[0]]
    Smat = np.diag([S, S, 1.0])
    for s in srcs:
        s["Hc"] = Smat @ s["H"]

    E = canvas
    empty = np.zeros(canvas.shape[:2], np.uint8)
    P, union, laid = (paint(canvas, admitted, params) if admitted
                      else (canvas, empty, []))
    X, union_x, laid_x = (paint(canvas, rejected, params) if rejected
                          else (canvas, empty, []))
    rec["laid"] = laid
    rec["laid_rejected"] = laid_x
    rec["union_px_share"] = round(float((union > 0).mean()), 3)
    rec["union_x_px_share"] = round(float((union_x > 0).mean()), 3)
    # the boxes are scored against whichever union carries this subpage's arm
    u_eval = union if admitted else union_x

    # --- the qualifying boxes: Stage 04 TEXT blocks fully inside the union ---
    scaled = [(int(b.bbox.x * S), int(b.bbox.y * S),
               int((b.bbox.x + b.bbox.w) * S), int((b.bbox.y + b.bbox.h) * S),
               str(getattr(b.type, "value", b.type)), b.id) for b in blocks]
    boxes = [b[:4] for b in scaled
             if b[4] not in NON_TEXT_TYPES and inside(u_eval, b[0], b[1],
                                                      b[2] - b[0], b[3] - b[1])]
    all_text = [b[:4] for b in scaled if b[4] not in NON_TEXT_TYPES]
    # Recorded, deciding NOTHING (pre-registration section 6): words a paint
    # lands on inside a FIGURE block. On this book that is a topo map's
    # annotations - real text, but not text the deliverable renders as text.
    fig_boxes = [b[:4] for b in scaled
                 if b[4] in NON_TEXT_TYPES and inside(u_eval, b[0], b[1],
                                                      b[2] - b[0], b[3] - b[1])]
    rec["text_blocks"] = len(all_text)
    rec["union_blocks"] = len(boxes)
    rec["union_figure_blocks"] = len(fig_boxes)

    if dump is not None:
        dump.mkdir(parents=True, exist_ok=True)
        stem = "%s_%s" % (name, sub.replace(".png", ""))
        for tag, im in (("E", E), ("P", P), ("X", X)):
            cv2.imwrite(str(dump / ("%s_%s.png" % (stem, tag))), im)
        cv2.imwrite(str(dump / ("%s_union.png" % stem)), union)

    wE = read(binary, cfg, E)
    wP = read(binary, cfg, P) if admitted else wE
    wX = read(binary, cfg, X) if rejected else wE
    rec["arms"] = {}
    for tag, ws in (("E", wE), ("P", wP), ("X", wX)):
        rec["arms"][tag] = {"union": score(ws, boxes),
                            "subpage": score(ws, all_text),
                            "union_figures": score(ws, fig_boxes)}
        rec["arms"][tag]["union_figures"].pop("text", None)
        # the text itself is long; keep it out of the summary but on disk
        rec["arms"][tag]["union"].pop("text", None)
        rec["arms"][tag]["subpage"].pop("text", None)

    if admitted:
        rec["diff_P_vs_E"] = diff(wE, wP, boxes)
    if rejected:
        rec["diff_X_vs_E"] = diff(wE, wX, boxes)

    nE = rec["arms"]["E"]["union"]["high_conf"]
    if nE < MIN_UNION_WORDS:
        rec["verdict"] = ("underpowered: %d high-confidence words in the union, "
                          "pre-registered floor %d" % (nE, MIN_UNION_WORDS))
        return rec
    nX = rec["arms"]["X"]["union"]["high_conf"]
    if not admitted:
        rec["delta_x"] = nX - nE
        rec["verdict"] = ("CONTROL ONLY (%d rejected sources painted): "
                          "X %+d high-confidence words vs E (%d -> %d)"
                          % (len(rejected), nX - nE, nE, nX))
        return rec
    nP = rec["arms"]["P"]["union"]["high_conf"]
    rec["delta_high_conf"] = nP - nE
    rec["delta_x"] = nX - nE
    rec["verdict"] = ("P %+d high-confidence words vs E (%d -> %d), X %+d; "
                      "%d lost / %d gained - text diff decides"
                      % (nP - nE, nE, nP, nX - nE,
                         rec["diff_P_vs_E"]["n_lost"],
                         rec["diff_P_vs_E"]["n_gained"]))
    return rec


def run_page(page_dir: Path, binary: str, cfg: dict, params: dict,
             dump: Path | None) -> dict:
    name = page_dir.name
    fj = json.loads((page_dir / "01_fuse/fuse.json").read_text(encoding="utf-8"))
    ij = json.loads((page_dir / "00_ingest/ingest.json").read_text(encoding="utf-8"))
    full = set(fj.get("fullspread_frames", []))
    closeups = [f["name"] for f in ij.get("frames", []) if f["name"] not in full]
    anchor = cv2.imread(str(page_dir / "01_fuse/anchor.png"), cv2.IMREAD_COLOR)
    layout = S4.LayoutResult.model_validate_json(
        (page_dir / "04_layout/layout.json").read_text(encoding="utf-8"))
    blocks = {p.name: p.blocks for p in layout.pages}

    pages = {}
    for sub in ("left.png", "right.png", "single.png"):
        p = page_dir / "03_dewarp" / sub
        if p.exists():
            im = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if im is not None:
                pages[sub] = im
    if not pages or anchor is None:
        return {"page": name, "error": "missing pixels"}

    kd_anchor = P0.feats(anchor)
    kd_pages = {k: P0.feats(v) for k, v in pages.items()}

    per_sub: dict[str, list] = {k: [] for k in pages}
    for fname in closeups:
        img = cv2.imread(str(page_dir / "00_ingest" / fname), cv2.IMREAD_COLOR)
        if img is None:
            print("  %s/%s DECODE FAILED" % (name, fname), flush=True)
            continue
        kd = P0.feats(img)
        # the anchor registration exists only to put the residual in ANCHOR
        # pixels, the unit the threshold is written in - it places nothing.
        seed(SEEDS[0])
        ra = P0.register(kd, kd_anchor)
        scale_a = (FH.local_scale(ra["H"], img.shape[1] / 2.0, img.shape[0] / 2.0)
                   if ra and ra["inliers"] >= P0.MIN_INLIERS else None)
        best = None
        for sub, im in pages.items():
            got = measure_source(img, im, kd, kd_pages[sub], params)
            if got and (best is None or got["inliers"] > best[1]["inliers"]):
                best = (sub, got)
        if best is None:
            continue
        sub, m = best
        sc = FH.local_scale(m["H"], img.shape[1] / 2.0, img.shape[0] / 2.0)
        m.update({"frame": fname, "img": img, "subpage": sub,
                  "k_page": (sc / scale_a) if scale_a else None})
        per_sub[sub].append(m)

    out = {"page": name, "subpages": []}
    for sub, srcs in per_sub.items():
        if not srcs:
            continue
        # a source whose own anchor registration failed inherits the subpage's
        # median scale - the same fallback the coverage estimate that fixed the
        # threshold used, so the rule is applied to the numbers that set it.
        ks = [s["k_page"] for s in srcs if s["k_page"]]
        kmed = float(np.median(ks)) if ks else 1.0
        for s in srcs:
            k = s["k_page"] or kmed
            s["k_used"] = round(k, 3)
            s["k_fallback"] = s["k_page"] is None
            s["flow_p95_anchor"] = (round(s["flow_p95"] / k, 2)
                                    if s["flow_p95"] is not None else None)
            s["admitted"] = bool(
                s["flow_p95_anchor"] is not None
                and s["flow_p95_anchor"] <= MAX_FLOW_P95_ANCHOR
                and s["own_scale"] >= MIN_OWN_SCALE)
        rec = run_subpage(name, sub, pages[sub], blocks.get(sub, []), srcs,
                          binary, cfg, params, dump)
        rec["sources"] = [{k: v for k, v in s.items()
                           if k not in ("img", "H", "Hc")} for s in srcs]
        for s in rec["sources"]:
            s.pop("box_native", None)
        out["subpages"].append(rec)
        print("  %s/%s: %s" % (name, sub, rec.get("verdict")), flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Panorama Phase 2 measurement")
    ap.add_argument("--job", default=str(DEFAULT_JOB))
    ap.add_argument("--pages", nargs="*", default=list(DEFAULT_PAGES))
    ap.add_argument("--out", default=str(REPO / "docs/data/panorama_phase2.json"))
    ap.add_argument("--dump", default=None,
                    help="write the E/P/X canvases and the union mask here")
    args = ap.parse_args()

    cfg = S3.load_config(REPO / "config.yaml")
    binary = S5.find_tesseract(cfg)
    if not binary:
        print("Tesseract not found; set tesseract.binary in config.yaml")
        return 2
    params = FH.resolve_params({})
    dump = Path(args.dump) if args.dump else None

    t0 = time.time()
    rows = []
    for pg in args.pages:
        pd = Path(args.job) / pg
        if not pd.is_dir():
            print("%s: no such page" % pg)
            continue
        print("%s ..." % pg, flush=True)
        rows.append(run_page(pd, binary, cfg, params, dump))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "job": args.job, "lang": LANG, "secs": round(time.time() - t0),
        "prereg": "docs/data/panorama_phase2_prereg_20260831.md",
        "rule": {"max_flow_p95_anchor_px": MAX_FLOW_P95_ANCHOR,
                 "min_own_scale": MIN_OWN_SCALE, "feather_px": FEATHER_PX,
                 "high_conf": HIGH_CONF, "min_union_words": MIN_UNION_WORDS,
                 "seeds": list(SEEDS),
                 "flow_p95_is": "worst of the seeded draws"},
        "pages": rows}, indent=1), encoding="utf-8")
    print("\n%.0fs -> %s" % (time.time() - t0, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
