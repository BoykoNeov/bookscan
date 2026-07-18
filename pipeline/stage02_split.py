"""Stage 02 — gutter split.

Splits a two-page book spread into ``left.png`` / ``right.png`` (or emits a
single ``single.png`` when no confident gutter is found). This is the first
concrete stage; it establishes the three-artifact contract every later stage
copies (see CLAUDE.md):

  * output image(s) + ``split.json`` (the stage's data: subpage manifest +
    crop geometry in ORIGINAL spread coordinates),
  * ``meta.json`` (StageMeta: version, params, timings, warnings),
  * a debug overlay in ``debug/02_split.png`` so a bad cut is visible at a glance.

Input contract: reads ONLY ``01_fuse/anchor.png`` from the page directory. To
test before Stage 00/01 exist, seed a page folder by copying a testset spread
to ``<page>/01_fuse/anchor.png`` (see ``tools`` / the eval harness).

Detector rationale (grounded in the actual handheld photos, not assumed):
the gutter is a WIDE bright whitespace valley between the two text blocks with
only a soft binding shadow — not a hard dark band. The page also sits on darker
fabric, so the far left/right columns are dark background. We therefore (a)
measure per-column INK (adaptive-threshold text mask, which is immune to the
smooth binding-shadow gradient), and (b) search only the CENTRAL band so the
dark fabric margins can't masquerade as the gutter. The cut is biased to sit in
the middle of the whitespace with a small overlap margin: losing text is the
only real failure; carrying a sliver of the other page's margin is harmless
(dewarp/layout re-crop downstream).

Known v1 limitations (recorded in meta.warnings): a single VERTICAL cut assumes
a near-vertical gutter; strong tilt/curvature is Stage 03's (dewarp) job. The
``single.png`` branch is untested — the current testset is all two-page spreads.

Usage:
    python -m pipeline.stage02_split jobs/<job_id>/<page>/ [--debug]
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

from pipeline.page_model import BBox, StageMeta

STAGE = "stage02_split"
VERSION = "0.2.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Detector defaults (overridable via config.yaml `split:`). These are tuned
# against the testset spreads; they are geometry heuristics, not the adaptive
# CONFIDENCE thresholds that CLAUDE.md forbids hard-coding (those live in
# Stage 06). Central search band keeps dark fabric margins out of the running.
DEFAULTS = {
    "search_lo": 0.30,     # gutter search window, fraction of width
    "search_hi": 0.70,
    "smooth_frac": 0.02,   # column-profile moving-average width, fraction of W
    # Confident gutter iff valley ink < ratio * page ink. Tuned on the 13
    # correctly-oriented flat testset spreads: real gutters score 0.11-0.47, so
    # 0.55 clears them all with margin. NOTE: the single-page side of this cut is
    # UNVALIDATED — the current testset has no single-page capture; a body-text
    # single page should score ~1.0, but a page with a central figure could dip.
    # Revisit when a single-page test image is appended (testset follow-up).
    "valley_ratio": 0.55,
    "margin_frac": 0.010,  # cut overlap each side, fraction of W (never lose text)
    "adaptive_block": 31,  # adaptiveThreshold blockSize (odd)
    "adaptive_C": 15,
    # --- Layer 2: spine-pinch cue (curved/tightly-held real spreads) ---------
    # On a curved handheld spread the inner text runs right to the binding, so
    # the ink whitespace valley (Layer 1) washes out (Finding 2: de_01/de_02 and
    # the Taleb prose spread score 0.85/0.67/0.91 — all above valley_ratio). But
    # the physical page is PINCHED at the spine: photographed from above, an open
    # book's paper outline dips down on top and rises up on the bottom at the
    # binding, so the per-column vertical EXTENT of the bright page region has a
    # minimum right at the gutter. That pinch is content-independent (it survives
    # figure-heavy pages where the ink valley and shadow both fail) and, crucially,
    # is created by the very curvature that kills Layer 1 — the two cues are
    # complementary, not competing. Calibrated on the testset: flat spreads pinch
    # <=0.09, the three curved spreads pinch 0.14-0.18 -> gate at 0.11 sits in the
    # gap. This layer only runs when Layer 1 is NOT confident, so all 13 flat
    # spreads keep their exact ink result (non-regression by construction).
    "pinch_smooth_frac": 0.04,   # extent-profile smoothing (2x the ink smoothing)
    "pinch_min_depth": 0.11,     # confident pinch iff extent dip >= this fraction
    "corroborate_frac": 0.03,    # a 2nd cue "agrees" if within this frac of W
    "pinch_margin_frac": 0.020,  # wider overlap for pinch (curved) cuts vs 0.010
}


# --------------------------------------------------------------------------
# Output schema (stage-local for v1; formalize into page_model when Stage 03
# consumes it, in its own schema commit — see CLAUDE.md).
# --------------------------------------------------------------------------


class SubPage(BaseModel):
    """One page carved out of the spread, with its crop box in spread coords."""

    name: str            # left.png | right.png | single.png
    box: BBox            # crop rectangle in ORIGINAL spread pixel coordinates


class SplitResult(BaseModel):
    """Contents of ``02_split/split.json`` — the stage's inter-stage data."""

    source: str
    width: int
    height: int
    gutter_x: int | None            # cut column in spread coords, None if single
    confident: bool
    method: str = "none"            # which layer resolved it: ink | pinch | none
    pages: list[SubPage] = Field(default_factory=list)
    # diagnostics (why the confidence decision went the way it did)
    valley: float = 0.0             # Layer 1: min ink in central band
    page_ref: float = 0.0           # Layer 1: typical text-column ink
    ratio: float = 0.0              # Layer 1: valley / page_ref (< valley_ratio => split)
    pinch_depth: float = 0.0        # Layer 2: extent dip at spine (>= pinch_min_depth => split)
    pinch_x: int | None = None      # Layer 2: spine column from the page-pinch cue
    shadow_x: int | None = None     # binding-shadow luminance-valley column (corroboration only)
    corroborated: bool = False      # for a pinch split: did shadow OR ink agree within tol?


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
    params.update(cfg.get("split", {}) or {})
    return params


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def ink_profile(gray: np.ndarray, block: int, c: int) -> np.ndarray:
    """Per-column count of text-ink pixels via adaptive threshold.

    Adaptive (local) thresholding turns dark text strokes into ink=1 while
    ignoring the smooth binding-shadow gradient and even lighting. Fabric
    background outside the central band produces some ink noise, but the gutter
    search never looks there.
    """
    block = block if block % 2 == 1 else block + 1
    ink = cv2.adaptiveThreshold(
        gray, 1, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=block, C=c,
    )
    return ink.sum(axis=0).astype(np.float64)


