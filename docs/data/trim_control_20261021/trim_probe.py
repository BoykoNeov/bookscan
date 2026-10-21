"""Run tools.layout_order_eval with the frame trimmed by hand (no model, no pad).

usage: trim_probe.py <image_id> <L> <T> <R> <B> <json_out>
L/T/R/B are pixels removed from that side of the upright frame; all zero runs
the eval exactly as shipped (find_book itself).
"""
import sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import book_boundary as BB
from tools import layout_order_eval as LO

image = sys.argv[1]
l, t, r, b = (int(v) for v in sys.argv[2:6])
out = sys.argv[6]
_orig = BB.find_book


def trimmed(img, p=None):
    if not (l or t or r or b):
        return _orig(img, p)
    h, w = img.shape[:2]
    rect = (l, t, w - r, h - b)
    print(f"trim_probe: frame {w}x{h}, rect {rect}", flush=True)
    return BB.BookBoundary(applied=True, reason=f"trim_probe {rect}",
                           emit=rect, search=rect)


BB.find_book = trimmed
raise SystemExit(LO.main(["--image", image, "--json-out", out]))
