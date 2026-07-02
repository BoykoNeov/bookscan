"""Unit tests for tools.ocr_metrics — the pure Gate 1 logic.

Run with pytest, or directly: ``python -m tools.tests.test_ocr_metrics``.
Every input here has an answer known by hand.
"""

from __future__ import annotations

from tools.ocr_metrics import (
    auroc,
    cer,
    flag_rate_stats,
    join_hyphenated,
    label_ocr_words,
    normalize_text,
    parse_tsv,
    tokenize,
    tsv_words_to_text,
    wer,
    word_accuracy,
)


def test_join_hyphenated_joins_linebreak():
    assert join_hyphenated("encyclo-\npedia") == "encyclopedia"
    # chained hyphenation across three lines
    assert join_hyphenated("anti-\ndis-\nestablishment") == "antidisestablishment"


def test_normalize_collapses_whitespace_and_is_idempotent_on_gt():
    gt = "the quick brown fox"  # already joined
    assert normalize_text(gt) == gt
    assert normalize_text("the   quick\n brown\tfox") == "the quick brown fox"


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize("   \n ") == []


def test_parse_tsv_filters_nonword_rows():
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        # structural rows (levels 1-4) with conf -1 and empty text -> dropped
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",
        "2\t1\t1\t0\t0\t0\t5\t5\t90\t90\t-1\t",
        "4\t1\t1\t1\t1\t0\t5\t5\t90\t20\t-1\t",
        # real words (level 5)
        "5\t1\t1\t1\t1\t1\t5\t5\t40\t18\t96.5\tHello",
        "5\t1\t1\t1\t1\t2\t50\t5\t35\t18\t88\tworld",
        # word-level row but empty text (spurious) -> dropped
        "5\t1\t1\t1\t1\t3\t90\t5\t5\t18\t0\t   ",
        # word-level row conf -1 -> dropped
        "5\t1\t1\t1\t1\t4\t95\t5\t5\t18\t-1\tx",
    ])
    words = parse_tsv(tsv)
    assert [w.text for w in words] == ["Hello", "world"]
    assert words[0].conf == 96.5
    assert words[0].width == 40


def test_tsv_words_to_text_preserves_line_structure():
    tsv = "\n".join([
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\tencyclo-",
        "5\t1\t1\t1\t2\t1\t0\t20\t10\t10\t90\tpedia",
    ])
    words = parse_tsv(tsv)
    text = tsv_words_to_text(words)
    assert text == "encyclo-\npedia"
    # and the harness would then join it:
    assert normalize_text(text) == "encyclopedia"


def test_label_ocr_words_substitution_and_insertion():
    gt = ["the", "cat", "sat"]
    ocr = ["the", "cot", "sat", "here"]  # cot=sub, here=spurious insert
    labels = label_ocr_words(gt, ocr)
    assert labels == [True, False, True, False]


def test_label_ocr_words_deletion_does_not_mislabel():
    gt = ["alpha", "beta", "gamma"]
    ocr = ["alpha", "gamma"]  # beta deleted; both present OCR words are correct
    assert label_ocr_words(gt, ocr) == [True, True]


def test_wer_and_accuracy():
    gt = ["a", "b", "c", "d"]
    ocr = ["a", "x", "c", "d"]  # one substitution
    assert wer(gt, ocr) == 0.25
    assert word_accuracy(gt, ocr) == 0.75


def test_cer_perfect_and_error():
    assert cer("hello world", "hello world") == 0.0
    # one char substitution out of 11 chars
    assert abs(cer("hello world", "hallo world") - 1 / 11) < 1e-9


def test_auroc_direction_perfect_separation():
    # wrong words have LOW conf, correct words HIGH conf -> AUROC ~ 1.0
    confs = [95, 92, 88, 30, 20, 10]
    is_wrong = [False, False, False, True, True, True]
    assert auroc(confs, is_wrong) == 1.0
    # fully reversed -> 0.0 (catches a sign flip)
    assert auroc(confs, [True, True, True, False, False, False]) == 0.0


def test_auroc_undefined_single_class():
    assert auroc([90, 80], [False, False]) is None
    assert auroc([], []) is None


def test_auroc_handles_ties_at_half():
    # all same confidence -> no separation -> 0.5
    assert auroc([50, 50, 50, 50], [True, False, True, False]) == 0.5


def test_flag_rate_stats_catches_low_conf_errors():
    # 10 words, 2 wrong, both at the lowest confidences
    confs = [99, 98, 97, 96, 95, 94, 93, 92, 20, 10]
    is_wrong = [False] * 8 + [True, True]
    stats = {s.flag_rate: s for s in flag_rate_stats(confs, is_wrong, [0.2])}
    s = stats[0.2]
    assert s.n_flagged == 2
    assert s.recall == 1.0       # both errors caught
    assert s.precision == 1.0    # both flags were real errors


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
