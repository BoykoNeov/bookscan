"""Stage 01 — fuse.

Turns the ingested frames for one spread into a single best ``anchor.png`` that
Stage 02 (split) consumes. Two jobs, per CLAUDE.md:

  1. **Pick the sharpest** full-spread frame (handheld bursts give several near
     duplicates; the sharpest wins — sharpness comes from Stage 00's manifest,
     no re-measure).
  2. **Stitch multi-zoom close-ups** onto that anchor: a close-up is a higher
     resolution photo of part of the spread; we locate it on the anchor by
     feature matching (ORB + RANSAC homography) and blend it in so that region
     gets its detail back.

Three-artifact contract (CLAUDE.md): ``01_fuse/anchor.png`` + ``fuse.json``
(which frame became the anchor, each close-up's match result) + ``meta.json`` +
``debug/01_fuse.png`` (anchor with the stitched regions outlined).

Input: reads ONLY ``00_ingest/ingest.json`` + ``00_ingest/frame_NN.png``.

Reality check on validation: the current testset is one full-spread frame per
capture, so the ONLY path exercised on real photos is the degenerate
single-frame one (anchor = that frame). The multi-zoom stitch is exercised by
synthetic unit tests (``pipeline/tests/test_stage01_fuse.py``) — there are no
real zoomset_* captures yet (a Gate-1-spec item never shot). Marked v0.1; real
multi-zoom validation is deferred to when the Android app produces close-ups.

Usage:
    python -m pipeline.stage01_fuse jobs/<job>/<page>/ [--debug]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from pydantic import BaseModel, Field

from pipeline.page_model import StageMeta

STAGE = "stage01_fuse"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # A frame counts as a full-spread candidate (eligible to be the sharpest
    # anchor) if its area >= this fraction of the largest frame's area. Smaller
    # frames are treated as close-ups to stitch.
    "fullspread_area_frac": 0.70,
    # ORB stitch quality gates. A close-up is only blended in if the homography
    # has at least this many RANSAC inliers and a sane (non-degenerate) scale.
    "orb_features": 4000,
    "ratio_test": 0.75,
    "min_inliers": 25,
    "feather_px": 40.0,     # blend feather width at the warped close-up border
}


class StitchResult(BaseModel):
    name: str
    matched: bool
    inliers: int = 0
    note: str = ""


class FuseResult(BaseModel):
    """Contents of ``01_fuse/fuse.json``."""

    n_frames: int
    anchor_source: str          # frame_NN.png chosen as the base
    method: str                 # single | sharpest | sharpest+stitch
    fullspread_frames: list[str] = Field(default_factory=list)
    closeups: list[StitchResult] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update(cfg.get("fuse", {}) or {})
    return params


# --------------------------------------------------------------------------
# Frame roles
# --------------------------------------------------------------------------


def partition_frames(frames: list[dict], area_frac: float
                     ) -> tuple[int, list[int], list[int]]:
    """Split frames into (base_idx, fullspread_idxs, closeup_idxs).

    Base = the SHARPEST among the full-spread-sized frames (area >= area_frac of
    the max). Everything smaller is a close-up to stitch. With one frame this
    trivially returns (0, [0], []).
    """
    areas = [f["width"] * f["height"] for f in frames]
    max_area = max(areas)
    fullspread = [i for i, a in enumerate(areas) if a >= area_frac * max_area]
    closeups = [i for i in range(len(frames)) if i not in fullspread]
    # sharpest full-spread frame is the base
    base_idx = max(fullspread, key=lambda i: frames[i].get("sharpness", 0.0))
    return base_idx, fullspread, closeups


# --------------------------------------------------------------------------
# Stitch (ORB + RANSAC homography + feathered blend)
# --------------------------------------------------------------------------


def stitch_closeup(base: np.ndarray, closeup: np.ndarray, p: dict
                   ) -> tuple[np.ndarray | None, int, str]:
    """Locate ``closeup`` on ``base`` and blend it in at full base resolution.

    Returns (blended_base_or_None, inliers, note). None means the close-up was
    not confidently located and the base is left unchanged.
    """
    gb = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    gc = cv2.cvtColor(closeup, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=int(p["orb_features"]))
    kb, db = orb.detectAndCompute(gb, None)
    kc, dc = orb.detectAndCompute(gc, None)
    if db is None or dc is None or len(kc) < 4 or len(kb) < 4:
        return None, 0, "too few features"

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(dc, db, k=2)  # query = close-up, train = base
    good = [m for m, n in (pair for pair in knn if len(pair) == 2)
            if m.distance < p["ratio_test"] * n.distance]
    if len(good) < p["min_inliers"]:
        return None, len(good), f"only {len(good)} good matches"

    src = np.float32([kc[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        return None, 0, "no homography"
    inliers = int(mask.sum()) if mask is not None else 0
    if inliers < p["min_inliers"]:
        return None, inliers, f"only {inliers} inliers"
    # Sanity: reject degenerate/flipped warps (non-positive or extreme scale).
    det = float(np.linalg.det(H[:2, :2]))
    if not (0.05 < abs(det) < 20.0) or det <= 0:
        return None, inliers, f"degenerate homography (det={det:.3f})"

    bh, bw = base.shape[:2]
    warped = cv2.warpPerspective(closeup, H, (bw, bh))
    wmask = cv2.warpPerspective(
        np.full(closeup.shape[:2], 255, np.uint8), H, (bw, bh))
    # Feather the border so the higher-res patch blends without a hard seam.
    dist = cv2.distanceTransform((wmask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    alpha = np.clip(dist / max(1.0, p["feather_px"]), 0.0, 1.0)[..., None]
    blended = (base * (1.0 - alpha) + warped * alpha).astype(np.uint8)
    return blended, inliers, "ok"


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, debug: bool = False) -> FuseResult:
    t0 = time.perf_counter()
    params = resolve_params(cfg)
    warnings: list[str] = []

    ingest_json = page_dir / "00_ingest" / "ingest.json"
    if not ingest_json.exists():
        raise FileNotFoundError(
            f"missing {ingest_json} — Stage 01 reads Stage 00's output. Run "
            f"stage00_ingest on this page first."
        )
    manifest = json.loads(ingest_json.read_text(encoding="utf-8"))
    frames = manifest.get("frames", [])
    if not frames:
        raise RuntimeError(f"no frames in {ingest_json}; nothing to fuse.")

    ingest_dir = page_dir / "00_ingest"

    def load(i: int) -> np.ndarray:
        img = cv2.imread(str(ingest_dir / frames[i]["name"]), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"unreadable frame: {frames[i]['name']}")
        return img

    base_idx, fullspread, closeups = partition_frames(
        frames, float(params["fullspread_area_frac"]))
    base = load(base_idx)

    stitch_results: list[StitchResult] = []
    t_stitch = time.perf_counter()
    n_stitched = 0
    for i in closeups:
        cu = load(i)
        blended, inliers, note = stitch_closeup(base, cu, params)
        ok = blended is not None
        if ok:
            base = blended
            n_stitched += 1
        else:
            warnings.append(f"close-up {frames[i]['name']} not stitched: {note}")
        stitch_results.append(StitchResult(
            name=frames[i]["name"], matched=ok, inliers=inliers, note=note))
    stitch_ms = (time.perf_counter() - t_stitch) * 1000.0

    if len(frames) == 1:
        method = "single"
    elif n_stitched > 0:
        method = "sharpest+stitch"
    else:
        method = "sharpest"

    # Artifacts.
    out_dir = page_dir / "01_fuse"
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "anchor.png"), base)

    result = FuseResult(
        n_frames=len(frames), anchor_source=frames[base_idx]["name"],
        method=method,
        fullspread_frames=[frames[i]["name"] for i in fullspread],
        closeups=stitch_results,
    )
    (out_dir / "fuse.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    # Debug overlay: anchor with a banner (+ stitched-region outlines if any).
    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "01_fuse.png"), _overlay(base, result))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={k: params[k] for k in DEFAULTS},
        timings_ms={"stitch": round(stitch_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "v0.1: multi-zoom stitch is unvalidated on real captures (testset "
            "has one full-spread frame per page); only the single-frame anchor "
            "path is exercised on real photos. ECC sub-pixel refine is a "
            "follow-up.",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return result


def _overlay(anchor: np.ndarray, result: FuseResult) -> np.ndarray:
    canvas = anchor.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    n_ok = sum(1 for c in result.closeups if c.matched)
    label = (f"fuse: {result.n_frames} frame(s)  anchor={result.anchor_source}  "
             f"method={result.method}  stitched={n_ok}/{len(result.closeups)}")
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 90), (40, 40, 40), -1)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (255, 200, 0), 3)
    return canvas


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 01 — fuse / pick anchor")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, debug=args.debug)
    print(f"{args.page_dir}: {result.n_frames} frame(s) -> anchor "
          f"{result.anchor_source} ({result.method})")
    for c in result.closeups:
        print(f"  close-up {c.name}: {'stitched' if c.matched else 'skipped'} "
              f"({c.inliers} inliers, {c.note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
