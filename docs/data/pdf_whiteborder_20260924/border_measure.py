"""Measure the bordered run against the audited run, exactly as pre-registered
(docs/data/pdf_whiteborder_prereg_20260924.md): edge census (all four sides),
tokens agreeing with the PDF's own text layer, overshoot re-registration, and
the gate. Also the reviewer's re-check of the text-layer marker's labelled sites."""
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import fitz  # noqa: E402

from pipeline import pdf_text_layer as L  # noqa: E402

BEFORE = Path(r"W:\temp\claude\pdf_textlayer\work\jobs")
AFTER = Path(sys.argv[1] if len(sys.argv) > 1 else r"W:\temp\claude\pdf_textlayer\border_run\jobs")
DATA = REPO / "docs" / "data" / "pdf_textlayer_20260924"
manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
key = json.loads((DATA / "key_labelled.json").read_text(encoding="utf-8"))


def resolved(page_dir):
    return json.loads((page_dir / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))


def edge_words(res):
    n = 0
    for sp in res["pages"]:
        W, H = sp["width"], sp["height"]
        for b in sp["blocks"]:
            for w in b.get("words") or []:
                x, y, ww, hh = w["bbox"]["x"], w["bbox"]["y"], w["bbox"]["w"], w["bbox"]["h"]
                n += x <= 1 or y <= 1 or x + ww >= W - 1 or y + hh >= H - 1
    return n


def agreement(res, layer):
    t = L.prep_tokens([(w["text"], i) for i, w in enumerate(L.page_words(res["pages"]))])
    lt = L.prep_tokens([(w, None) for w in layer])
    ops = L.align(t, lt)
    return sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal"), len(t), ops, t, lt


def overshoot(page_dir):
    """Map the ORIGINAL page's edges (inside the border) into the output frame."""
    split = json.loads((page_dir / "02_split" / "split.json").read_text(encoding="utf-8"))
    name = split["pages"][0]["name"]
    dew = json.loads((page_dir / "03_dewarp" / "dewarp.json").read_text(encoding="utf-8"))
    bl, bt, br, bb = next(p for p in dew["pages"] if p["name"] == name).get("border_px", [0, 0, 0, 0])
    a = cv2.imread(str(page_dir / "02_split" / name), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(page_dir / "03_dewarp" / name), cv2.IMREAD_GRAYSCALE)
    h, w = a.shape
    s = 1600 / max(b.shape)
    a2, b2 = cv2.resize(a, None, fx=s, fy=s), cv2.resize(b, None, fx=s, fy=s)
    sift = cv2.SIFT_create(6000)
    ka, da = sift.detectAndCompute(a2, None)
    kb, db = sift.detectAndCompute(b2, None)
    good = [x for x, y in cv2.BFMatcher().knnMatch(da, db, k=2) if x.distance < 0.75 * y.distance]
    pa = np.float32([ka[g.queryIdx].pt for g in good]) / s
    pb = np.float32([kb[g.trainIdx].pt for g in good]) / s
    H, _ = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    t = np.linspace(0, 1, 50)
    pts = np.concatenate([np.c_[np.zeros_like(t), t * (h - 1)], np.c_[np.full_like(t, w - 1), t * (h - 1)],
                          np.c_[t * (w - 1), np.zeros_like(t)], np.c_[t * (w - 1), np.full_like(t, h - 1)]])
    q = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), H).reshape(-1, 2)
    Hb, Wb = b.shape
    outside = max(0.0, -q[:, 0].min(), q[:, 0].max() - (Wb - 1), -q[:, 1].min(), q[:, 1].max() - (Hb - 1))
    return outside, [bl, bt, br, bb], (Wb, Hb), (w, h)


