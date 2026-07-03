"""Stage 03 — dewarp.

Flattens page curvature on each half-page produced by Stage 02 (split), so the
downstream OCR sees straight text lines. Reads ONLY ``02_split/split.json`` (the
pages manifest) + the images it names (``left.png`` / ``right.png`` /
``single.png``); writes a dewarped image PER PAGE at FULL resolution into
``03_dewarp/`` (same names), plus ``dewarp.json`` + ``meta.json`` +
``debug/03_dewarp.png``. Full resolution is a contract requirement: Stage 06
patch-mode crops word images from Stage 03's output, NOT a downscaled copy
(CLAUDE.md).

Two arms behind one seam (CLAUDE.md ``models.dewarp: uvdoc``):

  * **UVDoc** (default target) — a neural grid-based unwarper. Loaded lazily,
    VRAM released on CLI exit. NOT wired yet (see ``UVDocDewarper`` /
    task #3); ``--method auto`` falls back to classical until it is.
  * **Classical text-line rectification** (always-available fallback) — no
    torch. The distortion that survives Stage 02's split is the binding CURL
    near the gutter (the outer/top/bottom page edges are real, but the gutter
    edge is an artificial cut, so full page-quad perspective rectification would
    be wrong here). So we straighten the CURVED TEXT BASELINES instead: detect
    lines, fit a smooth vertical displacement field V(x,y) that flattens each
    baseline to its own median row, and ``remap`` the full-res page by it. Only
    the vertical curl is corrected (horizontal foreshortening near the gutter is
    left — it barely hurts OCR); recorded in meta.warnings.

Honesty rule (advisor): a "fallback" that is a silent passthrough is worse than
none — it would distort a before/after WER comparison by looking like a real
arm. So when there is no usable curl signal (too few baselines, or the fit's max
displacement is below ``min_disp_px``) we emit the page UNCHANGED but FLAG it in
meta.warnings + dewarp.json (method="identity"), never silently.

Usage:
    python -m pipeline.stage03_dewarp jobs/<job>/<page>/ [--method auto|uvdoc|classical] [--debug]
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

STAGE = "stage03_dewarp"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Classical text-line rectification knobs. These are GEOMETRY heuristics tuned to
# the handheld book photos (moderate gutter curl), not the adaptive CONFIDENCE
# thresholds CLAUDE.md forbids hard-coding (those live in Stage 06).
DEFAULTS = {
    "adaptive_block": 31,          # adaptiveThreshold blockSize for the ink mask (odd)
    "adaptive_C": 15,
    "n_strips": 36,                # vertical strips for the band-projection tracer
    "smooth_frac": 0.004,          # per-strip projection smoothing sigma (frac of H)
    "peak_prominence_frac": 0.12,  # line-peak prominence, frac of the strip's peak ink
    "min_line_spacing_frac": 0.012,# min vertical gap between line peaks (frac of H)
    "strip_min_ink_frac": 0.0015,  # skip near-empty strips (margins/fabric) below this
    "link_y_tol_frac": 0.010,      # peak-to-track link tolerance (frac of H)
    "link_gap_strips": 3,          # close a track after this many strips with no match
    "min_span_frac": 0.40,         # a baseline must span >= this frac of strips
    "min_lines": 6,                # fewer baselines than this -> can't fit a warp (identity)
    "min_disp_px": 3.0,            # max fitted displacement below this -> page is flat (identity)
    "max_disp_clamp_frac": 0.06,   # clamp |displacement| to this frac of H (reject a wild fit)
}


# --------------------------------------------------------------------------
# Output schema (stage-local for v1; promote into page_model when Stage 04
# consumes it, in its own schema commit — see CLAUDE.md).
# --------------------------------------------------------------------------


class PageDewarp(BaseModel):
    """Per-subpage dewarp outcome."""

    name: str                 # left.png | right.png | single.png
    method: str               # uvdoc | classical | identity
    n_lines: int = 0          # baselines detected (classical)
    max_disp_px: float = 0.0  # peak vertical correction applied
    fit_rms_px: float = 0.0   # RMS residual of the displacement fit (see note)
    applied: bool = False     # False == emitted unchanged (identity)
    note: str = ""


class DewarpResult(BaseModel):
    """Contents of ``03_dewarp/dewarp.json``."""

    source: str = "02_split/split.json"
    engine: str                       # requested method (auto|uvdoc|classical)
    pages: list[PageDewarp] = Field(default_factory=list)


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
    params.update(cfg.get("dewarp", {}) or {})
    return params


# --------------------------------------------------------------------------
# Classical text-line rectification
# --------------------------------------------------------------------------


def _ink_mask(gray: np.ndarray, p: dict) -> np.ndarray:
    """Local-threshold ink mask (text=255), immune to the smooth curl shading."""
    block = int(p["adaptive_block"])
    block = block if block % 2 == 1 else block + 1
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=block, C=int(p["adaptive_C"]),
    )


def detect_baselines(gray: np.ndarray, p: dict
                     ) -> tuple[list[tuple[np.ndarray, np.ndarray]], np.ndarray]:
    """Trace curved text-line baselines by band-projection + peak linking.

    Connected-component line-finding fails on the very pages we care about:
    justified text with wide word gaps and curl-induced slope fragments a line
    into pieces a horizontal dilation can't rejoin. Instead we cut the page into
    narrow VERTICAL STRIPS — within a strip a line is locally near-horizontal and
    the ink of all its words sums together — take each strip's horizontal ink
    projection, find the line peaks, then LINK peaks across strips left-to-right
    into baseline curves. Immune to word gaps and slope by construction.

    Returns (baselines, ink_mask); each baseline is (xs, ys) strip samples.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    h, w = gray.shape
    ink = _ink_mask(gray, p)
    inkf = (ink > 0).astype(np.float32)

    n_strips = max(4, int(p["n_strips"]))
    strip_w = max(1, w // n_strips)
    sigma = max(1.0, h * float(p["smooth_frac"]))
    min_dist = max(2, int(h * float(p["min_line_spacing_frac"])))
    strip_ink_floor = float(p["strip_min_ink_frac"]) * h  # min mean-ink*h per strip

    strip_x: list[int] = []
    strip_peaks: list[np.ndarray] = []
    for s in range(0, w - strip_w + 1, strip_w):
        proj = inkf[:, s:s + strip_w].sum(axis=1)
        if proj.sum() < strip_ink_floor:            # margin / fabric strip
            strip_x.append(s + strip_w // 2)
            strip_peaks.append(np.empty(0, int))
            continue
        proj = gaussian_filter1d(proj, sigma)
        prom = float(p["peak_prominence_frac"]) * float(proj.max())
        peaks, _ = find_peaks(proj, distance=min_dist, prominence=max(prom, 1e-6))
        strip_x.append(s + strip_w // 2)
        strip_peaks.append(peaks)

    # Greedy left-to-right linking. Each active track ends at (x, y); a strip's
    # peak joins the nearest track within y_tol, else starts a new track. Tracks
    # idle for link_gap_strips are closed (a figure/gap broke the line).
    y_tol = float(p["link_y_tol_frac"]) * h
    gap_max = int(p["link_gap_strips"])
    active: list[dict] = []     # {"xs":[], "ys":[], "last_y":float, "idle":int}
    done: list[dict] = []
    for xc, peaks in zip(strip_x, strip_peaks):
        used = set()
        for tr in active:
            tr["idle"] += 1
        for py in sorted(peaks):
            best, best_d = None, y_tol
            for tr in active:
                if id(tr) in used:
                    continue
                d = abs(tr["last_y"] - py)
                if d < best_d:
                    best, best_d = tr, d
            if best is None:
                active.append({"xs": [xc], "ys": [float(py)],
                               "last_y": float(py), "idle": 0})
            else:
                best["xs"].append(xc); best["ys"].append(float(py))
                best["last_y"] = float(py); best["idle"] = 0
                used.add(id(best))
        still, closed = [], []
        for tr in active:
            (still if tr["idle"] <= gap_max else closed).append(tr)
        done.extend(closed)
        active = still
    done.extend(active)

    min_span = max(3, int(p["min_span_frac"] * n_strips))
    baselines = [
        (np.asarray(tr["xs"], float), np.asarray(tr["ys"], float))
        for tr in done if len(tr["xs"]) >= min_span
    ]
    return baselines, ink


def _basis(xn: np.ndarray, yn: np.ndarray) -> np.ndarray:
    """Polynomial basis for the vertical displacement field V(x,y).

    Cubic in x captures the S/parabola of a curled line; linear/quadratic in y
    lets the curl magnitude change down the page (stronger toward the gutter's
    far end). Coordinates are normalized to [0,1] for conditioning.
    """
    return np.stack(
        [np.ones_like(xn), xn, xn ** 2, xn ** 3,
         yn, yn * xn, yn * xn ** 2, yn ** 2],
        axis=1,
    )


def fit_displacement(baselines: list[tuple[np.ndarray, np.ndarray]],
                     w: int, h: int) -> tuple[np.ndarray, float, float]:
    """Least-squares fit of V(x,y) = (line's median row) - y over all baseline
    samples. V is how far a source pixel moves DOWN to flatten its line.

    Returns (coeffs, max_abs_target_disp_px, fit_rms_px). fit_rms_px is a free
    fit-quality diagnostic, recorded (never thresholded — that would overfit the
    tiny testset). NOTE: measured on the testset it did NOT separate the figure
    page from the clean text pages (all ~4-8px) — because the figure-page harm is
    EXTRAPOLATION of the field into figure regions that have NO baseline samples,
    which a residual over the sampled baselines cannot see. The signal that would
    flag figure pages is baseline COVERAGE (large unsupported vertical gaps), a
    Stage-04 (layout) concern, not this residual."""
    xs = np.concatenate([b[0] for b in baselines])
    ys = np.concatenate([b[1] for b in baselines])
    dv = np.concatenate([np.median(b[1]) - b[1] for b in baselines])
    A = _basis(xs / w, ys / h)
    coeffs, *_ = np.linalg.lstsq(A, dv, rcond=None)
    max_disp = float(np.abs(dv).max()) if dv.size else 0.0
    rms = float(np.sqrt(np.mean((A @ coeffs - dv) ** 2))) if dv.size else 0.0
    return coeffs, max_disp, rms


def apply_dewarp(bgr: np.ndarray, coeffs: np.ndarray, clamp_px: float
                 ) -> np.ndarray:
    """Remap the full-res page by the fitted vertical field.

    cv2.remap needs the SOURCE coord for each output pixel. Output row obeys
    y_out = y_src + V(x, y_src); for the small, smooth V here the one-step
    inverse y_src ≈ y_out - V(x, y_out) is sub-pixel accurate. x is unchanged
    (vertical-only rectification)."""
    h, w = bgr.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    V = (_basis((xs / w).ravel(), (ys / h).ravel()) @ coeffs).reshape(h, w)
    V = np.clip(V, -clamp_px, clamp_px).astype(np.float32)
    map_y = (ys - V).astype(np.float32)
    return cv2.remap(bgr, xs, map_y, interpolation=cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def dewarp_classical(bgr: np.ndarray, p: dict
                     ) -> tuple[np.ndarray, PageDewarp, list]:
    """Classical arm. Returns (out_bgr, PageDewarp, baselines_for_debug).

    Emits the page UNCHANGED but FLAGGED (method="identity") when there is no
    usable curl signal — never a silent passthrough (advisor)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h, w = gray.shape
    baselines, _ = detect_baselines(gray, p)

    if len(baselines) < int(p["min_lines"]):
        pd = PageDewarp(
            name="", method="identity", n_lines=len(baselines), applied=False,
            note=(f"only {len(baselines)} baselines (< {p['min_lines']}); too "
                  f"little text structure to fit a warp — emitted unchanged"),
        )
        return bgr, pd, baselines

    coeffs, max_disp, rms = fit_displacement(baselines, w, h)
    if max_disp < float(p["min_disp_px"]):
        pd = PageDewarp(
            name="", method="identity", n_lines=len(baselines),
            max_disp_px=round(max_disp, 2), fit_rms_px=round(rms, 2),
            applied=False,
            note=(f"max baseline displacement {max_disp:.1f}px < "
                  f"{p['min_disp_px']}px — page effectively flat, emitted "
                  f"unchanged"),
        )
        return bgr, pd, baselines

    clamp = float(p["max_disp_clamp_frac"]) * h
    out = apply_dewarp(bgr, coeffs, clamp)
    pd = PageDewarp(
        name="", method="classical", n_lines=len(baselines),
        max_disp_px=round(max_disp, 2), fit_rms_px=round(rms, 2), applied=True,
        note=(f"vertical text-line rectification, {len(baselines)} baselines, "
              f"peak {max_disp:.1f}px (clamped ±{clamp:.0f}px), fit RMS "
              f"{rms:.1f}px; horizontal foreshortening not corrected"),
    )
    return out, pd, baselines


# --------------------------------------------------------------------------
# UVDoc arm (seam — wired in task #3)
# --------------------------------------------------------------------------


class UVDocDewarper:
    """Lazy UVDoc loader kept as the model seam so wiring is drop-in.

    Contract for when it lands (task #3): ``load()`` imports torch, builds the
    net, loads the checkpoint onto CUDA; ``dewarp()`` predicts a low-res sampling
    grid, UPSCALES the grid and ``remap``s the FULL-RES page (never unwarp a
    downscaled copy — Stage 06 crops from this output); ``close()`` drops the
    model and calls ``torch.cuda.empty_cache()`` so VRAM is freed on CLI exit
    (CLAUDE.md lazy-load / release-on-exit). Use as a context manager.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None

    def load(self) -> None:
        raise NotImplementedError(
            "UVDoc not wired yet (task #3: vendor model + checkpoint, verify "
            "full-res grid remap). Use --method classical or auto."
        )

    def dewarp(self, bgr: np.ndarray) -> tuple[np.ndarray, PageDewarp]:
        raise NotImplementedError

    def close(self) -> None:
        self.model = None

    def __enter__(self) -> "UVDocDewarper":
        self.load()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --------------------------------------------------------------------------
# Per-page dispatch (method selection + fallback)
# --------------------------------------------------------------------------


def dewarp_page(bgr: np.ndarray, method: str, cfg: dict, p: dict,
                warnings: list[str]) -> tuple[np.ndarray, PageDewarp, list]:
    """Dewarp one page by ``method`` (auto|uvdoc|classical), falling back to
    classical if UVDoc is requested but unavailable. Returns (out, PageDewarp,
    baselines_for_debug)."""
    if method in ("uvdoc", "auto"):
        try:
            with UVDocDewarper(cfg) as uv:
                out, pd = uv.dewarp(bgr)
            return out, pd, []
        except NotImplementedError as e:
            if method == "uvdoc":
                # Explicit request we can't honor — surface loudly, still fall
                # back so the pipeline keeps producing an artifact.
                warnings.append(f"UVDoc requested but unavailable ({e}); "
                                f"fell back to classical.")
            else:
                warnings.append("UVDoc not wired; used classical (auto).")
    return dewarp_classical(bgr, p)


# --------------------------------------------------------------------------
# Debug overlay
# --------------------------------------------------------------------------


def _page_panel(bgr_in: np.ndarray, bgr_out: np.ndarray, pd: PageDewarp,
                baselines: list, panel_w: int = 900) -> np.ndarray:
    """before|after panel for one page: input with detected baselines (green)
    and their flattened target rows (red) on the left, dewarped output on the
    right, with a status banner."""
    vis = bgr_in.copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    for xs, ys in baselines:
        pts = np.stack([xs, ys], axis=1).astype(np.int32)
        cv2.polylines(vis, [pts], False, (0, 220, 0), 2)
        ty = int(np.median(ys))
        cv2.line(vis, (int(xs.min()), ty), (int(xs.max()), ty), (0, 0, 230), 1)

    def _fit(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        s = panel_w / w
        return cv2.resize(img, (panel_w, max(1, int(h * s))))

    left, right = _fit(vis), _fit(bgr_out)
    hh = max(left.shape[0], right.shape[0])
    canvas = np.full((hh + 60, panel_w * 2 + 10, 3), 30, np.uint8)
    canvas[60:60 + left.shape[0], :panel_w] = left
    canvas[60:60 + right.shape[0], panel_w + 10:] = right
    label = (f"{pd.name}: method={pd.method} lines={pd.n_lines} "
             f"disp={pd.max_disp_px}px applied={pd.applied}")
    cv2.putText(canvas, label, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (255, 220, 0), 2)
    return canvas


def build_debug(panels: list[np.ndarray]) -> np.ndarray:
    """Stack per-page before/after panels vertically into one overlay."""
    if not panels:
        return np.zeros((100, 100, 3), np.uint8)
    w = max(pn.shape[1] for pn in panels)
    padded = [cv2.copyMakeBorder(pn, 0, 8, 0, w - pn.shape[1], cv2.BORDER_CONSTANT,
                                 value=(30, 30, 30)) for pn in panels]
    return np.vstack(padded)


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, method: str = "auto", debug: bool = False
        ) -> DewarpResult:
    t0 = time.perf_counter()
    p = resolve_params(cfg)
    warnings: list[str] = []

    split_json = page_dir / "02_split" / "split.json"
    if not split_json.exists():
        raise FileNotFoundError(
            f"missing {split_json} — Stage 03 reads Stage 02's pages manifest. "
            f"Run stage02_split on this page first."
        )
    manifest = json.loads(split_json.read_text(encoding="utf-8"))
    pages = manifest.get("pages", [])
    if not pages:
        raise RuntimeError(f"no pages in {split_json}; nothing to dewarp.")

    split_dir = page_dir / "02_split"
    out_dir = page_dir / "03_dewarp"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale images so a re-run's folder reflects ONLY this run (contract).
    for stale in ("left.png", "right.png", "single.png"):
        (out_dir / stale).unlink(missing_ok=True)

    results: list[PageDewarp] = []
    panels: list[np.ndarray] = []
    t_dew = time.perf_counter()
    for page in pages:
        name = page["name"]
        src = split_dir / name
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"unreadable subpage image: {src}")
        out, pd, baselines = dewarp_page(img, method, cfg, p, warnings)
        pd.name = name
        cv2.imwrite(str(out_dir / name), out)
        results.append(pd)
        panels.append(_page_panel(img, out, pd, baselines))
        if not pd.applied:
            warnings.append(f"{name}: {pd.note}")
    dew_ms = (time.perf_counter() - t_dew) * 1000.0

    result = DewarpResult(engine=method, pages=results)
    (out_dir / "dewarp.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "03_dewarp.png"), build_debug(panels))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={k: p[k] for k in DEFAULTS},
        timings_ms={"dewarp": round(dew_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "v0.1: UVDoc arm not wired (task #3) — classical text-line "
            "rectification only. Corrects vertical curl; horizontal "
            "foreshortening near the gutter is left. Identity emitted (flagged) "
            "on flat/low-text pages.",
            "FIGURE PAGES: a full-page warp (classical OR UVDoc) bends figures "
            "as well as text. Since CLAUDE.md crops figures from THIS dewarped "
            "image, a warp fit to body-text baselines can distort coin/photo "
            "crops on figure/multi-block pages (WER, being text-only, does not "
            "see this). The real fix is layout-aware dewarp — Stage 04 feeding "
            "per-region masks so figures are left unwarped — not a better engine. "
            "(fit_rms_px did NOT separate figure from text pages on the testset; "
            "baseline coverage would — see fit_displacement.)",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 03 — dewarp")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--method", choices=("auto", "uvdoc", "classical"),
                    default="auto", help="dewarp arm (auto tries uvdoc, "
                    "falls back to classical)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, method=args.method, debug=args.debug)
    print(f"{args.page_dir}: dewarp engine={result.engine}")
    for pd in result.pages:
        print(f"  {pd.name}: {pd.method} (lines={pd.n_lines}, "
              f"disp={pd.max_disp_px}px, applied={pd.applied})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
