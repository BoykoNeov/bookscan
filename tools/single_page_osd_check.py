"""Does Stage 00 turn an upright imported PDF page sideways?

Instrument for ``docs/data/single_page_osd_prereg_20261112.md`` (hand-off item 3).
Renders a fixed sample of real scanned-PDF pages exactly as ``pipeline/pdf_import``
does, and runs ``tools.normalize.orient_upright`` — Stage 00's orientation call,
with Stage 00's own Tesseract and floors — on three arms:

* ``U``   the page as rendered (upright by construction unless printed sideways);
* ``Rcw`` the page turned 90 deg clockwise on purpose  (right answer: 270);
* ``Rccw`` the page turned 90 deg counter-clockwise    (right answer: 90).

Two steps, so the by-eye verdict is given before it is combined with numbers:

    python -m tools.single_page_osd_check run        # OSD on every page, writes raw.json
                                                     # + a contact sheet with NO angles
    python -m tools.single_page_osd_check summarize  # reads adjudication.json, writes result.json

``adjudication.json`` (``{"<page id>": "upright" | "sideways_in_source"}``) is
written by hand after looking at the contact sheet; every page whose ``U`` arm
got a non-zero OSD proposal must be in it, or ``summarize`` refuses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import pdf_import  # noqa: E402
from pipeline import stage00_ingest as S0  # noqa: E402
from tools import normalize as N  # noqa: E402

MANIFEST = REPO / "docs" / "data" / "pdf_textlayer_20260924" / "manifest.json"
OUT = REPO / "docs" / "data" / "single_page_osd_20261112"
WORK = Path(r"W:\temp\claude\single_page_osd")
EXTRA_FRAMES = [
    ("pdfimp_en_coins_01/page_001", REPO / "jobs/pdfimp_import_en_coins_01/page_001"),
    ("pdfimp_en_coins_01/page_002", REPO / "jobs/pdfimp_import_en_coins_01/page_002"),
]
EXCLUDED_BY_DECISION = {"C"}   # our own re-typeset render, not a scan (prereg)
DPI = 300
PER_DOC = 20
# right answer (deg CW to apply) for each arm, given a page upright as rendered
EXPECT = {"U": 0, "Rcw": 270, "Rccw": 90}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sample_pages(page_count: int) -> list[int]:
    """Up to PER_DOC 1-based pages, evenly spaced first..last (prereg rule)."""
    n = min(PER_DOC, page_count)
    return sorted({int(round(x)) for x in np.linspace(1, page_count, n)})


def population() -> tuple[list[dict], list[str]]:
    """[{id, doc, pdf_page|None, verdict, path|None, page_dir|None}], notes."""
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items, notes = [], []
    for d in man["docs"]:
        if d["id"] in EXCLUDED_BY_DECISION:
            notes.append(f"{d['id']}: excluded by decision (prereg)")
            continue
        p = Path(d["file"])
        if not p.exists():
            notes.append(f"{d['id']}: file gone ({p.name}); excluded by rule")
            continue
        if _sha256(p) != d["sha256"]:
            notes.append(f"{d['id']}: SHA-256 differs from the manifest; excluded by rule")
            continue
        verdicts = {ip.pdf_page: ip.layout for ip in pdf_import.survey(p, DPI, "detect")[0]}
        for pg in sample_pages(d["page_count"]):
            items.append({"id": f"{d['id']}_p{pg:03d}", "doc": d["id"], "pdf": str(p),
                          "pdf_page": pg, "verdict": verdicts[pg]})
    for pid, page_dir in EXTRA_FRAMES:
        lay = json.loads((page_dir / "page_layout.json").read_text(encoding="utf-8"))
        items.append({"id": pid, "doc": "pdfimp_en_coins_01", "frame":
                      str(page_dir / "raw" / "frame_00.png"), "verdict": lay["layout"]})
    return items, notes


def render(item: dict) -> np.ndarray:
    if "frame" in item:
        return cv2.imread(item["frame"], cv2.IMREAD_COLOR)
    import fitz
    with fitz.open(item["pdf"]) as doc:
        pix = doc[item["pdf_page"] - 1].get_pixmap(dpi=DPI, alpha=False, colorspace=fitz.csRGB)
        rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _orient(bgr: np.ndarray, binary, tessdata, floors) -> dict:
    out, info = N.orient_upright(bgr, binary, tessdata, min_conf=floors[0], min_conf_180=floors[1])
    h, w = out.shape[:2]
    return {"osd_rotate": info.osd_rotate, "osd_conf": info.osd_conf,
            "applied": info.applied_rotate, "method": info.method,
            "result_portrait": h > w}


def cmd_run(args) -> int:
    cfg = S0.load_config(REPO / "config.yaml")
    binary, tessdata = S0.resolve_tesseract(cfg)
    params = S0.resolve_params(cfg)
    floors = (float(params["min_osd_conf"]), float(params["min_osd_conf_180"]))
    if binary is None:
        raise SystemExit("no Tesseract; nothing measured")
    items, notes = population()
    print(f"{len(items)} pages; " + "; ".join(notes))
    thumbs = WORK / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    def one(item: dict) -> dict:
        bgr = render(item)
        h, w = bgr.shape[:2]
        s = 500.0 / max(h, w)
        cv2.imwrite(str(thumbs / f"{item['id'].replace('/', '__')}.png"),
                    cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA))
        arms = {"U": bgr, "Rcw": cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE),
                "Rccw": cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)}
        rec = {k: v for k, v in item.items() if k not in ("pdf", "frame")}
        rec["size"] = [w, h]
        rec["arms"] = {a: _orient(img, binary, tessdata, floors) for a, img in arms.items()}
        print(f"  {item['id']:>34} {item['verdict']:6} "
              + "  ".join(f"{a}:{r['osd_rotate']}@{r['osd_conf']}->{r['applied']}"
                          for a, r in rec["arms"].items()), flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        recs = list(ex.map(one, items))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "raw.json").write_text(json.dumps({
        "prereg": "docs/data/single_page_osd_prereg_20261112.md", "dpi": DPI,
        "floors": {"min_osd_conf": floors[0], "min_osd_conf_180": floors[1]},
        "tesseract": binary, "tessdata": tessdata, "notes": notes, "pages": recs,
    }, indent=1), encoding="utf-8")

    # contact sheet of the pages that need a verdict — ids only, no angles
    need = [r for r in recs if r["arms"]["U"]["osd_rotate"] not in (0, None)]
    print(f"{len(need)} pages with a non-zero OSD proposal in U need a verdict")
    tiles = []
    for r in need:
        t = cv2.imread(str(thumbs / f"{r['id'].replace('/', '__')}.png"))
        tile = np.full((560, 520, 3), 255, np.uint8)
        tile[50:50 + t.shape[0], 10:10 + t.shape[1]] = t
        cv2.putText(tile, r["id"], (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 200), 2)
        tiles.append(tile)
    for i in range(0, len(tiles), 6):
        row = tiles[i:i + 6] + [np.full((560, 520, 3), 255, np.uint8)] * (6 - len(tiles[i:i + 6]))
        cv2.imwrite(str(WORK / f"sheet_{i // 6:02d}.png"), np.hstack(row))
    return 0


def cmd_summarize(args) -> int:
    raw = json.loads((OUT / "raw.json").read_text(encoding="utf-8"))
    adj = json.loads((OUT / "adjudication.json").read_text(encoding="utf-8"))
    pages = raw["pages"]
    missing = [r["id"] for r in pages
               if r["arms"]["U"]["osd_rotate"] not in (0, None) and r["id"] not in adj]
    if missing:
        raise SystemExit(f"no verdict for {missing}")
    res: dict = {"n_pages": len(pages), "by_verdict": {}}
    for verdict in ("single", "spread"):
        grp = [r for r in pages if r["verdict"] == verdict]
        up = [r for r in grp if adj.get(r["id"], "upright") == "upright"]
        side = [r for r in grp if adj.get(r["id"]) == "sideways_in_source"]
        u = [r["arms"]["U"] for r in up]
        wrong_props = [x for x in u if x["osd_rotate"] not in (0, None)]
        applied = [x for x in u if x["applied"] != 0]
        ctl_ok, ctl_bad, ctl_conf_ok, ctl_conf_bad = 0, 0, [], []
        for r in up:
            for arm in ("Rcw", "Rccw"):
                x = r["arms"][arm]
                if x["applied"] == EXPECT[arm]:
                    ctl_ok += 1
                    ctl_conf_ok.append(x["osd_conf"])
                else:
                    ctl_bad += 1
                    if x["osd_rotate"] is not None and x["osd_rotate"] % 360 != EXPECT[arm]:
                        ctl_conf_bad.append(x["osd_conf"])
        res["by_verdict"][verdict] = {
            "n": len(grp), "n_upright": len(up), "n_sideways_in_source": len(side),
            "U_applied_90_270": [ {"id": r["id"], **r["arms"]["U"]} for r in up
                                  if r["arms"]["U"]["applied"] in (90, 270)],
            "U_applied_180": [{"id": r["id"], **r["arms"]["U"]} for r in up
                              if r["arms"]["U"]["applied"] == 180],
            "U_wrong_proposals_conf": sorted(x["osd_conf"] for x in wrong_props),
            "U_wrong_proposal_conf_max": max((x["osd_conf"] for x in wrong_props), default=None),
            "U_n_applied_any": len(applied),
            "U_n_osd_unavailable": sum(x["method"] == "osd_unavailable" for x in u),
            "U_n_portrait_warning": sum(x["result_portrait"] for x in u),
            "control_restored": ctl_ok, "control_not_restored": ctl_bad,
            "control_correct_conf_min": min(ctl_conf_ok, default=None),
            "control_correct_conf_median": (float(np.median(ctl_conf_ok)) if ctl_conf_ok else None),
            "control_wrong_call_conf": sorted(c for c in ctl_conf_bad if c is not None),
            "sideways_in_source": [{"id": r["id"], **r["arms"]["U"]} for r in side],
        }
    single = res["by_verdict"]["single"]
    res["decision"] = ("skip_90_270_for_pdf_import" if single["U_applied_90_270"]
                       else "warning_fix_only")
    (OUT / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workers", type=int, default=4)
    sub.add_parser("summarize")
    a = ap.parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_summarize(a)


if __name__ == "__main__":
    raise SystemExit(main())
