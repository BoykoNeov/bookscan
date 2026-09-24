"""Post-hoc look at the scored text-layer sites (NOT part of the gate)."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"M:\claud_projects\bookscan")
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.second_opinion import load_lexicon  # noqa: E402

W = Path(r"W:\temp\claude\pdf_textlayer\work")
key = json.loads((W / "key_labelled.json").read_text(encoding="utf-8"))
lex = load_lexicon([Path(r"M:\claud_projects\bookscan\models\lexicons\en.dic")])
real = [s for s in key["primary"] if s["doc"] != "C" and s["in_uniform_sample"]]

print("catches by (tesseract, layer) reading:")
c = Counter((s["t_raw"], s["l_raw"]) for s in real if s["outcome"] == "catch")
for (t, l), n in c.most_common():
    print(f"  {n} x  T={t!r:14} L={l!r:14}")
print("false alarms:")
for s in real:
    if s["outcome"] == "false_alarm":
        print(f"  {s['doc']} T={s['t_raw']!r:14} L={s['l_raw']!r:14} label={s['label']}")

# the O2 / H2O2 family (one chemistry paper's repeated formula)
o2 = [s for s in real if s["outcome"] == "catch"
      and s["t_norm"] in {"02", "o", "0", "03", "0s", "h0", "h202", "hs20"}]
print(f"catches that are the O2/H2O2 formula family: {len(o2)}")

# sensitivity: drop pages whose alignment coverage < 0.5
keep = [s for s in real if s["page_coverage"] >= 0.5]
cc = sum(s["outcome"] == "catch" for s in keep)
ff = sum(s["outcome"] == "false_alarm" for s in keep)
print(f"without pages under 0.5 coverage: catches {cc}, false alarms {ff}, "
      f"precision {cc / (cc + ff):.3f}")

# dictionary membership of the Tesseract token, by outcome (exploratory)
for outcome in ("catch", "false_alarm"):
    ss = [s for s in real if s["outcome"] == outcome]
    t_in = sum(s["t_norm"] in lex for s in ss)
    both = sum(s["t_norm"] in lex and s["l_norm"] in lex for s in ss)
    print(f"{outcome}: {len(ss)}; Tesseract token a dictionary word {t_in}; "
          f"both dictionary words {both}")

# scale: how many words Stage 06 already flags on these pages
flags = words = 0
for page in sorted((W / "jobs").glob("D*/page_*")):
    res = json.loads((page / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
    for sp in res["pages"]:
        for b in sp["blocks"]:
            for w in b.get("words") or []:
                words += 1
                flags += (w.get("decision") or "keep") != "keep"
print(f"real-document pages: {words} words, Stage 06 flags {flags} ({flags / words:.1%})")
