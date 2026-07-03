"""Shared image ingest / orientation normalization.

ONE helper, imported by BOTH the pipeline (Stage 00 ingest) and the Gate 1
harness, so they feed Tesseract identically-oriented pixels. It lives in
``tools/`` on purpose: the dependency may flow ``pipeline -> tools`` and
``harness -> tools``, but NEVER ``harness -> pipeline`` (the harness documents
itself as independent of ``pipeline/`` so it stays a forever-valid regression
check — see ``tools/gate1_harness.py``).

Why this exists (the bug it fixes): the testset JPEGs carry EXIF
orientation=6, but the stored buffer is already an upright LANDSCAPE spread —
the tag is misleading. ``cv2.imread`` (OpenCV 5) applies EXIF and hands back a
sideways/portrait buffer; ``IMREAD_IGNORE_ORIENTATION`` hands back the upright
landscape one. So the harness (applies EXIF) and the pipeline (ignores it) were
feeding Tesseract differently-oriented images → divergent word boxes and
reading order even at equal WER.

Fix, and the invariant every downstream stage may now assume: **after this
helper, pixels are UPRIGHT and any EXIF orientation is baked in and stripped.**
IMREAD flags stop mattering downstream.

How upright is decided (EXIF is not trusted for rotation, because it is wrong
here): PIL ``exif_transpose`` first (this bakes/strips EXIF and, unlike a 90°
detector, is the only thing that can undo the mirror/flip orientations 2/4/5/7),
then **Tesseract OSD** (``--psm 0``) as the source of truth for the 0/90/180/270
rotation. OSD reliably calls the landscape spread upright regardless of the
buffer it is handed (verified on the testset). If OSD is unavailable or its
confidence is below ``min_conf``, we keep the exif_transpose result and record a
warning rather than trust a shaky 90° guess (rotating a correct page sideways is
worse than doing nothing).

Not gold-plated: the testset is all upright-landscape two-page spreads, so the
180° and single-page-portrait branches are exercised only by unit tests /
synthetic rotations, not real captures. Documented, not hidden.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Below this OSD "Orientation confidence" we do not trust the 90°-step call and
# fall back to the exif_transpose result. Observed on the testset spreads:
# ~13-14. A low floor rejects only genuinely garbage OSD (near-textless pages)
# while accepting every real detection. Tune when a low-text capture appears.
DEFAULT_MIN_OSD_CONF = 2.0

# cv2 exact (interpolation-free) rotations, keyed by clockwise degrees. OSD's
# "Rotate: N" is the clockwise rotation that makes the page upright.
_CW_ROTATE = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


@dataclass
class OrientInfo:
    """Provenance of the orientation decision (goes into Stage 00 meta.json)."""

    exif_orientation: int | None = None   # original EXIF tag (1..8), if any
    osd_rotate: int | None = None         # deg CW OSD recommends on the transposed buffer
    osd_conf: float | None = None
    applied_rotate: int = 0               # deg CW actually applied (0/90/180/270)
    method: str = "osd"                   # osd | osd_low_conf | osd_unavailable | exif_only
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Tesseract OSD
# --------------------------------------------------------------------------


def _parse_osd(stdout: str) -> tuple[int | None, float | None]:
    """Pull (rotate_degrees_cw, orientation_confidence) out of OSD stdout."""
    rotate: int | None = None
    conf: float | None = None
    for line in stdout.splitlines():
        if line.startswith("Rotate:"):
            try:
                rotate = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("Orientation confidence:"):
            try:
                conf = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return rotate, conf


def osd_rotation(
    bgr: np.ndarray, binary: str | None, tessdata_dir: str | None,
) -> tuple[int | None, float | None]:
    """Run Tesseract OSD on a BGR array; return (rotate_cw_deg, confidence).

    Returns (None, None) if Tesseract/OSD is unavailable or errors — the caller
    degrades gracefully. Never raises on a Tesseract failure.
    """
    if not binary or not Path(binary).exists():
        return None, None
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "osd.png"
        cv2.imwrite(str(img_path), bgr)
        cmd = [binary, str(img_path), "stdout", "--psm", "0"]
        if tessdata_dir and Path(tessdata_dir).exists():
            cmd += ["--tessdata-dir", tessdata_dir]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return None, None
        if proc.returncode != 0:
            return None, None
        return _parse_osd(proc.stdout)


def _rotate_cw(bgr: np.ndarray, deg: int) -> np.ndarray:
    deg %= 360
    if deg == 0:
        return bgr
    return cv2.rotate(bgr, _CW_ROTATE[deg])


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------


def orient_upright(
    bgr: np.ndarray,
    binary: str | None,
    tessdata_dir: str | None,
    min_conf: float = DEFAULT_MIN_OSD_CONF,
    exif_orientation: int | None = None,
) -> tuple[np.ndarray, OrientInfo]:
    """Rotate a BGR array to upright using Tesseract OSD.

    ``exif_orientation`` is only carried through into the returned info for
    provenance (the EXIF transpose itself happens in ``load_upright_bgr``). This
    array entry point assumes EXIF flips are already baked in.
    """
    info = OrientInfo(exif_orientation=exif_orientation)
    rotate, conf = osd_rotation(bgr, binary, tessdata_dir)
    info.osd_rotate, info.osd_conf = rotate, conf

    if rotate is None:
        info.method = "osd_unavailable"
        info.warnings.append(
            "Tesseract OSD unavailable (missing binary/osd.traineddata or it "
            "errored); left orientation as-is after EXIF transpose."
        )
        return bgr, info
    if conf is not None and conf < min_conf:
        info.method = "osd_low_conf"
        info.warnings.append(
            f"OSD confidence {conf:.2f} < {min_conf}; not trusting the "
            f"{rotate}deg call, left as-is after EXIF transpose."
        )
        return bgr, info

    out = _rotate_cw(bgr, rotate)
    info.applied_rotate = rotate % 360
    return out, info


def load_upright_bgr(
    path: str | Path,
    binary: str | None,
    tessdata_dir: str | None,
    min_conf: float = DEFAULT_MIN_OSD_CONF,
) -> tuple[np.ndarray, OrientInfo]:
    """Load an image file → upright BGR array + orientation provenance.

    PIL ``exif_transpose`` bakes/strips the EXIF orientation (and is the only
    step that can undo mirror/flip tags), then OSD fixes the 0/90/180/270
    rotation. This is the single ingest path for the pipeline AND the harness.
    """
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        exif_tag = im.getexif().get(0x0112)  # 274 = Orientation
        upright = ImageOps.exif_transpose(im).convert("RGB")
        rgb = np.asarray(upright)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return orient_upright(
        bgr, binary, tessdata_dir, min_conf=min_conf,
        exif_orientation=int(exif_tag) if exif_tag else None,
    )
