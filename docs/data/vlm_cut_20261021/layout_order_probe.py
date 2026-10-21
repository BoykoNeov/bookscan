"""Run tools.layout_order_eval with Stage 02's model cut applied (arm 'cut') or not."""
import json, sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import book_boundary as BB
from tools import layout_order_eval as LO

image, arm, out = sys.argv[1], sys.argv[2], sys.argv[3]
box = tuple(json.load(open(r"M:\claud_projects\bookscan\docs\data\vlm_box_split_20260829.json"))["boxes"][image][0]["box"])
_orig = BB.find_book

def patched(img, p=None):
    base = _orig(img, p)
    if arm == "cut" and not base.applied:
        return BB.model_cut(img, box, base, p)
    return base

BB.find_book = patched
raise SystemExit(LO.main(["--image", image, "--json-out", out]))
