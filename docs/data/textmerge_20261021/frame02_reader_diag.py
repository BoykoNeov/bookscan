import json, sys
from pathlib import Path
sys.path.insert(0, r"M:\claud_projects\bookscan")
import cv2, numpy as np
from pipeline import figure_hires as FH, stage04_layout as S4, stage05_ocr as S5, stage07_assemble as S7
from tools.gate1_harness import find_tesseract
page = Path(r"M:\claud_projects\bookscan\jobs\20261021-104424-6d43b587\page_003")
cfg = S4.load_config(Path(r"M:\claud_projects\bookscan\config.yaml")); p = FH.resolve_params(cfg)
x, y, w, h = 1652, 1410, 1388, 586
img = cv2.imread(str(page / "03_dewarp" / "single.png")); crop = img[y:y+h, x:x+w]
idx = [f for f in S7._capture_frames(page, p) if f.name == sys.argv[1]][0]
H, inl, _ = FH._match(crop, idx, p); im = idx.image; fh, fw = im.shape[:2]
c = cv2.perspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2), H).reshape(-1,2)
print("corners", c.round())
X0, Y0 = (int(max(0, v)) for v in c.min(0)); X1, Y1 = int(min(fw, c[:,0].max())), int(min(fh, c[:,1].max()))
sub = im[Y0:Y1, X0:X1]; print("sub", sub.shape)
cv2.imwrite("W:/temp/claude/textmerge_20261021/dbg_sub.jpg", cv2.resize(sub, None, fx=0.4, fy=0.4))
cw, sc = S5.ocr_subpage(find_tesseract(cfg), cfg, sub, "eng")
print("words", len(cw), "scale", sc, " ".join(t.text for t in cw[:60]))
from tools.gate1_harness import run_tesseract, resolve_tessdata_dir
g = cv2.cvtColor(np.ascontiguousarray(sub), cv2.COLOR_BGR2GRAY)
cv2.imwrite("W:/temp/claude/textmerge_20261021/dbg_sub_gray.png", g)
print("gray stats", g.dtype, g.shape, g.min(), g.max(), g.mean())
out = run_tesseract(find_tesseract(cfg), g, "eng", resolve_tessdata_dir(cfg), 1, 3)
print(out[:600])
for label, im2, psm in (("psm6", g, 6), ("otsu psm3", cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], 3)):
    from tools import ocr_metrics as M
    ws = M.parse_tsv(run_tesseract(find_tesseract(cfg), im2, "eng", resolve_tessdata_dir(cfg), 1, psm))
    print(label, len(ws), " ".join(t.text for t in ws[:40]))
