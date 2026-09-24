"""Census of stacked figure pairs: one picture cut in two, or two things touching?

``docs/OPEN_PROBLEMS.md`` P3. The owner's book renders single photographs as two
pictures with a white line between them, because the layout detector cut one
figure into two blocks. A whiteness-of-the-gap rule was rejected by inspection
(it glued orange text sidebars onto photographs). This asks whether the pixels
*continue* across the seam — measured as a census before any merge is built.

Everything that decides the result is pre-registered in
``docs/data/figure_continuity_prereg_20260924.md`` and is not to be moved: the
pair rule, the classes, the statistic, the controls, the threshold and the gate.
The order of work is part of that registration, so the tool has three modes:

  * ``sheets``  - find the population and draw every pair (and every positive-
    control candidate) for adjudication by eye. **Computes no score.**
  * ``score``   - needs the committed labels file; computes C for every pair and
    control, applies the gate, writes the JSON.
  * (tests call the pure functions directly.)

The statistic, in one line: on the document's own page image, the worst row in
the seam band, as the fraction of columns whose vertical step exceeds the pair's
own 95th-percentile step. A printed boundary is a straight row where nearly every
column jumps; a picture cut arbitrarily by a detector has no such row.

Usage::

    python -m tools.figure_continuity_census sheets [--out-dir DIR]
    python -m tools.figure_continuity_census score --labels L.json [--json-out J]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
OWNER_JOB = REPO / "jobs" / "20260829-084115-de3c20d3"
NEG_JOB = REPO / "jobs" / "figtext_it_geo_06"
DEFAULT_OUT = Path(r"W:\temp\claude\figure_continuity")

# --- pre-registered, docs/data/figure_continuity_prereg_20260924.md ----------
MIN_OVERLAP = 0.5            # of the narrower block's width
GAP_MIN_FRAC = -0.02         # of page height
GAP_MAX_FRAC = 0.05          # of page height
SOFA_SPREADS = ("page_001", "page_002", "page_003", "page_004")
BLUR_SIGMA = 1.0
TAU_PCT = 95.0               # the pair's own step percentile
BAND_PAD = 3                 # rows either side of the seam
CTRL_MIN_H, CTRL_MIN_W = 600, 300
CTRL_CUTS, CTRL_SEED = 5, 0
T_PCT = 95.0                 # threshold = this percentile of positive-control C
MIN_ONE, MIN_NEG, MIN_CTRL = 10, 5, 20


def _box(b: dict) -> tuple[int, int, int, int]:
    bb = b["bbox"]
    return int(bb["x"]), int(bb["y"]), int(bb["w"]), int(bb["h"])


def _xoverlap(a: dict, b: dict) -> float:
    ax, _, aw, _ = _box(a)
    bx, _, bw, _ = _box(b)
    ov = min(ax + aw, bx + bw) - max(ax, bx)
    return ov / max(1, min(aw, bw))


def _xrange(a: dict, b: dict) -> tuple[int, int]:
    ax, _, aw, _ = _box(a)
    bx, _, bw, _ = _box(b)
    return max(ax, bx), min(ax + aw, bx + bw)


def find_pairs(page: dict, sofa: tuple[str, ...] = SOFA_SPREADS) -> list[dict]:
    """Every pre-registered stacked figure pair on one subpage. ``sofa`` names
    the known-bad-crop spreads; they belong to the OWNER's job only (the
    negative-control job's single spread is also called ``page_001``)."""
    H = int(page["height"])
    figs = [b for b in page["blocks"] if b["type"] == "figure"]
    others = [b for b in page["blocks"] if b["type"] != "figure"]
    out = []
    for a in figs:
        ax, ay, aw, ah = _box(a)
        for b in figs:
            if a is b:
                continue
            bx, by, bw, bh = _box(b)
            if by < ay or (by == ay and b["id"] <= a["id"]):
                continue
            gap = by - (ay + ah)
            if not (GAP_MIN_FRAC * H <= gap <= GAP_MAX_FRAC * H):
                continue
            if _xoverlap(a, b) < MIN_OVERLAP:
                continue
            top, bot = min(ay + ah, by), max(ay + ah, by)
            blocked = False
            for c in figs:
                if c is a or c is b:
                    continue
                _, cy, _, ch = _box(c)
                inside = cy >= ay + ah - 1 and cy + ch <= by + 1
                if inside and _xoverlap(c, a) >= MIN_OVERLAP and _xoverlap(c, b) >= MIN_OVERLAP:
                    blocked = True
                    break
            if blocked:
                continue
            x0, x1 = _xrange(a, b)
            between = []
            for c in others:
                cx, cy, cw, ch = _box(c)
                if cx < x1 and cx + cw > x0 and cy < bot and cy + ch > top and bot > top:
                    between.append(c["type"])
            cls = "between" if between else "empty"
            if a.get("is_surface") or b.get("is_surface"):
                cls = "surface"
            elif page.get("source_spread") in sofa:
                cls = "sofa_spread"
            out.append({
                "page_id": page["page_id"], "a": a["id"], "b": b["id"],
                "gap": gap, "overlap": round(_xoverlap(a, b), 3),
                "a_box": list(_box(a)), "b_box": list(_box(b)),
                "class": cls, "between": between,
                "has_asset": bool(a.get("figure_asset") or b.get("figure_asset")),
            })
    return out


