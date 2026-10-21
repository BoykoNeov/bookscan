"""Grade geom_thin_prereg_20261021.md's G1/G2/G4 from the run outputs.

usage: summarize.py <out_dir> <summary_json>
Per run: the 0.04 arm's graded pairs (the eval's pairs_detail), and for each
subpage the pairs that differ between the 0 and 0.04 arms of the SAME call.
A pair present only at 0 is graded from the committed trim-control output of
that arm when one exists (trim_control_20261021/lo_<row>_<arm>.json).
"""
import json
import sys
from pathlib import Path

out, summ = Path(sys.argv[1]), Path(sys.argv[2])
committed = Path(r"M:\claud_projects\bookscan\docs\data\trim_control_20261021")
res = {}
for lo in sorted(out.glob("lo_*.json")):
    name = lo.stem[3:]
    side = json.loads((out / f"side_{name}.json").read_text(encoding="utf-8"))
    d = json.loads(lo.read_text(encoding="utf-8"))
    on_detail = [dict(p, subpage=s["name"]) for s in d["subpages"]
                 for p in s.get("pairs_detail", [])]
    diffs = [{"sub": i, "off": s["off"]["pairs"], "on": s["on"]["pairs"],
              "thin": {k: v for k, v in s["figures"].items()
                       if min(v[2] / max(1, s["page_w"] or 1), v[3] / max(1, s["page_h"])) < 0.04}}
             for i, s in enumerate(side) if s["off"]["pairs"] != s["on"]["pairs"]]
    row = {"on_pairs": on_detail,
           "on_wrong": sum(p["verdict"] == "wrong" for p in on_detail),
           "on_ok": sum(p["verdict"] == "ok" for p in on_detail),
           "on_ungraded": sum(p["verdict"] not in ("ok", "wrong") for p in on_detail),
           "differs": diffs}
    # the 0 arm graded by the committed run of the same rows/trim, where it exists
    base_row, arm = name.rsplit("_", 1)
    c = committed / f"lo_{base_row}_{arm}.json"
    if c.exists():
        cd = json.loads(c.read_text(encoding="utf-8"))
        off_detail = [dict(p, subpage=s["name"]) for s in cd["subpages"]
                      for p in s.get("pairs_detail", [])]
        row["committed_off_pairs"] = off_detail
        row["committed_off_wrong"] = sum(p["verdict"] == "wrong" for p in off_detail)
    res[name] = row
    print(f"{name:22s} on ok {row['on_ok']} wrong {row['on_wrong']}"
          f" ungraded {row['on_ungraded']}"
          f"  differs {len(diffs)}"
          + (f"  committed-off wrong {row['committed_off_wrong']}"
             if "committed_off_wrong" in row else ""))
    for df in diffs:
        print("    sub", df["sub"], "off", df["off"], "on", df["on"], "thin", df["thin"])
summ.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
