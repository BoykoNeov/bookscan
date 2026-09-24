"""Unit tests for pipeline.stage03_dewarp classical text-line rectification.

Synthetic pages with a hand-known warp — no photos, no Tesseract. The core
assertion: a page whose straight rows are bent by a known curl comes back
STRAIGHTER after dewarp; a genuinely flat page is left unchanged but FLAGGED
(never a silent passthrough). Run with pytest, or directly:
    python -m pipeline.tests.test_stage03_dewarp
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from pipeline import stage03_dewarp as S3
from pipeline.stage03_dewarp import DEFAULTS, dewarp_classical, detect_baselines


def _lined_page(w: int = 1200, h: int = 1600, spacing: int = 40) -> np.ndarray:
    """White page with evenly spaced dark horizontal 'text' bars (BGR)."""
    gray = np.full((h, w), 245, np.uint8)
    for y in range(120, h - 120, spacing):
        gray[y:y + 8, 60:w - 60] = 20
    return np.dstack([gray] * 3)


def _bend(bgr: np.ndarray, amp: float) -> np.ndarray:
    """Bend straight rows into a cylindrical curl of peak ``amp`` px."""
    h, w = bgr.shape[:2]
    xs = np.arange(w, dtype=np.float32)
    disp = (amp * 4.0 * (xs / w - 0.5) ** 2).astype(np.float32)   # 0 centre, amp edges
    ys, xg = np.mgrid[0:h, 0:w].astype(np.float32)
    import cv2
    map_y = (ys + disp[None, :]).astype(np.float32)
    return cv2.remap(bgr, xg, map_y, interpolation=cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def _curvature(bgr: np.ndarray) -> float:
    """Mean vertical spread (max-min y) of detected baselines — 0 == perfectly
    straight lines."""
    import cv2
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bls, _ = detect_baselines(gray, DEFAULTS)
    if not bls:
        return 0.0
    return float(np.mean([ys.max() - ys.min() for _, ys in bls]))


def test_dewarp_straightens_curved_text():
    warped = _bend(_lined_page(), amp=45.0)
    before = _curvature(warped)
    out, pd, _ = dewarp_classical(warped, DEFAULTS)
    after = _curvature(out)
    assert pd.applied and pd.method == "classical", pd.note
    assert out.shape == warped.shape, "dewarp must preserve full resolution"
    assert before > 20, f"synthetic warp too weak to test ({before:.1f}px)"
    assert after < 0.5 * before, f"not straightened: {before:.1f} -> {after:.1f}px"


def test_flat_page_is_identity_and_flagged():
    flat = _lined_page()
    out, pd, _ = dewarp_classical(flat, DEFAULTS)
    assert not pd.applied and pd.method == "identity", pd.note
    assert np.array_equal(out, flat), "flat page must be emitted byte-identical"
    assert "flat" in pd.note or "displacement" in pd.note


def test_blank_page_too_few_lines_flagged():
    blank = np.full((1600, 1200, 3), 245, np.uint8)
    out, pd, _ = dewarp_classical(blank, DEFAULTS)
    assert not pd.applied and pd.method == "identity"
    assert pd.n_lines < DEFAULTS["min_lines"]
    assert np.array_equal(out, blank)


# --------------------------------------------------------------------------
# An imported PDF page is not flattened (v0.3.0; RESULTS 2026-09-24). UVDoc is a
# stub here that shrinks what it is given, so a test can tell whether it ran.
# --------------------------------------------------------------------------


class _StubUV:
    def __init__(self):
        self.calls = 0

    def dewarp(self, bgr):
        self.calls += 1
        return bgr[1:-1, 1:-1].copy(), S3.PageDewarp(name="", method="uvdoc", applied=True)

    def close(self):
        pass


def _split_page(tmp: Path, img: np.ndarray, origin: str | None) -> Path:
    page_dir = tmp / "page_001"
    (page_dir / "02_split").mkdir(parents=True)
    cv2.imwrite(str(page_dir / "02_split" / "single.png"), img)
    split = {"pages": [{"name": "single.png"}]}
    if origin is not None:
        split["layout_origin"] = origin
    (page_dir / "02_split" / "split.json").write_text(json.dumps(split), encoding="utf-8")
    return page_dir


def test_an_imported_page_is_written_unchanged_and_uvdoc_is_never_loaded(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(S3, "make_dewarper",
                        lambda method, cfg, warnings: loaded.append(1) or _StubUV())
    img = _lined_page(400, 600)
    page_dir = _split_page(tmp_path, img, "pdf_import")
    res = S3.run(page_dir, {})
    out = cv2.imread(str(page_dir / "03_dewarp" / "single.png"), cv2.IMREAD_COLOR)
    assert np.array_equal(out, img)
    assert loaded == []
    assert (res.pages[0].method, res.pages[0].applied) == ("skipped-import", False)
    meta = json.loads((page_dir / "03_dewarp" / "meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == S3.VERSION and any("flattening skipped" in w for w in meta["warnings"])


def test_a_phone_page_is_still_flattened(tmp_path, monkeypatch):
    img = _lined_page(400, 600)
    for origin in (None, ""):
        uv = _StubUV()
        monkeypatch.setattr(S3, "make_dewarper", lambda method, cfg, warnings, uv=uv: uv)
        page_dir = _split_page(tmp_path / f"o{origin}", img, origin)
        res = S3.run(page_dir, {})
        assert uv.calls == 1 and res.pages[0].method == "uvdoc"
        out = cv2.imread(str(page_dir / "03_dewarp" / "single.png"), cv2.IMREAD_COLOR)
        assert out.shape == (598, 398, 3)


def _run() -> int:
    import inspect
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")
           and not inspect.signature(v).parameters]      # fixture tests need pytest
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
