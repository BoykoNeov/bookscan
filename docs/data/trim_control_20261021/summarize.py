"""Print per-subpage metrics for every lo_*.json in this folder (and the
committed 2026-10-21 base/cut runs, marked 'ref_')."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
REF = HERE.parent / "vlm_cut_20261021"


def rows():
    for p in sorted(REF.glob("lo_*.json")):
        yield "ref_" + p.stem.split("_")[-1], p
    for p in sorted(HERE.glob("lo_*.json")):
        yield p.stem.split("_")[-1], p


def pairs(sp):
    det = sp.get("pairs_detail") or sp.get("parser_pairs_detail") or []
    ok = sum(1 for d in det if d.get("verdict") == "ok")
    wrong = sum(1 for d in det if d.get("verdict") == "wrong")
    return ok, wrong


out = []
for arm, p in rows():
    g = json.loads(p.read_text(encoding="utf-8"))
    for sp in g["subpages"]:
        ok, wrong = pairs(sp)
        rec = {"image": g["image_id"], "arm": arm, "sub": sp["name"],
               "seg": f"{len(sp['matched'])}/{sp['n_gt']}",
               "misses": sp["misses"], "type_acc": sp.get("type_acc"),
               "tau": sp.get("tau_layout"), "pairs_ok": ok,
               "pairs_wrong": wrong}
        out.append(rec)
        print(rec)
    subs = [r for r in out if r["image"] == g["image_id"] and r["arm"] == arm]
    seg = sum(int(r["seg"].split("/")[0]) for r in subs)
    n = sum(int(r["seg"].split("/")[1]) for r in subs)
    print(f"  TOTAL {g['image_id']} {arm}: seg {seg}/{n}  pairs ok "
          f"{sum(r['pairs_ok'] for r in subs)} wrong "
          f"{sum(r['pairs_wrong'] for r in subs)}")
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1), encoding="utf-8")
