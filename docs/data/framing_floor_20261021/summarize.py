"""Summarize the framing-floor runs (docs/data/framing_floor_prereg_20261021.md).

usage: summarize.py <runs_dir> <summary_json>
Per row: the precondition checks, then for every statistic the base value, the
min/max over the reframing arms and how many arms move it. Statistics are
per subpage (seg matched, type_acc, tau_layout, tau_all, pairs_ok,
pairs_wrong, slivers) plus the row totals of seg and pairs.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
THIN = HERE.parent / "geom_thin_20261021"
CONTROL_ARMS = {"base", "repeat", "rect0"}
# floor arm -> geom_thin_20261021 arm graded on the same rectangle
COUNTERPART = {
    "it_geo_06": {"base": "base", "L4": "tiny", "L41": "ident", "R41": "R41",
                  "T41": "T41", "B41": "B41"},
    "it_geo_07": {"base": "base", "L4": "tiny", "L41": "L41", "R41": "R41",
                  "T41": "T41", "B41": "B41"},
}
for _r in ("de_01", "en_coins_01", "en_coins_02", "en_coins_03", "it_geo_04",
           "it_geo_05"):
    COUNTERPART[_r] = {"base": "base"}
SLIVER = 0.04   # figure_grouping's thinness floor (sole_min_fig_frac / geom_min_fig_frac)


def r4(x):
    return None if x is None else round(float(x), 4)


def stats(path: Path) -> dict:
    g = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    seg_t = n_t = ok_t = wrong_t = 0
    for sp in g["subpages"]:
        det = sp.get("pairs_detail") or []
        ok = sum(1 for d in det if d.get("verdict") == "ok")
        wrong = sum(1 for d in det if d.get("verdict") == "wrong")
        s5 = sp.get("stage05_detail") or {}
        pw, ph = (s5.get("page_wh") or [0, 0])
        slivers = sum(1 for b in s5.get("real_blocks", [])
                      if b["type"] == "figure" and pw and ph
                      and min(b["bbox"][2] / pw, b["bbox"][3] / ph) < SLIVER)
        sub = sp["name"].replace(".png", "")
        out[f"{sub}.seg"] = len(sp["matched"])
        out[f"{sub}.type_acc"] = r4(sp.get("type_acc"))
        out[f"{sub}.tau_layout"] = r4(sp.get("tau_layout"))
        out[f"{sub}.tau_all"] = r4((sp.get("order_all") or {}).get("tau"))
        out[f"{sub}.pairs_ok"] = ok
        out[f"{sub}.pairs_wrong"] = wrong
        out[f"{sub}.slivers"] = slivers
        seg_t += len(sp["matched"]); n_t += sp["n_gt"]; ok_t += ok; wrong_t += wrong
    out["row.seg"] = seg_t
    out["row.n_gt"] = n_t
    out["row.pairs_ok"] = ok_t
    out["row.pairs_wrong"] = wrong_t
    return out


def main() -> int:
    runs = Path(sys.argv[1])
    by_row: dict[str, dict[str, dict]] = {}
    for p in sorted(runs.glob("lo_*__*.json")):
        row, arm = p.stem[3:].split("__")
        by_row.setdefault(row, {})[arm] = stats(p)
    summary = {}
    for row, arms in by_row.items():
        base = arms.get("base")
        rec: dict = {"arms": sorted(arms), "precondition": {}}
        pre = rec["precondition"]
        if base is None:
            pre["base_missing"] = True
            summary[row] = rec
            continue
        for ctl in ("repeat", "rect0"):
            if ctl in arms:
                diff = {k: [base[k], arms[ctl][k]] for k in base if base[k] != arms[ctl].get(k)}
                pre[f"{ctl}_equals_base"] = not diff
                if diff:
                    pre[f"{ctl}_diff"] = diff
        for arm, tarm in COUNTERPART.get(row, {}).items():
            tp = THIN / f"lo_{row}_{tarm}.json"
            if arm in arms and tp.exists():
                ref = stats(tp)
                diff = {k: [ref[k], arms[arm][k]] for k in ref if ref[k] != arms[arm].get(k)}
                pre[f"{arm}_reproduces_geom_thin_{tarm}"] = not diff
                if diff:
                    pre[f"{arm}_vs_geom_thin_diff"] = diff
        reframe = {a: s for a, s in arms.items() if a not in CONTROL_ARMS}
        rec["n_reframing_arms"] = len(reframe)
        rec["thin_floor"] = len(reframe) < 4
        table = {}
        for k in base:
            vals = {a: s.get(k) for a, s in reframe.items()}
            nums = [v for v in vals.values() if v is not None]
            moved = sorted(a for a, v in vals.items() if v != base[k])
            table[k] = {"base": base[k],
                        "min": min(nums) if nums else None,
                        "max": max(nums) if nums else None,
                        "n_moved": len(moved), "moved_by": moved,
                        "values": vals}
        rec["stats"] = table
        rec["any_moved_arms"] = sorted(
            a for a, s in reframe.items()
            if any(s.get(k) != base[k] for k in base if not k.endswith(".slivers")))
        summary[row] = rec
        print(f"== {row}: {len(reframe)} reframing arms; precondition {pre}")
        for k, t in table.items():
            if t["n_moved"]:
                print(f"   {k:22s} base {t['base']}  range [{t['min']}, {t['max']}]  "
                      f"moved by {t['n_moved']}: {', '.join(t['moved_by'])}")
    Path(sys.argv[2]).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
