"""The higher-resolution figure pass: what it upgrades, and what it refuses.

The refusals are the important half. This pass replaces the pixels a reader
actually looks at, so every way it can be wrong — a source that is not this
picture, a source with no more detail than the page already had, a stale asset
after the figure is resized in the editor — has to end in the page crop rather
than in a confident mistake.
"""
from __future__ import annotations

import numpy as np
import pytest
import cv2

from pipeline import figure_hires as FH
from pipeline.page_model import BBox, Block, BlockType


def _texture(w: int, h: int, seed: int = 0) -> np.ndarray:
    """A smooth, feature-rich synthetic picture — SIFT needs structure, and a
    field of white noise has none at any scale it looks at."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (h // 16, w // 16, 3), dtype=np.uint8)
    img = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(img, (5, 5), 0)


class _FakeFrame(FH.FrameIndex):
    """A FrameIndex over an in-memory image (no file on disk)."""

    def __init__(self, name: str, img: np.ndarray, params: dict) -> None:
        super().__init__(name, __file__, params)   # path never read
        self._img = img


@pytest.fixture()
def params() -> dict:
    return FH.resolve_params({})


def test_a_sharper_capture_upgrades_the_figure(params):
    truth = _texture(1200, 900, seed=1)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    frames = [_FakeFrame("closeup.png", truth, params)]

    cands = FH.candidates(crop, frames, params)
    assert cands, "the close-up IS this picture at 2x; it must be a candidate"
    got = FH.compose(crop, cands, params)
    assert got is not None
    out, used = got
    # Same rectangle, more pixels. The aspect ratio must not move — Stage 08
    # places the asset in the block's box and a changed ratio would distort it.
    assert out.shape[1] / out.shape[0] == pytest.approx(crop.shape[1] / crop.shape[0],
                                                        abs=0.01)
    assert out.shape[1] > crop.shape[1] * 1.5
    assert [s.frame for s in used] == ["closeup.png"]


def test_a_capture_with_no_extra_detail_is_refused(params):
    """The page crop and the 'source' are the same size: substituting one for the
    other is a resampling and nothing else."""
    truth = _texture(600, 450, seed=2)
    frames = [_FakeFrame("same.png", truth.copy(), params)]
    assert FH.compose(truth, FH.candidates(truth, frames, params), params) is None


def test_a_different_picture_is_refused_however_well_it_matches(params):
    truth = _texture(1200, 900, seed=3)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    other = _texture(1200, 900, seed=99)          # a different picture entirely
    frames = [_FakeFrame("wrong.png", other, params)]
    assert FH.compose(crop, FH.candidates(crop, frames, params), params) is None


def test_two_captures_that_each_hold_half_are_composed(params):
    """Neither frame contains the whole figure. Together they do — which is the
    case a single-best-source rule cannot serve, and the reason ``compose``
    exists."""
    truth = _texture(1200, 900, seed=4)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    left = truth[:, :760].copy()                  # overlapping halves
    right = truth[:, 440:].copy()
    # a frame is a photograph, not a crop: pad so the halves are their own images
    frames = [_FakeFrame("left.png", left, params),
              _FakeFrame("right.png", right, params)]

    cands = FH.candidates(crop, frames, params)
    assert len(cands) == 2, "each half holds a usable piece"
    assert all(c.src.coverage < float(params["min_coverage"]) for c in cands), \
        "and neither half is enough on its own"
    got = FH.compose(crop, cands, params)
    assert got is not None
    out, used = got
    assert len(used) == 2
    assert out.shape[1] > crop.shape[1] * 1.5


def test_nothing_to_match_means_keep_the_page_crop(params):
    crop = _texture(600, 450, seed=5)
    assert FH.compose(crop, FH.candidates(crop, [], params), params) is None


def test_a_tiny_figure_is_not_worth_searching(params):
    """Below ``min_figure_px`` the search is skipped outright — a 60x60 stamp has
    nothing a reader can zoom into, and the search is the expensive part."""
    tiny = _texture(64, 64, seed=6)
    big = _texture(1200, 900, seed=6)
    assert FH.candidates(tiny, [_FakeFrame("f.png", big, params)], params) == []


def test_the_canvas_scale_comes_from_the_frame_that_sees_the_most(params):
    """A frame holding a sliver at high magnification must not set the resolution
    of the whole picture: the rest would be an upsample of the page crop wearing
    the sliver's scale."""
    truth = _texture(1200, 900, seed=7)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    wide = truth.copy()                                     # whole figure at 2x
    sliver = cv2.resize(truth[300:600, 400:700], (1200, 1200),
                        interpolation=cv2.INTER_CUBIC)      # a corner at ~8x
    got = FH.compose(crop, FH.candidates(crop, [
        _FakeFrame("wide.png", wide, params),
        _FakeFrame("sliver.png", sliver, params)], params), params)
    assert got is not None
    out, _ = got
    assert out.shape[1] / crop.shape[1] < 3.0


# --------------------------------------------------------------------------
# Stage 08 must never trust a stale asset
# --------------------------------------------------------------------------


def test_render_falls_back_when_the_figure_was_resized(tmp_path):
    """``document.json`` is mutable and the asset is not re-cut on an edit. A
    figure the user resized must fall back to the page crop: a high-resolution
    picture of the OLD outline is a WRONG picture, which is worse than a soft one.
    """
    from pipeline import stage08_render as S8

    page = _texture(800, 600, seed=8)
    asset = tmp_path / "document_assets"
    asset.mkdir()
    cv2.imwrite(str(asset / "fig.png"), _texture(400, 300, seed=9))

    box = BBox(x=10, y=10, w=200, h=150)
    blk = Block(id=0, type=BlockType.FIGURE, bbox=box, reading_order=0,
                figure_asset="document_assets/fig.png",
                figure_asset_box=box.model_copy(), figure_asset_scale=2.0)
    used_asset = S8._figure_data_uri(blk, page, None, tmp_path)

    blk.bbox = BBox(x=10, y=10, w=260, h=150)      # the user widened the figure
    used_crop = S8._figure_data_uri(blk, page, None, tmp_path)

    assert used_asset and used_crop and used_asset != used_crop


def test_a_missing_asset_file_falls_back_rather_than_failing(tmp_path):
    from pipeline import stage08_render as S8

    page = _texture(800, 600, seed=10)
    box = BBox(x=0, y=0, w=100, h=100)
    blk = Block(id=0, type=BlockType.FIGURE, bbox=box, reading_order=0,
                figure_asset="document_assets/gone.png",
                figure_asset_box=box.model_copy())
    assert S8._figure_data_uri(blk, page, None, tmp_path) is not None


def test_masked_text_lands_in_the_right_place_on_a_scaled_asset(tmp_path):
    """The mask boxes are in PAGE coordinates and the asset has more pixels than
    the rectangle they describe, so they have to be scaled, not offset. Painting
    them unscaled would blank the wrong part of the picture."""
    from pipeline import stage08_render as S8

    crop = np.full((100, 200, 3), 200, np.uint8)
    asset = cv2.resize(crop, (400, 200), interpolation=cv2.INTER_NEAREST)
    # a box covering the RIGHT half of the figure, in page coordinates
    out = S8._paint_out(asset, [BBox(x=100, y=0, w=100, h=100)], 0, 0, 200, 100)
    assert (out[:, :180] == 200).all(), "the left half must be untouched"
    assert out[:, 220:].std() < 1.0, "the right half must be filled flat"