def control_candidates(doc: dict, pairs: list[dict]) -> list[dict]:
    """Singleton figures eligible for the positive control (before eye check)."""
    paired = {(p["page_id"], p["a"]) for p in pairs} | {(p["page_id"], p["b"]) for p in pairs}
    out = []
    for page in doc["pages"]:
        if page.get("source_spread") in SOFA_SPREADS:
            continue
        for b in page["blocks"]:
            if b["type"] != "figure" or b.get("is_surface"):
                continue
            if (page["page_id"], b["id"]) in paired:
                continue
            x, y, w, h = _box(b)
            if h >= CTRL_MIN_H and w >= CTRL_MIN_W:
                out.append({"page_id": page["page_id"], "id": b["id"], "box": [x, y, w, h]})
    return out


# --- the statistic -----------------------------------------------------------

def step_image(img: np.ndarray) -> np.ndarray:
    """D(y, x) = max over channels |I(y+1,x) - I(y,x)| on the blurred image.
    Row y of the result is the step between rows y and y+1."""
    f = cv2.GaussianBlur(img.astype(np.float32), (0, 0), BLUR_SIGMA)
    d = np.abs(np.diff(f, axis=0))
    return d.max(axis=2) if d.ndim == 3 else d


def continuity_c(D: np.ndarray, x0: int, x1: int,
                 a_rows: tuple[int, int], b_rows: tuple[int, int]) -> dict:
    """C for one seam. a_rows / b_rows are the [top, bottom) rows of the upper
    and lower block. tau comes from the two blocks' interiors (each minus its
    BAND_PAD rows nearest the seam); the band is [a_bottom - pad, b_top + pad]."""
    a0, a1 = a_rows
    b0, b1 = b_rows
    s0 = max(0, min(a1, b0) - BAND_PAD)
    s1 = min(D.shape[0], max(a1, b0) + BAND_PAD)
    interior = np.concatenate([
        D[a0:max(a0, a1 - BAND_PAD), x0:x1].ravel(),
        D[min(b1, b0 + BAND_PAD):b1, x0:x1].ravel(),
    ])
    if interior.size == 0 or s1 <= s0 or x1 <= x0:
        return {"C": None, "tau": None, "row": None}
    tau = float(np.percentile(interior, TAU_PCT))
    frac = (D[s0:s1, x0:x1] > tau).mean(axis=1)
    k = int(np.argmax(frac))
    return {"C": float(frac[k]), "tau": tau, "row": s0 + k}


def score_pair(D: np.ndarray, p: dict) -> dict:
    ax, ay, aw, ah = p["a_box"]
    bx, by, bw, bh = p["b_box"]
    x0, x1 = max(ax, bx), min(ax + aw, bx + bw)
    return continuity_c(D, x0, x1, (ay, ay + ah), (by, by + bh))


