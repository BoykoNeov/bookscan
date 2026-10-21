"""List every reader-vs-reference difference (numbers marked), for the
pre-registered adjudication. Writes disagreements.txt."""
import difflib
import json
from pathlib import Path

import score as S

HERE = Path(__file__).parent
refs = {k: v for k, v in json.loads((HERE / "references.json").read_text(encoding="utf-8")).items()
        if not k.startswith("_") and v["stratum"] in ("table", "panel")}
q = json.loads((HERE / "readings_qwen3.6_27b.json").read_text(encoding="utf-8"))
g = json.loads((HERE / "readings_gemma4_31b.json").read_text(encoding="utf-8"))
lines = []
for stem, ref in refs.items():
    r = [t.lstrip(S.UNC) for t in S.ref_tokens(ref["text"])]
    for arm, src, key in (("Q-page", q, "page"), ("Q-close", q, "close"), ("G-page", g, "page")):
        t = (src.get(stem, {}).get(key) or {}).get("text")
        if t is None:
            continue
        m = S.model_tokens(t)
        sm = difflib.SequenceMatcher(None, m, r, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            mm, rr = " ".join(m[i1:i2]), " ".join(r[j1:j2])
            num = any(S.is_num(x) for x in m[i1:i2] + r[j1:j2])
            ctx = " ".join(r[max(0, j1 - 3):j1])
            lines.append(f"{'NUM ' if num else '    '}{stem:22s} {arm:8s} {tag:7s} ref[{rr}] model[{mm}]  after: ...{ctx}")
(HERE / "disagreements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
