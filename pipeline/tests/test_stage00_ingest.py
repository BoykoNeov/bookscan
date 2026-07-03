"""Unit tests for pipeline.stage00_ingest.

Orientation is stubbed (the real OSD path is covered in
tools/tests/test_normalize.py), so these tests need no Tesseract — they check
the stage contract: frame naming/order, the manifest, sharpness, RAW skipping,
and the three required artifacts. Run with pytest, or directly:
    python -m pipeline.tests.test_stage00_ingest
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from pipeline import stage00_ingest as S
from tools import normalize as N


def _stub_orient():
    """Replace the tesseract-dependent loader with a pure cv2 read."""
    def _load(path, binary, tessdata, min_conf=2.0):
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return bgr, N.OrientInfo(applied_rotate=0, method="osd", osd_conf=42.0,
                                 exif_orientation=1)
    return _load


def _sharp_image(w=400, h=300) -> np.ndarray:
    img = np.full((h, w, 3), 240, np.uint8)
    img[::4, :] = 10          # high-frequency stripes -> high Laplacian variance
    return img


def _blurry_image(w=400, h=300) -> np.ndarray:
    img = _sharp_image(w, h)
    return cv2.GaussianBlur(img, (21, 21), 0)


def test_sharpness_orders_sharp_above_blurry():
    assert S.sharpness(_sharp_image()) > S.sharpness(_blurry_image())


def test_single_frame_writes_the_three_artifacts(monkeypatch=None):
    orig = N.load_upright_bgr
    N.load_upright_bgr = _stub_orient()
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "cap.png"
            cv2.imwrite(str(src), _sharp_image())
            page = root / "page_001"
            result = S.run(page, cfg={}, src=src)
            # All filesystem checks MUST run before the temp dir is torn down.
            assert result.n_frames == 1
            f = result.frames[0]
            assert f.name == "frame_00.png" and f.source == "cap.png"
            assert f.width == 400 and f.height == 300 and f.sharpness > 0
            assert (page / "00_ingest" / "frame_00.png").exists()
            manifest = json.loads((page / "00_ingest" / "ingest.json").read_text())
            assert manifest["n_frames"] == 1
            assert (page / "00_ingest" / "meta.json").exists()
            assert (page / "debug" / "00_ingest.png").exists()
    finally:
        N.load_upright_bgr = orig


def test_multi_frame_ordering_and_manifest():
    orig = N.load_upright_bgr
    N.load_upright_bgr = _stub_orient()
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capdir = root / "caps"
            capdir.mkdir()
            cv2.imwrite(str(capdir / "a.png"), _sharp_image())
            cv2.imwrite(str(capdir / "b.png"), _blurry_image())
            page = root / "page_001"
            result = S.run(page, cfg={}, src=capdir)
    finally:
        N.load_upright_bgr = orig

    assert [f.name for f in result.frames] == ["frame_00.png", "frame_01.png"]
    assert [f.source for f in result.frames] == ["a.png", "b.png"]
    # frame_00 (from a.png, sharp) should out-score frame_01 (from b.png, blurry).
    assert result.frames[0].sharpness > result.frames[1].sharpness


def test_stale_frames_cleared_on_rerun():
    orig = N.load_upright_bgr
    N.load_upright_bgr = _stub_orient()
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capdir = root / "caps"
            capdir.mkdir()
            cv2.imwrite(str(capdir / "a.png"), _sharp_image())
            cv2.imwrite(str(capdir / "b.png"), _sharp_image())
            page = root / "page_001"
            S.run(page, cfg={}, src=capdir)              # 2 frames
            (capdir / "b.png").unlink()                  # now only 1 source
            S.run(page, cfg={}, src=capdir)              # re-run
            frames = sorted((page / "00_ingest").glob("frame_*.png"))
    finally:
        N.load_upright_bgr = orig
    assert [p.name for p in frames] == ["frame_00.png"], "stale frame_01 not cleared"


def test_raw_without_rawpy_is_skipped_not_crashed():
    # A .dng source with rawpy absent must warn+skip, not raise.
    try:
        import rawpy  # noqa: F401
        print("  skip: rawpy present, cannot test the absent-branch")
        return
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "shot.dng"
        src.write_bytes(b"not a real raw")     # never decoded — skipped first
        page = root / "page_001"
        result = S.run(page, cfg={}, src=src)
        assert result.n_frames == 0
        meta = json.loads((page / "00_ingest" / "meta.json").read_text())
        assert any("rawpy not installed" in w for w in meta["warnings"])


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
