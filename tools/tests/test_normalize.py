"""Unit tests for tools.normalize (shared orientation helper).

The pure logic (OSD parsing, exact rotations, the confidence fallback) is tested
without Tesseract. One integration test exercises real OSD but self-skips when
Tesseract/OSD is unavailable or not confident, so the suite stays green in a
bare CI. Run with pytest, or directly:
    python -m tools.tests.test_normalize
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np

from tools import normalize as N

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------
# Pure logic (no Tesseract)
# --------------------------------------------------------------------------


def test_parse_osd():
    sample = (
        "Page number: 0\n"
        "Orientation in degrees: 90\n"
        "Rotate: 270\n"
        "Orientation confidence: 13.63\n"
        "Script: Latin\n"
        "Script confidence: 4.09\n"
    )
    rotate, conf = N._parse_osd(sample)
    assert rotate == 270
    assert abs(conf - 13.63) < 1e-6


def test_parse_osd_missing_fields():
    rotate, conf = N._parse_osd("Warning. Invalid resolution 0 dpi.\n")
    assert rotate is None and conf is None


def test_rotate_cw_is_exact_and_roundtrips():
    # Non-square so a wrong axis would change the shape and fail.
    a = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    assert N._rotate_cw(a, 0).shape == a.shape
    assert N._rotate_cw(a, 90).shape == (3, 2, 3)
    assert N._rotate_cw(a, 180).shape == a.shape
    assert N._rotate_cw(a, 270).shape == (3, 2, 3)
    # Four 90s return to identity (pixel-exact).
    r = a
    for _ in range(4):
        r = N._rotate_cw(r, 90)
    assert np.array_equal(r, a)
    # 270 CW undoes 90 CW.
    assert np.array_equal(N._rotate_cw(N._rotate_cw(a, 90), 270), a)


def test_low_conf_fallback_leaves_image_untouched(monkeypatch=None):
    a = np.zeros((3, 5, 3), np.uint8)
    orig = N.osd_rotation
    N.osd_rotation = lambda bgr, b, t: (90, 0.5)  # confident-looking but below floor
    try:
        out, info = N.orient_upright(a, "x", "y", min_conf=2.0)
    finally:
        N.osd_rotation = orig
    assert info.method == "osd_low_conf"
    assert info.applied_rotate == 0
    assert np.array_equal(out, a), "low-conf OSD must NOT rotate"


def test_osd_unavailable_leaves_image_untouched():
    a = np.zeros((3, 5, 3), np.uint8)
    orig = N.osd_rotation
    N.osd_rotation = lambda bgr, b, t: (None, None)
    try:
        out, info = N.orient_upright(a, None, None)
    finally:
        N.osd_rotation = orig
    assert info.method == "osd_unavailable"
    assert info.applied_rotate == 0
    assert np.array_equal(out, a)


def test_confident_osd_applies_rotation():
    a = np.arange(2 * 4 * 3, dtype=np.uint8).reshape(2, 4, 3)
    orig = N.osd_rotation
    N.osd_rotation = lambda bgr, b, t: (90, 20.0)
    try:
        out, info = N.orient_upright(a, "x", "y", min_conf=2.0)
    finally:
        N.osd_rotation = orig
    assert info.method == "osd"
    assert info.applied_rotate == 90
    assert np.array_equal(out, N._rotate_cw(a, 90))


def test_pure_rotation_tag_is_distrusted_kept_landscape():
    """A JPEG tagged orientation=6 on already-upright LANDSCAPE pixels must stay
    landscape when OSD can't confirm — the pure-rotation tag is distrusted, not
    applied. This is the de_* real-capture fix: the old code transposed it to a
    (wrong) sideways portrait; the cascade keeps the raw upright buffer."""
    from PIL import Image

    land = np.zeros((300, 500, 3), np.uint8)      # landscape source (already upright)
    land[:, :250] = (0, 0, 200)                    # left half red-ish (BGR)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tagged.jpg"
        pil = Image.fromarray(cv2.cvtColor(land, cv2.COLOR_BGR2RGB))
        exif = pil.getexif()
        exif[0x0112] = 6                            # spurious "rotate 90 CW to view"
        pil.save(p, exif=exif)
        # binary=None → OSD unavailable → cascade falls back to the raw buffer.
        out, info = N.load_upright_bgr(p, None, None)
    assert info.exif_orientation == 6
    assert info.exif_mirror_baked is False, "6 is a pure-rotation tag, not a mirror"
    assert info.method == "osd_unavailable"
    assert out.shape[1] > out.shape[0], "orientation=6 must NOT be transposed to portrait"


def test_mirror_tag_is_still_baked():
    """A mirror orientation (2/4/5/7) is NOT the spurious flat-book case, so it is
    still honoured at load: the horizontal flip must be baked even with no OSD."""
    from PIL import Image

    land = np.zeros((300, 500, 3), np.uint8)
    land[:, :250] = (0, 0, 200)                    # left half coloured
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "mirrored.jpg"
        pil = Image.fromarray(cv2.cvtColor(land, cv2.COLOR_BGR2RGB))
        exif = pil.getexif()
        exif[0x0112] = 2                            # mirror horizontal
        pil.save(p, exif=exif, quality=100)
        out, info = N.load_upright_bgr(p, None, None)
    assert info.exif_orientation == 2
    assert info.exif_mirror_baked is True
    assert out.shape[1] > out.shape[0], "a horizontal mirror keeps landscape shape"
    # After un-mirroring, the coloured half has moved from left to right.
    left_red = int(out[:, :250, 2].mean())
    right_red = int(out[:, 250:, 2].mean())
    assert right_red > left_red, "mirror not baked: coloured half should be on the right"


# --------------------------------------------------------------------------
# Integration (real OSD) — self-skips when Tesseract/OSD is not confident
# --------------------------------------------------------------------------


def _find_tesseract() -> tuple[str | None, str | None]:
    binary = shutil.which("tesseract")
    win = Path(r"C:/Program Files/Tesseract-OCR/tesseract.exe")
    if not binary and win.exists():
        binary = str(win)
    td = REPO_ROOT / "models" / "tessdata_best"
    return binary, (str(td) if td.exists() else None)


def _text_image() -> np.ndarray:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except Exception:
        font = ImageFont.load_default()
    img = Image.new("RGB", (1400, 900), "white")
    d = ImageDraw.Draw(img)
    lines = ["The quick brown fox jumps over the lazy dog.",
             "Pack my box with five dozen liquor jugs.",
             "Sphinx of black quartz, judge my vow.",
             "How vexingly quick daft zebras jump!"]
    for i, ln in enumerate(lines):
        d.text((60, 120 + i * 140), ln, fill="black", font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def test_osd_corrects_a_known_rotation():
    binary, tessdata = _find_tesseract()
    if not binary:
        print("  skip: tesseract not found")
        return
    upright = _text_image()
    rotated = cv2.rotate(upright, cv2.ROTATE_90_CLOCKWISE)   # deliberately sideways
    out, info = N.orient_upright(rotated, binary, tessdata)
    if info.method != "osd":
        print(f"  skip: OSD not confident ({info.method}, conf={info.osd_conf})")
        return
    assert info.osd_rotate == 270, f"OSD should undo a 90 CW rotation, got {info.osd_rotate}"
    assert out.shape == upright.shape, "corrected image should match upright dims"


def test_orientation_gt_fixtures_resolve_to_upright():
    """Run the resolver on every testset orientation-GT fixture and assert the
    correct upright aspect. The de_* fixtures are the regression target: they used
    to ingest sideways (OSD starves on figure-heavy pages); the cascade must now
    keep them landscape via the raw-buffer fallback. Self-skips without Tesseract."""
    import json

    binary, tessdata = _find_tesseract()
    if not binary:
        print("  skip: tesseract not found")
        return
    gt_path = REPO_ROOT / "testset" / "gt" / "orientation.json"
    testset = REPO_ROOT / "testset"
    if not gt_path.exists():
        print("  skip: no orientation GT")
        return
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    checked = 0
    for iid, spec in gt.items():
        if iid.startswith("_"):
            continue
        img = testset / f"{iid}.jpg"
        if not img.exists():
            continue
        out, info = N.load_upright_bgr(img, binary, tessdata)
        h, w = out.shape[:2]
        is_landscape = w > h
        want_landscape = spec["upright_aspect"] == "landscape"
        assert is_landscape == want_landscape, (
            f"{iid}: got {'landscape' if is_landscape else 'portrait'} "
            f"({w}x{h}), want {spec['upright_aspect']} (method={info.method}, "
            f"osd_conf={info.osd_conf})")
        # Stronger than aspect: every fixture's raw buffer is already upright
        # (raw_is_upright), so the correct resolution is net-zero rotation. This
        # also catches a 180° (which passes the aspect check). On a confident-OSD
        # fixture osd_rotate==0 independently certifies "already upright"; the
        # low-conf de_* fall back to the (upright) raw buffer, also net-zero.
        if spec.get("raw_is_upright"):
            assert info.applied_rotate == 0, (
                f"{iid}: expected net-0 rotation (raw already upright), "
                f"applied {info.applied_rotate} (method={info.method})")
        checked += 1
    assert checked >= 2, f"expected >=2 fixtures resolved, only {checked}"
    print(f"  {checked} orientation fixtures resolved upright")


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
