"""Unit tests for ``pipeline.figure_label`` — the in-photo corner-label reader.

The load-bearing property here is CONSERVATISM ("0 wrong"): ``pair_by_number``
attributes a caption to a figure BY the recovered number, so a single wrong read
on a mispairing-trap fixture is worse than a miss. These tests pin the exact
acceptance logic that guarantees it — including the real it_geo_06 failure the
rule was built from (the F25 split box OCR'd ``['25','2','25','2']``: a 2-digit
read that truncates to its first digit on some PSMs must NOT be vetoed by the
truncation, yet a lone weak 1-digit fragment must stay ``None``).

The acceptance tests monkeypatch ``_ocr_digits`` (so they need NO Tesseract and
NO fixture image and are fully deterministic); the guard tests exercise the real
cv2 path up to — but not into — Tesseract (isolation returns ``None`` on a blank
patch before any OCR runs), so they too need no Tesseract binary.
"""

from __future__ import annotations

import numpy as np

from pipeline import figure_label as FL


# --------------------------------------------------------------------------
# Acceptance logic (the "0 wrong" invariant). We patch _isolate_label to hand
# back a dummy crop and _ocr_digits to replay a controlled per-PSM read list,
# then assert read_corner_label's decision. _PSMS = (7, 8, 10, 13).
# --------------------------------------------------------------------------

def _run_with_reads(monkeypatch, per_psm: dict[int, str]):
    """Drive read_corner_label with a fixed {psm: ocr_string} mapping."""
    dummy = np.zeros((10, 10), np.uint8)
    monkeypatch.setattr(FL, "_isolate_label", lambda fig, p: dummy)
    monkeypatch.setattr(FL, "_ocr_digits",
                        lambda img, tb, psm: per_psm.get(psm, ""))
    fig = np.zeros((100, 100, 3), np.uint8)
    return FL.read_corner_label(fig, "tesseract-not-used")


def test_clean_two_digit_all_agree(monkeypatch):
    # All four PSMs read "25" -> the easy, unambiguous case.
    assert _run_with_reads(monkeypatch, {7: "25", 8: "25", 10: "25", 13: "25"}) == 25


def test_two_digit_survives_truncation(monkeypatch):
    # THE real it_geo_06 F25 split-box case: ['25','2','25','2']. Two votes for
    # the full "25", the "2" votes are truncation noise. A 2-digit value wins on
    # >=2 votes when it is the ONLY 2-digit read -> 25, not vetoed, not None.
    assert _run_with_reads(monkeypatch, {7: "25", 8: "2", 10: "25", 13: "2"}) == 25


def test_two_digit_lone_vote_rejected(monkeypatch):
    # A single 2-digit vote (cnt < 2) is not enough -> None (don't guess).
    assert _run_with_reads(monkeypatch, {7: "25", 8: "", 10: "", 13: ""}) is None


def test_conflicting_two_digit_reads_reject(monkeypatch):
    # Two DIFFERENT 2-digit values -> genuine ambiguity -> None. This is the
    # guard against a texture patch that yields a plausible-but-wrong number.
    assert _run_with_reads(monkeypatch, {7: "25", 8: "27", 10: "25", 13: "2"}) is None


def test_strong_single_digit_accepted(monkeypatch):
    # A 1-digit label needs >= min_psm_agree (3) with no competitor.
    assert _run_with_reads(monkeypatch, {7: "3", 8: "3", 10: "3", 13: "3"}) == 3


def test_weak_single_digit_rejected(monkeypatch):
    # The it_geo_06 F28 texture fragment: a lone weak "3" (cnt < 3) stays None.
    assert _run_with_reads(monkeypatch, {7: "3", 8: "", 10: "", 13: ""}) is None


def test_competing_single_digits_reject(monkeypatch):
    # Two different 1-digit values, neither dominant -> None (len(one) != 1).
    assert _run_with_reads(monkeypatch, {7: "3", 8: "3", 10: "5", 13: "5"}) is None


def test_two_digit_beats_single_digit_when_present(monkeypatch):
    # If any 2-digit value clears the bar, 1-digit reads never override it.
    assert _run_with_reads(monkeypatch, {7: "26", 8: "26", 10: "2", 13: "6"}) == 26


def test_out_of_range_numbers_ignored(monkeypatch):
    # num_min=1, num_max=99: "0" is below range, "100" is 3 digits (neither
    # counter) -> nothing accepted.
    assert _run_with_reads(monkeypatch, {7: "0", 8: "0", 10: "0", 13: "0"}) is None
    assert _run_with_reads(monkeypatch, {7: "100", 8: "100", 10: "100", 13: "100"}) is None


def test_no_digits_read(monkeypatch):
    # Tesseract returns nothing on every PSM (blank/garbled) -> None.
    assert _run_with_reads(monkeypatch, {7: "", 8: "", 10: "", 13: ""}) is None


def test_isolation_none_short_circuits(monkeypatch):
    # If localization fails, we never OCR and return None (a miss, not a crash).
    monkeypatch.setattr(FL, "_isolate_label", lambda fig, p: None)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return "99"
    monkeypatch.setattr(FL, "_ocr_digits", _boom)
    assert FL.read_corner_label(np.zeros((50, 50, 3), np.uint8), "x") is None
    assert called["n"] == 0, "must not OCR when isolation returns None"


# --------------------------------------------------------------------------
# Guard cases — real cv2 path, no Tesseract needed.
# --------------------------------------------------------------------------

def test_none_and_empty_inputs():
    assert FL.read_corner_label(None, "x") is None
    assert FL.read_corner_label(np.zeros((0, 0, 3), np.uint8), "x") is None


def test_blank_patch_localizes_nothing():
    # A uniform patch has no bright glyph blob -> top-hat is empty -> isolation
    # returns None BEFORE any Tesseract call. Exercises the real cv2 pipeline and
    # confirms the "no fabricated number on featureless input" property.
    flat = np.full((200, 200, 3), 120, np.uint8)
    assert FL._isolate_label(flat, dict(FL.DEFAULTS)) is None
    assert FL.read_corner_label(flat, "tesseract-not-used") is None


def test_tiny_region_returns_none():
    # A figure crop so small the bottom-right search region is < 4px -> None.
    assert FL._isolate_label(np.zeros((3, 3, 3), np.uint8), dict(FL.DEFAULTS)) is None


def test_param_overrides_are_whitelisted():
    # Unknown keys in an override dict must be ignored (only DEFAULTS keys apply),
    # so a caller typo can't silently disable a guard.
    flat = np.full((200, 200, 3), 120, np.uint8)
    # bogus key ignored; still returns None on a blank patch.
    assert FL.read_corner_label(flat, "x", {"not_a_real_knob": 999}) is None
