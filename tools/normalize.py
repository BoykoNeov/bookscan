"""Shared image ingest / orientation normalization.

ONE helper, imported by BOTH the pipeline (Stage 00 ingest) and the Gate 1
harness, so they feed Tesseract identically-oriented pixels. It lives in
``tools/`` on purpose: the dependency may flow ``pipeline -> tools`` and
``harness -> tools``, but NEVER ``harness -> pipeline`` (the harness documents
itself as independent of ``pipeline/`` so it stays a forever-valid regression
check — see ``tools/gate1_harness.py``).

Why this exists (the bug it fixes): this project's phone captures carry EXIF
orientation 6/8, but the stored buffer is *already* an upright LANDSCAPE spread —
the tag is misleading (a gyro-confused flat down-shot). All 15 testset spreads
share this (14×6, 1×8); see ``testset/gt/orientation.json``. Blindly honouring
the tag (PIL ``exif_transpose`` / ``cv2.imread``'s default) rotates the correct
landscape into a sideways portrait buffer.

**Orientation is a confidence-gated priority cascade** (see
``docs/notes/2026-07-18-orientation-policy-options.md``). Each layer wins only
when confident; the EXIF *rotation* is distrusted and never re-applied as a
fallback (that is the historical bug), while the EXIF *mirror* component is still
honoured. Priority, highest first:

  1. explicit capture hint (Android app / manifest) — pluggable slot, empty today
  2. text-baseline geometric detector — pluggable slot, stub today
  3. Tesseract OSD (``--psm 0``) — the working source of truth for rotation
  4. EXIF: **mirror** baked at load (orientations 2/4/5/7); pure-rotation tags
     (1/3/6/8) are NOT applied — we keep the raw pixel orientation instead
  5. landscape prior — a book spread must be landscape; used to FLAG (not force)
     a portrait result so a genuine mis-orientation stays visible

Fix, and the invariant every downstream stage may assume: **after this helper,
pixels are UPRIGHT** (mirror baked/stripped; rotation resolved by the cascade).
IMREAD flags stop mattering downstream.

Why this is no-regression on the existing testset: for an orientation-6 spread
with confident OSD, the old path was ``exif_transpose`` (raw +90 CW) then OSD
undoing it (−90) = the raw landscape buffer; the cascade returns that same raw
landscape buffer directly. Identical final pixels → identical WER. Only the
OSD-can't-decide case changes — from a wrong sideways buffer to the raw upright
one (the ``de_*`` figure-heavy fixtures, where OSD confidence is ~0.04–1.46).

Not gold-plated: layers 1 (capture hint) and 2 (text-baseline) are declared
slots the cascade skips until their inputs exist — the Android orientation stamp
(Gate 5) and a geometric detector measured on the ``de_*`` fixtures. The 180°
branch still relies on OSD (a distrusted pure-rotation EXIF tag cannot supply it,
and the landscape prior cannot see it). Documented, not hidden.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Below this OSD "Orientation confidence" we do not trust the 90°-step call and
# keep the raw pixel orientation. Observed on the testset spreads: ~13-14. A low
# floor rejects only genuinely garbage OSD (near-textless / figure-heavy pages,
# e.g. the de_* fixtures at ~0.04-1.46) while accepting every real detection.
DEFAULT_MIN_OSD_CONF = 2.0

# EXIF orientations whose transform includes a horizontal mirror. These are rare
# (scanner / front-camera), NOT the flat-book spurious-rotation-tag case, so we
# honour EXIF fully for them (bake mirror + rotation) and let OSD refine rotation.
_EXIF_MIRRORED = frozenset({2, 4, 5, 7})

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
    exif_mirror_baked: bool = False       # True iff a mirror tag (2/4/5/7) was applied at load
    osd_rotate: int | None = None         # deg CW OSD recommends on the loaded buffer
    osd_conf: float | None = None
    applied_rotate: int = 0               # deg CW actually applied (0/90/180/270)
    method: str = "osd"                   # capture_hint | text_baseline | osd | osd_low_conf | osd_unavailable
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


# Text-baseline detector confidence below which its call is ignored. Unused while
# the detector is a stub; wired so the cascade layer is a drop-in slot.
TEXT_BASELINE_MIN_CONF = 1.0


def text_baseline_rotation(bgr: np.ndarray) -> tuple[int | None, float | None]:
    """Cascade layer 2 (STUB): geometric text-line orientation.

    Intended to catch the 90° axis on figure-heavy pages where OSD starves for
    text (the de_* failure mode) via projection-profile / line-structure. Returns
    (None, None) today so the cascade falls through to OSD; filled in and measured
    on the de_* fixtures later. See docs/notes/2026-07-18-orientation-policy-options.md.
    """
    return None, None


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
    hint_rotate: int | None = None,
) -> tuple[np.ndarray, OrientInfo]:
    """Resolve ``bgr`` to upright via the priority cascade (mirror already baked).

    Operates on an already-loaded buffer, so it runs cascade layers 1 (capture
    hint), 2 (text-baseline), 3 (OSD) and 5 (landscape prior). The EXIF layer (4)
    happens in ``load_upright_bgr`` at file-load time; a raw-decode / array caller
    (Stage 00 RAW path) has no EXIF and simply skips it. ``exif_orientation`` is
    carried through for provenance only.
    """
    info = OrientInfo(exif_orientation=exif_orientation)

    # Layer 1 — explicit capture hint (device ground truth). Empty slot today.
    if hint_rotate is not None:
        info.method = "capture_hint"
        info.applied_rotate = hint_rotate % 360
        return _rotate_cw(bgr, info.applied_rotate), info

    # Layer 2 — text-baseline geometric detector. Stub today (returns None).
    tb_rotate, tb_conf = text_baseline_rotation(bgr)
    if tb_rotate is not None and (tb_conf is None or tb_conf >= TEXT_BASELINE_MIN_CONF):
        info.method = "text_baseline"
        info.applied_rotate = tb_rotate % 360
        return _rotate_cw(bgr, info.applied_rotate), info

    # Layer 3 — Tesseract OSD (the working rotation source of truth).
    rotate, conf = osd_rotation(bgr, binary, tessdata_dir)
    info.osd_rotate, info.osd_conf = rotate, conf
    if rotate is None:
        info.method = "osd_unavailable"
        info.warnings.append(
            "Tesseract OSD unavailable (missing binary/osd.traineddata or it "
            "errored); kept the raw pixel orientation (EXIF rotation is distrusted "
            "and NOT applied — see tools/normalize)."
        )
        out = bgr
    elif conf is not None and conf < min_conf:
        info.method = "osd_low_conf"
        info.warnings.append(
            f"OSD confidence {conf:.2f} < {min_conf}; did not trust the {rotate}deg "
            f"call and kept the raw pixel orientation (EXIF rotation distrusted)."
        )
        out = bgr
    else:
        info.method = "osd"
        info.applied_rotate = rotate % 360
        out = _rotate_cw(bgr, info.applied_rotate)

    # Layer 5 — landscape prior. A book spread must be landscape. We cannot know
    # the correct direction to force, so FLAG (not rotate) a portrait result so a
    # genuine mis-orientation stays visible in the stage warnings.
    h, w = out.shape[:2]
    if h > w:
        info.warnings.append(
            "result is PORTRAIT, but a book spread should be landscape — "
            "orientation may be wrong (OSD weak + EXIF rotation distrusted). "
            "A capture-side orientation hint or text-baseline detector would resolve it."
        )
    return out, info


def load_upright_bgr(
    path: str | Path,
    binary: str | None,
    tessdata_dir: str | None,
    min_conf: float = DEFAULT_MIN_OSD_CONF,
    hint_rotate: int | None = None,
) -> tuple[np.ndarray, OrientInfo]:
    """Load an image file → upright BGR array + orientation provenance.

    EXIF layer of the cascade: a **mirror** orientation (2/4/5/7 — rare, scanner /
    front-cam) is baked via ``exif_transpose`` and OSD then refines its rotation;
    a **pure-rotation** tag (1/3/6/8 — including this project's spurious 6/8) is
    NOT applied — the raw pixel buffer is used and the cascade (OSD etc.) owns
    rotation. Then delegates to ``orient_upright`` for layers 1–3 + 5.
    """
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        exif_tag = im.getexif().get(0x0112)  # 274 = Orientation
        orientation = int(exif_tag) if exif_tag else 1
        mirror = orientation in _EXIF_MIRRORED
        base = ImageOps.exif_transpose(im) if mirror else im
        rgb = np.asarray(base.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    out, info = orient_upright(
        bgr, binary, tessdata_dir, min_conf=min_conf,
        exif_orientation=(orientation if exif_tag else None),
        hint_rotate=hint_rotate,
    )
    info.exif_mirror_baked = mirror
    return out, info