def smooth(profile: np.ndarray, width: int) -> np.ndarray:
    width = max(1, width)
    kernel = np.ones(width) / width
    return np.convolve(profile, kernel, mode="same")


def extent_profile(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Per-column vertical extent (last-first bright row) of the page region.

    Otsu-separates the bright page from the dark capture background, then for
    each column measures how tall the bright run is. An open book photographed
    from above is pinched at the binding, so this profile dips at the spine — a
    content-independent gutter cue that survives figure-heavy pages where the
    ink-whitespace valley and the binding shadow both fail.

    ASSUMES a dark background (page brighter than surroundings) — true for every
    current fixture (books on dark fabric). Recorded in meta.warnings; on a bright
    background Otsu inverts and this cue is meaningless, but Layer 1 (ink) and the
    depth gate keep it from firing wrongly there.
    """
    h, w = gray.shape
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    page = gray > thr
    any_bright = page.any(axis=0)
    first = np.argmax(page, axis=0)
    last = h - 1 - np.argmax(page[::-1], axis=0)
    ext = np.where(any_bright, last - first, 0).astype(np.float64)
    return ext, float(thr)


def detect_gutter(gray: np.ndarray, p: dict) -> tuple[int | None, dict]:
    """Layered gutter resolver. Returns (gutter_x, diagnostics).

    Priority cascade (mirrors the Stage 00 orientation resolver):
      Layer 1 — ink whitespace valley: confident on FLAT open spreads with a
                real gutter gap. When it fires, it wins outright, so all 13 flat
                testset spreads keep byte-identical behaviour (non-regression).
      Layer 2 — spine pinch: only consulted when Layer 1 is not confident. Rescues
                CURVED handheld spreads (Finding 2) whose inner text fills the
                gutter and washes the ink valley out.
      else    — no confident gutter -> None (emit single.png).

    diagnostics carries every layer's numbers for the overlay + meta, plus the
    resolving ``method``.
    """
    h, w = gray.shape
    x0, x1 = int(w * p["search_lo"]), int(w * p["search_hi"])
    x1 = max(x1, x0 + 1)
    band = slice(x0, x1)

    # --- Layer 1: ink whitespace valley --------------------------------------
    prof = ink_profile(gray, int(p["adaptive_block"]), int(p["adaptive_C"]))
    cols = smooth(prof, int(w * p["smooth_frac"]))
    ink_x = x0 + int(np.argmin(cols[band]))
    valley = float(cols[ink_x])
    # Page ink reference: typical text-column density, ignoring near-white
    # margin columns so the valley is compared to real text, not to whitespace.
    floor = 0.05 * float(cols.max()) if cols.max() > 0 else 0.0
    texty = cols[cols > floor]
    page_ref = float(np.median(texty)) if texty.size else 0.0
    ratio = valley / page_ref if page_ref > 0 else 1.0
    ink_confident = page_ref > 0 and ratio < p["valley_ratio"]

    # --- Layer 2: spine pinch (page vertical-extent minimum) -----------------
    ext = smooth(extent_profile(gray)[0], int(w * p["pinch_smooth_frac"]))
    pinch_x = x0 + int(np.argmin(ext[band]))
    pinch_val = float(ext[pinch_x])
    # Compare the dip to the page height at the OUTER fifths of the band (away
    # from the spine), not the band median — the median already includes the dip.
    fifth = max(1, (x1 - x0) // 5)
    edge_ref = float(np.median(
        np.concatenate([ext[x0:x0 + fifth], ext[x1 - fifth:x1]])))
    pinch_depth = (1.0 - pinch_val / edge_ref) if edge_ref > 0 else 0.0
    pinch_confident = pinch_depth >= p["pinch_min_depth"]

    # --- Binding-shadow luminance valley (corroboration only, never decides) --
    lum = smooth(gray.mean(axis=0).astype(np.float64), int(w * p["smooth_frac"]))
    shadow_x = x0 + int(np.argmin(lum[band]))

    # A pinch split is more trustworthy when a second, independent cue lands on
    # the same column. On prose the shadow/ink corroborate within ~30px; on
    # figure-heavy pages (de_01) shadow drifts onto a dark photo, so pinch stands
    # alone — we still split, but flag it (advisor: require agreement where we
    # can get it, don't gate the whole cue on it).
    tol = int(w * p["corroborate_frac"])
    corroborated = (abs(shadow_x - pinch_x) <= tol) or (abs(ink_x - pinch_x) <= tol)

    diag = {
        "cols": cols, "window": (x0, x1), "valley": valley,
        "page_ref": page_ref, "ratio": ratio,
        "ext": ext, "pinch_x": pinch_x, "pinch_depth": pinch_depth,
        "shadow_x": shadow_x, "corroborated": corroborated,
    }

    if ink_confident:
        diag["method"] = "ink"
        return ink_x, diag
    if pinch_confident:
        diag["method"] = "pinch"
        return pinch_x, diag
    diag["method"] = "none"
    return None, diag


# --------------------------------------------------------------------------
# Cutting + artifacts
# --------------------------------------------------------------------------


def cut_pages(image: np.ndarray, gutter_x: int | None, margin: int
              ) -> list[tuple[str, np.ndarray, BBox]]:
    """Carve the spread into subpages. Cut biased into whitespace with overlap
    so neither half loses text (advisor: losing text is the only real failure).
    """
    h, w = image.shape[:2]
    if gutter_x is None:
        return [("single.png", image, BBox(x=0, y=0, w=w, h=h))]

    lx2 = min(w, gutter_x + margin)
    rx1 = max(0, gutter_x - margin)
    left = image[:, :lx2]
    right = image[:, rx1:]
    return [
        ("left.png", left, BBox(x=0, y=0, w=lx2, h=h)),
        ("right.png", right, BBox(x=rx1, y=0, w=w - rx1, h=h)),
    ]


def draw_overlay(image: np.ndarray, gutter_x: int | None, diag: dict) -> np.ndarray:
    """Spread with the gutter line, search window, and column ink-profile drawn
    so a human can see at a glance whether the cut landed in the whitespace.
    """
    canvas = image.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    h, w = canvas.shape[:2]

    cols = diag["cols"]
    x0, x1 = diag["window"]
    # search window (faint blue verticals)
    for x in (x0, x1):
        cv2.line(canvas, (x, 0), (x, h), (200, 120, 0), 2)

    def _curve(prof: np.ndarray, color: tuple, amp_frac: float) -> None:
        if prof.max() <= prof.min():
            return
        norm = (prof - prof.min()) / (prof.max() - prof.min())
        base, amp = h - 10, int(h * amp_frac)
        pts = [(x, int(base - norm[x] * amp)) for x in range(0, w, max(1, w // 1000))]
        for a, b in zip(pts, pts[1:]):
            cv2.line(canvas, a, b, color, 1)

    # ink whitespace profile (orange, bottom third) and page-extent pinch
    # profile (green) so a human can see which cue carried the decision.
    _curve(cols, (0, 160, 255), 0.30)
    _curve(diag["ext"], (0, 200, 0), 0.30)

    method = diag.get("method", "none")
    # corroborating cue markers (thin): shadow = cyan, pinch candidate = green
    cv2.line(canvas, (diag["shadow_x"], 0), (diag["shadow_x"], h), (255, 200, 0), 1)
    if method != "pinch":
        cv2.line(canvas, (diag["pinch_x"], 0), (diag["pinch_x"], h), (0, 200, 0), 1)

    if gutter_x is not None:
        cv2.line(canvas, (gutter_x, 0), (gutter_x, h), (0, 0, 230), 3)
        if method == "pinch":
            label = (f"gutter x={gutter_x} via PINCH depth={diag['pinch_depth']:.2f}"
                     f" corrob={diag['corroborated']} (ink ratio={diag['ratio']:.2f})")
        else:
            label = f"gutter x={gutter_x} via INK ratio={diag['ratio']:.2f}"
        color = (0, 0, 230)
    else:
        label = (f"NO GUTTER  ink={diag['ratio']:.2f} pinch={diag['pinch_depth']:.2f}"
                 f" (single page)")
        color = (0, 200, 255)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    return canvas


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, debug: bool = False) -> SplitResult:
    t0 = time.perf_counter()
    params = resolve_params(cfg)
    warnings: list[str] = []

    src = page_dir / "01_fuse" / "anchor.png"
    if not src.exists():
        raise FileNotFoundError(
            f"missing {src} — Stage 02 reads 01_fuse/anchor.png. Seed it by "
            f"copying a spread there (Stage 00/01 not built yet)."
        )
    # IMREAD_IGNORE_ORIENTATION: never let cv2 apply the EXIF rotation here.
    # Orientation is Stage 00 (ingest)'s job; anchor.png is expected already
    # normalized to a readable LANDSCAPE spread (gutter vertical). We read the
    # raw buffer so a mis-normalized upstream shows up in the assertion below
    # instead of being silently rotated.
    image = cv2.imread(str(src), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise RuntimeError(f"unreadable image: {src}")
    h, w = image.shape[:2]

    # A two-page spread is always wider than tall. Portrait input means the
    # orientation was not normalized upstream — the vertical-gutter detector
    # would then be looking along the wrong axis. Fail loud (warn), don't
    # silently adapt (advisor): a dual-axis search would mask the ingest bug
    # and can mistake a horizontal paragraph gap for the gutter.
    if h > w:
        warnings.append(
            f"PORTRAIT input ({w}x{h}): a book spread must be landscape "
            f"(gutter vertical). Orientation not normalized upstream (Stage 00 "
            f"ingest); gutter detection along the vertical axis is unreliable."
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    t_detect = time.perf_counter()
    gutter_x, diag = detect_gutter(gray, params)
    detect_ms = (time.perf_counter() - t_detect) * 1000.0

    method = diag["method"]
    if gutter_x is None:
        warnings.append(
            f"no confident gutter (ink ratio={diag['ratio']:.2f} >= "
            f"{params['valley_ratio']}, pinch depth={diag['pinch_depth']:.2f} < "
            f"{params['pinch_min_depth']}); emitting single.png"
        )
    elif method == "pinch":
        # Layer-2 rescue: the ink valley was washed out (curved spread); the
        # spine came from the page-pinch cue. Wider overlap margin because a
        # curved gutter is not a perfectly vertical line — the extra buffer keeps
        # the straight cut from clipping text at the page's top/bottom.
        warnings.append(
            f"gutter from spine-pinch (Layer 2): ink ratio={diag['ratio']:.2f} "
            f"failed, pinch depth={diag['pinch_depth']:.2f}, corroborated="
            f"{diag['corroborated']}. Pinch cue assumes a DARK capture background "
            f"(Otsu page/background split)."
        )
        if not diag["corroborated"]:
            warnings.append(
                "pinch split is UNCORROBORATED (neither the binding-shadow nor "
                "the ink valley agree within tolerance) — lower confidence; "
                "check debug/02_split.png."
            )

    margin_frac = params["pinch_margin_frac"] if method == "pinch" else params["margin_frac"]
    margin = int(w * margin_frac)
    pieces = cut_pages(image, gutter_x, margin)

    # Write artifacts.
    out_dir = page_dir / "02_split"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear the other branch's stale images so a re-run's folder reflects ONLY
    # this run (stage contract). Otherwise flipping single<->split leaves a
    # phantom page for any downstream stage that globs instead of reading the
    # split.json pages manifest.
    for stale in ("left.png", "right.png", "single.png"):
        (out_dir / stale).unlink(missing_ok=True)
    subpages: list[SubPage] = []
    for name, img, box in pieces:
        cv2.imwrite(str(out_dir / name), img)
        subpages.append(SubPage(name=name, box=box))

    result = SplitResult(
        source="01_fuse/anchor.png", width=w, height=h,
        gutter_x=gutter_x, confident=gutter_x is not None, method=method,
        pages=subpages,
        valley=round(diag["valley"], 1), page_ref=round(diag["page_ref"], 1),
        ratio=round(diag["ratio"], 3),
        pinch_depth=round(diag["pinch_depth"], 3), pinch_x=int(diag["pinch_x"]),
        shadow_x=int(diag["shadow_x"]), corroborated=bool(diag["corroborated"]),
    )
    (out_dir / "split.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    # Debug overlay (always — the contract requires one per stage).
    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    overlay = draw_overlay(image, gutter_x, diag)
    cv2.imwrite(str(debug_dir / "02_split.png"), overlay)
    if debug:
        # extra intermediates: raw + smoothed column profile as CSV
        np.savetxt(out_dir / "col_profile.csv", diag["cols"], delimiter=",")

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={k: params[k] for k in DEFAULTS},
        timings_ms={"detect": round(detect_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "single vertical cut assumes a near-vertical gutter; residual "
            "tilt/curvature is Stage 03 (dewarp)'s job. single.png branch is "
            "still untested (no single-page fixture in the testset).",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8"
    )
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 02 — gutter split")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true",
                    help="also dump column profile CSV")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, debug=args.debug)
    names = ", ".join(p.name for p in result.pages)
    if result.gutter_x is not None and result.method == "pinch":
        print(f"{args.page_dir}: gutter x={result.gutter_x} via PINCH "
              f"(depth={result.pinch_depth}, corrob={result.corroborated}; "
              f"ink ratio={result.ratio}) -> {names}")
    elif result.gutter_x is not None:
        print(f"{args.page_dir}: gutter x={result.gutter_x} via INK "
              f"(ratio={result.ratio}) -> {names}")
    else:
        print(f"{args.page_dir}: no gutter (ink ratio={result.ratio}, "
              f"pinch depth={result.pinch_depth}) -> {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
