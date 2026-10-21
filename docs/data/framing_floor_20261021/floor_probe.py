"""Run tools.layout_order_eval on one model-free reframing of a testset photo.

usage: floor_probe.py <image_id> <L> <T> <R> <B> <json_out> [--rect]
Pre-registration: docs/data/framing_floor_prereg_20261021.md. L/T/R/B are
pixels removed from that side of the upright frame, exactly as
trim_control_20261021/trim_probe.py: a hand-built rectangle replaces
book_boundary.find_book (no model, no pad). All zero runs find_book as shipped,
unless --rect, which hands the eval the whole frame through the rectangle path
(applied=True) — the control for the path itself.
"""
import sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import book_boundary as BB
from tools import layout_order_eval as LO

image = sys.argv[1]
l, t, r, b = (int(v) for v in sys.argv[2:6])
out = sys.argv[6]
force_rect = "--rect" in sys.argv[7:]
_orig = BB.find_book


def trimmed(img, p=None):
    if not (l or t or r or b or force_rect):
        return _orig(img, p)
    h, w = img.shape[:2]
    rect = (l, t, w - r, h - b)
    print(f"floor_probe: frame {w}x{h}, rect {rect}", flush=True)
    return BB.BookBoundary(applied=True, reason=f"floor_probe {rect}",
                           emit=rect, search=rect)


BB.find_book = trimmed
raise SystemExit(LO.main(["--image", image, "--json-out", out]))
