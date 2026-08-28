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


def test_area_abstain_states_a_measurement_not_a_framing_verdict():
    """The 83 % gate must not claim the photograph was tightly framed.

    That sentence is an inference from a detection that, by the act of
    abstaining, was never confirmed — and on the two pale-background captures it
    was wrong AND actionable: it told an operator to reframe a correctly framed
    shot (RESULTS 2026-08-28). The refusal may report what it measured; the
    caveat lives in ``evidence``.
    """
    img = np.dstack([np.zeros((1500, 2000), np.uint8)] * 3)
    img[:, :] = _paper(1500, 2000)
    bb = BB.find_book(img)
    assert not bb.applied
    assert "tightly framed" not in bb.reason.lower()
    assert "covers" in bb.reason and "%" in bb.reason
    # …and it says out loud what it cannot tell apart.
    assert bb.evidence, "the area gate must qualify its own refusal"
    assert "NOT a finding that the shot is tightly framed" in bb.evidence


def test_only_the_area_gate_needs_the_caveat():
    """A refusal that IS conclusive must not be watered down with one.

    'No mask formed at all' and 'the mask is a speck' are direct observations,
    not inferences, so they carry no evidence string — otherwise the caveat
    stops meaning anything wherever it appears.
    """
    img = np.clip(RNG.integers(0, 60, (1500, 2000, 3), dtype=np.int16),
                  0, 255).astype(np.uint8)
    assert BB.find_book(img).evidence == ""
    img[700:760, 900:980] = 245
    speck = BB.find_book(img)
    assert "too small" in speck.reason and speck.evidence == ""


def test_operator_box_is_padded_outward_not_used_as_drawn():
    """The padding is the whole safety property, so assert it directly.

    Measured 2026-08-28 on the eight labelled spreads: cropping to the box
    exactly loses 1.95 % of the book on a 1 % undersized drag and 9.73 % on a
    5 % one, while padding it loses 0.00 % at every perturbation up to 5 %.
    Losing text is the one failure this stage treats as real, and a hand-drawn
    box is exactly where a small error is expected.
    """
    img, _ = _cluttered_frame()
    drawn = (400, 300, 1600, 1200)
    bb = BB.user_box(img, drawn)
    assert bb.applied, bb.reason
    ex0, ey0, ex1, ey1 = bb.emit
    assert ex0 < drawn[0] and ey0 < drawn[1]
    assert ex1 > drawn[2] and ey1 > drawn[3]
    # emit can never be tighter than search — the same invariant find_book has
    sx0, sy0, sx1, sy1 = bb.search
    assert ex0 <= sx0 and ey0 <= sy0 and ex1 >= sx1 and ey1 >= sy1
    assert bb.diag["user_box"] == list(drawn)
    assert bb.diag["emit_source"] == "operator"


def test_an_undersized_drag_still_contains_the_book():
    """Simulate a sloppy mouse: shrink the true book box 5 % and draw THAT."""
    img, (x0, y0, x1, y1) = _cluttered_frame()
    dx, dy = int((x1 - x0) * 0.025), int((y1 - y0) * 0.025)
    bb = BB.user_box(img, (x0 + dx, y0 + dy, x1 - dx, y1 - dy))
    assert bb.applied, bb.reason
    ex0, ey0, ex1, ey1 = bb.emit
    assert ex0 <= x0 and ey0 <= y0 and ex1 >= x1 and ey1 >= y1, (
        "a 5 % undersized drag clipped the book — the outward pad is not working")


def test_operator_box_refuses_nonsense_rather_than_cropping_to_it():
    img, _ = _cluttered_frame()
    assert not BB.user_box(img, (5, 5, 5, 5)).applied
    assert not BB.user_box(img, (-90, -90, -10, -10)).applied
    speck = BB.user_box(img, (900, 700, 1000, 780))
    assert not speck.applied and "too small" in speck.reason


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