def fake_cuts(ctrl: dict, gaps: list[int], rng: np.random.Generator) -> list[dict]:
    """CTRL_CUTS fake seams inside one singleton figure, each with a gap drawn
    from the census's empty-class gaps (clipped >= 0) so the band is as tall
    as a real one."""
    x, y, w, h = ctrl["box"]
    pool = [max(0, g) for g in gaps] or [0]
    out = []
    for _ in range(CTRL_CUTS):
        cut = int(rng.uniform(0.25 * h, 0.75 * h))
        g = int(rng.choice(pool))
        g = min(g, max(0, h // 4))
        out.append({"x0": x, "x1": x + w,
                    "a_rows": (y, y + cut), "b_rows": (y + cut + g, y + h),
                    "cut": cut, "gap": g})
    return out


# --- drawing -----------------------------------------------------------------

def _crop_pair(img: np.ndarray, boxes: list[list[int]], pad: int = 40,
               max_side: int = 900) -> np.ndarray:
    x0 = max(0, min(b[0] for b in boxes) - pad)
    y0 = max(0, min(b[1] for b in boxes) - pad)
    x1 = min(img.shape[1], max(b[0] + b[2] for b in boxes) + pad)
    y1 = min(img.shape[0], max(b[1] + b[3] for b in boxes) + pad)
    crop = img[y0:y1, x0:x1].copy()
    colours = [(0, 0, 255), (255, 0, 0)]
    for i, (bx, by, bw, bh) in enumerate(boxes):
        cv2.rectangle(crop, (bx - x0, by - y0), (bx - x0 + bw, by - y0 + bh),
                      colours[i % 2], 4)
    s = max_side / max(crop.shape[:2])
    if s < 1:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return crop


def _sheet(tiles: list[tuple[str, np.ndarray]], cols: int = 3,
           cell: int = 620) -> np.ndarray:
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * (cell + 40), cols * cell, 3), 255, np.uint8)
    for i, (label, t) in enumerate(tiles):
        s = min(cell / t.shape[1], cell / t.shape[0], 1.0)
        t = cv2.resize(t, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else t
        r, c = divmod(i, cols)
        oy, ox = r * (cell + 40) + 40, c * cell
        sheet[oy:oy + t.shape[0], ox:ox + t.shape[1]] = t
        cv2.putText(sheet, label, (ox + 5, oy - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 0, 0), 2)
    return sheet


def _load(job: Path) -> tuple[dict, dict]:
    doc = json.loads((job / "document.json").read_text(encoding="utf-8"))
    return doc, {p["page_id"]: p for p in doc["pages"]}


def _img(job: Path, page: dict) -> np.ndarray:
    im = cv2.imread(str(job / page["image_asset"]), cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(job / page["image_asset"])
    return im


def population(job: Path) -> tuple[dict, list[dict]]:
    doc, _ = _load(job)
    sofa = SOFA_SPREADS if job == OWNER_JOB else ()
    pairs = []
    for page in doc["pages"]:
        pairs.extend(find_pairs(page, sofa))
    return doc, pairs


def pair_key(p: dict) -> str:
    return f"{p['page_id']}#{p['a']}-{p['b']}"


def cmd_sheets(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = {}
    for tag, job in (("owner", OWNER_JOB), ("neg", NEG_JOB)):
        doc, pairs = population(job)
        pages = {p["page_id"]: p for p in doc["pages"]}
        tiles, imgs = [], {}
        for i, p in enumerate(pairs):
            pg = pages[p["page_id"]]
            if p["page_id"] not in imgs:
                imgs[p["page_id"]] = _img(job, pg)
            tiles.append((f"{i:02d} {pair_key(p)} {p['class']}",
                          _crop_pair(imgs[p["page_id"]], [p["a_box"], p["b_box"]])))
        for s in range(0, len(tiles), 6):
            cv2.imwrite(str(out_dir / f"{tag}_pairs_{s // 6:02d}.png"), _sheet(tiles[s:s + 6]))
        listing[tag] = [dict(p, key=pair_key(p), idx=i) for i, p in enumerate(pairs)]
        from collections import Counter
        print(f"[{tag}] {len(pairs)} pairs  {dict(Counter(p['class'] for p in pairs))}")
        if tag == "owner":
            ctrl = control_candidates(doc, pairs)
            ctiles = []
            for i, c in enumerate(ctrl):
                pg = pages[c["page_id"]]
                if c["page_id"] not in imgs:
                    imgs[c["page_id"]] = _img(job, pg)
                ctiles.append((f"c{i:02d} {c['page_id']}#{c['id']}",
                               _crop_pair(imgs[c["page_id"]], [c["box"]])))
            for s in range(0, len(ctiles), 6):
                cv2.imwrite(str(out_dir / f"ctrl_{s // 6:02d}.png"), _sheet(ctiles[s:s + 6]))
            listing["ctrl"] = [dict(c, key=f"{c['page_id']}#{c['id']}", idx=i)
                               for i, c in enumerate(ctrl)]
            print(f"[ctrl] {len(ctrl)} singleton candidates")
    (out_dir / "population.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    print(f"sheets + population.json -> {out_dir}")
    return 0


def cmd_score(labels_path: Path, json_out: Path | None, out_dir: Path) -> int:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    result: dict = {"prereg": "docs/data/figure_continuity_prereg_20260924.md",
                    "labels": str(labels_path.as_posix())}
    # owner + negative-control pairs
    rows = {}
    for tag, job in (("owner", OWNER_JOB), ("neg", NEG_JOB)):
        doc, pairs = population(job)
        pages = {p["page_id"]: p for p in doc["pages"]}
        Ds = {}
        rows[tag] = []
        for p in pairs:
            if p["page_id"] not in Ds:
                Ds[p["page_id"]] = step_image(_img(job, pages[p["page_id"]]))
            r = dict(p, key=pair_key(p), label=labels[tag].get(pair_key(p), "unlabelled"))
            r.update(score_pair(Ds[p["page_id"]], p))
            rows[tag].append(r)
    # positive control
    doc, pairs = population(OWNER_JOB)
    pages = {p["page_id"]: p for p in doc["pages"]}
    gaps = [p["gap"] for p in pairs if p["class"] == "empty"]
    rng = np.random.default_rng(CTRL_SEED)
    ctrl_rows = []
    for c in control_candidates(doc, pairs):
        key = f"{c['page_id']}#{c['id']}"
        verdict = labels["ctrl"].get(key, "unlabelled")
        cuts = fake_cuts(c, gaps, rng)   # drawn for every candidate: same stream either way
        if verdict != "single":
            continue
        D = step_image(_img(OWNER_JOB, pages[c["page_id"]]))
        for f in cuts:
            r = continuity_c(D, f["x0"], f["x1"], f["a_rows"], f["b_rows"])
            ctrl_rows.append(dict(key=key, cut=f["cut"], gap=f["gap"], **r))
    Cc = [r["C"] for r in ctrl_rows if r["C"] is not None]
    T = float(np.percentile(Cc, T_PCT)) if Cc else None

    gated = [r for r in rows["owner"] if r["class"] == "empty"]
    one = [r for r in gated if r["label"] == "one"]
    sep = [r for r in gated if r["label"] in ("two", "sidebar")]
    neg = [r for r in rows["neg"] if r["label"] in ("two", "sidebar")]
    wrong = [r["key"] for r in sep + neg if T is not None and r["C"] is not None and r["C"] <= T]
    one_hit = [r for r in one if T is not None and r["C"] is not None and r["C"] <= T]
    if len(one) < MIN_ONE or len(sep) + len(neg) < MIN_NEG or len(Cc) < MIN_CTRL:
        verdict = "NO VERDICT"
    elif wrong or len(one_hit) * 2 < len(one):
        verdict = "FAIL"
    else:
        verdict = "PASS"
    summary = {
        "T": T, "n_ctrl_seams": len(Cc),
        "ctrl_C": _dist(Cc),
        "gated_one": len(one), "gated_one_at_or_below_T": len(one_hit),
        "gated_separate": len(sep), "neg_control": len(neg),
        "wrong_merges": wrong,
        "one_C": _dist([r["C"] for r in one]),
        "separate_C": _dist([r["C"] for r in sep + neg]),
        "verdict": verdict,
    }
    result.update(summary=summary, owner=rows["owner"], neg=rows["neg"], ctrl=ctrl_rows)
    print(json.dumps(summary, indent=1))
    for r in sorted(rows["owner"] + rows["neg"], key=lambda r: (r["class"], r["label"], r["C"] or 0)):
        print(f"{r['class']:12s} {r['label']:8s} C={r['C'] if r['C'] is None else round(r['C'], 3)!s:6s} "
              f"gap={r['gap']:4d} asset={int(r['has_asset'])} {r['key']}")
    if json_out:
        json_out.write_text(json.dumps(result, indent=1, default=_np), encoding="utf-8")
        print(f"-> {json_out}")
    return 0


def _dist(v: list) -> dict:
    v = [x for x in v if x is not None]
    if not v:
        return {"n": 0}
    a = np.array(v)
    return {"n": len(v), "min": round(float(a.min()), 4), "median": round(float(np.median(a)), 4),
            "p95": round(float(np.percentile(a, 95)), 4), "max": round(float(a.max()), 4)}


def _np(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Figure continuity census (P3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheets")
    s.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    c = sub.add_parser("score")
    c.add_argument("--labels", type=Path, required=True)
    c.add_argument("--json-out", type=Path, default=None)
    c.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.cmd == "sheets":
        return cmd_sheets(args.out_dir)
    return cmd_score(args.labels, args.json_out, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
