"""Ask the local vision model whether a stacked figure pair is one picture or two.

``docs/OPEN_PROBLEMS.md`` P3, the experiment after the pixel-continuity rule was
refused. The population, the eye labels and the positive-control singles are
the census's (``tools/figure_continuity_census.py``); this tool changes only the
judge. Everything that decides the result — both prompts, the images each is
shown, the draws, the gate — is pre-registered in
``docs/data/figure_split_vlm_prereg_20260924.md`` and is not to be moved. An
edited prompt is an unmeasured prompt: change one word and it needs a new
pre-registration, not a re-run.

Two questions, deliberately different in what they ask, not only in what they
show:

  * **crop** — the rectangle around both blocks, unmarked: "ONE continuous
    picture, or TWO OR MORE separate items stacked?"
  * **seam** — a taller window of the page between two white margins, each with
    a red arrow pointing at the row the detector cut at: "does one picture
    CONTINUE across that line, or is it a BOUNDARY where one item ends?" It asks
    about the cut itself, not how many things there are. Nothing is drawn on
    the page pixels, so no line crosses the seam.

A pair counts as a merge only when both draws of both questions say ONE /
CONTINUES. (A first second question — coloured bars beside each block, "SAME or
DIFFERENT?" — was dropped on out-of-population probes before anything was asked
of the graded pairs; the pre-registration records why.)

Usage::

    python -m tools.figure_split_vlm probe --job jobs/<other job>/ page_001__left:10 page_001__left:10-15
    python -m tools.figure_split_vlm run --json-out docs/data/figure_split_vlm_20260924.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from pipeline import figure_surface
from tools.figure_continuity_census import (
    NEG_JOB, OWNER_JOB, _img, _load, control_candidates, pair_key, population,
)

REPO = Path(__file__).resolve().parent.parent
LABELS = REPO / "docs" / "data" / "figure_continuity_labels_20260924.json"
GROUPS = REPO / "docs" / "data" / "figure_split_vlm_groups_20260924.json"
DEFAULT_OUT = Path(r"W:\temp\claude\figure_split_vlm")

# --- pre-registered, docs/data/figure_split_vlm_prereg_20260924.md -----------
CROP_PROMPT = (
    "This image is a region cut from a page of a printed book.\n"
    "Does it show ONE single continuous picture (one photograph, one map or "
    "one drawing, possibly with a caption printed on it), or TWO OR MORE "
    "separate items placed one above the other (for example two different "
    "photographs, or a picture and a separate box or panel of text)?\n"
    "Answer with one word only: ONE or TWO."
)
SEAM_PROMPT = (
    "This is part of a page of a printed book. The two red arrows in the white "
    "margins point at one horizontal line across the page. Look along that "
    "line.\n"
    "Does one single picture (a photograph, map or drawing) CONTINUE across "
    "that line, with the same picture above and below it? Or is that line a "
    "BOUNDARY, where one item ends and a different item begins (a separate "
    "photograph, a box of text, a coloured panel, or blank paper)?\n"
    "Answer with one word only: CONTINUES or BOUNDARY."
)
CROP_MAX_SIDE = 768          # figure_surface's measured crop size
SEAM_MAX_SIDE = 1120         # figure_surface's measured page size
PAD_X_FRAC, PAD_X_MIN = 0.10, 40     # seam window: horizontal pad
PAD_Y_FRAC, PAD_Y_MIN = 0.50, 150    # seam window: vertical pad
STRIP_FRAC, STRIP_MIN = 0.06, 48     # each white margin, of the window width
DRAWS = 2
MAX_UNREADABLE = 0.10        # of all first-draw answers -> NO VERDICT
MIN_CTRL_PASS = 0.50         # singles both-arms ONE/CONTINUES below this -> NO VERDICT
SEPARATE = ("two", "sidebar", "surface")

RED = (0, 0, 255)    # BGR


# --- the two images ----------------------------------------------------------

def union_box(a: list[int], b: list[int], w: int, h: int) -> tuple[int, int, int, int]:
    """[x0, y0, x1, y1) around both boxes, clipped to the page. Pixels inside
    it that belong to neither block (text beside a narrower block) stay in."""
    x0 = max(0, min(a[0], b[0]))
    y0 = max(0, min(a[1], b[1]))
    x1 = min(w, max(a[0] + a[2], b[0] + b[2]))
    y1 = min(h, max(a[1] + a[3], b[1] + b[3]))
    return x0, y0, x1, y1


def crop_image(page: np.ndarray, a: list[int], b: list[int]) -> np.ndarray:
    h, w = page.shape[:2]
    x0, y0, x1, y1 = union_box(a, b, w, h)
    return page[y0:y1, x0:x1].copy()


def seam_row(a: list[int], b: list[int]) -> int:
    """The page row the detector cut at: the middle of the gap between the
    upper block's bottom and the lower block's top (of the overlap, if the
    boxes overlap)."""
    return (a[1] + a[3] + b[1]) // 2


def seam_image(page: np.ndarray, a: list[int], b: list[int]) -> np.ndarray:
    """A padded window of the page between two white margins, each carrying a
    red arrow pointing inward at the seam row. Nothing is drawn on the page
    pixels, so no line crosses the seam itself."""
    h, w = page.shape[:2]
    x0, y0, x1, y1 = union_box(a, b, w, h)
    uw, uh = x1 - x0, y1 - y0
    px = max(PAD_X_MIN, int(PAD_X_FRAC * uw))
    py = max(PAD_Y_MIN, int(PAD_Y_FRAC * uh))
    wx0, wy0 = max(0, x0 - px), max(0, y0 - py)
    wx1, wy1 = min(w, x1 + px), min(h, y1 + py)
    win = page[wy0:wy1, wx0:wx1]
    sw = max(STRIP_MIN, int(STRIP_FRAC * win.shape[1]))
    canvas = np.full((win.shape[0], 2 * sw + win.shape[1], 3), 255, np.uint8)
    canvas[:, sw:sw + win.shape[1]] = win
    y = int(np.clip(seam_row(a, b) - wy0, 0, canvas.shape[0] - 1))
    half = max(8, sw // 3)
    tip_l, tip_r = sw - 4, sw + win.shape[1] + 4
    left = np.array([[tip_l, y], [tip_l - 2 * half, y - half], [tip_l - 2 * half, y + half]])
    right = np.array([[tip_r, y], [tip_r + 2 * half, y - half], [tip_r + 2 * half, y + half]])
    cv2.fillPoly(canvas, [left, right], RED)
    return canvas


def control_halves(box: list[int]) -> tuple[list[int], list[int]]:
    """A single picture presented as a pair: its top half and bottom half, cut
    at the fixed midpoint (no random draw), gap 0."""
    x, y, w, h = box
    m = h // 2
    return [x, y, w, m], [x, y + m, w, h - m]


# --- asking ------------------------------------------------------------------

def parse(answer: str, yes: str, no: str) -> str:
    """``yes`` / ``no`` when exactly one of the two words is present, else
    ``"?"`` (unreadable, empty, or both)."""
    has_y, has_n = yes in answer, no in answer
    if has_y and not has_n:
        return yes
    if has_n and not has_y:
        return no
    return "?"


def ask_pair(page: np.ndarray, a: list[int], b: list[int], params: dict,
             save: Path | None = None) -> dict:
    ci, si = crop_image(page, a, b), seam_image(page, a, b)
    if save is not None:
        save.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(save.with_name(save.name + "_crop.jpg")), ci)
        cv2.imwrite(str(save.with_name(save.name + "_seam.jpg")), si)
    out: dict = {"crop_raw": [], "seam_raw": []}
    t0 = time.perf_counter()
    for _ in range(DRAWS):
        out["crop_raw"].append(figure_surface._ask(ci, CROP_PROMPT, CROP_MAX_SIDE, params)[:40])
        out["seam_raw"].append(figure_surface._ask(si, SEAM_PROMPT, SEAM_MAX_SIDE, params)[:40])
    out["ms"] = round((time.perf_counter() - t0) * 1000.0)
    out["crop"] = [parse(r, "ONE", "TWO") for r in out["crop_raw"]]
    out["seam"] = [parse(r, "CONTINUES", "BOUNDARY") for r in out["seam_raw"]]
    out["flip"] = len(set(out["crop"])) > 1 or len(set(out["seam"])) > 1
    out["crop_one"] = all(x == "ONE" for x in out["crop"])
    out["seam_cont"] = all(x == "CONTINUES" for x in out["seam"])
    out["merge"] = out["crop_one"] and out["seam_cont"]
    return out


# --- grading -----------------------------------------------------------------

def restored(group_pairs: list[tuple[int, int]], merged: set[tuple[int, int]]) -> bool:
    """Do the merged pairs connect every block of this picture into one group?"""
    blocks = {x for p in group_pairs for x in p}
    parent = {x: x for x in blocks}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p in group_pairs:
        if p in merged:
            parent[find(p[0])] = find(p[1])
    return len({find(x) for x in blocks}) == 1


def grade(rows: list[dict], ctrl: list[dict], groups: dict[str, list[str]]) -> dict:
    """The pre-registered gate over asked rows (owner + neg) and controls."""
    ones = [r for r in rows if r["label"] == "one"]
    seps = [r for r in rows if r["label"] in SEPARATE]

    def arm_table(key_ok) -> dict:
        return {"one_hit": sum(1 for r in ones if key_ok(r)),
                "separate_wrong": sorted(r["key"] for r in seps if key_ok(r))}
    table = {
        "crop_alone": arm_table(lambda r: r["crop"][0] == "ONE"),
        "seam_alone": arm_table(lambda r: r["seam"][0] == "CONTINUES"),
        "both_agree": arm_table(lambda r: r["merge"]),
    }
    merged_by_page: dict[str, set] = {}
    for r in rows:
        if r["merge"]:
            merged_by_page.setdefault(r["page_id"], set()).add((r["a"], r["b"]))
    pic = {}
    for g, keys in groups.items():
        pid = keys[0].split("#")[0]
        pairs = [tuple(int(x) for x in k.split("#")[1].split("-")) for k in keys]
        pic[g] = {"pairs": len(pairs),
                  "restored": restored(pairs, merged_by_page.get(pid, set())),
                  "any_merged": any(p in merged_by_page.get(pid, set()) for p in pairs)}
    n_pic = len(pic)
    n_restored = sum(1 for v in pic.values() if v["restored"])
    first = [x for r in rows + ctrl for x in (r["crop"][0], r["seam"][0])]
    unread = sum(1 for x in first if x == "?") / max(1, len(first))
    ctrl_pass = sum(1 for c in ctrl if c["merge"]) / max(1, len(ctrl))
    wrong = table["both_agree"]["separate_wrong"]
    if unread > MAX_UNREADABLE or ctrl_pass < MIN_CTRL_PASS or not ctrl:
        verdict = "NO VERDICT"
    elif wrong or n_restored * 2 < n_pic:
        verdict = "FAIL"
    else:
        verdict = "PASS"
    return {
        "arms": table,
        "n_one_pairs": len(ones), "n_separate_pairs": len(seps),
        "pictures": pic, "n_pictures": n_pic, "pictures_restored": n_restored,
        "pictures_any_merged": sum(1 for v in pic.values() if v["any_merged"]),
        "one_pairs_merged_outside_map": sum(
            1 for r in ones if r["merge"] and r["key"] not in groups.get("map_025L", [])),
        "ctrl_n": len(ctrl), "ctrl_both_pass": round(ctrl_pass, 3),
        "ctrl_crop_one": sum(1 for c in ctrl if c["crop"][0] == "ONE"),
        "ctrl_seam_cont": sum(1 for c in ctrl if c["seam"][0] == "CONTINUES"),
        "unreadable_frac": round(unread, 4),
        "flips": sorted(r["key"] for r in rows + ctrl if r["flip"]),
        "wrong_merges": wrong,
        "verdict": verdict,
    }


# --- commands ----------------------------------------------------------------

def _params() -> dict:
    return dict(figure_surface.DEFAULTS)


def cmd_probe(job: Path, specs: list[str], out_dir: Path) -> int:
    """Format and sanity check on a job OUTSIDE the graded population. Each spec
    is ``page_id:ID`` (a single figure, asked as its top/bottom halves) or
    ``page_id:A-B`` (two blocks, A above B). Writes nothing under docs/."""
    doc, pages = _load(job)
    for spec in specs:
        pid, ids = spec.split(":")
        page = pages[pid]
        boxes = {b["id"]: [int(b["bbox"][k]) for k in ("x", "y", "w", "h")] for b in page["blocks"]}
        if "-" in ids:
            ia, ib = (int(x) for x in ids.split("-"))
            a, b = boxes[ia], boxes[ib]
        else:
            a, b = control_halves(boxes[int(ids)])
        r = ask_pair(_img(job, page), a, b, _params(),
                     out_dir / "probe" / f"{job.name}_{pid}_{ids}")
        print(f"{job.name} {spec:24s} crop={r['crop_raw']} seam={r['seam_raw']} {r['ms']} ms", flush=True)
    return 0


def cmd_run(json_out: Path | None, out_dir: Path) -> int:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    groups = json.loads(GROUPS.read_text(encoding="utf-8"))["pictures"]
    params = _params()
    rows = []
    for tag, job in (("owner", OWNER_JOB), ("neg", NEG_JOB)):
        doc, pairs = population(job)
        pages = {p["page_id"]: p for p in doc["pages"]}
        imgs: dict = {}
        for p in pairs:
            key = pair_key(p)
            if p["page_id"] not in imgs:
                imgs[p["page_id"]] = _img(job, pages[p["page_id"]])
            r = dict(p, tag=tag, key=key, label=labels[tag].get(key, "unlabelled"))
            r.update(ask_pair(imgs[p["page_id"]], p["a_box"], p["b_box"], params,
                              out_dir / tag / key.replace("#", "_")))
            rows.append(r)
            print(f"{tag:5s} {r['label']:8s} crop={r['crop']} seam={r['seam']} "
                  f"merge={int(r['merge'])} {key}", flush=True)
    doc, pairs = population(OWNER_JOB)
    pages = {p["page_id"]: p for p in doc["pages"]}
    ctrl = []
    for c in control_candidates(doc, pairs):
        key = f"{c['page_id']}#{c['id']}"
        if labels["ctrl"].get(key) != "single":
            continue
        a, b = control_halves(c["box"])
        r = dict(key=key, box=c["box"])
        r.update(ask_pair(_img(OWNER_JOB, pages[c["page_id"]]), a, b, params,
                          out_dir / "ctrl" / key.replace("#", "_")))
        ctrl.append(r)
        print(f"ctrl  single   crop={r['crop']} seam={r['seam']} merge={int(r['merge'])} {key}",
              flush=True)
    summary = grade(rows, ctrl, groups)
    print(json.dumps({k: v for k, v in summary.items() if k != "pictures"}, indent=1))
    if json_out:
        json_out.write_text(json.dumps({
            "prereg": "docs/data/figure_split_vlm_prereg_20260924.md",
            "model": params["model"], "summary": summary, "pairs": rows, "ctrl": ctrl,
        }, indent=1), encoding="utf-8")
        print(f"-> {json_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Two-question local-model check for split pictures (P3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("specs", nargs="+")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    r = sub.add_parser("run")
    r.add_argument("--json-out", type=Path, default=None)
    r.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.cmd == "probe":
        return cmd_probe(args.job, args.specs, args.out_dir)
    return cmd_run(args.json_out, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
