"""Stage 00 — ingest.

The pipeline's entry boundary: takes the raw capture(s) for ONE page/spread
(a single photo, or an anchor frame + multi-zoom close-ups) and normalizes each
to an **upright RGB PNG**, writing them plus a capture-metadata manifest into
``00_ingest/``. Everything downstream may then assume upright pixels with EXIF
already baked in and stripped (see ``tools/normalize.py`` for why that invariant
matters — the testset JPEGs carry a *misleading* EXIF orientation).

Three-artifact stage contract (CLAUDE.md), same as Stage 02:
  * ``00_ingest/frame_NN.png`` (upright RGB, one per source frame) +
    ``ingest.json`` (frame manifest: source name, size, orientation provenance,
    sharpness),
  * ``meta.json`` (StageMeta: version, params, timings, warnings),
  * ``debug/00_ingest.png`` (anchor frame with an orientation/sharpness banner
    so a wrong rotation is visible at a glance).

Orientation is decided by the SHARED helper ``tools.normalize`` (PIL
exif_transpose → Tesseract OSD), the same code the Gate 1 harness uses, so the
pipeline and the harness feed Tesseract identically-oriented pixels.

Input: reads raw capture files from ``--src`` (a file or a directory of frames);
if omitted, reads any images already sitting in ``<page_dir>/raw/``. Frames are
ordered by filename; ``frame_00`` is the anchor candidate. Sharpness
(variance-of-Laplacian) is recorded per frame so Stage 01 (fuse) can pick the
sharpest without re-reading pixels.

RAW decode (.dng/.cr2/.nef/...) needs ``rawpy``, which is not yet installed and
has no test image — the branch is present but guarded: it warns and skips rather
than crashing. JPEG/PNG/TIFF is the validated path.

Usage:
    python -m pipeline.stage00_ingest jobs/<job>/<page>/ --src testset/bg_01.jpg
    python -m pipeline.stage00_ingest jobs/<job>/<page>/            # reads <page>/raw/
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from pydantic import BaseModel, Field

from pipeline.page_model import StageMeta
from tools import normalize as N

STAGE = "stage00_ingest"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef"}

DEFAULTS = {
    # Below this OSD orientation confidence, keep the exif_transpose result
    # rather than trust a shaky 90-degree call (see tools/normalize.py).
    "min_osd_conf": N.DEFAULT_MIN_OSD_CONF,
}


# --------------------------------------------------------------------------
# Output schema (stage-local; formalize into page_model when a later stage
# consumes it, in its own schema commit — see CLAUDE.md).
# --------------------------------------------------------------------------


class IngestFrame(BaseModel):
    """One normalized capture frame + how it was oriented, for the manifest."""

    name: str                       # frame_00.png ...
    source: str                     # original filename
    width: int
    height: int
    sharpness: float                # variance of Laplacian (higher = sharper)
    exif_orientation: int | None = None
    osd_rotate: int | None = None
    osd_conf: float | None = None
    applied_rotate: int = 0
    orient_method: str = "osd"


class IngestResult(BaseModel):
    """Contents of ``00_ingest/ingest.json``."""

    source: str
    n_frames: int
    frames: list[IngestFrame] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_tesseract(cfg: dict) -> tuple[str | None, str | None]:
    """(binary, tessdata_dir) for OSD; relative tessdata resolves at repo root."""
    tcfg = cfg.get("tesseract", {}) or {}
    binary = tcfg.get("binary")
    if not (binary and Path(binary).exists()):
        binary = shutil.which("tesseract")
    raw = tcfg.get("tessdata_dir")
    tessdata = None
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = REPO_ROOT / p
        tessdata = str(p) if p.exists() else None
    return binary, tessdata


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update(cfg.get("ingest", {}) or {})
    return params


# --------------------------------------------------------------------------
# Source discovery + decode
# --------------------------------------------------------------------------


def gather_sources(page_dir: Path, src: Path | None) -> list[Path]:
    """Ordered list of raw capture files for this page."""
    if src is not None:
        if src.is_file():
            return [src]
        if src.is_dir():
            base = src
        else:
            raise FileNotFoundError(f"--src not found: {src}")
    else:
        base = page_dir / "raw"
        if not base.is_dir():
            raise FileNotFoundError(
                f"no --src given and no {base}/ to read. Point --src at a capture "
                f"file or a folder of frames."
            )
    files = [
        p for p in sorted(base.iterdir())
        if p.suffix.lower() in IMG_EXTS | RAW_EXTS
    ]
    if not files:
        raise FileNotFoundError(f"no image/raw files in {base}")
    return files


def sharpness(bgr: np.ndarray) -> float:
    """Variance of the Laplacian — the standard focus measure (higher=sharper).

    Recorded per frame so Stage 01 can pick the sharpest frame without redoing
    the read. Computed on grayscale.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, src: Path | None = None,
        debug: bool = False) -> IngestResult:
    t0 = time.perf_counter()
    params = resolve_params(cfg)
    binary, tessdata = resolve_tesseract(cfg)
    min_conf = float(params["min_osd_conf"])
    warnings: list[str] = []
    if binary is None:
        warnings.append(
            "Tesseract not found; orientation falls back to EXIF transpose only "
            "(no OSD rotation). Set tesseract.binary in config.yaml."
        )

    sources = gather_sources(page_dir, src)

    out_dir = page_dir / "00_ingest"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear any stale frames from a prior run so the folder reflects ONLY this
    # run (stage contract — a downstream glob must not see a phantom frame).
    for stale in out_dir.glob("frame_*.png"):
        stale.unlink(missing_ok=True)

    frames: list[IngestFrame] = []
    orient_ms = 0.0
    for i, sp in enumerate(sources):
        ext = sp.suffix.lower()
        if ext in RAW_EXTS:
            try:
                import rawpy  # noqa: F401
            except ImportError:
                warnings.append(
                    f"skipped RAW {sp.name}: rawpy not installed (Stage 00 RAW "
                    f"decode is deferred — see requirements.txt)."
                )
                continue
            # rawpy path (unvalidated: no RAW test image yet).
            import rawpy
            with rawpy.imread(str(sp)) as raw:
                rgb = raw.postprocess()
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            t_o = time.perf_counter()
            bgr, info = N.orient_upright(bgr, binary, tessdata, min_conf=min_conf)
            orient_ms += (time.perf_counter() - t_o) * 1000.0
        else:
            t_o = time.perf_counter()
            bgr, info = N.load_upright_bgr(sp, binary, tessdata, min_conf=min_conf)
            orient_ms += (time.perf_counter() - t_o) * 1000.0

        name = f"frame_{i:02d}.png"
        cv2.imwrite(str(out_dir / name), bgr)
        h, w = bgr.shape[:2]
        frames.append(IngestFrame(
            name=name, source=sp.name, width=w, height=h,
            sharpness=round(sharpness(bgr), 2),
            exif_orientation=info.exif_orientation, osd_rotate=info.osd_rotate,
            osd_conf=(round(info.osd_conf, 2) if info.osd_conf is not None else None),
            applied_rotate=info.applied_rotate, orient_method=info.method,
        ))
        warnings.extend(f"{name}: {msg}" for msg in info.warnings)

    if not frames:
        warnings.append("no frames ingested (all sources skipped/unreadable).")

    result = IngestResult(
        source=str(src) if src is not None else str(page_dir / "raw"),
        n_frames=len(frames), frames=frames,
    )
    (out_dir / "ingest.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    # Debug overlay: anchor frame (frame_00) with an orientation/sharpness banner.
    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    if frames:
        anchor = cv2.imread(str(out_dir / frames[0].name), cv2.IMREAD_COLOR)
        cv2.imwrite(str(debug_dir / "00_ingest.png"),
                    _overlay(anchor, frames))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={"min_osd_conf": min_conf},
        timings_ms={"orient": round(orient_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "orientation via shared tools.normalize (priority cascade: capture-hint"
            " / text-baseline [both stubs] -> OSD -> EXIF mirror-only, pure-rotation"
            " tag distrusted -> landscape prior); RAW decode deferred (rawpy absent);"
            " 180 branch still OSD-only; de_* fixtures guard the figure-heavy case.",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8"
    )
    return result


def _overlay(anchor: np.ndarray, frames: list[IngestFrame]) -> np.ndarray:
    canvas = anchor.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    f0 = frames[0]
    label = (f"ingest: {len(frames)} frame(s)  anchor rot={f0.applied_rotate} "
             f"conf={f0.osd_conf} sharp={f0.sharpness:.0f} ({f0.orient_method})")
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 90), (40, 40, 40), -1)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (0, 230, 0), 3)
    return canvas


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 00 — ingest / orient")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--src", type=Path, default=None,
                    help="capture file or folder of frames (default: <page>/raw/)")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, src=args.src, debug=args.debug)
    for f in result.frames:
        print(f"  {f.name} <- {f.source}: {f.width}x{f.height} "
              f"rot={f.applied_rotate} conf={f.osd_conf} sharp={f.sharpness}")
    print(f"{args.page_dir}: ingested {result.n_frames} frame(s) -> 00_ingest/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
