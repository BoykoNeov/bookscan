"""Tests for tools.book_box_editor — the operator's book box.

Pure logic only: no HTTP, no browser. The rules worth pinning are the ones that
protect page content, because the whole point of a hand-drawn box is that it
carries a human's confidence and will therefore be trusted.

Run with pytest, or directly:
    python -m tools.tests.test_book_box_editor
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from pipeline import book_boundary as BB
from pipeline import stage02_split as S2
from tools import book_box_editor as BE


def _spread(w: int = 2000, h: int = 1500) -> np.ndarray:
    """Bright two-page spread on a saturated background, book well inside."""
    rng = np.random.default_rng(20260828)
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2] = 70, 40, 105
    img = np.clip(img.astype(np.int16)
                  + rng.integers(-25, 25, (h, w, 3), dtype=np.int16),
                  0, 255).astype(np.uint8)
    bx0, by0, bx1, by1 = 400, 300, 1600, 1200
    page = np.full((by1 - by0, bx1 - bx0, 3), 238, np.uint8)
    ph, pw = page.shape[:2]
    gut = pw // 2
    for y in range(int(ph * 0.1), int(ph * 0.9), 24):
        page[y:y + 10, int(pw * 0.05):gut - 60] = 25
        page[y:y + 10, gut + 60:int(pw * 0.95)] = 25
    img[by0:by1, bx0:bx1] = page
    return img


def _job(tmp: Path, n: int = 1) -> Path:
    job = tmp / "job"
    for i in range(1, n + 1):
        pd = job / f"page_{i:03d}" / "01_fuse"
        pd.mkdir(parents=True)
        cv2.imwrite(str(pd / "anchor.png"), _spread())
    return job


def test_lists_only_pages_that_have_an_anchor():
    with tempfile.TemporaryDirectory() as td:
        job = _job(Path(td), n=2)
        (job / "page_003").mkdir()          # no Stage 01 output yet
        assert [p.name for p in BE.list_pages(job)] == ["page_001", "page_002"]


def test_saved_box_carries_the_provenance_stage02_checks():
    """Frame identity is not decoration — Stage 02 refuses on it."""
    with tempfile.TemporaryDirectory() as td:
        job = _job(Path(td))
        page = job / "page_001"
        r = BE.save_user_box(page, [400, 300, 1600, 1200])
        assert r["ok"], r
        rec = json.loads((page / S2.USER_BOX_FILE).read_text(encoding="utf-8"))
        assert rec["frame"] == "01_fuse/anchor.png"
        assert rec["frame_size"] == [2000, 1500]
        assert rec["drawn_at"]
        # and the check it enables actually fires on the wrong frame
        stale = S2.UserBookBox(box=rec["box"], frame_size=[999, 888])
        assert S2.user_box_mismatch(stale, 2000, 1500)
        assert S2.user_box_mismatch(
            S2.UserBookBox(box=rec["box"], frame_size=[2000, 1500]),
            2000, 1500) is None


def test_a_backwards_drag_is_still_a_box():
    """People drag bottom-right to top-left. That must not become an empty box."""
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        r = BE.save_user_box(page, [1600, 1200, 400, 300])
        assert r["ok"] and r["box"] == [400, 300, 1600, 1200]


def test_a_drag_outside_the_frame_is_clamped_not_rejected():
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        r = BE.save_user_box(page, [-500, -400, 9000, 9000])
        assert r["ok"] and r["box"] == [0, 0, 2000, 1500]


def test_a_stray_click_is_refused_before_it_reaches_the_pipeline():
    """Telling the operator now beats a warning buried in meta.json later."""
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        r = BE.save_user_box(page, [800, 700, 812, 712])
        assert not r["ok"] and "too small" in r["error"]
        assert not (page / S2.USER_BOX_FILE).exists(), (
            "a refused box must not be written")


def test_clearing_restores_the_detector_exactly():
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        before = S2.run(page, {})
        BE.save_user_box(page, [420, 320, 1580, 1180])
        with_box = S2.run(page, {})
        assert with_box.book_crop_source == "operator"
        BE.clear_user_box(page)
        after = S2.run(page, {})
        assert after.book_crop_source == "detector"
        assert (after.gutter_x, after.book_crop, after.book_crop_reason) == \
               (before.gutter_x, before.book_crop, before.book_crop_reason)


def test_page_state_reports_what_the_operator_needs_to_judge():
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        S2.run(page, {})
        st = BE.page_state(page)
        assert st["frame_w"] == 2000 and st["frame_h"] == 1500
        assert st["user_box"] is None and st["crop_source"] == "detector"
        assert st["reason"], "the detector's own account must reach the operator"
        assert st["has_overlay"] is True
        BE.save_user_box(page, [400, 300, 1600, 1200])
        st = BE.page_state(page)
        assert st["user_box"] == [400, 300, 1600, 1200]
        assert st["user_box_stale"] is None


def test_preview_is_scaled_and_leaves_no_file_behind():
    with tempfile.TemporaryDirectory() as td:
        page = _job(Path(td)) / "page_001"
        before = sorted(p.name for p in page.rglob("*"))
        blob = BE.preview_jpeg(page / "01_fuse" / "anchor.png", width=600)
        img = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[1] == 600
        assert sorted(p.name for p in page.rglob("*")) == before


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
