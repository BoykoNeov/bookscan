import json, sys
sys.path.insert(0, r"M:\claud_projects\bookscan")
import cv2, numpy as np
from pipeline import figure_hires as FH, stage04_layout as S4, stage07_assemble as S7
page = __import__("pathlib").Path(r"M:\claud_projects\bookscan\jobs\20261021-104424-6d43b587\page_003")
cfg = S4.load_config(__import__("pathlib").Path(r"M:\claud_projects\bookscan\config.yaml"))
p = FH.resolve_params(cfg)
R = json.load(open(r"M:\claud_projects\bookscan\docs\data\textmerge_20261021\regions.json"))
img = cv2.imread(str(page / "03_dewarp" / "single.png"))
for name, r in R.items():
    x, y, w, h = r["box"]; crop = img[y:y+h, x:x+w]
    for idx in [f for f in S7._capture_frames(page, p) if f.name != "frame_00.png"]:
        got = FH._match(crop, idx, p)
        if not got or got[1] < 8: continue
        fh, fw = idx.image.shape[:2]
        xs = np.linspace(0, w, 200); best = 0
        for yy in np.linspace(h*0.05, h*0.95, 12):
            q = cv2.perspectiveTransform(np.float32([[[a, yy]] for a in xs]), got[0]).reshape(-1, 2)
            inside = ((q[:,0]>0)&(q[:,0]<fw)&(q[:,1]>0)&(q[:,1]<fh)).mean()
            best = max(best, inside)
        print(name, idx.name, "scale %.2f" % FH.local_scale(got[0], w/2, h/2), "max line fraction held %.2f" % best)
        idx.release()
