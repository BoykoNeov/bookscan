"""Run tools.layout_order_eval with group_figures evaluated at BOTH arms.

usage: thin_probe.py <image_id> <L> <T> <R> <B> <json_out> <side_out>
Pre-registration: docs/data/geom_thin_prereg_20261021.md. L/T/R/B trim the
upright frame by hand exactly as trim_control_20261021/trim_probe.py (all zero
= find_book as shipped). The eval grades geom_min_fig_frac = 0.04; the pairs
of the same call at 0 (today's default) are logged to <side_out>.
"""
import json
import sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import book_boundary as BB
from pipeline import figure_grouping as FG
from tools import layout_order_eval as LO

image = sys.argv[1]
l, t, r, b = (int(v) for v in sys.argv[2:6])
out, side_out = sys.argv[6], sys.argv[7]
_orig_find = BB.find_book
_orig_group = FG.group_figures
side = []


def trimmed(img, p=None):
    if not (l or t or r or b):
        return _orig_find(img, p)
    h, w = img.shape[:2]
    rect = (l, t, w - r, h - b)
    print(f"thin_probe: frame {w}x{h}, rect {rect}", flush=True)
    return BB.BookBoundary(applied=True, reason=f"thin_probe {rect}",
                           emit=rect, search=rect)


def both(views, page_h, *a, **k):
    params = dict(k.pop("params", None) or {})
    off = _orig_group(views, page_h, *a, params={**params, "geom_min_fig_frac": 0.0}, **k)
    on = _orig_group(views, page_h, *a, params={**params, "geom_min_fig_frac": 0.04}, **k)
    figs = {v.key: [v.bbox.x, v.bbox.y, v.bbox.w, v.bbox.h] for v in views
            if v.btype == "figure"}
    side.append({"page_h": page_h, "page_w": k.get("page_w"), "figures": figs,
                 "off": {"pairs": off.pairs, "source": off.pair_source,
                         "abstained": off.abstained},
                 "on": {"pairs": on.pairs, "source": on.pair_source,
                        "abstained": on.abstained}})
    return on


BB.find_book = trimmed
FG.group_figures = both
rc = LO.main(["--image", image, "--json-out", out])
with open(side_out, "w", encoding="utf-8") as f:
    json.dump(side, f, indent=1, ensure_ascii=False)
raise SystemExit(rc)
