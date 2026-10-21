"""Score the readings (pre-registration: ../panelread_prereg_20261021.md).

    python -X utf8 docs/data/panelread_20261021/score.py

Reads references.json, readings_qwen3.6_27b.json, readings_gemma4_31b.json and the
shipped Tesseract words; writes scores.json and prints the tables.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
JOB = HERE.parents[2] / "jobs" / "20260829-084115-de3c20d3"
UNC = "\x00"   # prefix marking an uncertain reference token


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    for a in "’‘´`":
        s = s.replace(a, "'")
    for a in "“”„":
        s = s.replace(a, '"')
    s = s.replace("½", " 1/2").replace("¼", " 1/4").replace("¾", " 3/4")
    s = s.replace("|", " ")
    s = re.sub(r"(\w)-\s+([a-zäöüß])", r"\1\2", s)
    return re.sub(r"\s+", " ", s).strip()


def model_tokens(s: str) -> list[str]:
    s = norm(s)
    return [] if s in ("", "NO TEXT") else s.split(" ")


def ref_tokens(s: str) -> list[str]:
    # [?x] -> uncertain; normalise the inside, keep the mark on every piece
    out = []
    for part in re.split(r"(\[\?[^\]]*\])", s):
        if part.startswith("[?"):
            out += [UNC + t for t in norm(part[2:-1]).split(" ") if t]
        else:
            out += [t for t in norm(part).split(" ") if t]
    # the dehyphenation join can only see plain text; apply it across tokens too
    return out


def is_num(t: str) -> bool:
    return any(c.isdigit() for c in t)


def align(m: list[str], r: list[str]) -> dict:
    """Per model token: 'right' | 'wrong' | 'spill' | 'unc'; plus deletion count."""
    rr = [t[1:] if t.startswith(UNC) else t for t in r]
    sm = difflib.SequenceMatcher(None, m, rr, autojunk=False)
    ops = sm.get_opcodes()
    eq = [o for o in ops if o[0] == "equal"]
    lab = ["wrong"] * len(m)
    dele = 0
    del_nums = 0
    if not eq:
        lab = ["wrong"] * len(m)
        dele = sum(1 for t in r if not t.startswith(UNC))
        del_nums = sum(1 for t in r if not t.startswith(UNC) and is_num(t))
        return {"labels": lab, "deleted": dele, "deleted_nums": del_nums,
                "ref_matched": [False] * len(r)}
    first, last = eq[0][1], eq[-1][2]
    ref_matched = [False] * len(r)
    for tag, i1, i2, j1, j2 in ops:
        unc_span = any(r[j].startswith(UNC) for j in range(j1, j2))
        if tag == "equal":
            for k, i in enumerate(range(i1, i2)):
                j = j1 + k
                if r[j].startswith(UNC):
                    lab[i] = "unc"
                else:
                    lab[i] = "right"
                    ref_matched[j] = True
            continue
        for i in range(i1, i2):
            if i < first or i >= last:
                lab[i] = "spill"
            elif unc_span and tag == "replace":
                lab[i] = "unc"
        for j in range(j1, j2):
            if not r[j].startswith(UNC):
                dele += 1 if tag in ("delete", "replace") else 0
    # deleted = reference tokens not matched (excl. uncertain)
    dele = sum(1 for j, t in enumerate(r) if not t.startswith(UNC) and not ref_matched[j])
    del_nums = sum(1 for j, t in enumerate(r)
                   if not t.startswith(UNC) and not ref_matched[j] and is_num(t))
    return {"labels": lab, "deleted": dele, "deleted_nums": del_nums, "ref_matched": ref_matched}


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def block_score(mtext: str | None, ref: str) -> dict | None:
    if mtext is None:
        return None
    m, r = model_tokens(mtext), ref_tokens(ref)
    a = align(m, r)
    lab = a["labels"]
    n_ref = sum(1 for t in r if not t.startswith(UNC))
    n_ref_num = sum(1 for t in r if not t.startswith(UNC) and is_num(t))
    wrong = [i for i, l in enumerate(lab) if l == "wrong"]
    right = [i for i, l in enumerate(lab) if l == "right"]
    # substitutions+insertions = wrong model tokens; deletions = unmatched ref tokens.
    # WER numerator: max(wrong, ...) is not used; we count S as min(wrong, deleted)
    # pairs, I = wrong - S, D = deleted - S.
    S = min(len(wrong), a["deleted"])
    errs = S + (len(wrong) - S) + (a["deleted"] - S)
    ref_plain = " ".join(t for t in r if not t.startswith(UNC))
    kept = " ".join(m[i] for i, l in enumerate(lab) if l in ("right", "wrong"))
    return {"n_ref": n_ref, "n_ref_num": n_ref_num, "right": len(right), "wrong": len(wrong),
            "deleted": a["deleted"], "errors": errs,
            "num_matched": sum(1 for j, t in enumerate(r) if a["ref_matched"][j] and is_num(t)),
            "wrong_nums": sum(1 for i in wrong if is_num(m[i])),
            "spill": lab.count("spill"), "unc": lab.count("unc"),
            "cer_num": lev(kept, ref_plain), "cer_den": len(ref_plain),
            "tokens": m, "labels": lab}


def bag(mtext: str | None, ref: str) -> dict | None:
    if mtext is None:
        return None
    m = Counter(model_tokens(mtext))
    r = Counter(t for t in ref_tokens(ref) if not t.startswith(UNC))
    hit = sum((m & r).values())
    return {"hit": hit, "n_model": sum(m.values()), "n_ref": sum(r.values())}


def flags(m_tokens: list[str], s_text: str | None) -> list[bool] | None:
    """True where a token of M is not in an equal block when aligned to S."""
    if s_text is None:
        return None
    s = model_tokens(s_text)
    sm = difflib.SequenceMatcher(None, m_tokens, s, autojunk=False)
    f = [True] * len(m_tokens)
    for tag, i1, i2, _, _ in sm.get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                f[i] = False
    return f


def tesseract_text() -> dict[str, str]:
    doc = json.loads((JOB / "document.json").read_text(encoding="utf-8"))
    out = {}
    for p in doc["pages"]:
        for b in p["blocks"]:
            out[f"{p['page_id']}__b{b['id']:03d}"] = " ".join(
                (w.get("text_ocr") or w.get("text") or "") for w in b["words"])
    return out


def main() -> None:
    refs = {k: v for k, v in json.loads((HERE / "references.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")}
    q = json.loads((HERE / "readings_qwen3.6_27b.json").read_text(encoding="utf-8"))
    gp = HERE / "readings_gemma4_31b.json"
    g = json.loads(gp.read_text(encoding="utf-8")) if gp.exists() else {}
    tess = tesseract_text()

    def text(src, stem, arm):
        return (src.get(stem, {}).get(arm) or {}).get("text")

    arms = {"T": lambda s: tess.get(s), "Q-page": lambda s: text(q, s, "page"),
            "Q-close": lambda s: text(q, s, "close"), "G-page": lambda s: text(g, s, "page")}
    result = {"blocks": {}, "pooled": {}, "flags": {}, "notext": {}, "map": {}}
    pooled: dict = {}
    for stem, ref in refs.items():
        st = ref["stratum"]
        if st == "excluded":
            continue
        for arm, get in arms.items():
            t = get(stem)
            if st == "notext":
                if t is not None:
                    result["notext"].setdefault(arm, {})[stem] = len(model_tokens(t))
                continue
            if st == "map":
                b = bag(t, ref["text"])
                if b:
                    result["map"].setdefault(arm, {})[stem] = b
                continue
            s = block_score(t, ref["text"])
            if s is None:
                continue
            result["blocks"].setdefault(stem, {})[arm] = {k: v for k, v in s.items()
                                                          if k not in ("tokens", "labels")}
            P = pooled.setdefault((st, arm), Counter())
            for k in ("n_ref", "n_ref_num", "right", "wrong", "deleted", "errors",
                      "num_matched", "wrong_nums", "cer_num", "cer_den"):
                P[k] += s[k]
            P["blocks"] += 1
    for (st, arm), P in sorted(pooled.items()):
        result["pooled"][f"{st}/{arm}"] = dict(P, wer=round(P["errors"] / max(1, P["n_ref"]), 4),
                                               cer=round(P["cer_num"] / max(1, P["cer_den"]), 4),
                                               num_recall=round(P["num_matched"] / max(1, P["n_ref_num"]), 4))
    # close-up comparison on blocks that have both
    both = [s for s in result["blocks"] if "Q-close" in result["blocks"][s]]
    cmp = Counter()
    for s in both:
        a, b = result["blocks"][s]["Q-page"], result["blocks"][s]["Q-close"]
        wa, wb = a["errors"] / max(1, a["n_ref"]), b["errors"] / max(1, b["n_ref"])
        cmp["close_better" if wb < wa else "close_worse" if wb > wa else "tie"] += 1
        cmp["page_err"] += a["errors"]; cmp["close_err"] += b["errors"]; cmp["n_ref"] += a["n_ref"]
    result["close_vs_page"] = dict(cmp, blocks=len(both))
    # flags
    seconds = {"Q-page": {"S1 Tesseract": arms["T"], "S2 other model": arms["G-page"],
                          "S3 other photo": arms["Q-close"]},
               "Q-close": {"S1 Tesseract": arms["T"], "S3 other photo": arms["Q-page"]}}
    for marm, sops in seconds.items():
        for sname, sget in sops.items():
            F = {}
            for stem, ref in refs.items():
                st = ref["stratum"]
                if st not in ("table", "panel"):
                    continue
                mt = arms[marm](stem)
                st_text = sget(stem)
                if mt is None or st_text is None:
                    continue
                s = block_score(mt, ref["text"])
                f = flags(s["tokens"], st_text)
                C = F.setdefault(st, Counter())
                C["blocks"] += 1
                for tok, lab, fl in zip(s["tokens"], s["labels"], f):
                    if lab == "wrong":
                        C["wrong"] += 1; C["wrong_flagged"] += fl
                        if is_num(tok):
                            C["wrong_num"] += 1; C["wrong_num_flagged"] += fl
                    elif lab == "right":
                        C["right"] += 1; C["right_flagged"] += fl
            for st, C in F.items():
                catch = C["wrong_flagged"] / C["wrong"] if C["wrong"] else None
                ncatch = C["wrong_num_flagged"] / C["wrong_num"] if C["wrong_num"] else None
                fa = C["right_flagged"] / C["right"] if C["right"] else None
                ok = (catch is not None and catch >= 0.90 and (ncatch is None or ncatch == 1.0)
                      and fa is not None and fa <= 0.25)
                result["flags"][f"{marm} vs {sname} / {st}"] = dict(
                    C, catch=catch and round(catch, 3), num_catch=ncatch and round(ncatch, 3),
                    false_alarm=fa and round(fa, 3), meets_bar=ok)
    (HERE / "scores.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print("POOLED (stratum/arm): blocks  WER  CER  num_recall  wrong_nums")
    for k, v in result["pooled"].items():
        print(f"  {k:18s} {v['blocks']:3d}  {v['wer']:.3f}  {v['cer']:.3f}  {v['num_recall']:.3f}  {v['wrong_nums']}")
    print("CLOSE vs PAGE (Q):", result["close_vs_page"])
    print("NO-TEXT tokens invented:", result["notext"])
    print("MAP bag hits:", result["map"])
    print("FLAGS: catch / num_catch / false_alarm / meets bar")
    for k, v in result["flags"].items():
        print(f"  {k:40s} {v['catch']} / {v['num_catch']} / {v['false_alarm']} / {v['meets_bar']}"
              f"   (wrong {v['wrong']}, wrong nums {v.get('wrong_num', 0)}, right {v['right']})")


if __name__ == "__main__":
    main()
