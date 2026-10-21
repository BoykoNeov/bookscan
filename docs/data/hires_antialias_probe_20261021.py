"""P7 follow-up: does figure_hires' per-source likeness gate punish sharp sources?

Pre-registration: docs/data/hires_antialias_prereg_20261021.md (committed before
this ran). Replays Stage 07's hires search over every FIGURE block of a job, with
a full gate trace per candidate, and scores each candidate that reaches the NCC
gate twice: as the pipeline does today (bilinear pull-back, no prefilter) and
with a Gaussian prefilter of sigma = 0.5*sqrt(s^2 - 1) source px. Then composes
each figure under both arms and saves the changed ones for the by-eye check.

    python docs/data/hires_antialias_probe_20261021.py <out_dir> <job_dir> [<job_dir> ...]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402


def sigma_for(s: float) -> float:
    return 0.5 * math.sqrt(s * s - 1.0) if s > 1.0 else 0.0


def pull_back(img, H, w, h, sigma):
    src = cv2.GaussianBlur(img, (0, 0), sigma) if sigma > 0 else img
    Hi = np.linalg.inv(H)
    back = cv2.warpPerspective(src, Hi, (w, h))
    fh, fw = img.shape[:2]
    m = cv2.warpPerspective(np.full((fh, fw), 255, np.uint8), Hi, (w, h))
    return back, m


def trace_candidates(crop, frames, params):
    """candidates() with every gate recorded; returns (trace, cands_now, cands_aa)."""
    h, w = crop.shape[:2]
    trace, now, aa = [], [], []
    if h * w < int(params["min_figure_px"]):
        return [{"stop": "min_figure_px"}], now, aa
    for idx in frames:
        row = {"frame": idx.name}
        trace.append(row)
        got = FH._match(crop, idx, params)
        if got is None:
            row["stop"] = "no match"
            continue
        H, inliers, good = got
        row.update(inliers=inliers, good=good)
        if inliers < int(params["min_inliers"]) or not FH._sane(H):
            row["stop"] = "inliers/sane"
            continue
        img = idx.image
        if img is None:
            row["stop"] = "decode"
            continue
        fh, fw = img.shape[:2]
        cov = FH._coverage(H, w, h, fw, fh)
        row["coverage"] = round(cov, 3)
        if cov < float(params["min_piece"]):
            row["stop"] = "min_piece"
            continue
        s = FH.local_scale(H, w / 2.0, h / 2.0)
        row["scale"] = round(s, 3)
        if not (float(params["min_scale"]) <= s <= float(params["max_scale"])):
            row["stop"] = "scale"
            continue
        sig = sigma_for(s)
        b0, m0 = pull_back(img, H, w, h, 0.0)
        b1, m1 = pull_back(img, H, w, h, sig)
        n_now, n_aa = FH._ncc(crop, b0, m0), FH._ncc(crop, b1, m1)
        row.update(sigma=round(sig, 3), ncc_now=round(n_now, 4),
                   ncc_aa=round(n_aa, 4), stop="ncc_gate")
        thr = float(params["min_ncc"])
        if n_now >= thr:
            now.append(FH.Candidate(H, idx, FH.HiResSource(idx.name, s, inliers,
                                                          good, n_now, cov)))
            # shift control: H o T(d), crop displaced by 5 % / 10 % of short side
            shifts = []
            for frac in (0.05, 0.10):
                d = frac * min(w, h)
                for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)):
                    T = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], np.float64)
                    Hs = H @ T
                    a0, k0 = pull_back(img, Hs, w, h, 0.0)
                    a1, k1 = pull_back(img, Hs, w, h, sig)
                    shifts.append({"frac": frac, "dx": round(dx, 1), "dy": round(dy, 1),
                                   "ncc_now": round(FH._ncc(crop, a0, k0), 4),
                                   "ncc_aa": round(FH._ncc(crop, a1, k1), 4)})
            row["shifts"] = shifts
        if n_aa >= thr:
            aa.append(FH.Candidate(H, idx, FH.HiResSource(idx.name, s, inliers,
                                                         good, n_aa, cov)))
    return trace, now, aa


def subpage_image(job: Path, page_id: str):
    pdir, stem = page_id.split("__")
    return job / pdir, cv2.imread(str(job / pdir / "03_dewarp" / f"{stem}.png"),
                                  cv2.IMREAD_COLOR)


def main(out: Path, jobs: list[Path]) -> int:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    params = FH.resolve_params(cfg)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for job in jobs:
        doc = json.loads((job / "document.json").read_text(encoding="utf-8"))
        by_dir: dict[str, list] = {}
        for p in doc["pages"]:
            by_dir.setdefault(p["page_id"].split("__")[0], []).append(p)
        for pdir_name, pages in sorted(by_dir.items()):
            frames = S7._capture_frames(job / pdir_name, params)
            for page in pages:
                pdir, img = subpage_image(job, page["page_id"])
                if img is None:
                    continue
                H_, W_ = img.shape[:2]
                for b in page["blocks"]:
                    if b["type"] != "figure" or b.get("deleted"):
                        continue
                    bb = b["bbox"]
                    x0, y0 = max(0, bb["x"]), max(0, bb["y"])
                    x1, y1 = min(W_, bb["x"] + bb["w"]), min(H_, bb["y"] + bb["h"])
                    if x1 - x0 < 2 or y1 - y0 < 2:
                        continue
                    crop = img[y0:y1, x0:x1]
                    trace, now, aa = trace_candidates(crop, frames, params)
                    r_now = FH.compose(crop, now, params) if now else None
                    r_aa = FH.compose(crop, aa, params) if aa else None
                    u_now = [s.frame for s in r_now[1]] if r_now else []
                    u_aa = [s.frame for s in r_aa[1]] if r_aa else []
                    row = {"job": job.name, "page": page["page_id"], "block": b["id"],
                           "crop_wh": [x1 - x0, y1 - y0],
                           "shipped_asset": bool(b.get("figure_asset")),
                           "upgraded_now": r_now is not None, "used_now": u_now,
                           "upgraded_aa": r_aa is not None, "used_aa": u_aa,
                           "trace": trace}
                    rows.append(row)
                    if u_now != u_aa:
                        tag = f"{job.name}__{page['page_id']}__b{b['id']:03d}"
                        cv2.imwrite(str(out / f"{tag}__crop.png"), crop)
                        if r_now:
                            cv2.imwrite(str(out / f"{tag}__now.png"), r_now[0])
                        if r_aa:
                            cv2.imwrite(str(out / f"{tag}__aa.png"), r_aa[0])
                    print(job.name[-8:], page["page_id"], b["id"],
                          "now", u_now, "aa", u_aa, flush=True)
            for f in frames:
                f.release()
    (out / "hires_antialias_20261021.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), [Path(a) for a in sys.argv[2:]]))
