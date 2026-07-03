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
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Detector defaults (overridable via config.yaml `split:`). These are tuned
# against the testset spreads; they are geometry heuristics, not the adaptive
# CONFIDENCE thresholds that CLAUDE.md forbids hard-coding (those live in
# Stage 06). Central search band keeps dark fabric margins out of the running.
DEFAULTS = {
    "search_lo": 0.30,     # gutter search window, fraction of width
    "search_hi": 0.70,
    "smooth_frac": 0.02,   # column-profile moving-average width, fraction of W
    # Confident gutter iff valley ink < ratio * page ink. Tuned on the 9
    # correctly-oriented testset spreads: real gutters score 0.11-0.47, so 0.55
    # clears them all with margin. NOTE: the single-page side of this cut is
    # UNVALIDATED — the current testset has no single-page capture; a body-text
    # single page should score ~1.0, but a page with a central figure could dip.
    # Revisit when a single-page test image is appended (testset follow-up).
    "valley_ratio": 0.55,
    "margin_frac": 0.010,  # cut overlap each side, fraction of W (never lose text)
    "adaptive_block": 31,  # adaptiveThreshold blockSize (odd)
    "adaptive_C": 15,
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
    pages: list[SubPage] = Field(default_factory=list)
    # diagnostics (why the confidence decision went the way it did)
    valley: float = 0.0
    page_ref: float = 0.0
    ratio: float = 0.0


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


def detect_gutter(gray: np.ndarray, p: dict) -> tuple[int | None, dict]:
    """Find the gutter column, or None if there is no confident valley.

    Returns (gutter_x, diagnostics). diagnostics carries the smoothed profile
    and the numbers behind the confidence decision (for the overlay + meta).
    """
    h, w = gray.shape
    prof = ink_profile(gray, int(p["adaptive_block"]), int(p["adaptive_C"]))
    cols = smooth(prof, int(w * p["smooth_frac"]))

    x0, x1 = int(w * p["search_lo"]), int(w * p["search_hi"])
    x1 = max(x1, x0 + 1)
    gi = x0 + int(np.argmin(cols[x0:x1]))
    valley = float(cols[gi])

    # Page ink reference: typical text-column density, ignoring near-white
    # margin columns so the valley is compared to real text, not to whitespace.
    floor = 0.05 * float(cols.max()) if cols.max() > 0 else 0.0
    texty = cols[cols > floor]
    page_ref = float(np.median(texty)) if texty.size else 0.0

    ratio = valley / page_ref if page_ref > 0 else 1.0
    confident = page_ref > 0 and ratio < p["valley_ratio"]

    diag = {
        "cols": cols, "window": (x0, x1), "valley": valley,
        "page_ref": page_ref, "ratio": ratio,
    }
    return (gi if confident else None), diag


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

    # ink profile as a curve along the bottom third
    if cols.max() > 0:
        norm = cols / cols.max()
        base, amp = h - 10, int(h * 0.30)
        pts = [(x, int(base - norm[x] * amp)) for x in range(0, w, max(1, w // 1000))]
        for a, b in zip(pts, pts[1:]):
            cv2.line(canvas, a, b, (0, 160, 255), 1)

    if gutter_x is not None:
        cv2.line(canvas, (gutter_x, 0), (gutter_x, h), (0, 0, 230), 3)
        label = f"gutter x={gutter_x}  ratio={diag['ratio']:.2f}"
        color = (0, 0, 230)
    else:
        label = f"NO GUTTER  ratio={diag['ratio']:.2f} (single page)"
        color = (0, 200, 255)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 3)
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

    if gutter_x is None:
        warnings.append(
            f"no confident gutter (valley/page_ref={diag['ratio']:.2f} >= "
            f"{params['valley_ratio']}); emitting single.png"
        )

    margin = int(w * params["margin_frac"])
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
        gutter_x=gutter_x, confident=gutter_x is not None, pages=subpages,
        valley=round(diag["valley"], 1), page_ref=round(diag["page_ref"], 1),
        ratio=round(diag["ratio"], 3),
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
            "v1: single vertical cut assumes near-vertical gutter; tilt/curvature "
            "is Stage 03 (dewarp). single.png branch is untested on current testset.",
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
    if result.gutter_x is not None:
        print(f"{args.page_dir}: gutter x={result.gutter_x} "
              f"(ratio={result.ratio}) -> {names}")
    else:
        print(f"{args.page_dir}: no gutter (ratio={result.ratio}) -> {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
