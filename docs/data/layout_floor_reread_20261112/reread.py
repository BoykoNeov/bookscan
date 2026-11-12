"""Re-read past layout deltas against the framing floor.

Rule: docs/data/layout_floor_reread_prereg_20261112.md (committed before this ran).
Inputs: deltas.json (here) + docs/data/framing_floor_20261021/summary.json and the
floor's per-arm eval outputs (lo_<row>__<arm>.json). No pipeline code runs.

usage: python docs/data/layout_floor_reread_20261112/reread.py
writes verdicts.json and verdicts.md next to this file.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
FLOOR = HERE.parent / "framing_floor_20261021"
THIN_ROWS = {"en_coins_03", "it_geo_04"}
CONTROL_ARMS = {"base", "repeat", "rect0"}


def floor_cell(summary: dict, row: str, cell: str) -> dict | None:
    s = summary.get(row, {}).get("stats", {}).get(cell)
    if s is None:
        return None
    vals = s["values"]
    defined = [v for v in vals.values() if v is not None]
    pool = defined + ([s["base"]] if s["base"] is not None else [])
    swing = (max(pool) - min(pool)) if pool else None
    n_moved = sum(1 for v in vals.values() if v != s["base"])
    return {"base": s["base"], "n_arms": len(vals), "n_moved": n_moved,
            "swing": None if swing is None else round(swing, 4),
            "moved_by": sorted(a for a, v in vals.items() if v != s["base"])}


def verdict(d: dict, fc: dict | None) -> tuple[str, str]:
    if d["arm"] == "pre0706":
        return "CANNOT JUDGE", "before the 2026-07-06 matching change (and Stage-04-only)"
    if fc is None:
        return "CANNOT JUDGE", "statistic not carried by the floor"
    if d["arm"] != "default":
        return "CANNOT JUDGE", "graded on the Stage-04-only arm (a different quantity)"
    if d["row"] in THIN_ROWS:
        return "CANNOT JUDGE", "thin floor (3 bottom-only trims)"
    delta = abs(d["after"] - d["before"])
    if fc["n_moved"] == 0:
        return "OUTSIDE", "no reframing ever moved this cell"
    if delta <= fc["swing"] + 1e-9:
        return "INSIDE", f"|delta| {delta:.4g} <= reframing swing {fc['swing']:.4g}"
    return "OUTSIDE", f"|delta| {delta:.4g} > reframing swing {fc['swing']:.4g}"


# ---- supplementary, NOT pre-registered: does the specific block a past change
# was about survive each reframing? Read off the floor's own eval outputs. ----
def arms(row: str) -> dict[str, dict]:
    out = {}
    for p in sorted(FLOOR.glob(f"lo_{row}__*.json")):
        a = p.stem.split("__")[1]
        if a not in CONTROL_ARMS:
            out[a] = json.loads(p.read_text(encoding="utf-8"))
    return out


def sub(g: dict, name: str) -> dict:
    return next(s for s in g["subpages"] if s["name"] == f"{name}.png")


def has_pair(s: dict, cap: str, fig: str) -> bool:
    return any(d.get("caption") == cap and d.get("figure") == fig and d.get("verdict") == "ok"
               for d in s.get("pairs_detail") or [])


CHECKS = [
    # (id, past change it belongs to, row, subpage, description, predicate)
    ("de01R_order", "within_column_0718", "de_01", "right", "text order exact (tau +1.00)",
     lambda s: s.get("tau_layout") == 1.0),
    ("it06L_F26_last", "column_major_0809", "it_geo_06", "left",
     "F26 ordered after F25/F27/F28 (the column-major fix)",
     lambda s: (s["order_all"].get("seq_det") or [])[:4] == ["F25", "F27", "F28", "F26"]),
    ("it06L_number_pairs", "grouping_0809 / corner_label*", "it_geo_06", "left",
     "C25-C28 all paired to their figures by number",
     lambda s: all(has_pair(s, f"C{n}", f"F{n}") for n in (25, 26, 27, 28))),
    ("it06L_C28", "corner_label3_0810", "it_geo_06", "left", "C28 -> F28 (the round-3 plate read)",
     lambda s: has_pair(s, "C28", "F28")),
    ("it06R_C29","grouping_0809 / phase_b_0809", "it_geo_06", "right", "C29 -> F29 correct",
     lambda s: has_pair(s, "C29", "F29")),
    ("it06R_no_wrong", "zero-wrong bar", "it_geo_06", "right", "no wrong pair",
     lambda s: not any(d.get("verdict") == "wrong" for d in s.get("pairs_detail") or [])),
    ("coins01_pairs", "coins_grouping_01_0818", "en_coins_01", "left+right", "C96-C99 paired",
     None),
    ("coins02_pairs", "coins_grouping_02_0818", "en_coins_02", "right", "C101/C102 paired",
     lambda s: has_pair(s, "C101", "F101") and has_pair(s, "C102", "F102")),
    ("coins03_pairs", "coins_grouping_03_0818", "en_coins_03", "right", "C104/C105 paired",
     lambda s: has_pair(s, "C104", "F104") and has_pair(s, "C105", "F105")),
    ("it05R_C3", "sole_figure_05_0826", "it_geo_05", "right", "C3 -> F3 (sole-figure arm)",
     lambda s: has_pair(s, "C3", "F3")),
    ("it05L_C2_found", "caption_eject (2026-08-10)", "it_geo_05", "left", "caption C2 matched",
     lambda s: "C2" in s["matched"]),
    ("it05L_C2_pair", "caption_eject (2026-08-10)", "it_geo_05", "left", "C2 -> F2 paired",
     lambda s: has_pair(s, "C2", "F2")),
    ("it07L_D1", "fig_rescue_07_*", "it_geo_07", "left", "picture D1 matched",
     lambda s: "D1" in s["matched"]),
    ("it07L_T5right", "starved_reread_0826", "it_geo_07", "left", "paragraph T5right matched",
     lambda s: "T5right" in s["matched"]),
    ("it04L_B6L", "fig_rescue_04_*", "it_geo_04", "left", "picture B6L matched (thin: 3 trims)",
     lambda s: "B6L" in s["matched"]),
    ("coins01L_FN1", "rescued_footnote_0826", "en_coins_01", "left", "FN1 typed footnote",
     lambda s: bool((s.get("type_ok") or {}).get("FN1"))),
]


def run_check(c) -> dict:
    cid, past, row, spn, desc, pred = c
    base = json.loads((FLOOR / f"lo_{row}__base.json").read_text(encoding="utf-8"))
    if cid == "coins01_pairs":
        def pred_g(g):
            l, r = sub(g, "left"), sub(g, "right")
            return (has_pair(l, "C96", "F96") and has_pair(l, "C97", "F97")
                    and has_pair(r, "C98", "F98") and has_pair(r, "C99", "F99"))
    else:
        def pred_g(g):
            return pred(sub(g, spn))
    trims = arms(row)
    held = {a: pred_g(g) for a, g in trims.items()}
    return {"id": cid, "past_change": past, "row": row, "subpage": spn, "what": desc,
            "holds_uncut": pred_g(base), "holds_on": sum(held.values()), "n_trims": len(held),
            "fails_on": sorted(a for a, v in held.items() if not v)}


def main() -> None:
    summary = json.loads((FLOOR / "summary.json").read_text(encoding="utf-8"))
    deltas = json.loads((HERE / "deltas.json").read_text(encoding="utf-8"))
    rows = []
    for d in deltas["deltas"]:
        fc = floor_cell(summary, d["row"], d["cell"]) if d["cell"] else None
        v, why = verdict(d, fc)
        rows.append({**d, "floor": fc, "verdict": v, "why": why})
    checks = [run_check(c) for c in CHECKS]
    out = {"verdicts": rows, "supplementary_block_checks": checks,
           "_note": "verdicts = pre-registered rule; supplementary_block_checks = NOT pre-registered"}
    (HERE / "verdicts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    md = ["# Past layout deltas vs the framing floor — verdicts (generated by reread.py)", "",
          "| past change | row | cell | delta | arm | floor: moved / arms, swing | verdict | why |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        fc = r["floor"]
        fl = "—" if fc is None else f"{fc['n_moved']}/{fc['n_arms']}, {fc['swing']}"
        md.append(f"| {r['result']} (RESULTS:{r['line']}) | `{r['row']}` | {r['cell'] or '—'} | "
                  f"{r['stat_text']} | {r['arm']} | {fl} | **{r['verdict']}** | {r['why']} |")
    md += ["", "## Supplementary (NOT pre-registered): does the block the change was about survive the trims?", "",
           "| check | past change | row / subpage | uncut | holds on trims | fails on |", "|---|---|---|---|---|---|"]
    for c in checks:
        md.append(f"| {c['what']} | {c['past_change']} | `{c['row']}` {c['subpage']} | "
                  f"{'yes' if c['holds_uncut'] else 'NO'} | {c['holds_on']}/{c['n_trims']} | "
                  f"{', '.join(c['fails_on']) or '—'} |")
    (HERE / "verdicts.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
