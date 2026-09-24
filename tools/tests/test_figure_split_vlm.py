"""Pure-function tests for tools/figure_split_vlm.py (no model is called)."""

import numpy as np

from tools.figure_split_vlm import (
    RED, control_halves, grade, parse, restored, seam_image, seam_row, union_box,
)


def test_parse_needs_exactly_one_of_the_two_words():
    assert parse("ONE", "ONE", "TWO") == "ONE"
    assert parse("TWO.", "ONE", "TWO") == "TWO"
    assert parse("", "ONE", "TWO") == "?"
    assert parse("ONE OR TWO", "ONE", "TWO") == "?"
    assert parse("CONTINUES", "CONTINUES", "BOUNDARY") == "CONTINUES"


def test_union_box_clips_to_the_page():
    assert union_box([10, 20, 100, 50], [0, 80, 50, 500], 90, 400) == (0, 20, 90, 400)


def test_seam_row_is_the_middle_of_the_gap_or_overlap():
    assert seam_row([0, 0, 10, 100], [0, 120, 10, 50]) == 110
    assert seam_row([0, 0, 10, 100], [0, 90, 10, 50]) == 95


def test_control_halves_cover_the_block_exactly():
    a, b = control_halves([5, 10, 40, 101])
    assert a == [5, 10, 40, 50] and b == [5, 60, 40, 51]


def test_seam_image_leaves_page_pixels_untouched():
    page = np.full((400, 300, 3), 77, np.uint8)
    img = seam_image(page, [50, 100, 200, 60], [50, 170, 200, 60])
    red = np.all(img == np.array(RED, np.uint8), axis=2)
    assert red.any()
    grey = np.all(img == 77, axis=2)
    cols = np.where(grey.any(axis=0))[0]
    # every red pixel lies outside the page window's columns
    assert not red[:, cols.min():cols.max() + 1].any()


def test_restored_needs_the_merged_pairs_to_connect_every_block():
    pairs = [(12, 13), (13, 19), (19, 20)]
    assert restored(pairs, {(12, 13), (13, 19), (19, 20)})
    assert not restored(pairs, {(12, 13), (19, 20)})


def _row(key, label, crop, seam):
    pid, ab = key.split("#")
    a, b = (int(x) for x in ab.split("-"))
    return {"key": key, "page_id": pid, "a": a, "b": b, "label": label,
            "crop": [crop, crop], "seam": [seam, seam], "flip": False,
            "merge": crop == "ONE" and seam == "CONTINUES"}


def test_grade_one_wrong_merge_fails():
    rows = [_row("p#1-2", "one", "ONE", "CONTINUES"),
            _row("p#3-4", "two", "ONE", "CONTINUES")]
    ctrl = [{"key": "c", "crop": ["ONE"] * 2, "seam": ["CONTINUES"] * 2,
             "merge": True, "flip": False}]
    s = grade(rows, ctrl, {"g": ["p#1-2"]})
    assert s["wrong_merges"] == ["p#3-4"] and s["verdict"] == "FAIL"


def test_grade_counts_pictures_not_pairs():
    rows = [_row("p#1-2", "one", "ONE", "CONTINUES"),
            _row("p#2-3", "one", "ONE", "CONTINUES"),
            _row("q#1-2", "one", "TWO", "CONTINUES"),
            _row("r#1-2", "one", "TWO", "BOUNDARY"),
            _row("s#1-2", "sidebar", "TWO", "CONTINUES")]
    ctrl = [{"key": "c", "crop": ["ONE"] * 2, "seam": ["CONTINUES"] * 2,
             "merge": True, "flip": False}]
    s = grade(rows, ctrl, {"big": ["p#1-2", "p#2-3"], "q": ["q#1-2"], "r": ["r#1-2"]})
    # 2 of 4 pairs merged, but only 1 of 3 pictures -> recall bar missed
    assert s["pictures_restored"] == 1 and s["verdict"] == "FAIL"
    assert s["arms"]["seam_alone"]["separate_wrong"] == ["s#1-2"]
    assert s["arms"]["both_agree"]["separate_wrong"] == []


def test_grade_broken_control_is_no_verdict():
    rows = [_row("p#1-2", "one", "ONE", "CONTINUES")]
    ctrl = [{"key": "c", "crop": ["TWO"] * 2, "seam": ["BOUNDARY"] * 2,
             "merge": False, "flip": False}]
    assert grade(rows, ctrl, {"g": ["p#1-2"]})["verdict"] == "NO VERDICT"
