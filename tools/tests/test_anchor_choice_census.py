"""Unit tests for the pure logic in tools.anchor_choice_census.

The census's value is its measurement (docs/RESULTS.md 2026-08-19, evidence in
docs/data/anchor_choice_census_20260819.json), which needs the real fixtures and
Tesseract. What is pinned here is the plumbing that could silently corrupt that
measurement: set discovery (a set silently dropped = a claim about a corpus that
was never measured), TSV parsing, and the ungated box's behaviour when the paper
mask finds nothing — bg_taleb_01 hits exactly that path.

Run: ``python -m pytest tools/tests/test_anchor_choice_census.py``
"""

from __future__ import annotations

import numpy as np

from pipeline.book_boundary import DEFAULTS as BOOK_DEFAULTS
from tools.anchor_choice_census import (
    conf_ge_80,
    discover_sets,
    languages,
    ungated_emit_box,
)


def _tsv(rows: list[tuple[float, str]]) -> str:
    head = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext")
    body = [f"5\t1\t1\t1\t1\t{i}\t0\t0\t10\t10\t{c}\t{t}"
            for i, (c, t) in enumerate(rows)]
    return "\n".join([head, *body])


# --- TSV parsing ----------------------------------------------------------

def test_conf_ge_80_counts_only_words_with_text():
    tsv = _tsv([(95.0, "Sentiero"), (81.0, "delle"), (12.0, "Pa1ete"),
                (99.0, "   ")])          # whitespace-only -> not a word
    n, mean = conf_ge_80(tsv)
    assert n == 2
    assert mean == round((95.0 + 81.0 + 12.0) / 3, 1)


def test_conf_ge_80_boundary_is_inclusive_and_empty_is_zero():
    assert conf_ge_80(_tsv([(80.0, "x")]))[0] == 1
    assert conf_ge_80(_tsv([(79.9, "x")]))[0] == 0
    assert conf_ge_80(_tsv([])) == (0, 0.0)


# --- fixture discovery ----------------------------------------------------

def test_discover_sets_finds_all_three_fixture_families():
    sets = discover_sets()
    # multi-zoom, multi-view, and the manifest.csv re-shoot triples
    assert sets["zoomset_de_02"] == ["zoomset_de_02_f00", "zoomset_de_02_f01",
                                     "zoomset_de_02_f02"]
    assert sorted(sets["skewset_it_01"]) == ["skewset_it_01_134801",
                                             "skewset_it_01_134804"]
    assert sorted(sets["de_02"]) == ["de_02", "de_02_092054", "de_02_092058"]
    # single-frame fixtures are not sets — there is no anchor choice to make
    assert "it_geo_04" not in sets
    assert all(len(v) > 1 for v in sets.values())


def test_every_discovered_frame_has_a_language():
    langs = languages()
    for ids in discover_sets().values():
        for i in ids:
            assert langs.get(i) in {"eng", "deu", "ita", "bul"}, i


# --- ungated box ----------------------------------------------------------

def test_ungated_box_falls_back_to_the_whole_frame_with_no_paper():
    """A frame with nothing bright and colourless must score the whole image.

    Returning a degenerate box instead would hand the census a garbage scoring
    window that still LOOKS like a number — the bg_taleb_01 failure mode, where
    the mask sees 0.1 % of the frame.
    """
    dark = np.zeros((240, 320, 3), np.uint8)
    box, src = ungated_emit_box(dark, dict(BOOK_DEFAULTS))
    assert box == (0, 0, 320, 240)
    assert src == "no_mask"


def test_ungated_box_finds_a_bright_page_and_is_not_the_whole_frame():
    img = np.full((240, 320, 3), 30, np.uint8)          # dark room
    img[60:180, 80:240] = 250                            # bright page
    box, src = ungated_emit_box(img, dict(BOOK_DEFAULTS))
    x0, y0, x1, y1 = box
    assert src in {"grabcut", "mask_bbox_fallback"}
    assert (x1 - x0) * (y1 - y0) < 320 * 240
    assert x0 < 120 and x1 > 200 and y0 < 100 and y1 > 160
