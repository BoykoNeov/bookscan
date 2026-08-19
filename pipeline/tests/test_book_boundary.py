"""Unit tests for pipeline.book_boundary.

Synthetic frames with a hand-known answer — no photos. The real-photo evidence
lives in ``tools/split_eval`` (graded against ``testset/gt/gutter.json`` and
``testset/gt/book_box.json``); these tests pin the CONTRACT: abstain is safe and
total, the emitted box never excludes the searched one, and the guards refuse
rather than crop to garbage.

Run with pytest, or directly:
    python -m pipeline.tests.test_book_boundary
"""

from __future__ import annotations

import numpy as np

from pipeline import book_boundary as BB

RNG = np.random.default_rng(20260819)


def _paper(h: int, w: int) -> np.ndarray:
    """Bright, nearly colourless page with faint print texture."""
    page = np.full((h, w, 3), 238, np.uint8)
    noise = RNG.integers(-8, 8, (h, w, 1), dtype=np.int16)
    page = np.clip(page.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    for y in range(int(h * 0.08), int(h * 0.92), 40):
        page[y:y + 14, int(w * 0.06):int(w * 0.94)] = 30
    return page


def _cluttered_frame(fw: int = 2000, fh: int = 1500,
                     box: tuple[int, int, int, int] = (400, 300, 1600, 1200)
                     ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """A book laid on a saturated, textured background — the lap-shot shape."""
    img = np.zeros((fh, fw, 3), np.uint8)
    img[:, :, 0] = 70          # saturated, mid-dark surroundings
    img[:, :, 1] = 40
    img[:, :, 2] = 105
    img = np.clip(img.astype(np.int16)
                  + RNG.integers(-25, 25, (fh, fw, 3), dtype=np.int16),
                  0, 255).astype(np.uint8)
    x0, y0, x1, y1 = box
    img[y0:y1, x0:x1] = _paper(y1 - y0, x1 - x0)
    return img, box


def test_abstains_when_the_page_already_fills_the_frame():
    """A tightly framed spread must take the untouched path, boxes = full frame.

    This is the non-regression guarantee: every pre-existing fixture keeps
    byte-identical output because nothing is cropped, not because a threshold
    was tuned to leave it alone.
    """
    img = np.dstack([np.zeros((1500, 2000), np.uint8)] * 3)
    img[:, :] = _paper(1500, 2000)
    bb = BB.find_book(img)
    assert not bb.applied
    assert bb.emit == (0, 0, 2000, 1500)
    assert bb.search == (0, 0, 2000, 1500)
    assert bb.reason


def test_crops_a_book_out_of_a_cluttered_frame():
    img, (x0, y0, x1, y1) = _cluttered_frame()
    bb = BB.find_book(img)
    assert bb.applied, bb.reason
    ex0, ey0, ex1, ey1 = bb.emit
    # The emitted crop must CONTAIN the book: losing page content is the one
    # failure Stage 02 treats as real.
    assert ex0 <= x0 and ey0 <= y0 and ex1 >= x1 and ey1 >= y1
    # ... and must still be a crop, or it buys nothing.
    assert (ex1 - ex0) * (ey1 - ey0) < 0.90 * img.shape[0] * img.shape[1]


def test_emit_box_contains_the_search_box():
    """A gutter found in the search box must lie inside the pixels being cut."""
    img, _ = _cluttered_frame()
    bb = BB.find_book(img)
    ex0, ey0, ex1, ey1 = bb.emit
    sx0, sy0, sx1, sy1 = bb.search
    assert ex0 <= sx0 and ey0 <= sy0 and ex1 >= sx1 and ey1 >= sy1


def test_search_box_ignores_a_thin_bright_leak():
    """The percentile trim exists for this: a bright cable/chair edge touching
    the page drags a plain bounding box to the frame border, and a search box
    that wide puts the spine back outside the detector's central band."""
    img, (x0, y0, x1, y1) = _cluttered_frame()
    ymid = (y0 + y1) // 2
    img[ymid - 6:ymid + 6, x1:] = 240          # thin bright tendril to the edge
    bb = BB.find_book(img)
    assert bb.applied, bb.reason
    # Search box stops well short of the frame edge the leak reaches.
    assert bb.search[2] < img.shape[1] - 100


def test_refuses_when_there_is_no_page():
    img = np.clip(RNG.integers(0, 60, (1500, 2000, 3), dtype=np.int16),
                  0, 255).astype(np.uint8)
    bb = BB.find_book(img)
    assert not bb.applied
    assert bb.emit == (0, 0, 2000, 1500)


def test_refuses_a_speck_too_small_to_be_a_spread():
    img = np.clip(RNG.integers(0, 60, (1500, 2000, 3), dtype=np.int16),
                  0, 255).astype(np.uint8)
    img[700:760, 900:980] = 245                 # a bright chip, not a book
    bb = BB.find_book(img)
    assert not bb.applied
    assert "too small" in bb.reason


def test_disabled_by_config_is_a_clean_no_op():
    img, _ = _cluttered_frame()
    p = BB.resolve_params({"book_crop": {"enabled": False}})
    bb = BB.find_book(img, p)
    assert not bb.applied
    assert bb.emit == (0, 0, img.shape[1], img.shape[0])


def test_grabcut_fallback_still_contains_the_book():
    """With GrabCut off the raw mask bbox + wider pad must still not clip."""
    img, (x0, y0, x1, y1) = _cluttered_frame()
    p = BB.resolve_params({"book_crop": {"grabcut": False}})
    bb = BB.find_book(img, p)
    assert bb.applied, bb.reason
    assert bb.diag["emit_source"] == "mask_bbox_fallback"
    ex0, ey0, ex1, ey1 = bb.emit
    assert ex0 <= x0 and ey0 <= y0 and ex1 >= x1 and ey1 >= y1


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
