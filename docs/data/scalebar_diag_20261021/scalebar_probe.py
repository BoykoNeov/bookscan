"""Which Stage 04 pass turns it_geo_07-left's scale bars into figures under a trim?

usage: scalebar_probe.py <json_out>
Runs it_geo_07 uncut, L41 and mirror (rectangles as trim_control_20261021),
split + dewarp exactly as tools.layout_order_eval, then on the LEFT subpage:
  - every raw DocLayout-YOLO detection (conf >= 0.02) in the scale-bar band,
  - the figure blocks layout_page emits with the shipped knobs and with
    fig_rescue / fig_split / fig_vsplit turned off one at a time.
"""
import json
import sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pathlib import Path
from pipeline import book_boundary as BB
from pipeline import stage04_layout as S4
from tools import layout_order_eval as LO

REPO = Path(r"M:\claud_projects\bookscan")
ARMS = {"base": (0, 0, 0, 0), "L41": (41, 0, 0, 0), "mirror": (34, 25, 41, 27)}
BAND = (700, 1000)   # y range on the left subpage that holds the two scale bars
_orig = BB.find_book
cur = {"t": (0, 0, 0, 0)}


def trimmed(img, p=None):
    l, t, r, b = cur["t"]
    if not (l or t or r or b):
        return _orig(img, p)
    h, w = img.shape[:2]
    rect = (l, t, w - r, h - b)
    return BB.BookBoundary(applied=True, reason=f"probe {rect}", emit=rect, search=rect)


BB.find_book = trimmed
cfg = LO.load_config(REPO / "config.yaml")
binary = LO.find_tesseract(cfg)
td = LO.resolve_tessdata_dir(cfg)
bgr0, _ = LO.NORM.load_upright_bgr(REPO / "testset" / "it_geo_07.jpg", binary, td)
warns: list[str] = []
det = S4.make_detector("auto", cfg, warns)
p0 = S4.resolve_params(cfg)
variants = {"shipped": {}, "no_rescue": {"fig_rescue": False},
            "no_split": {"fig_split": False}, "no_vsplit": {"fig_vsplit": False}}
out = {}
for arm, t in ARMS.items():
    cur["t"] = t
    halves, _ = LO.split_halves(bgr0, cfg)
    dw = LO.dewarp_halves(halves, cfg, "auto")
    name, img, _pd = next(x for x in dw if "left" in x[0])
    h, w = img.shape[:2]
    p_low = dict(p0, conf_thresh=0.02)
    raw = det.detect(img, p_low)
    band = [{"label": d.label, "conf": round(float(d.conf), 4),
             "bbox": [d.bbox.x, d.bbox.y, d.bbox.w, d.bbox.h]}
            for d in raw if d.bbox.y + d.bbox.h > BAND[0] and d.bbox.y < BAND[1]]
    rec = {"page_wh": [w, h], "raw_in_band": sorted(band, key=lambda r: r["bbox"][1])}
    for vname, over in variants.items():
        pl = S4.layout_page(img, cfg, dict(p0, **over), warns, det)
        rec[vname] = {"note": pl.note,
                      "figures": [[b.bbox.x, b.bbox.y, b.bbox.w, b.bbox.h]
                                  for b in pl.blocks if b.type.value == "figure"]}
    out[arm] = rec
    print(arm, json.dumps(rec, indent=1), flush=True)
Path(sys.argv[1]).write_text(json.dumps(out, indent=1), encoding="utf-8")
