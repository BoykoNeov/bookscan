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
    # **kw so the stub keeps working when the cascade gains a knob. It grew
    # min_conf_180 on 2026-08-19 and this stub was the only thing that noticed.
    def _load(path, binary, tessdata, min_conf=2.0, **kw):
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


def _run_portrait(layout_json: str | None) -> dict:
    """Run Stage 00 on a portrait frame with OSD stubbed to 'upright, confident';
    return its meta.json. ``layout_json`` is written as page_layout.json."""
    orig = N.osd_rotation
    N.osd_rotation = lambda bgr, b, t: (0, 20.0)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "cap.png"
            cv2.imwrite(str(src), _sharp_image(w=300, h=400))
            page = root / "page_001"
            page.mkdir()
            if layout_json is not None:
                (page / "page_layout.json").write_text(layout_json, encoding="utf-8")
            # a binary that "exists" so the cascade reaches the (stubbed) OSD
            S.run(page, cfg={"tesseract": {"binary": str(src)}}, src=src)
            return json.loads((page / "00_ingest" / "meta.json").read_text())
    finally:
        N.osd_rotation = orig


def test_declared_single_page_gets_no_portrait_warning():
    meta = _run_portrait('{"layout": "single", "source": "pdf_import_aspect", '
                         '"origin": "pdf_import"}')
    assert not any("PORTRAIT" in w for w in meta["warnings"]), meta["warnings"]
    assert meta["params"]["declared_layout"] == "single"


def test_spread_still_gets_the_portrait_warning():
    for layout in (None, '{"layout": "spread", "source": "operator"}',
                   '{"layout": "detect", "source": "operator"}'):
        meta = _run_portrait(layout)
        assert any("PORTRAIT" in w for w in meta["warnings"]), layout


def test_corrupt_page_layout_warns_and_runs_as_before():
    meta = _run_portrait("{not json")
    assert any("page_layout.json unreadable" in w for w in meta["warnings"])
    assert any("PORTRAIT" in w for w in meta["warnings"])
    assert meta["params"]["declared_layout"] is None


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
