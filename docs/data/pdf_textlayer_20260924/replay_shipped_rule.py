"""Does pipeline.pdf_text_layer.check reproduce the MEASURED site set exactly?

Runs the shipped rule on the audited work pages and compares, per document:
the 1<->1 sites (kept + flagged), the other-replace count, the coverage list,
and the identity of every labelled site in the committed key_labelled.json.
Also reports which pages the shipped abstention edges would skip.
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import fitz  # noqa: E402

from pipeline import pdf_text_layer as L  # noqa: E402

WORK = Path(sys.argv[1] if len(sys.argv) > 1 else r"W:\temp\claude\pdf_textlayer\work")
DATA = REPO / "docs" / "data" / "pdf_textlayer_20260924"
key = json.loads((DATA / "key_labelled.json").read_text(encoding="utf-8"))
manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
RAW = dict(L.DEFAULTS, min_layer_words=0, min_coverage=0.0)


def site_id(doc, pno, sub, box, tn, ln):
    return (doc, pno, sub, tuple(box), tn, ln)


ok = True
replay_primary = Counter()
for d in manifest["docs"]:
    src = fitz.open(d["file"])
    st = key["per_doc"][d["id"]]
    n_sites = n_kept = n_flag = n_other = 0
    cov = []
    for k, pno in enumerate(d["pages_1based"]):
        page_dir = WORK / "jobs" / d["id"] / f"page_{k + 1:03d}"
        res = json.loads((page_dir / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
        words, subs = [], []
        for sp in res["pages"]:
            for w in L.page_words([sp]):
                words.append(w)
                subs.append(sp["name"])
        layer = L.layer_words(src[pno - 1])
        chk = L.check(words, layer, RAW)
        shipped = L.check(words, layer)
        cov.append(round(chk.coverage, 3))
        n_other += chk.other_replace
        for t, lt in chk.sites:
            ws = [words[r] for r in t["refs"]]
            kept = all((w.get("decision") or "keep") == "keep" for w in ws)
            n_sites += 1
            n_kept += kept
            n_flag += not kept
            x0 = min(w["bbox"]["x"] for w in ws)
            y0 = min(w["bbox"]["y"] for w in ws)
            x1 = max(w["bbox"]["x"] + w["bbox"]["w"] for w in ws)
            y1 = max(w["bbox"]["y"] + w["bbox"]["h"] for w in ws)
            if kept or d["id"] == "C":
                replay_primary[site_id(d["id"], pno, subs[t["refs"][0]],
                                       [x0, y0, x1 - x0, y1 - y0], t["norm"], lt["norm"])] += 1
        tag = "marks" if not shipped.abstained else f"ABSTAINS: {shipped.abstained}"
        print(f"  {d['id']} p{pno}: layer {len(layer)} words, coverage {chk.coverage:.3f}, "
              f"{len(chk.sites)} sites, shipped rule {tag}"
              + (f" ({len(shipped.marked)} words)" if not shipped.abstained else ""))
    src.close()
    same = (n_sites, n_kept, n_flag, n_other, cov) == (
        st["sites"], st["sites_kept"], st["sites_flagged"], st["other_replace"], st["coverage"])
    ok &= same
    print(f"{d['id']}: sites {n_sites}/{st['sites']} kept {n_kept}/{st['sites_kept']} "
          f"flagged {n_flag}/{st['sites_flagged']} other {n_other}/{st['other_replace']} "
          f"coverage {cov} vs {st['coverage']} -> {'SAME' if same else 'DIFFERENT'}")

key_primary = Counter(site_id(s["doc"], s["pdf_page"], s["sub"], s["box"], s["t_norm"],
                              s["l_norm"]) for s in key["primary"])
print(f"labelled sites: key {sum(key_primary.values())}, replay {sum(replay_primary.values())}, "
      f"only in key {sum((key_primary - replay_primary).values())}, "
      f"only in replay {sum((replay_primary - key_primary).values())}")
ok &= key_primary == replay_primary
print("REPRODUCED EXACTLY" if ok else "MISMATCH")
