"""Is a picture upgrade sharper than the page crop? The pre-registered focus statistic.

Pre-registration: ``docs/data/figure_focus_prereg_20261112.md`` (hand-off item 5,
``docs/open_problems`` P7). The statistic, fixed there before any value exists on
the population:

    ratio = mean |Sobel gradient| of the upgrade  /  mean |Sobel gradient| of the page crop

on the luminance channel, both images brought to the page crop's size with area
interpolation (the upgrade is shrunk; the crop is untouched). Gate: an upgrade
ships only if ``ratio >= 1.0``. Not tuned on the labelled pictures.

    python -m tools.figure_focus_eval control jobs/<job>/   # instrument check; any job
    python -m tools.figure_focus_eval score  <labels.json>  # refuses unless labels complete

``control`` checks the instrument on a job that is NOT a labelled population: a
picture against itself must give exactly 1.0, and a copy blurred on purpose
(Gaussian sigma 2) must score below 1.0 against the original.
``score`` computes the ratio only for a job whose owner's verdicts are complete,
so the number cannot be looked at first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.figure_focus_labels import upgraded_pictures  # noqa: E402


def mean_gradient(bgr: np.ndarray) -> float:
    y = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(np.sqrt(gx * gx + gy * gy)))


def focus_ratio(upgrade: np.ndarray, crop: np.ndarray) -> float:
    """Pre-registered statistic. ``crop`` sets the size; ``upgrade`` is area-shrunk to it."""
    h, w = crop.shape[:2]
    up = upgrade if upgrade.shape[:2] == (h, w) else cv2.resize(
        upgrade, (w, h), interpolation=cv2.INTER_AREA)
    den = mean_gradient(crop)
    return mean_gradient(up) / den if den > 0 else float("nan")


def page_crop_and_upgrade(job_dir: Path, item: dict) -> tuple[np.ndarray, np.ndarray]:
    page = cv2.imread(str(job_dir / "document_assets" / f"{item['page_id']}.png"), cv2.IMREAD_COLOR)
    up = cv2.imread(str(job_dir / item["asset"]), cv2.IMREAD_COLOR)
    x, y, w, h = (item["bbox"][k] for k in ("x", "y", "w", "h"))
    return page[y:y + h, x:x + w].copy(), up


def cmd_control(job_dir: Path) -> int:
    items = upgraded_pictures(job_dir)
    rows, ok = [], True
    for it in items:
        crop, up = page_crop_and_upgrade(job_dir, it)
        self_r = focus_ratio(up, up)
        blur = cv2.GaussianBlur(up, (0, 0), 2.0)
        blur_r = focus_ratio(blur, up)
        good = self_r == 1.0 and blur_r < 1.0
        ok &= good
        rows.append({"page_id": it["page_id"], "block_id": it["block_id"],
                     "self": self_r, "blurred_sigma2_vs_self": round(blur_r, 4), "pass": good})
        print(f"  {it['page_id']} #{it['block_id']}: self {self_r:.4f}  blurred {blur_r:.4f}  "
              f"{'pass' if good else 'FAIL'}")
    print(f"control on {job_dir.name}: {'PASS' if ok else 'FAIL'} ({len(rows)} pictures)")
    print(json.dumps({"job": job_dir.name, "pass": ok, "rows": rows}, indent=1))
    return 0 if ok else 1


def cmd_score(labels_path: Path, jobs_root: Path) -> int:
    lab = json.loads(labels_path.read_text(encoding="utf-8"))
    if not lab.get("complete") or any(it.get("answer") is None for it in lab["items"]):
        raise SystemExit("labels are not complete; the statistic is not computed before "
                         "every verdict is in (pre-registration)")
    job_dir = jobs_root / lab["job"]
    rows = []
    for it in lab["items"]:
        crop, up = page_crop_and_upgrade(job_dir, it)
        r = focus_ratio(up, crop)
        rows.append({"page_id": it["page_id"], "block_id": it["block_id"],
                     "verdict": it["verdict"], "ratio": round(r, 4), "ships": r >= 1.0})
    told = [r for r in rows if r["verdict"] != "cannot_tell"]
    agree = sum((r["verdict"] == "upgrade_sharper") == r["ships"] for r in told)
    shipped_worse = [r for r in told if r["verdict"] == "crop_sharper" and r["ships"]]
    res = {
        "labels": str(labels_path), "n": len(rows), "n_told_apart": len(told),
        "agree": agree, "agreement": (agree / len(told)) if told else None,
        "shipped_but_owner_called_worse": shipped_worse,
        "pass": bool(told) and agree / len(told) >= 0.90 and not shipped_worse,
        "rows": rows,
    }
    print(json.dumps(res, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("control")
    c.add_argument("job_dir", type=Path)
    s = sub.add_parser("score")
    s.add_argument("labels", type=Path)
    s.add_argument("--jobs-root", type=Path, default=REPO / "jobs")
    a = ap.parse_args(argv)
    return cmd_control(a.job_dir) if a.cmd == "control" else cmd_score(a.labels, a.jobs_root)


if __name__ == "__main__":
    sys.exit(main())
