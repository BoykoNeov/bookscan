import sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
from pathlib import Path
from pipeline import stage04_layout as S4
from tools import layout_order_eval as LO
REPO = Path(r"M:\claud_projects\bookscan")
cfg = LO.load_config(REPO / "config.yaml"); binary = LO.find_tesseract(cfg); td = LO.resolve_tessdata_dir(cfg)
bgr0, _ = LO.NORM.load_upright_bgr(REPO / "testset" / "it_geo_07.jpg", binary, td)
halves, _ = LO.split_halves(bgr0, cfg)
dw = LO.dewarp_halves(halves, cfg, "auto")
name, img, _ = next(x for x in dw if "left" in x[0])
h, w = img.shape[:2]
warns = []; det = S4.make_detector("auto", cfg, warns); p = S4.resolve_params(cfg)
allraw = det.detect(img, dict(p, conf_thresh=0.02))
raw = [d for d in allraw if d.conf >= p["conf_thresh"]]
blocks = S4.dets_to_blocks(raw, w, h, p, bgr=img)
claimed = [b.bbox for b in blocks]
text = [d.bbox for d in allraw if d.label != "figure" and d.conf >= p["fig_rescue_text_conf"]]
for d in allraw:
    if d.label == "figure" and p["fig_rescue_conf"] <= d.conf < p["conf_thresh"]:
        print(f"cand conf {d.conf:.3f} bbox {[d.bbox.x,d.bbox.y,d.bbox.w,d.bbox.h]} "
              f"claimed_cover {S4.covered_fraction(d.bbox, claimed, w, h):.3f} (max {p['fig_rescue_max_cover']}) "
              f"text_cover {S4.covered_fraction(d.bbox, text, w, h):.3f} (max {p['fig_rescue_max_text_cover']})")
