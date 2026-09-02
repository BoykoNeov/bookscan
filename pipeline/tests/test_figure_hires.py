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


def test_the_canvas_scale_comes_from_the_sharpest_source(params):
    """A source holding a piece of the picture at higher magnification must set
    the resolution of that piece, not be resampled down into a wider source's
    canvas.

    This test used to assert the opposite, on the argument that a frame holding a
    fifth of the picture should not decide the resolution of the other four
    fifths. Measured on the owner's via-ferrata topo map (RESULTS 2026-08-29) that
    argument is wrong: the canvas is only a container, a region is as good as the
    source that lands on it, and the smaller container merely threw the fifth
    away — 1.86x delivered where 3.16x was available.
    """
    truth = _texture(1500, 1200, seed=7)
    crop = cv2.resize(truth, (500, 400), interpolation=cv2.INTER_AREA)
    wide = cv2.resize(truth, (1000, 800), interpolation=cv2.INTER_AREA)   # 2x, all
    piece = truth[300:900, 400:1100]                                      # 3x, part
    got = FH.compose(crop, FH.candidates(crop, [
        _FakeFrame("wide.png", wide, params),
        _FakeFrame("piece.png", piece, params)], params), params)
    assert got is not None
    out, used = got
    assert {s.frame for s in used} == {"wide.png", "piece.png"}
    assert out.shape[1] / crop.shape[1] > 2.5


def test_a_source_beyond_max_scale_is_refused(params):
    """The guard behind that change: a "match" claiming an implausible
    magnification is a degenerate homography, not a windfall."""
    truth = _texture(1200, 900, seed=11)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    absurd = cv2.resize(truth[400:500, 500:600], (2000, 2000),
                        interpolation=cv2.INTER_CUBIC)
    cands = FH.candidates(crop, [_FakeFrame("absurd.png", absurd, params)], params)
    assert all(c.src.scale <= params["max_scale"] for c in cands)


def test_bending_a_source_onto_the_page_is_optional_and_harmless(params):
    """``mesh_align`` corrects what a homography cannot express. On synthetic
    sources there is nothing to correct, so it must change the ANSWER not at all —
    the guard against a refinement that quietly becomes a gate."""
    truth = _texture(1200, 900, seed=13)
    crop = cv2.resize(truth, (600, 450), interpolation=cv2.INTER_AREA)
    frames = [_FakeFrame("closeup.png", truth, params)]
    on = FH.compose(crop, FH.candidates(crop, frames, params), params)
    off = FH.compose(crop, FH.candidates(crop, frames, params),
                     dict(params, mesh_align=False))
    assert on is not None and off is not None
    assert on[0].shape == off[0].shape
    assert [s.frame for s in on[1]] == [s.frame for s in off[1]]


def test_the_result_gate_is_judged_only_where_a_source_landed(params):
    """Where nothing landed the composite IS the page crop resized, so counting
    that region would be the crop agreeing with itself — the backstop would lose
    its power exactly as coverage falls, which is where it is needed."""
    truth = _texture(900, 900, seed=17)
    crop = cv2.resize(truth, (450, 450), interpolation=cv2.INTER_AREA)
    out = cv2.resize(crop, (900, 900), interpolation=cv2.INTER_CUBIC)
    out[:, 450:] = 0                       # half the picture is plainly wrong
    union = np.zeros((900, 900), np.uint8)
    union[:, 450:] = 255                   # ... and it is the half a source covered
    assert FH._result_agreement(crop, out, union) < params["min_result_ncc"]
    # Unmasked, the untouched half would carry the verdict.
    assert FH._result_agreement(crop, out) > FH._result_agreement(crop, out, union)


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


def test_a_frame_that_cannot_be_decoded_is_skipped_and_says_so(params, tmp_path):
    """The skip is right (no pixels to cut from); the SILENCE was the bug.
    RESULTS 2026-08-29 left one figure upgrading in isolation and refused in
    the batch, with a frame decode returning None the likeliest cause and no
    record that it had happened. A frame that fails to decode must now say so,
    so Stage 07 can list it in document.meta.json."""
    crop = _texture(600, 450, seed=5)
    missing = FH.FrameIndex("gone.png", tmp_path / "gone.png", params)
    assert missing.decode_failed is False          # nothing has been asked yet
    assert FH.candidates(crop, [missing], params) == []
    assert missing.decode_failed is True
    ok = _FakeFrame("f.png", _texture(1200, 900, seed=5), params)
    FH.candidates(crop, [ok], params)
    assert ok.decode_failed is False
