"""At the words that touched the edge in the audited run (D6 p1, p3), what does
each arm read? Via the PDF's own text layer: find the layer token each audited
edge word was aligned to, then see whether the arm's reading of the page has an
EQUAL match on that same layer token (read right) or not."""
import json
import sys
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import fitz  # noqa: E402

from pipeline import pdf_text_layer as L  # noqa: E402

T = Path(r"W:\temp\claude\pdf_textlayer")
PDF = r"W:\Claude_projects\space-station\sources\biochemj01085-0088.pdf"
src = fitz.open(PDF)


def layer_map(res, layer):
    """layer token index -> (how it is matched, tesseract raw) for this reading."""
    words = L.page_words(res["pages"])
    t = L.prep_tokens([(w["text"], i) for i, w in enumerate(words)])
    lt = L.prep_tokens([(w, None) for w in layer])
    m = {}
    for tag, i1, i2, j1, j2 in L.align(t, lt):
        if tag == "equal":
            for k in range(j2 - j1):
                m[j1 + k] = ("right", t[i1 + k]["raw"])
        elif tag == "replace":
            for k in range(j1, j2):
                m[k] = ("wrong", " ".join(x["raw"] for x in t[i1:i2]))
    return words, t, lt, m


for pn, pno in (("page_001", 3), ("page_003", 5)):
    layer = L.layer_words(src[pno - 1])
    base = json.loads((T / "work/jobs/D6" / pn / "06_uncertain/resolved.json").read_text(encoding="utf-8"))
    words, t, lt, m0 = layer_map(base, layer)
    W, H = base["pages"][0]["width"], base["pages"][0]["height"]
    edge = {i for i, w in enumerate(words)
            if w["bbox"]["x"] <= 1 or w["bbox"]["x"] + w["bbox"]["w"] >= W - 1}
    # the layer tokens those edge words were aligned to (equal or replace)
    targets = set()
    for tag, i1, i2, j1, j2 in L.align(t, lt):
        if tag in ("equal", "replace"):
            for ti in range(i1, i2):
                if set(t[ti]["refs"]) & edge:
                    targets.update(range(j1, j2))
    print(f"D6 {pn}: {len(edge)} edge words -> {len(targets)} layer tokens")
    for arm in ("work", "skip_run", "border_run"):
        res = json.loads((T / arm / "jobs/D6" / pn / "06_uncertain/resolved.json").read_text(encoding="utf-8"))
        _, _, _, m = layer_map(res, layer)
        right = sum(m.get(j, ("missing",))[0] == "right" for j in targets)
        wrong = sum(m.get(j, ("missing",))[0] == "wrong" for j in targets)
        missing = len(targets) - right - wrong
        print(f"  {arm:10s}: read right {right:3d}, read wrong {wrong:3d}, not read at all {missing:3d}")
        if arm == "skip_run":
            ex = [(lt[j]["raw"], m0.get(j, ("-", "-"))[1], m.get(j, ("-", "-"))[1])
                  for j in sorted(targets)][:12]
            for lay, before, after in ex:
                print(f"      layer {lay!r:18} audited {before!r:18} skip {after!r}")

print("\n-- the edge words themselves (audited run) --")
for pn, pno in (("page_001", 3), ("page_003", 5)):
    layer = L.layer_words(src[pno - 1])
    base = json.loads((T / "work/jobs/D6" / pn / "06_uncertain/resolved.json").read_text(encoding="utf-8"))
    words, t, lt, _ = layer_map(base, layer)
    W = base["pages"][0]["width"]
    edge = {i for i, w in enumerate(words)
            if w["bbox"]["x"] <= 1 or w["bbox"]["x"] + w["bbox"]["w"] >= W - 1}
    ok, bad = 0, []
    for tag, i1, i2, j1, j2 in L.align(t, lt):
        for ti in range(i1, i2):
            if set(t[ti]["refs"]) & edge:
                if tag == "equal":
                    ok += 1
                else:
                    bad.append((tag, t[ti]["raw"], " ".join(x["raw"] for x in lt[j1:j2])))
    print(f"D6 {pn}: {len(edge)} edge words: {ok} match the layer exactly; not matching: {len(bad)}")
    for b in bad:
        print("   ", b)
