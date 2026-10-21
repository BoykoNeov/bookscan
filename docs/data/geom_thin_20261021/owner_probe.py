"""group_figures at geom_min_fig_frac 0 and 0.04 over every subpage of a job,
called exactly as Stage 07 calls it (06_uncertain blocks, the dewarped page,
the page's OCR language, config grouping params). Lists every pair that differs.

usage: owner_probe.py <job_dir> <json_out>
Pre-registration: docs/data/geom_thin_prereg_20261021.md (G3).
"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, r"M:\claud_projects\bookscan")
from pipeline import figure_grouping as FG  # noqa: E402
from pipeline import stage06_uncertainty as S6  # noqa: E402
from pipeline import stage04_layout as S4  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from tools.gate1_harness import find_tesseract  # noqa: E402

job, out = Path(sys.argv[1]), Path(sys.argv[2])
cfg = S4.load_config(Path(r"M:\claud_projects\bookscan\config.yaml"))
gp = dict((cfg.get("reconstruct", {}) or {}).get("grouping") or {})
tess = find_tesseract(cfg)
rows, n_pairs = [], {"off": 0, "on": 0}
for pd in sorted(p for p in job.iterdir() if (p / "06_uncertain" / "resolved.json").exists()):
    res = S6.UncertaintyResult.model_validate_json(
        (pd / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
    lang = S7._ocr_language(pd)
    for rp in res.pages:
        img = cv2.imread(str(pd / "03_dewarp" / rp.name), cv2.IMREAD_COLOR)
        views = FG.views_from_blocks(rp.blocks)
        arms = {}
        for name, v in (("off", 0.0), ("on", 0.04)):
            g = FG.group_figures(views, page_h=rp.height, page_w=rp.width, lang=lang,
                                 page_bgr=img, tess_bin=tess,
                                 params={**gp, "geom_min_fig_frac": v})
            arms[name] = g
            n_pairs[name] += len(g.pairs)
        if (arms["off"].pairs != arms["on"].pairs
                or arms["off"].pair_source != arms["on"].pair_source):
            byk = {v.key: v for v in views}
            rows.append({
                "page": f"{pd.name}__{Path(rp.name).stem}", "page_wh": [rp.width, rp.height],
                "off": {c: [f, arms["off"].pair_source[c]] for c, f in arms["off"].pairs.items()},
                "on": {c: [f, arms["on"].pair_source[c]] for c, f in arms["on"].pairs.items()},
                "abstained_on": arms["on"].abstained,
                "blocks": {k: {"type": byk[k].btype,
                               "bbox": [byk[k].bbox.x, byk[k].bbox.y, byk[k].bbox.w, byk[k].bbox.h],
                               "text": byk[k].text[:80]}
                           for k in set(arms["off"].pairs) | set(arms["off"].pairs.values())
                           | set(arms["on"].pairs) | set(arms["on"].pairs.values())}})
            print(rows[-1]["page"], "off", rows[-1]["off"], "on", rows[-1]["on"], flush=True)
out.write_text(json.dumps({"n_pairs": n_pairs, "differs": rows}, indent=1,
                          ensure_ascii=False), encoding="utf-8")
print("pairs", n_pairs, "subpages differing", len(rows))