rows, sites_after = [], Counter()
for d in manifest["docs"]:
    src = fitz.open(d["file"])
    for k, pno in enumerate(d["pages_1based"]):
        pn = f"page_{k + 1:03d}"
        pb, pa = BEFORE / d["id"] / pn, AFTER / d["id"] / pn
        rb, ra = resolved(pb), resolved(pa)
        layer = L.layer_words(src[pno - 1])
        eb, tb, *_ = agreement(rb, layer)
        ea, ta, ops, t, lt = agreement(ra, layer)
        out_px, border, size_after, size_before = overshoot(pa)
        # text-layer sites on the bordered page, identified like the key
        words = L.page_words(ra["pages"])
        subs = [sp["name"] for sp in ra["pages"] for _ in L.page_words([sp])]
        for tag, i1, i2, j1, j2 in ops:
            if tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
                ws = [words[r] for r in t[i1]["refs"]]
                kept = all((w.get("decision") or "keep") == "keep" for w in ws)
                if kept or d["id"] == "C":
                    sites_after[(d["id"], pno, t[i1]["norm"], lt[j1]["norm"])] += 1
        rows.append({"page": f"{d['id']}/{pn}", "doc": d["id"], "pdf_page": pno,
                     "edge_before": edge_words(rb), "edge_after": edge_words(ra),
                     "agree_before": eb, "agree_after": ea, "tokens_before": tb, "tokens_after": ta,
                     "overshoot_px": round(out_px, 1), "border_px": border,
                     "size_before": size_before, "size_after": size_after})
        r = rows[-1]
        print(f"{r['page']}: edge {r['edge_before']:3d} -> {r['edge_after']:3d}   agreeing tokens "
              f"{eb:4d}/{tb:4d} -> {ea:4d}/{ta:4d} ({ea - eb:+d})   original edge outside frame "
              f"{out_px:.0f} px, border {border}", flush=True)
    src.close()

tot = lambda k, f=lambda r: True: sum(r[k] for r in rows if f(r))  # noqa: E731
d6 = lambda r: r["page"] in ("D6/page_001", "D6/page_003")  # noqa: E731
other = lambda r: r["doc"] != "C" and not d6(r)  # noqa: E731
ctrl = lambda r: r["doc"] == "C"  # noqa: E731
worst_page = min((r["agree_after"] - r["agree_before"]) / max(1, r["agree_before"])
                 for r in rows if other(r))
g0 = {
    "edge words <= 3 (was %d)" % tot("edge_before"): tot("edge_after") <= 3,
    "D6 p1+p3 gain agreeing tokens": tot("agree_after", d6) > tot("agree_before", d6),
    "other 22 pages lose <= 0.5 %": tot("agree_after", other) >= 0.995 * tot("agree_before", other),
    "no other page loses > 2 %": worst_page >= -0.02,
    "control does not fall": tot("agree_after", ctrl) >= tot("agree_before", ctrl),
}
g = {k: bool(v) for k, v in g0.items()}
fallback = bool(max(r["overshoot_px"] for r in rows) > 0)
print(f"\nedge words {tot('edge_before')} -> {tot('edge_after')}")
print(f"D6 p1+p3 agreeing {tot('agree_before', d6)} -> {tot('agree_after', d6)}")
print(f"other 22 pages agreeing {tot('agree_before', other)} -> {tot('agree_after', other)} "
      f"({tot('agree_after', other) / tot('agree_before', other) - 1:+.2%}); worst page {worst_page:+.2%}")
print(f"control agreeing {tot('agree_before', ctrl)} -> {tot('agree_after', ctrl)}")
print(f"fallback trigger (any original edge outside the frame): {fallback}")
for k, v in g.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("VERDICT:", "SHIP" if all(g.values()) else "REFUSE",
      "(fallback width due)" if fallback else "")

# the reviewer's re-check: labelled text-layer sites on the bordered pages
before = Counter((s["doc"], s["pdf_page"], s["t_norm"], s["l_norm"]) for s in key["primary"])
lab = {(s["doc"], s["pdf_page"], s["t_norm"], s["l_norm"]): (s["label"], s["outcome"])
       for s in key["primary"]}
gone = before - sites_after
new = sites_after - before
print(f"\ntext-layer sites judged before: {sum(before.values())}; still there: "
      f"{sum((before & sites_after).values())}; gone: {sum(gone.values())}; new: {sum(new.values())}")
for s in sorted(gone):
    print("  gone:", s, "labelled", lab[s])
for s in sorted(new):
    print("  new: ", s)
Path(AFTER.parent / "border_measure.json").write_text(json.dumps(
    {"rows": rows, "gates": g, "fallback": fallback,
     "sites_gone": [list(s) + list(lab[s]) for s in sorted(gone)],
     "sites_new": [list(s) for s in sorted(new)]}, indent=1, ensure_ascii=False), encoding="utf-8")
