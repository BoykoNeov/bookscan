"""Re-judge the text-layer marker on the pages as now shipped (prereg addendum 2).

    python rejudge.py prepare   -> rejudge/key.json (carried + new sites), blind sheets
                                   of the NEW sites only, rejudge/labels_new_template.json
    python rejudge.py score     -> joins rejudge/labels_new.json + the carried labels and
                                   runs the measurement tool's own score()
"""
import json
import random
import sys
from pathlib import Path

REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import fitz  # noqa: E402

from pipeline import pdf_text_layer as L  # noqa: E402
from pipeline.second_opinion import load_lexicon  # noqa: E402
from tools import pdf_textlayer_eval as E  # noqa: E402

JOBS = Path(r"W:\temp\claude\pdf_textlayer\shipped_skip\jobs")
WORK = Path(r"W:\temp\claude\pdf_textlayer\rejudge")
DATA = REPO / "docs" / "data" / "pdf_textlayer_20260924"
SEED = "20260924-rejudge"


def ident(s):
    return (s["doc"], s["pdf_page"], s["t_norm"], s["l_norm"])


def prepare():
    WORK.mkdir(exist_ok=True)
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    old = json.loads((DATA / "key_labelled.json").read_text(encoding="utf-8"))
    pool = {}
    for s in old["primary"]:
        pool.setdefault(ident(s), []).append(s)
    lex = load_lexicon([REPO / "models" / "lexicons" / "en.dic"])
    per_doc, carried, new = {}, [], []
    for d in manifest["docs"]:
        src = fitz.open(d["file"])
        stats = {"pages": 0, "t_tokens": 0, "l_tokens": 0, "equal_t": 0, "coverage": [],
                 "sites": 0, "sites_kept": 0, "sites_flagged": 0, "armb_kept": 0,
                 "other_replace": 0, "flagged_agree": 0}
        kept = []
        for k, pno in enumerate(d["pages_1based"]):
            page_dir = JOBS / d["id"] / f"page_{k + 1:03d}"
            words = E.tesseract_words(page_dir)
            t = L.prep_tokens([(w["text"], i) for i, w in enumerate(words)])
            lt = L.prep_tokens([(w, None) for w in L.layer_words(src[pno - 1])])
            ops = L.align(t, lt)
            eq = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
            cov = eq / len(t) if t else 0.0
            stats["pages"] += 1
            stats["t_tokens"] += len(t)
            stats["l_tokens"] += len(lt)
            stats["equal_t"] += eq
            stats["coverage"].append(round(cov, 3))
            for tag, i1, i2, j1, j2 in ops:
                if tag != "replace":
                    continue
                if i2 - i1 != 1 or j2 - j1 != 1:
                    stats["other_replace"] += 1
                    continue
                s = E._site(d["id"], pno, page_dir, words, t[i1], lt[j1], lex, cov)
                stats["sites"] += 1
                if s["kept"]:
                    stats["sites_kept"] += 1
                    stats["armb_kept"] += s["arm_b"]
                else:
                    stats["sites_flagged"] += 1
                if s["kept"] or d["id"] == "C":
                    kept.append(s)
        src.close()
        assert len(kept) <= E.CAP_PRIMARY, (d["id"], len(kept))   # no sampling needed
        for s in kept:
            s["in_uniform_sample"] = True
            got = pool.get(ident(s))
            if got:                                 # same readings on the same page
                o = got.pop(0)
                s.update(id=o["id"], a_is_tesseract=o["a_is_tesseract"], carried=True)
                carried.append(s)
            else:
                s["carried"] = False
                new.append(s)
        per_doc[d["id"]] = stats
        print(f"{d['id']}: {stats['sites']} sites, {len(kept)} to score "
              f"({sum(x['carried'] for x in kept)} carried)")
    random.Random(SEED).shuffle(new)
    for n, s in enumerate(new, 1):
        s["id"] = f"R{n:03d}"
        s["a_is_tesseract"] = random.Random(f"{SEED}-{s['id']}").random() < 0.5
    (WORK / "key.json").write_text(json.dumps(
        {"per_doc": per_doc, "primary": carried + new, "agree": []}, indent=1,
        ensure_ascii=False), encoding="utf-8")
    (WORK / "labels_new_template.json").write_text(json.dumps(
        {s["id"]: "" for s in new}, indent=1), encoding="utf-8")
    E._sheets(WORK, new, [])
    print(f"{len(carried)} carried, {len(new)} new -> {WORK / 'sheets'}")


def score():
    key = json.loads((WORK / "key.json").read_text(encoding="utf-8"))
    old = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))["primary"]
    new = json.loads((WORK / "labels_new.json").read_text(encoding="utf-8"))
    labels = {"primary": {s["id"]: (old[s["id"]] if s["carried"] else new[s["id"]])
                          for s in key["primary"]}, "agree": {}}
    (WORK / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
    out = E.score(WORK)
    nl = [s for s in json.loads((WORK / "key_labelled.json").read_text(encoding="utf-8"))["primary"]
          if not s["carried"] and s["doc"] != "C"]
    c = sum(s["outcome"] == "catch" for s in nl)
    f = sum(s["outcome"] == "false_alarm" for s in nl)
    print(f"NEW sites alone (D1-D7): {c} catches, {f} false alarms, "
          f"{sum(s['outcome'] is None for s in nl)} can't tell")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    {"prepare": prepare, "score": score}[sys.argv[1]]()
